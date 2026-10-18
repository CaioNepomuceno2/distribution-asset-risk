"""Pipeline completo: painel -> backtest -> previsão 2026 -> SHAP -> risco -> carteira ótima.

Pré-requisitos (dados brutos processados):
    python scripts/build_interrupcoes.py
    python scripts/build_bdgd.py
    python scripts/build_clima.py
"""
import json
import logging

import numpy as np
import pandas as pd
import shap

from gridrisk import features as F
from gridrisk import model as M
from gridrisk import otimizacao as O
from gridrisk import risco as R
from gridrisk.config import ROOT, Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("pipeline")
cfg = Config.load()
OUT = ROOT / "reports"
OUT.mkdir(exist_ok=True)
ANOS_TESTE = [2023, 2024, 2025]
ANO_PREV = 2026

# ---------------------------------------------------------------- painel
falhas = F.falhas_por_alimentador(cfg.interim / "interrupcoes_emt.parquet", cfg.interim)
falhas.to_parquet(cfg.interim / "falhas.parquet", index=False)
clima = pd.read_parquet(cfg.interim / "clima_alimentador_mes.parquet")
panel = F.build_panel(falhas, cfg.interim, clima, list(range(2019, ANO_PREV + 1)))
panel.to_parquet(cfg.processed / "panel.parquet", index=False)
treino_total = panel[panel.ano < ANO_PREV]
log.info("painel: %s linhas, %d alimentadores", len(panel), panel.alimentador.nunique())

# ---------------------------------------------------------------- backtest
resumos, calib = [], {}
for alvo in ["n_falhas", "chi"]:
    bt = M.backtest(treino_total, alvo, ANOS_TESTE)
    resumos.append(bt.resumo.assign(alvo=alvo))
    bt.previsoes.to_parquet(cfg.processed / f"backtest_{alvo}.parquet", index=False)
    calib[alvo] = M.calibracao(bt.previsoes, alvo)
    calib[alvo].to_csv(OUT / f"calibracao_{alvo}.csv")
resumo = pd.concat(resumos)
resumo.to_csv(OUT / "backtest_resumo.csv", index=False)
media = resumo.groupby(["alvo", "metodo"]).mean(numeric_only=True).drop(columns="ano_teste")
media.to_csv(OUT / "backtest_media.csv")
log.info("backtest (média %s):\n%s", ANOS_TESTE, media.round(3).to_string())

# ---------------------------------------------------------------- modelo final e previsão
alvo_prev = panel[panel.ano == ANO_PREV].copy()
X_prev = M.design(alvo_prev)
modelos = {}
for alvo in ["n_falhas", "chi"]:
    preds = []
    for seed in range(5):  # média de sementes para estabilidade do ranking
        m = M.fit(treino_total, alvo, seed=seed)
        preds.append(m.predict(X_prev))
        if seed == 0:
            modelos[alvo] = m
    alvo_prev[f"pred_{alvo}"] = np.mean(preds, axis=0)
alvo_prev["prob_ao_menos_1_falha"] = 1 - np.exp(-alvo_prev.pred_n_falhas)
prev = alvo_prev[M.ID + ["pred_n_falhas", "pred_chi", "prob_ao_menos_1_falha", "n_falhas", "chi"]]
prev = prev.rename(columns={"n_falhas": "n_falhas_obs_parcial", "chi": "chi_obs_parcial"})
prev.to_parquet(cfg.processed / f"previsao_{ANO_PREV}.parquet", index=False)

# ---------------------------------------------------------------- SHAP
X = M.design(treino_total[treino_total.ano >= 2023])
amostra = X.sample(min(len(X), 6000), random_state=0)
sv = shap.TreeExplainer(modelos["chi"]).shap_values(amostra)
imp = pd.Series(np.abs(sv).mean(0), index=amostra.columns).sort_values(ascending=False)
imp.rename("shap_medio_abs").to_csv(OUT / "shap_importancia_chi.csv")
pd.DataFrame(sv, columns=amostra.columns, index=amostra.index).to_parquet(cfg.processed / "shap_chi.parquet")
amostra.to_parquet(cfg.processed / "shap_amostra_X.parquet")

# ---------------------------------------------------------------- consequência (R$/CHI)
fin, catalogo = O.carregar_catalogo(ROOT / "configs" / "intervencoes.yaml")
ult_snap = max(int(p.stem.split("_")[-1]) for p in cfg.interim.glob("bdgd_feeders_*.parquet"))
feeders = (pd.read_parquet(cfg.interim / f"bdgd_feeders_{ult_snap}.parquet")
           .rename(columns={"alimentador_nome": "alimentador"}).drop_duplicates("alimentador"))
comp = R.compensacao_por_chi(cfg.raw / "continuidade" / "indicadores-continuidade-coletivos-compensacao-2020-2029.parquet",
                             cfg.interim / "interrupcoes_emt.parquet", cfg.sigla, [2022, 2023, 2024, 2025])
