"""Quanto a carteira muda se as eficácias de catálogo forem trocadas pelas medidas nos dados?

O projeto irmão `automation-impact` estimou, por diferenças em diferenças nos mesmos dados (BDGD + ANEEL),
o efeito de ganhar religadores sobre o CHI do alimentador: -16,6% (IC 95%: -24,8% a -7,5%). Para o telecomando,
o efeito medido foi nulo (+1,7%, IC -1,8% a +5,4%). As premissas de `configs/intervencoes.yaml` equivalem a
-22,5% (religador: alcance 0,5 x eficácia 0,45) e -21% (automação: 0,6 x 0,35) no CHI do alimentador.

Este script refaz a carteira de R$ 20 mi em quatro cenários, com o resto das premissas igual:

* ``catalogo``: premissas do YAML (o resultado do README);
* ``medido``: religador com o efeito central medido e automação sem efeito;
* ``medido_ic_inferior`` / ``medido_ic_superior``: religador nos limites do IC 95%, automação sem efeito.

Pré-requisito: ``scripts/run_pipeline.py`` (usa data/processed e data/interim).
Saída: ``reports/sensibilidade_eficacias.csv``.
"""
import dataclasses

import pandas as pd

from gridrisk import features as F
from gridrisk import otimizacao as O
from gridrisk.config import carregar

cfg = carregar("Quanto a carteira muda se as eficácias de catálogo forem trocadas pelas medidas nos dados?")
if not cfg.eficacias_medidas:
    raise SystemExit(f"{cfg.sigla}: sem a chave eficacias_medidas na configuração. As eficácias medidas vêm do "
                     "automation-impact, rodado para a própria distribuidora; use-as só depois dessa medição.")
OUT = cfg.reports
ORCAMENTO = 20e6
# efeito no CHI do alimentador (fração evitada), do automation-impact (reports/efeitos_principais.csv lá),
# lido da configuração da distribuidora (chave eficacias_medidas.religador)
RELIGADOR = cfg.eficacias_medidas["religador"]

fin, catalogo = O.carregar_catalogo(cfg.catalogo)
ult = max(int(p.stem.split("_")[-1]) for p in cfg.interim.glob("bdgd_feeders_*.parquet"))
feeders = (pd.read_parquet(cfg.interim / f"bdgd_feeders_{ult}.parquet")
           .rename(columns={"alimentador_nome": "alimentador"}).drop_duplicates("alimentador")
           .set_index("alimentador"))
prev = pd.read_parquet(cfg.processed / f"previsao_{cfg.ano_previsao}.parquet")
chi_modo = prev.pivot_table(index="alimentador", columns="modo", values="pred_chi", observed=False)[F.MODOS]
frac_reg = pd.read_csv(OUT / "frac_chi_regulatorio_modo.csv", index_col=0).iloc[:, 0].reindex(F.MODOS)
chi_modo_reg = chi_modo * frac_reg
risco = pd.read_parquet(cfg.processed / "risco_alimentador.parquet").set_index("alimentador")


def catalogo_cenario(nome: str) -> list[O.Intervencao]:
    if nome == "catalogo":
        return catalogo
    out = []
    for itv in catalogo:
        if itv.nome == "religador":
            itv = dataclasses.replace(itv, eficacia={"todos": RELIGADOR[nome] / itv.alcance})
        elif itv.nome == "automacao":
            itv = dataclasses.replace(itv, eficacia={"todos": 0.0})
        out.append(itv)
    return out


linhas = []
for visao in ["social", "compensacao"]:
    valor = risco[f"rs_por_chi_{visao}"]
    base_chi = chi_modo if visao == "social" else chi_modo_reg
    for cenario in ["catalogo", *RELIGADOR]:
        cands = O.pacotes(feeders, base_chi, valor, catalogo_cenario(cenario), fin, chi_modo_reg=chi_modo_reg)
        front = O.fronteira(cands, [ORCAMENTO], risco.chi_historico_3a)
        mix = O.otimizar(cands, ORCAMENTO).pacote.str.split("+").explode().value_counts().to_dict()
        for _, r in front.iterrows():
            linhas.append({"visao": visao, "cenario": cenario, "metodo": r.metodo, "investido": r.investido,
                           "vpl": r.vpl, "chi_evitado_ano": r.chi_evitado_ano,
                           "dec_evitado_h": r.chi_reg_evitado_ano / feeders.n_uc.sum(),
                           "n_alimentadores": r.n_alimentadores,
                           "mix_otimo": ";".join(f"{k}={v}" for k, v in mix.items()) if r.metodo == "otimo" else ""})
res = pd.DataFrame(linhas)
res.to_csv(OUT / "sensibilidade_eficacias.csv", index=False)
print(res.assign(vpl_mi=res.vpl / 1e6, investido_mi=res.investido / 1e6)
      .drop(columns=["vpl", "investido"]).round(2).to_string(index=False))