pesos = R.conjunto_do_alimentador(cfg.interim / "interrupcoes_emt.parquet", cfg.interim / f"crosswalk_{ult_snap}.parquet")
cenarios = {
    "compensacao": R.valor_chi_alimentador(comp, pesos, feeders, 0.0),
    "social": R.valor_chi_alimentador(comp, pesos, feeders, fin["custo_ens_rs_mwh"]),
}

chi_modo = prev.pivot_table(index="alimentador", columns="modo", values="pred_chi", observed=False)[F.MODOS]
# fração do CHI que é regulatória (sem expurgo), por modo, nos últimos 3 anos
rec = falhas[falhas.ano.between(ANO_PREV - 3, ANO_PREV - 1)].groupby("modo")[["chi", "chi_regulatorio"]].sum()
frac_reg = (rec.chi_regulatorio / rec.chi).reindex(F.MODOS)
frac_reg.rename("frac_chi_regulatorio").to_csv(OUT / "frac_chi_regulatorio_modo.csv")
chi_modo_reg = chi_modo * frac_reg
risco = chi_modo.sum(axis=1).rename("chi_previsto").to_frame()
risco["chi_reg_previsto"] = chi_modo_reg.sum(axis=1)
risco["n_falhas_previsto"] = prev.groupby("alimentador").pred_n_falhas.sum()
for nome, v in cenarios.items():
    risco[f"rs_por_chi_{nome}"] = v.set_index("alimentador").rs_por_chi
    base_chi = risco.chi_reg_previsto if nome == "compensacao" else risco.chi_previsto
    risco[f"risco_rs_{nome}"] = base_chi * risco[f"rs_por_chi_{nome}"]
risco["modo_dominante"] = chi_modo.idxmax(axis=1)
hist = falhas[falhas.ano.between(ANO_PREV - 3, ANO_PREV - 1)].groupby("alimentador").chi.sum() / 3
risco["chi_historico_3a"] = hist
risco = risco.join(feeders.set_index("alimentador")[["lat", "lon", "rede_mt_km", "n_uc", "frac_rural",
                                                      "frac_cabo_nu", "subestacao_bdgd"]])
n_uc_total = feeders.n_uc.sum()
risco["dec_contribuicao_h"] = risco.chi_reg_previsto / n_uc_total
risco.reset_index().to_parquet(cfg.processed / "risco_alimentador.parquet", index=False)

# ---------------------------------------------------------------- carteira ótima
orcamentos = [5e6, 10e6, 20e6, 40e6, 80e6]
resultados = {}
for nome, v in cenarios.items():
    cands = O.pacotes(feeders.set_index("alimentador"), chi_modo_reg if nome == "compensacao" else chi_modo,
                      v.set_index("alimentador").rs_por_chi, catalogo, fin, chi_modo_reg=chi_modo_reg)
    cands.to_parquet(cfg.processed / f"candidatos_{nome}.parquet", index=False)
    front = O.fronteira(cands, orcamentos, risco.chi_historico_3a)
    front["dec_evitado_h"] = front.chi_reg_evitado_ano / n_uc_total
    front.to_csv(OUT / f"fronteira_{nome}.csv", index=False)
    escolha = O.otimizar(cands, 20e6)
    escolha.to_csv(OUT / f"carteira_20M_{nome}.csv", index=False)
    resultados[nome] = {"fronteira": front.round(2).to_dict("records"),
                        "mix_20M": escolha.pacote.str.split("+").explode().value_counts().to_dict()}
    log.info("fronteira [%s]:\n%s", nome, front.round(1).to_string())

# ---------------------------------------------------------------- checagem parcial 2026
obs = prev.groupby("alimentador")[["n_falhas_obs_parcial", "pred_n_falhas"]].sum()
from scipy.stats import spearmanr

check = {"spearman_parcial_jan_jul": float(spearmanr(obs.n_falhas_obs_parcial, obs.pred_n_falhas).statistic),
         "captura_top10_parcial": M.captura_top(obs.n_falhas_obs_parcial, obs.pred_n_falhas, 0.10)}
(OUT / "resultados.json").write_text(json.dumps({"backtest_media": media.round(4).reset_index().to_dict("records"),
                                                 "otimizacao": resultados, "check_2026": check,
                                                 "n_uc_total": int(n_uc_total)}, indent=2, ensure_ascii=False))
log.info("checagem 2026 (jan-jul, parcial): %s", check)

# ---------------------------------------------------------------- artefatos leves para o painel
APP = ROOT / "app" / "data"
APP.mkdir(parents=True, exist_ok=True)
for nome in ["risco_alimentador", "previsao_2026", "candidatos_social", "candidatos_compensacao"]:
    pd.read_parquet(cfg.processed / f"{nome}.parquet").to_parquet(APP / f"{nome}.parquet", index=False)
