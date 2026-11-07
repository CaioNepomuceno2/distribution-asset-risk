"""Comparativo descritivo entre a Energisa MT e a Energisa MS (``docs/comparativo_mt_ms.md``).

Lê **só saídas já publicadas**: ``reports/``, ``reports/ems/``, ``app/data/`` e ``app/data/ems/`` deste repositório e,
para as outras partes, ``reports/`` e ``reports/ems/`` dos repositórios irmãos (``recloser-performance``,
``substation-health-index``, ``automation-impact`` e ``switchgear-survival``, clonados ao lado deste). Não roda
pipeline, não baixa nada e não regenera resultado de MT nem de MS. O que não existe nos arquivos publicados vira
"não disponível": nada é recalculado por outro caminho, e um arquivo ou repositório ausente derruba só as métricas
que dependem dele.

Saídas em ``reports/comparativo_mt_ms/``: ``metricas.csv`` (cada métrica, com definição, numerador, denominador e
arquivo de origem), uma tabela CSV por bloco, ``verificacoes.csv`` (números derivados contra os publicados),
``fontes.csv`` (arquivos lidos, com SHA-256) e ``figures/*.png``. Com ``--atualizar-docs`` regrava também
``docs/comparativo_mt_ms.md`` e o bloco "Comparativo MT × MS" do README (só se nenhum arquivo de origem faltar).

Neste texto, "MT" é sempre a empresa (Energisa MT); a tensão é escrita "média tensão".

    python scripts/comparativo_mt_ms.py                    # CSVs e figuras
    python scripts/comparativo_mt_ms.py --atualizar-docs   # e o documento e o README
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import numbers
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROPRIO, RECL, SHI, AUTO, SWITCH = ("distribution-asset-risk", "recloser-performance", "substation-health-index",
                                    "automation-impact", "switchgear-survival")
ND = "não disponível"
DIST = ("mt", "ms")
SIGLA = {"mt": "EMT", "ms": "EMS"}
NOME = {"mt": "Energisa MT", "ms": "Energisa MS"}
MODOS = ["EQUIPAMENTO", "DESCARGA_ATMOSFERICA", "VENTO", "VEGETACAO", "ANIMAIS", "TERCEIROS", "OUTRAS"]
NOME_MODO = {"EQUIPAMENTO": "Falha de equipamento", "DESCARGA_ATMOSFERICA": "Descarga atmosférica", "VENTO": "Vento",
             "VEGETACAO": "Vegetação", "ANIMAIS": "Animais", "TERCEIROS": "Terceiros", "OUTRAS": "Outras / não identificada"}
JANELA = "2023-2025"          # janela embutida nos arquivos publicados (falhas por modo e fração regulatória)
ANO_REF = 2025                # cadastro (BDGD de 31/12) usado em todos os denominadores
ANO_PARCIAL = 2026            # ano corrente: dados só até meados do ano
ORCAMENTO_REF = 20e6
JANELA_COMP = (2022, 2025)    # janela de compensações pagas do modelo (e da média publicada)
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro",
         "dezembro"]
TOLERANCIA_DEC = 0.01         # o DEC (ou FEC) recalculado "bate" se difere do oficial em até 1%
TOLERANCIA_VERIFICACAO = 0.01  # diferença relativa aceita entre um número derivado aqui e o publicado
VPL_MIN_RAZAO = 1e6           # razão ótima ÷ tradicional só se o VPL da tradicional passa de R$ 1 mi
PALAVRAS_CAUSAIS = re.compile(r"\b(porque|por causa|devido|explica|explicam|graças|deve-se|resulta de|em razão de)\b",
                              re.IGNORECASE)
MARCA_INI, MARCA_FIM = "<!-- comparativo-mt-ms:inicio -->", "<!-- comparativo-mt-ms:fim -->"


# --------------------------------------------------------------------------------------------- arquivos de origem
@dataclass(frozen=True)
class Arq:
    """Um arquivo publicado. ``dist``: um por distribuidora (MS em ``<base>/ems/``); ``unico``: um só caminho."""
    chave: str
    repo: str
    base: str
    nome: str
    tipo: str = "dist"
    so: str | None = None      # "ms" ou "mt" quando o arquivo existe só para uma distribuidora

    def rel(self, d: str | None = None) -> str:
        if self.tipo == "unico":
            return f"{self.base}/{self.nome}"
        return f"{self.base}/{self.nome}" if d == "mt" else f"{self.base}/ems/{self.nome}"

    def existe_para(self, d: str) -> bool:
        return self.so is None or self.so == d


DIAG = "reports/ems/diagnostico"
ARQUIVOS = [
    Arq("risco", PROPRIO, "app/data", "risco_alimentador.parquet"),
    Arq("resumo_decisao", PROPRIO, "reports", "resumo_decisao.json"),
    Arq("resultados", PROPRIO, "reports", "resultados.json"),
    Arq("fronteira_social", PROPRIO, "reports", "fronteira_social.csv"),
    Arq("fronteira_caixa", PROPRIO, "reports", "fronteira_compensacao.csv"),
    Arq("frac_reg", PROPRIO, "reports", "frac_chi_regulatorio_modo.csv"),
    Arq("validacao", PROPRIO, "reports", "validacao_dec_fec.csv"),
    Arq("comparacao", PROPRIO, DIAG, "comparacao_descritiva.csv", "unico"),
    Arq("circuitos_vazios", PROPRIO, DIAG, "circuitos_vazios.csv", "unico"),
    Arq("vinculo", PROPRIO, DIAG, "vinculo_circuitos_comparacao.csv", "unico"),
    Arq("interrupcoes_mes", PROPRIO, DIAG, "interrupcoes_por_mes.csv", "unico"),
    Arq("expurgo_codigos", PROPRIO, DIAG, "expurgo_codigos_por_ano.csv", "unico"),
    Arq("elegibilidade", PROPRIO, DIAG, "elegibilidade_catalogo.csv", "unico"),
    Arq("chi_por_modo_ms", PROPRIO, DIAG, "chi_por_modo.csv", "unico", "ms"),
    Arq("compensacoes_ms", PROPRIO, DIAG, "compensacoes_por_ano.csv", "unico", "ms"),
    Arq("falhas_expurgo_ms", PROPRIO, DIAG, "falhas_por_expurgo.csv", "unico", "ms"),
    Arq("dec_correlacao_ms", PROPRIO, DIAG, "dec_correlacao.csv", "unico", "ms"),
    Arq("falhas_modo", RECL, "reports", "falhas_por_modo.csv"),
    Arq("recl_diag", RECL, "reports", "diagnostico.json"),
    Arq("recl_topo", RECL, "reports", "qualidade_topologia.json"),
    Arq("se_resumo", SHI, "reports", "resumo_2025.json"),
    Arq("valor", AUTO, "reports", "valor.json"),
    Arq("subestacoes", AUTO, "reports", "subestacoes.csv"),
    Arq("regra_ms", AUTO, "reports/ems", "regra_decisao.json", "unico", "ms"),
    Arq("mt_ref", AUTO, DIAG, "mt_contagens_referencia.json", "unico", "mt"),
    Arq("transicoes_ms", AUTO, DIAG, "transicoes_religadores.csv", "unico", "ms"),
    Arq("snapshot_ms", AUTO, DIAG, "religadores_por_snapshot.csv", "unico", "ms"),
    Arq("qual_classes", SWITCH, "reports", "qualidade_classes.csv"),
    Arq("vida", SWITCH, "reports", "vida_weibull.csv"),
    Arq("tuc_tensao_ms", SWITCH, DIAG, "tuc_x_tensao.csv", "unico", "ms"),
]
POR_CHAVE = {a.chave: a for a in ARQUIVOS}


class Fontes:
    """Lê os arquivos publicados e guarda o que foi (ou não) encontrado. Nunca escreve nada."""

    def __init__(self, raiz: Path, irmaos: Path):
        self.raiz, self.irmaos = Path(raiz), Path(irmaos)
        self.registro: dict[tuple[str, str], Path | None] = {}
        self.avisos: list[str] = []

    def caminho(self, repo: str, rel: str) -> Path:
        return (self.raiz if repo == PROPRIO else self.irmaos / repo) / rel

    def ler(self, repo: str, rel: str):
        p = self.caminho(repo, rel)
        if not p.is_file():
            self.registro[(repo, rel)] = None
            return None
        self.registro[(repo, rel)] = p
        try:
            if p.suffix == ".csv":
                return pd.read_csv(p)
            if p.suffix == ".parquet":
                return pd.read_parquet(p)
            if p.suffix == ".json":
                return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:  # ValueError inclui JSON, CSV e Parquet ilegíveis
            self.avisos.append(f"{repo}/{rel}: arquivo ilegível ({type(e).__name__}: {e})")
        return None

    def faltas(self) -> list[str]:
        return sorted(f"{repo}/{rel}" for (repo, rel), p in self.registro.items() if p is None)


def ler_arquivos(F: Fontes):
    """Devolve ``C[d][chave]`` (um arquivo por distribuidora) e ``S[chave]`` (arquivo único); ``None`` se faltar."""
    C: dict[str, dict] = {d: {} for d in DIST}
    S: dict = {}
    for a in ARQUIVOS:
        if a.tipo == "unico":
            S[a.chave] = F.ler(a.repo, a.rel())
        else:
            for d in DIST:
                C[d][a.chave] = F.ler(a.repo, a.rel(d))
    return C, S


def origem(chaves, d: str) -> str:
    """Caminhos (``repo/arquivo``) de ``chaves`` para a distribuidora ``d``, como aparecem nas tabelas."""
    saida = []
    for k in chaves:
        a = POR_CHAVE[k]
        if a.existe_para(d):
            saida.append(f"{a.repo}/{a.rel(d)}")
    return "; ".join(saida) if saida else "—"


# --------------------------------------------------------------------------------------------- contas
def numerico(v) -> bool:
    return isinstance(v, numbers.Real) and not isinstance(v, bool) and math.isfinite(v)


def div(a, b, k: float = 1.0):
    """``a / b * k``; ``None`` se algum lado faltar ou ``b`` for zero."""
    if not numerico(a) or not numerico(b) or b == 0:
        return None
    return float(a) / float(b) * k


def razao(ms, mt):
    return div(ms, mt) if numerico(ms) and numerico(mt) else None


def fmt(v, casas: int = 1, pct: bool = False) -> str:
    """Número no formato do README: milhar com ponto e decimal com vírgula."""
    if v is None:
        return ND
    if isinstance(v, str):
        return v
    if not numerico(v):
        return ND
    v = 0.0 if round(float(v), casas) == 0 else float(v)
    s = f"{v:,.{casas}f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return s + ("%" if pct else "")


def fmt_mi(v, casas: int = 1) -> str:
    return ND if not numerico(v) else "R$ " + fmt(v / 1e6, casas) + " mi"


class Calc:
    """Guarda ``p[chave]``; uma conta que falha por dado ausente ou fora do formato vira ``None`` e um aviso."""

    def __init__(self, p: dict, avisos: list[str], d: str):
        self.p, self.avisos, self.d = p, avisos, d

    def __call__(self, chave: str, fn) -> None:
        try:
            v = fn()
        except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError, AttributeError) as e:
            self.avisos.append(f"{NOME[self.d]} / {chave}: {type(e).__name__}: {e}")
            v = None
        if isinstance(v, numbers.Real) and not isinstance(v, bool):
            v = float(v) if math.isfinite(v) else None
        self.p[chave] = v


def linha(df: pd.DataFrame, d: str, ano: int, col: str) -> float:
    x = df[(df["distribuidora"] == SIGLA[d]) & (df["ano"] == ano)][col]
    return float(x.iloc[0])


def concentracao(s: pd.Series, frac: float) -> tuple[float, int]:
    """Parcela do total nos ``round(n * frac)`` maiores valores, como em ``scripts/resumo_decisao.py``."""
    s = s.astype(float).sort_values(ascending=False)
    k = round(len(s) * frac)
    return float(s.head(k).sum() / s.sum()), k


def anos_que_nao_batem(v: pd.DataFrame) -> list[int]:
    """Anos em que o DEC ou o FEC recalculado difere do oficial em mais de ``TOLERANCIA_DEC`` (relativa)."""
    ruins = []
    for _, r in v.iterrows():
        dif_dec = abs(r["DEC_calculado"] - r["DEC_oficial"]) / r["DEC_oficial"]
        dif_fec = abs(r["FEC_calculado"] - r["FEC_oficial"]) / r["FEC_oficial"]
        if dif_dec > TOLERANCIA_DEC or dif_fec > TOLERANCIA_DEC:
            ruins.append(int(r["ano"]))
    return ruins


def chi_regulatorio_por_modo(fm: pd.DataFrame, fr: pd.DataFrame) -> pd.Series:
    """CHI regulatório anual por modo = CHI × fração regulatória do modo; falha se algum modo não tiver fração."""
    chi = fm.set_index("modo")["chi"]
    frac = fr.set_index("modo")["frac_chi_regulatorio"].reindex(chi.index)
    if frac.isna().any():
        raise ValueError("modos sem fração regulatória: " + ", ".join(frac.index[frac.isna()]))
    return chi * frac


def vpl_de(f: pd.DataFrame, metodo: str, orcamento: float, col: str = "vpl"):
    x = f[(f["metodo"] == metodo) & (f["orcamento"] == orcamento)][col]
    return float(x.iloc[0])


def razao_carteira(f: pd.DataFrame, orcamento: float):
    """VPL da carteira ótima ÷ VPL da regra tradicional; ``None`` se o VPL da tradicional não passa de R$ 1 mi."""
    ot, tr = vpl_de(f, "otimo", orcamento), vpl_de(f, "tradicional", orcamento)
    return None if tr < VPL_MIN_RAZAO else ot / tr


# --------------------------------------------------------------------------------------------- derivação
def derivar(C: dict, S: dict, avisos: list[str]) -> dict:
    """Todos os números do comparativo, por distribuidora: ``P[d][chave]`` (``None`` = não disponível)."""
    P = {d: derivar_dist(d, C[d], S, avisos) for d in DIST}
    derivar_so_uma_distribuidora(P, C, S, avisos)
    return P


def derivar_dist(d: str, x: dict, S: dict, avisos: list[str]) -> dict:
    """Números de uma distribuidora (``d``) a partir dos arquivos dela (``x``) e dos compartilhados (``S``)."""
    p: dict = {}
    c = Calc(p, avisos, d)
    r, fm, fr, val, rd = x["risco"], x["falhas_modo"], x["frac_reg"], x["validacao"], x["recl_diag"]
    # (a) tamanho
    c("n_alim", lambda: int(r.shape[0]))
    c("uc", lambda: float(r["n_uc"].sum()))
    c("km", lambda: float(r["rede_mt_km"].sum()))
    c("uc_por_km", lambda: div(p.get("uc"), p.get("km")))
    c("km_por_alim", lambda: div(p.get("km"), p.get("n_alim")))
    c("uc_por_alim", lambda: div(p.get("uc"), p.get("n_alim")))
    c("vazios", lambda: linha(S["circuitos_vazios"], d, ANO_REF, "sem_rede_e_sem_uc"))
    c("sem_uc", lambda: linha(S["circuitos_vazios"], d, ANO_REF, "sem_uc"))
    # (b) falhas na média tensão (registros da ANEEL ligados a um circuito, média anual 2023-2025)
    c("falhas_ano", lambda: float(fm["n_falhas"].sum()))
    c("falhas_100km", lambda: div(p.get("falhas_ano"), p.get("km"), 100))
    c("falhas_1000uc", lambda: div(p.get("falhas_ano"), p.get("uc"), 1000))
    c("falhas_100km_pub", lambda: float(fm["falhas_por_100km_ano"].sum()))
    for m in MODOS:
        c(f"falhas_ano:{m}", lambda m=m: float(fm.set_index("modo").loc[m, "n_falhas"]))
        c(f"falhas_100km:{m}", lambda m=m: div(p.get(f"falhas_ano:{m}"), p.get("km"), 100))
        c(f"falhas_1000uc:{m}", lambda m=m: div(p.get(f"falhas_ano:{m}"), p.get("uc"), 1000))
        c(f"falhas_pct:{m}", lambda m=m: div(p.get(f"falhas_ano:{m}"), p.get("falhas_ano"), 100))
        c(f"falhas_100km_pub:{m}", lambda m=m: float(fm.set_index("modo").loc[m, "falhas_por_100km_ano"]))
    # (c) CHI = consumidor-hora interrompido
    c("chi_ano", lambda: float(fm["chi"].sum()))
    c("chi_reg_ano", lambda: float(chi_regulatorio_por_modo(fm, fr).sum()))
    c("chi_uc", lambda: div(p.get("chi_ano"), p.get("uc")))
    c("chi_reg_uc", lambda: div(p.get("chi_reg_ano"), p.get("uc")))
    c("chi_km", lambda: div(p.get("chi_ano"), p.get("km")))
    c("frac_exp", lambda: 100 * (1 - p["chi_reg_ano"] / p["chi_ano"]))
    for m in MODOS:
        c(f"chi_uc:{m}", lambda m=m: div(float(fm.set_index("modo").loc[m, "chi"]), p.get("uc")))
        c(f"chi_reg_uc:{m}", lambda m=m: div(float(chi_regulatorio_por_modo(fm, fr)[m]), p.get("uc")))
        c(f"frac_exp:{m}", lambda m=m: 100 * (1 - float(fr.set_index("modo").loc[m, "frac_chi_regulatorio"])))
    c("chi_por_registro", lambda: div(p.get("chi_ano"), p.get("falhas_ano")))
    # (d) DEC e FEC oficiais
    c("dec_of", lambda: float(val.set_index("ano").loc[ANO_REF, "DEC_oficial"]))
    c("fec_of", lambda: float(val.set_index("ano").loc[ANO_REF, "FEC_oficial"]))
    c("dec_calc", lambda: float(val.set_index("ano").loc[ANO_REF, "DEC_calculado"]))
    c("anos_nao_batem", lambda: ", ".join(map(str, anos_que_nao_batem(val))) or "nenhum")
    c("corr_mensal", lambda: float(val["corr_mensal_conjunto_DEC"].iloc[0]))
    # (e) compensações: pagas (só MS tem a série publicada) e previstas pelo modelo
    if d == "ms":
        c("comp_paga_ano", lambda: media_compensacoes(S["compensacoes_ms"], *JANELA_COMP))
        c("comp_paga_uc", lambda: div(p.get("comp_paga_ano"), p.get("uc")))
    else:
        p["comp_paga_ano"] = p["comp_paga_uc"] = None
    c("risco_comp", lambda: float(r["risco_rs_compensacao"].sum()))
    c("risco_comp_uc", lambda: div(p.get("risco_comp"), p.get("uc")))
    c("risco_social", lambda: float(r["risco_rs_social"].sum()))
    c("risco_social_uc", lambda: div(p.get("risco_social"), p.get("uc")))
    c("dec_previsto", lambda: float(r["dec_contribuicao_h"].sum()))
    # (f) concentração do risco previsto para 2026
    for nome_vis, col in (("social", "risco_rs_social"), ("comp", "risco_rs_compensacao")):
        for frac in (10, 20):
            c(f"top{frac}_{nome_vis}", lambda col=col, frac=frac: 100 * concentracao(r[col], frac / 100)[0])
            c(f"k{frac}_{nome_vis}", lambda col=col, frac=frac: concentracao(r[col], frac / 100)[1])
    c("top10_social_pub", lambda: 100 * x["resumo_decisao"]["frac_risco_social_top10pct_alimentadores"])
    c("top20_social_pub", lambda: 100 * x["resumo_decisao"]["frac_risco_social_top20pct_alimentadores"])
    # (g) carteira ótima contra a regra tradicional, orçamento de referência
    fs, fc = x["fronteira_social"], x["fronteira_caixa"]
    for sufixo, f in (("", fs), ("_caixa", fc)):
        c(f"razao_carteira{sufixo}", lambda f=f: razao_carteira(f, ORCAMENTO_REF))
        for met in ("otimo", "tradicional"):
            c(f"vpl_{met}{sufixo}", lambda f=f, met=met: vpl_de(f, met, ORCAMENTO_REF))
            c(f"investido_{met}{sufixo}", lambda f=f, met=met: vpl_de(f, met, ORCAMENTO_REF, "investido"))
            c(f"n_{met}{sufixo}", lambda f=f, met=met: vpl_de(f, met, ORCAMENTO_REF, "n_alimentadores"))
        c(f"investido_max_otimo{sufixo}", lambda f=f: float(f[f["metodo"] == "otimo"]["investido"].max()))
    c("dec_evitado_otimo", lambda: vpl_de(fs, "otimo", ORCAMENTO_REF, "dec_evitado_h"))
    c("dec_evitado_trad", lambda: vpl_de(fs, "tradicional", ORCAMENTO_REF, "dec_evitado_h"))
    # (h) subestações e religadores
    se = x["se_resumo"]
    c("ses", lambda: float(se["n_ses"]))
    c("ses_uc", lambda: float(se["n_uc"]))
    c("ses_por_1000km", lambda: div(p.get("ses"), p.get("km"), 1000))
    c("uc_por_se", lambda: div(p.get("ses_uc"), p.get("ses")))
    c("ses_um_trafo", lambda: float(se["ses_um_trafo"]))
    c("ses_um_trafo_pct", lambda: div(p.get("ses_um_trafo"), p.get("ses"), 100))
    c("uc_um_trafo_pct", lambda: div(float(se["uc_em_ses_um_trafo"]), p.get("ses_uc"), 100))
    c("uc_sem_transf_pct", lambda: 100 * float(se["frac_uc_sem_transferencia"]))
    c("ses_n1", lambda: float(se["ses_sem_folga_n1_com_2mais_trafos"]))
    c("ses_n1_ventilacao", lambda: (
        float(se["sensibilidades_da_configuracao"]["estagios_cadastrados"]["ses_sem_folga_n1_com_2mais_trafos"])
        if d == "ms" else float(se["ses_sem_folga_n1_com_2mais_trafos"])))
    c("ses_util80", lambda: float(se["ses_utilizacao_acima_80pct"]))
    c("ses_vinculo_mt", lambda: float(se["sensibilidades_da_configuracao"]["vinculo_regra_mt"]["ses"])
      if d == "ms" else float(se["n_ses"]))
    c("eventos_se", lambda: float(se["eventos_se_ano_total"]))
    c("eventos_se_pct_chi", lambda: 100 * float(se["frac_chi_mt_em_eventos_se"]))
    inv = (rd or {}).get("inventario", {}) if isinstance(rd, dict) else {}
    c("recl_cadastro", lambda: float(inv["religadores_no_cadastro"]))
    c("recl_linha", lambda: float(inv["religadores_de_linha_com_clientes"]))
    c("recl_saida", lambda: float(inv["religadores_de_saida"]))
    c("recl_telecom", lambda: float(inv["religadores_telecomandados_cadastro"]))
    c("recl_aberto", lambda: float(inv["religadores_normalmente_abertos"]))
    c("recl_cad_100km", lambda: div(p.get("recl_cadastro"), p.get("km"), 100))
    c("recl_linha_100km", lambda: div(p.get("recl_linha"), p.get("km"), 100))
    c("recl_telecom_pct", lambda: div(p.get("recl_telecom"), p.get("recl_cadastro"), 100))
    c("zona_mediana", lambda: float(rd["zonas_religador_linha"]["clientes_zona_mediana"]))
    c("zona_menos50", lambda: 100 * float(rd["zonas_religador_linha"]["frac_com_menos_de_50_clientes_na_zona"]))
    c("zonas_top10_chi", lambda: 100 * float(rd["zonas_criticas"]["top10pct_frac_chi_esperado"]))
    c("zonas_top10_saida", lambda: 100 * float(rd["zonas_criticas"]["top10pct_frac_saida"]))
    c("alim_sem_recl_pct", lambda: div(float(rd["alimentadores_sem_religador_de_linha"]["n"]), p.get("n_alim"), 100))
    c("uc_ligadas_saida", lambda: 100 * float(x["recl_topo"][str(ANO_REF)]["frac_uc_alcancadas"]))
    c("recl_km_pub", lambda: float(rd["rede"]["km_mt"]))
    c("recl_100km_pub", lambda: float(rd["rede"]["falhas_mt_por_100km_ano"]))
    c("spearman_zonas", lambda: float(rd["validacao_modelo"]["spearman_ci_modelo_vs_observado"]))
    c("razao_ci_zonas", lambda: float(rd["validacao_modelo"]["razao_ci_observado_sobre_modelo_mediana"]))
    # (i) apoio à seção "o que não dá para comparar"
    c("spearman_2026", lambda: float(x["resultados"]["check_2026"]["spearman_parcial_jan_jul"]))
    c("vinculo_2026", lambda: linha_vinculo(S["vinculo"], d, ANO_PARCIAL, "pct_eventos"))
    c("registros_mar_2026", lambda: registros_mes(S["interrupcoes_mes"], d, ANO_PARCIAL, 3))
    c("meses_parcial", lambda: faixas_de_meses(meses_com_registro(S["interrupcoes_mes"], d, ANO_PARCIAL)[0]))
    c("meses_faltando", lambda: faixas_de_meses(meses_com_registro(S["interrupcoes_mes"], d, ANO_PARCIAL)[1]))
    c("uc_snapshot_2024", lambda: float(x["recl_topo"]["2024"]["uc_total"]))
    c("uc_snapshot_2025", lambda: float(x["recl_topo"][str(ANO_REF)]["uc_total"]))
    c("uc_valor_json", lambda: float(x["valor"]["uc_total"]))
    c("alim_snapshot_2024", lambda: float(x["recl_topo"]["2024"]["alimentadores"]))
    c("ses_automacao", lambda: float(x["subestacoes"].shape[0]))
    c("recl_valor_json", lambda: float(x["valor"]["religadores_2025"]))
    c("recl_switch", lambda: float(x["qual_classes"].set_index("classe").loc["religador", "frota_2025"]))
    c("disj_switch", lambda: float(x["qual_classes"].set_index("classe").loc["disjuntor", "frota_2025"]))
    c("efeito_religador", lambda: float(x["valor"]["efeito_chi_pct"]))
    c("origem_efeito", lambda: x["valor"].get("origem_efeito", "medido"))
    c("eventos_did", lambda: float(x["valor"]["eventos"]))
    c("vida_recl", lambda: vida_mediana(x["qual_classes"], x["vida"], "religador"))
    c("vida_disj", lambda: vida_mediana(x["qual_classes"], x["vida"], "disjuntor"))
    c("classes_aprovadas", lambda: float(x["qual_classes"]["confiavel"].astype(bool).sum()))
    c("classes_total", lambda: float(x["qual_classes"].shape[0]))
    return p


def derivar_so_uma_distribuidora(P: dict, C: dict, S: dict, avisos: list[str]) -> None:
    """Números que só existem publicados para MT ou para MS."""
    cm, cs = Calc(P["ms"], avisos, "ms"), Calc(P["mt"], avisos, "mt")
    t = S["tuc_tensao_ms"]
    cm("tuc210_at", lambda: float(t[(t["ano"] == ANO_REF) & (t["tuc"].astype(str).str.zfill(3) == "210")
                                    & (t["gru_ten"] == "AT")]["equipamentos"].sum()))
    cm("tuc210_mt", lambda: float(t[(t["ano"] == ANO_REF) & (t["tuc"].astype(str).str.zfill(3) == "210")
                                    & (t["gru_ten"] == "MT")]["equipamentos"].sum()))
    cm("tuc210_at_pct", lambda: div(P["ms"].get("tuc210_at"), P["ms"]["tuc210_at"] + P["ms"]["tuc210_mt"], 100))
    cs("tuc210_at_pct", lambda: None)
    reg = S["regra_ms"]
    cm("regra_eventos", lambda: float(reg["n_eventos"]))
    cm("regra_controles", lambda: float(reg["n_controles"]))
    cm("regra_min_eventos", lambda: float(reg["min_eventos"]))
    cm("regra_min_controles", lambda: float(reg["min_controles"]))
    mt = S["mt_ref"]
    cs("regra_eventos", lambda: float(mt["n_eventos"]))
    cs("regra_controles", lambda: float(mt["n_controles"]))
    tr = S["transicoes_ms"]
    cm("recl_ganhos_brutos", lambda: float(tr["religadores_ganhos"].sum()))
    cm("recl_ganho_liquido", lambda: float(tr["ganho_liquido"].sum()))
    cm("recl_transicoes", lambda: float(tr.shape[0]))
    cm("telecom_2024", lambda: float(S["snapshot_ms"].set_index("ano_snapshot").loc[2024, "religadores_telecomandados"]))
    cm("telecom_2025", lambda: float(S["snapshot_ms"].set_index("ano_snapshot").loc[2025, "religadores_telecomandados"]))
    cm("recl_auto_2024", lambda: float(S["snapshot_ms"].set_index("ano_snapshot").loc[2024, "religadores"]))
    cm("recl_auto_2025", lambda: float(S["snapshot_ms"].set_index("ano_snapshot").loc[2025, "religadores"]))
    ex = S["expurgo_codigos"]
    for d_, cc in (("mt", cs), ("ms", cm)):
        cc("expurgo_cod1_anos", lambda d_=d_: ", ".join(
            map(str, sorted(ex[(ex["distribuidora"] == SIGLA[d_]) & (ex["codigo"].astype(str) == "1")]["ano"].unique()))) or "nenhum")
    cm("corr_mensal_sem_buracos", lambda: float(S["dec_correlacao_ms"].iloc[1]["corr_dec"]))
    cm("meses_buraco", lambda: str(S["dec_correlacao_ms"].iloc[1]["meses_excluidos"]).replace("-", "/"))


def linha_vinculo(v: pd.DataFrame, d: str, ano: int, col: str) -> float:
    x = v[(v["distribuidora"] == SIGLA[d]) & (v["ano"] == ano) & (v["corte"] == "todos") & (v["escopo"] == "falhas")]
    return float(x[col].iloc[0])


def registros_mes(df: pd.DataFrame, d: str, ano: int, mes: int) -> float:
    """Registros de interrupção no mês; 0 se a distribuidora tem o ano no arquivo mas não o mês."""
    x = df[(df["distribuidora"] == SIGLA[d]) & (df["ano"] == ano)]
    if x.empty:
        raise ValueError(f"sem registros de {SIGLA[d]} em {ano}")
    return float(x[x["mes"] == mes]["registros"].sum())


def meses_com_registro(df: pd.DataFrame, d: str, ano: int) -> tuple[list[int], list[int]]:
    """Meses do ano com registro de interrupção e meses sem registro até o último mês presente."""
    x = df[(df["distribuidora"] == SIGLA[d]) & (df["ano"] == ano) & (df["registros"] > 0)]
    if x.empty:
        raise ValueError(f"sem registros de {SIGLA[d]} em {ano}")
    presentes = sorted(int(m) for m in x["mes"].unique())
    return presentes, [m for m in range(1, presentes[-1] + 1) if m not in presentes]


def faixas_de_meses(meses: list[int]) -> str:
    """[1, 2, 4, 5] -> "janeiro a fevereiro e abril a maio"; lista vazia -> "nenhum"."""
    if not meses:
        return "nenhum"
    grupos, ini, ant = [], meses[0], meses[0]
    for m in meses[1:]:
        if m == ant + 1:
            ant = m
            continue
        grupos.append((ini, ant))
        ini = ant = m
    grupos.append((ini, ant))
    partes = [MESES[a - 1] if a == b else f"{MESES[a - 1]} a {MESES[b - 1]}" for a, b in grupos]
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]


def media_compensacoes(df: pd.DataFrame, ini: int, fim: int) -> float:
    """Média anual (R$) de ``pg_reais`` em ``ini`` a ``fim``; falha se faltar algum ano."""
    x = df[df["ano"].between(ini, fim)].set_index("ano")["pg_reais"]
    if len(x) != fim - ini + 1:
        raise ValueError(f"faltam anos de compensação entre {ini} e {fim}")
    return float(x.mean())


def vida_mediana(qual: pd.DataFrame, vida: pd.DataFrame, classe: str):
    """Vida mediana (anos) do cenário principal, só se a classe passou no teste de consistência; senão ``None``."""
    ok = bool(qual.set_index("classe").loc[classe, "confiavel"])
    if not ok:
        return None
    x = vida[(vida["classe"] == classe) & (vida["cenario"] == "principal")]
    return float(x["mediana"].iloc[0])


# --------------------------------------------------------------------------------------------- métricas (o que cada número é)
@dataclass(frozen=True)
class Espec:
    bloco: str
    chave: str
    nome: str
    unidade: str
    casas: int
    definicao: str
    numerador: str
    denominador: str
    fontes: tuple[str, ...]
    diferenca: str             # "Não", "Possível" ou "Sim": a diferença pode vir de definição?
    nota: str = ""
    pct: bool = False
    com_razao: bool = True


def _e(*a, **k) -> Espec:
    return Espec(*a, **k)


JAN = f"média {JANELA}"
ORC = fmt_mi(ORCAMENTO_REF, 0)
ESPECS: list[Espec] = [
    # (a) tamanho
    _e("a", "n_alim", "Alimentadores (circuitos de média tensão) no cadastro de 31/12/2025", "alimentadores", 0,
       "Linhas de risco_alimentador (um alimentador por linha).", "Contagem de alimentadores", "—", ("risco",),
       "Possível", "A Energisa MT conta todos os circuitos do cadastro; o painel da Energisa MS exclui os sem rede e "
       "sem consumidor.", com_razao=False),
    _e("a", "vazios", "Circuitos sem rede de média tensão e sem consumidor (2025)", "circuitos", 0,
       "Circuitos do cadastro de 2025 com 0 km de rede e 0 consumidor.", "Contagem de circuitos vazios", "—",
       ("circuitos_vazios",), "Sim", "Entram na contagem de alimentadores da Energisa MT e ficam fora do painel da "
       "Energisa MS.", com_razao=False),
    _e("a", "sem_uc", "Circuitos sem nenhum consumidor (2025)", "circuitos", 0,
       "Circuitos do cadastro de 2025 com 0 consumidor (podem ter rede).", "Contagem de circuitos sem consumidor", "—",
       ("circuitos_vazios",), "Não", com_razao=False),
    _e("a", "uc", "Consumidores", "consumidores", 0, "Soma de n_uc dos alimentadores (cadastro de 31/12/2025).",
       "Σ n_uc", "—", ("risco",), "Não", "Outros repositórios usam o cadastro de 2024 ou outra contagem; ver a seção 9.",
       com_razao=False),
    _e("a", "km", "Rede de média tensão", "km", 0, "Soma de rede_mt_km dos alimentadores (cadastro de 2025).",
       "Σ rede_mt_km", "—", ("risco",), "Não", com_razao=False),
    _e("a", "uc_por_km", "Consumidores por km de rede de média tensão", "consumidores/km", 1,
       "Consumidores divididos pela rede de média tensão.", "Consumidores", "km de rede de média tensão", ("risco",), "Não"),
    _e("a", "km_por_alim", "Rede de média tensão por alimentador", "km", 1, "Média por alimentador.",
       "km de rede", "Alimentadores", ("risco",), "Possível", "Muda com a contagem de alimentadores (circuitos vazios)."),
    _e("a", "uc_por_alim", "Consumidores por alimentador", "consumidores", 0, "Média por alimentador.",
       "Consumidores", "Alimentadores", ("risco",), "Possível", "Muda com a contagem de alimentadores (circuitos vazios)."),
    # (b) falhas
    _e("b", "falhas_100km", f"Falhas na média tensão por 100 km por ano ({JAN})", "falhas/100 km/ano", 1,
       "Registros da ANEEL de interrupção interna, não programada, em média tensão, ligados a um circuito.",
       "Σ n_falhas por ano (média 2023-2025)", "km de rede de média tensão ÷ 100", ("falhas_modo", "risco"),
       "Possível", "É contagem de registros, não de eventos; não medi se as duas distribuidoras registram da mesma forma."),
    _e("b", "falhas_1000uc", f"Falhas na média tensão por mil consumidores por ano ({JAN})", "falhas/mil consumidores/ano", 1,
       "Mesma contagem de falhas, por consumidor.", "Σ n_falhas por ano (média 2023-2025)", "Consumidores ÷ 1.000",
       ("falhas_modo", "risco"), "Possível", "Mesma ressalva dos registros."),
    _e("b", "chi_por_registro", f"CHI por registro de falha ({JAN})", "consumidor-hora/registro", 0,
       "Consumidor-hora interrompido médio de cada registro de falha.", "Σ CHI por ano", "Σ n_falhas por ano",
       ("falhas_modo",), "Possível", "Depende de como cada distribuidora abre e divide os registros."),
    # (c) CHI
    _e("c", "chi_uc", f"CHI das falhas por consumidor por ano, total ({JAN})", "h/consumidor/ano", 1,
       "Consumidor-hora interrompido (CHI) das falhas, com todo o CHI (inclusive o expurgado).", "Σ CHI por ano",
       "Consumidores", ("falhas_modo", "risco"), "Não"),
    _e("c", "chi_reg_uc", f"CHI das falhas por consumidor por ano, regulatório ({JAN})", "h/consumidor/ano", 1,
       "CHI sem expurgo e com 3 minutos ou mais: o que entra no DEC e nas compensações.",
       "Σ (CHI do modo × fração regulatória do modo), por ano", "Consumidores",
       ("falhas_modo", "frac_reg", "risco"), "Sim", "A regra de expurgo pesa muito diferente nas duas empresas."),
    _e("c", "frac_exp", f"Fração do CHI das falhas que é expurgada ({JAN})", "%", 1,
       "1 − CHI regulatório ÷ CHI total (dia crítico, situação de emergência etc.).", "CHI regulatório por ano",
       "CHI total por ano", ("falhas_modo", "frac_reg"), "Sim", "A regra de expurgo pesa muito diferente.", pct=True),
    _e("c", "chi_km", f"CHI das falhas por km de rede de média tensão por ano ({JAN})", "h/km/ano", 1,
       "CHI total das falhas por km de rede.", "Σ CHI por ano", "km de rede de média tensão", ("falhas_modo", "risco"),
       "Não"),
    # (d) DEC e FEC
    _e("d", "dec_of", f"DEC oficial de {ANO_REF}", "h", 2, "Duração equivalente de interrupção por consumidor, "
       "publicada pela ANEEL (todas as interrupções, com a regra de expurgo).", "Σ DEC dos conjuntos × consumidores",
       "Consumidores do conjunto", ("validacao",), "Não"),
    _e("d", "fec_of", f"FEC oficial de {ANO_REF}", "interrupções/consumidor", 2,
       "Frequência equivalente de interrupção por consumidor, publicada pela ANEEL.", "Σ FEC dos conjuntos × consumidores",
       "Consumidores do conjunto", ("validacao",), "Não"),
    _e("d", "dec_calc", f"DEC recalculado das interrupções, {ANO_REF}", "h", 2,
       "DEC reconstruído das interrupções individuais, sem expurgo e com 3 minutos ou mais.", "Σ CHI dos conjuntos",
       "Consumidores do conjunto", ("validacao",), "Não"),
    _e("d", "anos_nao_batem", f"Anos em que o DEC ou o FEC recalculado difere do oficial em mais de "
       f"{fmt(100 * TOLERANCIA_DEC, 0)}%", "anos", 0, "Diferença relativa |calculado − oficial| ÷ oficial acima da tolerância.",
       "|calculado − oficial|", "oficial", ("validacao",), "Sim",
       f"Em {ANO_PARCIAL} os dois lados cobrem meses diferentes; a Energisa MS tem meses com problema nos dados (seção 4).",
       com_razao=False),
    _e("d", "corr_mensal", "Correlação mensal por conjunto entre DEC calculado e oficial (todos os meses)", "correlação", 4,
       "Valor único do arquivo, repetido em todas as linhas.", "—", "—", ("validacao",), "Sim",
       "A correlação da Energisa MS é menor; há meses com problema nos dados (seção 4).", com_razao=False),
    # (e) compensações
    _e("e", "comp_paga_uc", f"Compensações pagas por consumidor por ano (média {JANELA_COMP[0]}-{JANELA_COMP[1]})", "R$/consumidor/ano", 2,
       "Σ dos indicadores PG* da ANEEL por conjunto, lidos sem as linhas repetidas do arquivo.", "R$ pagos por ano",
       "Consumidores (cadastro de 2025, denominador fixo)", ("compensacoes_ms", "risco"), "Não",
       "Para a Energisa MT não há série de compensações pagas nos arquivos publicados."),
    _e("e", "risco_comp_uc", "Risco previsto em compensações para 2026 (modelo), por consumidor", "R$/consumidor/ano", 2,
       "Previsão do modelo: CHI regulatório previsto × R$ por CHI das compensações de 2022-2025. Não é compensação paga.",
       "Σ risco_rs_compensacao", "Consumidores", ("risco",), "Possível",
       "Depende da fração regulatória e do R$ por CHI de cada empresa."),
    # (f) concentração e risco
    _e("f", "top10_social", "Parcela do risco social previsto nos 10% de alimentadores de maior risco", "%", 1,
       "Os round(n × 10%) alimentadores de maior risco_rs_social.", "Σ risco_rs_social dos 10% de maior risco",
       "Σ risco_rs_social", ("risco",), "Possível", "O número de alimentadores muda (circuitos vazios).", pct=True),
    _e("f", "top20_social", "Parcela do risco social previsto nos 20% de alimentadores de maior risco", "%", 1,
       "Os round(n × 20%) alimentadores de maior risco_rs_social.", "Σ risco_rs_social dos 20% de maior risco",
       "Σ risco_rs_social", ("risco",), "Possível", "O número de alimentadores muda (circuitos vazios).", pct=True),
    _e("f", "top10_comp", "Parcela do risco em compensações nos 10% de alimentadores de maior risco", "%", 1,
       "Os round(n × 10%) alimentadores de maior risco_rs_compensacao.", "Σ risco_rs_compensacao dos 10% de maior risco",
       "Σ risco_rs_compensacao", ("risco",), "Possível", "O número de alimentadores muda (circuitos vazios).", pct=True),
    _e("f", "top20_comp", "Parcela do risco em compensações nos 20% de alimentadores de maior risco", "%", 1,
       "Os round(n × 20%) alimentadores de maior risco_rs_compensacao.", "Σ risco_rs_compensacao dos 20% de maior risco",
       "Σ risco_rs_compensacao", ("risco",), "Possível", "O número de alimentadores muda (circuitos vazios).", pct=True),
    _e("f", "risco_social_uc", "Risco social previsto para 2026 (modelo), por consumidor", "R$/consumidor/ano", 1,
       "Previsão do modelo: compensação + energia não suprida (custo da energia não suprida: premissa ilustrativa).",
       "Σ risco_rs_social", "Consumidores", ("risco",), "Possível", "Mesmas premissas nas duas empresas, sem calibrar."),
    _e("f", "dec_previsto", "DEC previsto para 2026 por falhas na média tensão (modelo)", "h", 2,
       "Previsão do modelo para 2026 (CHI regulatório previsto por consumidor).", "Σ dec_contribuicao_h", "—",
       ("risco",), "Possível", "Depende da fração regulatória (expurgo)."),
    # (g) carteira
    _e("g", "razao_carteira", f"Carteira ótima ÷ regra tradicional, VPL em 10 anos, orçamento de {ORC} (visão social)",
       "razão", 2, "VPL da carteira escolhida por programação inteira dividido pelo da regra tradicional "
       "(piores alimentadores primeiro, pacote padrão).", "VPL da carteira ótima", "VPL da regra tradicional",
       ("fronteira_social",), "Possível", "Premissas ilustrativas iguais, sem calibrar; a elegibilidade das intervenções "
       "depende do cadastro de cada empresa.", com_razao=False),
    _e("g", "investido_otimo", f"Investido pela carteira ótima com orçamento de {ORC} (visão social)", "R$", 0,
       "Custo da carteira ótima.", "Σ custo das intervenções escolhidas", "—", ("fronteira_social",), "Possível",
       com_razao=False),
    _e("g", "investido_max_otimo", "Maior investimento da carteira ótima entre os orçamentos testados (visão social)", "R$", 0, "A ótima só escolhe pacotes de VPL positivo e pode parar de investir.",
       "máx. do investido da carteira ótima", "—", ("fronteira_social",), "Possível", com_razao=False),
    _e("g", "n_otimo", f"Alimentadores tratados pela carteira ótima ({ORC}, social)", "alimentadores", 0,
       "Alimentadores com pacote na carteira ótima.", "Contagem", "—", ("fronteira_social",), "Possível", com_razao=False),
    _e("g", "n_tradicional", f"Alimentadores tratados pela regra tradicional ({ORC}, social)", "alimentadores", 0,
       "Alimentadores com pacote na regra tradicional.", "Contagem", "—", ("fronteira_social",), "Possível", com_razao=False),
    _e("g", "vpl_otimo_caixa", f"VPL da carteira ótima na visão de caixa (só compensações), orçamento de {ORC}", "R$", 0,
       "VPL em 10 anos contando só a compensação evitada.", "VPL da carteira ótima", "—", ("fronteira_caixa",), "Possível",
       com_razao=False),
    _e("g", "vpl_tradicional_caixa", f"VPL da regra tradicional na visão de caixa, orçamento de {ORC}", "R$", 0,
       "VPL em 10 anos contando só a compensação evitada.", "VPL da regra tradicional", "—", ("fronteira_caixa",), "Possível",
       com_razao=False),
    _e("g", "investido_max_otimo_caixa", "Maior investimento da carteira ótima na visão de caixa entre os orçamentos testados", "R$", 0,
       "Obras com VPL positivo contando só a compensação.", "máx. do investido da carteira ótima", "—",
       ("fronteira_caixa",), "Possível", com_razao=False),
    # (h) subestações
    _e("h", "ses", "Subestações com transformador de alta para média tensão e carga cadastrada (2025)", "subestações", 0,
       "SEs do índice de saúde e criticidade.", "Contagem de SEs", "—", ("se_resumo",), "Possível",
       "Outros repositórios contam as SEs com outro filtro, e a regra que liga alimentador a SE difere; ver a seção 9.",
       com_razao=False),
    _e("h", "ses_por_1000km", "Subestações por 1.000 km de rede de média tensão", "SEs/1.000 km", 2,
       "SEs do índice por km de rede.", "Contagem de SEs", "km de rede ÷ 1.000", ("se_resumo", "risco"), "Possível"),
    _e("h", "uc_por_se", "Consumidores por subestação", "consumidores/SE", 0, "Consumidores atendidos por SE (base do índice).",
       "Consumidores dos alimentadores das SEs", "SEs", ("se_resumo",), "Possível"),
    _e("h", "ses_um_trafo_pct", "Subestações com um único transformador de média tensão", "% das SEs", 1,
       "SEs sem capacidade firme na própria SE.", "SEs com um trafo", "SEs", ("se_resumo",), "Possível",
       "A regra que liga alimentador a SE difere (Energisa MS: pelo circuito).", pct=True),
    _e("h", "uc_um_trafo_pct", "Consumidores atendidos por subestações com um único transformador", "% dos consumidores", 1,
       "Consumidores das SEs de um trafo só.", "Consumidores dessas SEs", "Consumidores das SEs do índice", ("se_resumo",),
       "Possível", pct=True),
    _e("h", "uc_sem_transf_pct", "Consumidores em alimentadores sem chave normalmente aberta para outra SE", "% dos consumidores",
       1, "Alimentadores sem rota de transferência para alimentador de outra SE.", "Consumidores sem rota", "Consumidores "
       "das SEs do índice", ("se_resumo",), "Possível", pct=True),
    _e("h", "ses_n1_ventilacao", "SEs com 2 ou mais trafos cujo pico estimado não cabe se o maior sair (estágios de ventilação)",
       "subestações", 0, "Teste N-1 com a capacidade dos estágios de ventilação cadastrados (a base da Energisa MT).",
       "Contagem de SEs", "—", ("se_resumo",), "Possível",
       "Na Energisa MS o número principal usa a potência nominal (ver a seção 8).", com_razao=False),
    _e("h", "ses_n1", "SEs com 2 ou mais trafos sem folga N-1 (base de cada publicação)", "subestações", 0,
       "Mesmo teste com a base principal de cada repositório: estágios de ventilação (Energisa MT) e potência nominal "
       "(Energisa MS).", "Contagem de SEs", "—", ("se_resumo",), "Sim", "Bases diferentes: não comparar este par.",
       com_razao=False),
    _e("h", "ses_util80", "SEs com pico estimado acima de 80% da potência instalada", "subestações", 0,
       "Utilização estimada no pico.", "Contagem de SEs", "—", ("se_resumo",), "Possível",
       "O pico vem da energia dos circuitos e de um fator de carga da Energisa MT.", com_razao=False),
    _e("h", "eventos_se", "Eventos de SE por ano (interrupção simultânea em 3 ou mais alimentadores)", "eventos/ano", 0,
       "Média anual de eventos de SE no período do índice.", "Contagem de eventos", "—", ("se_resumo",), "Possível",
       com_razao=False),
    _e("h", "eventos_se_pct_chi", "Parcela do CHI das falhas que vem de eventos de SE", "%", 1,
       "CHI de eventos de SE ÷ CHI das falhas de média tensão.", "CHI de eventos de SE", "CHI das falhas",
       ("se_resumo",), "Possível", pct=True),
    # (h) religadores
    _e("h", "recl_cad_100km", "Religadores no cadastro de 2025 por 100 km de rede (TIP_UNID 32)", "religadores/100 km", 2,
       "Religadores do cadastro (recloser-performance).", "Religadores no cadastro", "km de rede ÷ 100", ("recl_diag", "risco"),
       "Possível", "Outros repositórios contam os religadores com outro filtro (seção 9)."),
    _e("h", "recl_linha_100km", "Religadores de linha (com clientes a jusante) por 100 km de rede", "religadores/100 km", 2,
       "Religadores com clientes a jusante, fora os de saída da subestação.", "Religadores de linha", "km de rede ÷ 100",
       ("recl_diag", "risco"), "Possível"),
    _e("h", "recl_linha", "Religadores de linha (com clientes a jusante)", "religadores", 0,
       "Religadores com clientes a jusante, fora os de saída da subestação.", "Contagem", "—", ("recl_diag",), "Possível",
       com_razao=False),
    _e("h", "recl_saida", "Religadores que fazem papel de disjuntor de saída", "religadores", 0,
       "Religadores na subestação, antes do início do alimentador.", "Contagem", "—", ("recl_diag",), "Possível",
       com_razao=False),
    _e("h", "recl_telecom_pct", "Religadores com telecomando (TLCD = 1) no cadastro de 2025", "% dos religadores", 1,
       "Religadores do cadastro com telecomando.", "Religadores com TLCD = 1", "Religadores no cadastro", ("recl_diag",),
       "Possível", "O número de religadores telecomandados muda muito de um cadastro para o outro na Energisa MS (seção 9).", pct=True),
    _e("h", "zona_mediana", "Clientes na zona de proteção do religador de linha, mediana", "clientes", 0,
       "Clientes entre o religador e o próximo religador a jusante.", "Mediana das zonas", "—", ("recl_diag",), "Possível"),
    _e("h", "zona_menos50", "Zonas de religador de linha com menos de 50 clientes", "% das zonas", 1,
       "Zonas com menos de 50 clientes.", "Zonas com < 50 clientes", "Zonas de religador de linha", ("recl_diag",),
       "Possível", pct=True),
    _e("h", "zonas_top10_chi", "Parcela do CHI esperado nas 10% de zonas de proteção mais críticas", "%", 1,
       "CHI esperado do modelo de zonas nas zonas de maior CHI.", "CHI esperado do top 10%", "CHI esperado total",
       ("recl_diag",), "Possível", "Vem do modelo de zonas, que calibra pior na Energisa MS (seção 9).", pct=True),
    _e("h", "alim_sem_recl_pct", "Alimentadores sem nenhum religador de linha", "% dos alimentadores", 1,
       "Alimentadores sem religador de linha.", "Alimentadores sem religador de linha", "Alimentadores (cadastro de 2025)",
       ("recl_diag", "risco"), "Possível", pct=True),
    _e("h", "uc_ligadas_saida", "Clientes ligados à saída do seu alimentador na topologia reconstruída (2025)",
       "% dos clientes", 3, "Clientes alcançados no grafo a partir da saída do alimentador.", "Clientes alcançados",
       "Clientes do cadastro", ("recl_topo",), "Não", pct=True),
]
ESPEC_POR_CHAVE = {e.chave: e for e in ESPECS}


def montar_metricas(P: dict) -> pd.DataFrame:
    linhas = []
    for e in ESPECS:
        mt, ms = P["mt"].get(e.chave), P["ms"].get(e.chave)
        linhas.append({
            "bloco": e.bloco, "id": e.chave, "metrica": e.nome, "unidade": e.unidade,
            "energisa_mt": ND if mt is None else mt, "energisa_ms": ND if ms is None else ms,
            "razao_ms_mt": (razao(ms, mt) if e.com_razao else None) if numerico(ms) and numerico(mt) else None,
            "definicao": e.definicao, "numerador": e.numerador, "denominador": e.denominador,
            "fonte_mt": origem(e.fontes, "mt"), "fonte_ms": origem(e.fontes, "ms"),
            "definicao_pode_diferir": e.diferenca, "nota": e.nota})
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------------------------- tabelas
def por_ano(df: pd.DataFrame | None, d: str, **filtros) -> pd.DataFrame | None:
    if df is None:
        return None
    x = df[df["distribuidora"] == SIGLA[d]]
    for k, v in filtros.items():
        x = x[x[k] == v]
    return x


def tabelas(C: dict, S: dict, P: dict, avisos: list[str]) -> dict[str, pd.DataFrame]:
    T: dict[str, pd.DataFrame] = {}
    # (b) por modo e por ano
    linhas = []
    for m in [*MODOS, "TOTAL"]:
        sufixo = "" if m == "TOTAL" else f":{m}"
        t = {"modo": m}
        for d in DIST:
            p = P[d]
            t[f"falhas_ano_{d}"] = p.get(f"falhas_ano{sufixo}")
            t[f"falhas_100km_{d}"] = p.get(f"falhas_100km{sufixo}")
            t[f"falhas_1000uc_{d}"] = p.get(f"falhas_1000uc{sufixo}")
            t[f"pct_das_falhas_{d}"] = p.get(f"falhas_pct{sufixo}") if m != "TOTAL" else 100.0
            t[f"falhas_100km_publicado_{d}"] = p.get(f"falhas_100km_pub{sufixo}")
        t["razao_ms_mt_100km"] = razao(t["falhas_100km_ms"], t["falhas_100km_mt"])
        linhas.append(t)
    T["falhas_por_modo"] = nd_df(pd.DataFrame(linhas))
    T["falhas_por_ano"] = serie_anual(S, P)
    # (c) por modo
    linhas = []
    for m in [*MODOS, "TOTAL"]:
        sufixo = "" if m == "TOTAL" else f":{m}"
        t = {"modo": m}
        for d in DIST:
            t[f"chi_uc_{d}"] = P[d].get(f"chi_uc{sufixo}")
            t[f"chi_reg_uc_{d}"] = P[d].get(f"chi_reg_uc{sufixo}")
            t[f"pct_expurgado_{d}"] = P[d].get(f"frac_exp{sufixo}")
        linhas.append(t)
    T["chi_por_modo"] = nd_df(pd.DataFrame(linhas))
    # (d) DEC e FEC por ano
    T["dec_fec_oficial"] = tabela_dec(C)
    # (e) compensações por ano (só a Energisa MS tem a série)
    T["compensacoes_por_ano"] = tabela_compensacoes(S, P)
    # (f) concentração
    linhas = []
    for vis, nome_vis in (("social", "risco social"), ("comp", "risco em compensações")):
        for frac in (10, 20):
            t = {"visao": nome_vis, "pct_alimentadores": frac}
            for d in DIST:
                t[f"alimentadores_no_grupo_{d}"] = P[d].get(f"k{frac}_{vis}")
                t[f"parcela_do_risco_{d}"] = P[d].get(f"top{frac}_{vis}")
                t[f"parcela_publicada_{d}"] = P[d].get(f"top{frac}_social_pub") if vis == "social" else None
            linhas.append(t)
    T["concentracao_risco"] = nd_df(pd.DataFrame(linhas))
    # (g) carteira por orçamento
    T["carteira_por_orcamento"] = tabela_carteira(C)
    T["elegibilidade_catalogo"] = S["elegibilidade"].copy() if S.get("elegibilidade") is not None else nd_df(pd.DataFrame())
    # (i) o que não dá para comparar
    T["nao_comparavel"] = nao_comparavel(C, S, P)
    return T


def nd_df(df: pd.DataFrame) -> pd.DataFrame:
    """Troca os vazios por "não disponível" (colunas viram texto onde faltar dado)."""
    return df.astype(object).where(df.notna(), ND)


def serie_anual(S: dict, P: dict) -> pd.DataFrame:
    """Falhas e CHI por ano (todas as falhas de média tensão, ligadas ou não a um circuito), com denominador fixo de 2025."""
    v = S.get("vinculo")
    linhas: dict[int, dict] = {}
    for d in DIST:
        x = None
        if v is not None:
            x = v[(v["distribuidora"] == SIGLA[d]) & (v["corte"] == "todos") & (v["escopo"] == "falhas")]
        if x is None or x.empty:
            continue
        for _, r in x.iterrows():
            t = linhas.setdefault(int(r["ano"]), {"ano": int(r["ano"]), "ano_parcial": int(r["ano"]) >= ANO_PARCIAL})
            t[f"registros_{d}"] = float(r["eventos"])
            t[f"falhas_100km_{d}"] = div(r["eventos"], P[d].get("km"), 100)
            t[f"falhas_1000uc_{d}"] = div(r["eventos"], P[d].get("uc"), 1000)
            t[f"chi_uc_{d}"] = div(r["chi"], P[d].get("uc"))
            t[f"chi_por_registro_{d}"] = div(r["chi"], r["eventos"])
            t[f"pct_ligado_a_circuito_{d}"] = float(r["pct_eventos"])
    fe = S.get("falhas_expurgo_ms")
    if fe is not None:
        for ano, g in fe.groupby("ano"):
            t = linhas.setdefault(int(ano), {"ano": int(ano), "ano_parcial": int(ano) >= ANO_PARCIAL})
            sem = float(g[g["expurgo"] == "NAO HOUVE EXPURGO"]["chi"].sum())
            t["chi_sem_expurgo_uc_ms"] = div(sem, P["ms"].get("uc"))
            t["pct_chi_expurgado_ms"] = 100 * (1 - sem / float(g["chi"].sum())) if g["chi"].sum() else None
    cols = ["ano", "ano_parcial"] + [f"{k}_{d}" for k in ("registros", "falhas_100km", "falhas_1000uc", "chi_uc", "chi_por_registro",
                                                          "pct_ligado_a_circuito") for d in DIST] + [
        "chi_sem_expurgo_uc_ms", "pct_chi_expurgado_ms"]
    df = pd.DataFrame([linhas[a] for a in sorted(linhas)], columns=cols) if linhas else pd.DataFrame(columns=cols)
    df["chi_sem_expurgo_uc_mt"] = None
    df["pct_chi_expurgado_mt"] = None
    return nd_df(df)


def tabela_dec(C: dict) -> pd.DataFrame:
    frames = []
    for d in DIST:
        v = C[d].get("validacao")
        if v is None:
            continue
        x = v.copy()
        x["dif_dec_pct"] = 100 * (x["DEC_calculado"] - x["DEC_oficial"]) / x["DEC_oficial"]
        x["dif_fec_pct"] = 100 * (x["FEC_calculado"] - x["FEC_oficial"]) / x["FEC_oficial"]
        x["dec_bate"] = x["dif_dec_pct"].abs() <= 100 * TOLERANCIA_DEC
        x["fec_bate"] = x["dif_fec_pct"].abs() <= 100 * TOLERANCIA_DEC
        x = x.drop(columns=["corr_mensal_conjunto_DEC"]).add_suffix(f"_{d}").rename(columns={f"ano_{d}": "ano"})
        frames.append(x)
    if not frames:
        return pd.DataFrame(columns=["ano"])
    out = frames[0]
    for f in frames[1:]:
        out = out.merge(f, on="ano", how="outer")
    out.insert(1, "ano_parcial", out["ano"] >= ANO_PARCIAL)
    return nd_df(out.sort_values("ano").reset_index(drop=True))


def tabela_compensacoes(S: dict, P: dict) -> pd.DataFrame:
    c = S.get("compensacoes_ms")
    anos = sorted(c["ano"].astype(int).unique()) if c is not None else []
    linhas = []
    for ano in anos:
        pg = float(c[c["ano"] == ano]["pg_reais"].sum())
        linhas.append({"ano": ano, "ano_parcial": ano >= ANO_PARCIAL, "pg_reais_ms": pg,
                       "pg_por_consumidor_ms": div(pg, P["ms"].get("uc")), "pg_reais_mt": None, "pg_por_consumidor_mt": None})
    cols = ["ano", "ano_parcial", "pg_reais_mt", "pg_por_consumidor_mt", "pg_reais_ms", "pg_por_consumidor_ms"]
    return nd_df(pd.DataFrame(linhas, columns=cols))


def tabela_carteira(C: dict) -> pd.DataFrame:
    linhas = []
    for chave, vis in (("fronteira_social", "social"), ("fronteira_caixa", "caixa (só compensações)")):
        orcs = set()
        for d in DIST:
            f = C[d].get(chave)
            if f is not None:
                orcs |= set(f["orcamento"].astype(float))
        for o in sorted(orcs):
            t = {"visao": vis, "orcamento": o}
            for d in DIST:
                f = C[d].get(chave)
                for met in ("otimo", "guloso", "tradicional"):
                    for col, nome in (("vpl", "vpl"), ("investido", "investido"), ("n_alimentadores", "n_alim")):
                        try:
                            t[f"{nome}_{met}_{d}"] = vpl_de(f, met, o, col)
                        except (TypeError, IndexError, KeyError):
                            t[f"{nome}_{met}_{d}"] = None
                try:
                    r_ = razao_carteira(f, o)
                    t[f"razao_otimo_tradicional_{d}"] = "não se aplica" if r_ is None else r_
                except (TypeError, IndexError, KeyError):
                    t[f"razao_otimo_tradicional_{d}"] = None
            linhas.append(t)
    return nd_df(pd.DataFrame(linhas))


def nao_comparavel(C: dict, S: dict, P: dict) -> pd.DataFrame:
    """Lista do que não dá para comparar, com a evidência que sai dos arquivos publicados."""
    mt, ms = P["mt"], P["ms"]

    def f0(d_, chave):
        return fmt(P[d_].get(chave), 0)

    vz = S.get("circuitos_vazios")
    try:
        vz_antigo = f"{fmt(linha(vz, 'ms', 2019, 'sem_rede_e_sem_uc'), 0)} de {fmt(linha(vz, 'ms', 2019, 'circuitos'), 0)}"
    except (TypeError, AttributeError, IndexError, KeyError):
        vz_antigo = ND
    tuc_total = None
    if numerico(ms.get("tuc210_at")) and numerico(ms.get("tuc210_mt")):
        tuc_total = ms["tuc210_at"] + ms["tuc210_mt"]
    linhas = [
        ("Circuitos vazios",
         (f"Usa todos os circuitos do cadastro: {f0('mt', 'vazios')} dos {f0('mt', 'n_alim')} de {ANO_REF} não têm rede de média "
          "tensão nem consumidor."),
         (f"O painel exclui circuitos sem rede e sem consumidor: {f0('ms', 'vazios')} em {ANO_REF} (no cadastro de 2019 eram "
          f"{vz_antigo})."),
         ("Não muda somas por km nem por consumidor (os vazios têm zero nos dois). Muda a contagem de alimentadores, as médias "
          "por alimentador e os grupos de 10% e 20% de maior risco."),
         "circuitos_vazios.csv"),
        ("Regra de expurgo",
         (f"{fmt(mt.get('frac_exp'), 1, True)} do CHI das falhas é expurgado (descarga atmosférica: "
          f"{fmt(mt.get('frac_exp:DESCARGA_ATMOSFERICA'), 0, True)}; vento: {fmt(mt.get('frac_exp:VENTO'), 0, True)})."),
         (f"{fmt(ms.get('frac_exp'), 1, True)} do CHI das falhas é expurgado (descarga atmosférica: "
          f"{fmt(ms.get('frac_exp:DESCARGA_ATMOSFERICA'), 0, True)}; vento: {fmt(ms.get('frac_exp:VENTO'), 0, True)})."),
         ("O CHI total é comparável. O CHI regulatório, o DEC previsto por falhas, as compensações e a visão de caixa pesam "
          "muito diferente nas duas empresas."),
         "falhas_por_modo.csv; frac_chi_regulatorio_modo.csv"),
        ("Anos de snapshot e denominadores",
         (f"Consumidores: {f0('mt', 'uc_snapshot_2024')} no cadastro de 2024 e {f0('mt', 'uc_snapshot_2025')} no de {ANO_REF} "
          f"(recloser-performance); {f0('mt', 'uc_valor_json')} no automation-impact; {f0('mt', 'uc')} neste documento."),
         (f"Consumidores: {f0('ms', 'uc_snapshot_2024')} no cadastro de 2024 e {f0('ms', 'uc_snapshot_2025')} no de {ANO_REF} "
          f"(recloser-performance); {f0('ms', 'uc_valor_json')} no automation-impact; {f0('ms', 'uc')} neste documento."),
         ("O automation-impact usa o cadastro de 2024 e os demais, o de 2025. Números de repositórios diferentes não se misturam; "
          f"as taxas deste documento usam todas o cadastro de {ANO_REF} do distribution-asset-risk."),
         "qualidade_topologia.json; valor.json; risco_alimentador.parquet"),
        (f"Meses de {ANO_PARCIAL}",
         (f"Meses com registro de interrupção em {ANO_PARCIAL}: {mt.get('meses_parcial', ND)}. Meses sem registro: "
          f"{mt.get('meses_faltando', ND)} ({f0('mt', 'registros_mar_2026')} registros em março)."),
         (f"Meses com registro de interrupção em {ANO_PARCIAL}: {ms.get('meses_parcial', ND)}. Meses sem registro: "
          f"{ms.get('meses_faltando', ND)} ({f0('ms', 'registros_mar_2026')} registros em março)."),
         (f"Todo número de {ANO_PARCIAL} da Energisa MS (DEC, checagem parcial do modelo, elemento que abriu o circuito) deixa de "
          "fora o mês sem registro; o recorte de meses não é o mesmo nos dois lados."),
         "interrupcoes_por_mes.csv"),
        (f"Checagem do modelo em {ANO_PARCIAL}",
         (f"Spearman do ranking de falhas previstas contra as observadas no ano parcial: {fmt(mt.get('spearman_2026'), 2)}; "
          f"{fmt(mt.get('vinculo_2026'), 1, True)} das falhas do ano ligadas a um circuito."),
         (f"Spearman: {fmt(ms.get('spearman_2026'), 2)}; {fmt(ms.get('vinculo_2026'), 1, True)} das falhas do ano ligadas a um "
          "circuito."),
         (f"Os dois números são parciais ({ANO_PARCIAL} usa circuitos de um cadastro ainda não publicado) e o da Energisa MS não "
          "inclui o mês sem registro."),
         "resultados.json; vinculo_circuitos_comparacao.csv"),
        (f"Quebra de série em {ANO_REF} (falha nas instalações da unidade consumidora)",
         f"O código de expurgo dessa categoria existe nos anos: {mt.get('expurgo_cod1_anos', ND)}.",
         f"O código só existe nos anos: {ms.get('expurgo_cod1_anos', ND)} (mais a categoria equivalente do layout novo).",
         "Na Energisa MS a série por categoria de expurgo muda quando a categoria aparece; na Energisa MT ela existe desde o início.",
         "expurgo_codigos_por_ano.csv; falhas_por_expurgo.csv"),
        ("Efeito do religador",
         (f"Medido: {fmt(mt.get('efeito_religador'), 1)}% no CHI do alimentador ({f0('mt', 'eventos_did')} eventos, "
          f"{f0('mt', 'regra_controles')} controles nunca tratados)."),
         (f"Não medido: usa o efeito da Energisa MT (origem_efeito = {ms.get('origem_efeito', ND)}); {f0('ms', 'regra_eventos')} "
          f"eventos (mínimo {f0('ms', 'regra_min_eventos')}) e {f0('ms', 'regra_controles')} controles (mínimo "
          f"{f0('ms', 'regra_min_controles')}). O cadastro mistura instalação e remanejamento: {f0('ms', 'recl_ganhos_brutos')} "
          f"religadores ganhos contra saldo de {f0('ms', 'recl_ganho_liquido')} em {f0('ms', 'recl_transicoes')} transições."),
         "Qualquer R$ ou DEC evitado por religador na Energisa MS é a exposição da Energisa MS vezes o efeito da Energisa MT.",
         "valor.json; regra_decisao.json; transicoes_religadores.csv; mt_contagens_referencia.json"),
        ("Disjuntores (TUC 210)",
         "Não disponível: nenhum arquivo publicado separa o TUC 210 da Energisa MT por tensão.",
         (f"A classe mistura alta e média tensão em {ANO_REF}: {f0('ms', 'tuc210_at')} de {fmt(tuc_total, 0)} equipamentos são de "
          f"alta tensão ({fmt(ms.get('tuc210_at_pct'), 0, True)})."),
         "Contagem e idade de disjuntores não são comparáveis entre as duas empresas.",
         "tuc_x_tensao.csv"),
        ("Vida útil dos equipamentos",
         (f"Estimada para religador (mediana de {fmt(mt.get('vida_recl'), 1)} anos) e disjuntor ({fmt(mt.get('vida_disj'), 1)} anos); "
          f"{f0('mt', 'classes_aprovadas')} de {f0('mt', 'classes_total')} classes passam no teste de consistência do cadastro."),
         (f"Não estimada: {f0('ms', 'classes_aprovadas')} de {f0('ms', 'classes_total')} classes passam no teste de consistência "
          "do cadastro."),
         "Não há vida útil da Energisa MS para comparar: a contagem de equipamentos por safra sobe e desce de um cadastro para o outro.",
         "qualidade_classes.csv; vida_weibull.csv"),
        ("Contagem de religadores",
         (f"{f0('mt', 'recl_cadastro')} (recloser-performance), {f0('mt', 'recl_valor_json')} (automation-impact) e "
          f"{f0('mt', 'recl_switch')} (switchgear-survival)."),
         f"{f0('ms', 'recl_cadastro')}, {f0('ms', 'recl_valor_json')} e {f0('ms', 'recl_switch')}.",
         "Cada repositório usa um filtro (TIP_UNID 32, filtro do painel, TUC 345). Compare só dentro do mesmo repositório.",
         "diagnostico.json; valor.json; qualidade_classes.csv"),
        ("Telecomando no cadastro",
         f"{f0('mt', 'recl_telecom')} religadores com TLCD = 1 no cadastro de {ANO_REF}.",
         (f"{f0('ms', 'recl_telecom')} em {ANO_REF}; no filtro do automation-impact, {f0('ms', 'telecom_2024')} em 2024 e "
          f"{f0('ms', 'telecom_2025')} em {ANO_REF}, com {f0('ms', 'recl_auto_2024')} e {f0('ms', 'recl_auto_2025')} religadores."),
         ("O telecomando muda muito de um cadastro para o outro na Energisa MS; a diferença entre as empresas não deve ser lida "
          "como diferença de rede."),
         "diagnostico.json; religadores_por_snapshot.csv"),
        ("Subestações",
         (f"{f0('mt', 'ses')} SEs no índice (substation-health-index) e {f0('mt', 'ses_automacao')} no automation-impact. N-1: "
          f"{f0('mt', 'ses_n1')} SEs (estágios de ventilação)."),
         (f"{f0('ms', 'ses')} SEs no índice e {f0('ms', 'ses_automacao')} no automation-impact; com a regra de vínculo da Energisa "
          f"MT o índice teria {f0('ms', 'ses_vinculo_mt')}. N-1: {f0('ms', 'ses_n1')} SEs pela potência nominal e "
          f"{f0('ms', 'ses_n1_ventilacao')} pelos estágios de ventilação (a base da Energisa MT)."),
         "A contagem de SEs depende do filtro e da regra de vínculo; o teste N-1 só se compara na mesma base.",
         "resumo_2025.json; subestacoes.csv"),
        ("Registros de falha por km",
         (f"{fmt(mt.get('falhas_100km'), 1)} registros por 100 km por ano e {fmt(mt.get('chi_por_registro'), 0)} "
          "consumidores-hora por registro."),
         (f"{fmt(ms.get('falhas_100km'), 1)} registros por 100 km por ano e {fmt(ms.get('chi_por_registro'), 0)} "
          "consumidores-hora por registro."),
         ("Hipótese, não testada: mais registros por km com CHI por consumidor parecido é compatível com registros menores em "
          "média. Não medi como cada distribuidora abre e divide os registros no arquivo da ANEEL."),
         "falhas_por_modo.csv; vinculo_circuitos_comparacao.csv"),
        ("Premissas e elegibilidade da carteira",
         "Custos, eficácias e energia não suprida são ilustrativos (catálogo da Energisa MT).",
         ("As mesmas premissas, sem calibrar para a Energisa MS; a elegibilidade das intervenções vem do cadastro dela, e a "
          "sensibilidade com eficácias medidas não foi feita."),
         ("A razão ótima ÷ tradicional depende dessas premissas; o valor absoluto do VPL serve para comparar estratégias, não "
          "para aprovar verba."),
         "fronteira_social.csv; elegibilidade_catalogo.csv"),
        (f"DEC de {ANO_PARCIAL}",
         (f"Gerado sem alinhar os meses e de um download anterior do arquivo de indicadores (ver docs/dados.md). Meses com "
          f"interrupções: {mt.get('meses_parcial', ND)}."),
         (f"Compara só os meses que existem nas interrupções (`--alinhar-meses`): {ms.get('meses_parcial', ND)}. Meses com problema "
          f"nos dados: {ms.get('meses_buraco', ND)}."),
         f"O recorte de meses de {ANO_PARCIAL} não é o mesmo nos dois lados: o nível de {ANO_PARCIAL} não se compara.",
         "validacao_dec_fec.csv; dec_correlacao.csv"),
    ]
    return pd.DataFrame(linhas, columns=["tema", "energisa_mt", "energisa_ms", "o_que_limita", "arquivos"])


# --------------------------------------------------------------------------------------------- verificações e fontes
def verificar(C: dict, S: dict, P: dict) -> pd.DataFrame:
    """Números derivados aqui contra os publicados em outros arquivos (tolerância relativa de 1%)."""
    linhas = []

    def v(chave, desc, derivado, publicado, fonte):
        if not numerico(derivado) or not numerico(publicado):
            linhas.append({"verificacao": chave, "descricao": desc, "derivado": derivado, "publicado": publicado,
                           "diferenca_relativa": None, "passou": ND, "fonte_publicada": fonte})
            return
        dif = abs(derivado - publicado) / abs(publicado) if publicado else abs(derivado - publicado)
        linhas.append({"verificacao": chave, "descricao": desc, "derivado": derivado, "publicado": publicado,
                       "diferenca_relativa": dif, "passou": bool(dif <= TOLERANCIA_VERIFICACAO), "fonte_publicada": fonte})

    cmp_ = S.get("comparacao")
    for d in DIST:
        p, nome = P[d], NOME[d]

        def pub(col, d=d):
            try:
                return float(cmp_[cmp_["distribuidora"] == SIGLA[d]][col].iloc[0])
            except (TypeError, IndexError, KeyError):
                return None

        fonte = "reports/ems/diagnostico/comparacao_descritiva.csv"
        v(f"consumidores_{d}", f"{nome}: consumidores", p.get("uc"), pub("consumidores"), fonte)
        v(f"rede_km_{d}", f"{nome}: km de rede de média tensão", p.get("km"), pub("rede_mt_km"), fonte)
        v(f"uc_por_km_{d}", f"{nome}: consumidores por km", p.get("uc_por_km"), pub("consumidores_por_km"), fonte)
        v(f"risco_social_uc_{d}", f"{nome}: risco social por consumidor", p.get("risco_social_uc"),
          pub("risco_social_rs_por_consumidor"), fonte)
        v(f"risco_comp_uc_{d}", f"{nome}: risco em compensações por consumidor", p.get("risco_comp_uc"),
          pub("risco_compensacao_rs_por_consumidor"), fonte)
        v(f"dec_previsto_{d}", f"{nome}: DEC previsto por falhas", p.get("dec_previsto"), pub("dec_previsto_falhas_mt_h"), fonte)
        v(f"top10_{d}", f"{nome}: parcela do risco social nos 10% de maior risco", p.get("top10_social"), p.get("top10_social_pub"),
          "reports/[ems/]resumo_decisao.json")
        v(f"top20_{d}", f"{nome}: parcela do risco social nos 20% de maior risco", p.get("top20_social"), p.get("top20_social_pub"),
          "reports/[ems/]resumo_decisao.json")
        try:
            v(f"uc_total_{d}", f"{nome}: consumidores contra n_uc_total", p.get("uc"), float(C[d]["resultados"]["n_uc_total"]),
              "reports/[ems/]resultados.json")
            v(f"n_alim_{d}", f"{nome}: alimentadores", p.get("n_alim"), float(C[d]["resumo_decisao"]["n_alimentadores"]),
              "reports/[ems/]resumo_decisao.json")
        except (TypeError, KeyError):
            v(f"uc_total_{d}", f"{nome}: consumidores contra n_uc_total", p.get("uc"), None, "reports/[ems/]resultados.json")
        v(f"falhas_100km_{d}", f"{nome}: falhas por 100 km contra a taxa publicada pelo recloser-performance (km da topologia)",
          p.get("falhas_100km"), p.get("recl_100km_pub"), "recloser-performance/reports/[ems/]diagnostico.json")
        v(f"km_topologia_{d}", f"{nome}: km de rede contra o km da topologia reconstruída", p.get("km"), p.get("recl_km_pub"),
          "recloser-performance/reports/[ems/]diagnostico.json")
    c = S.get("chi_por_modo_ms")
    try:
        tot = c[c["modo"] == "TOTAL"].iloc[0]
        v("chi_total_ms", "Energisa MS: CHI total das falhas contra chi_por_modo.csv", P["ms"].get("chi_ano"), float(tot["chi"]),
          "reports/ems/diagnostico/chi_por_modo.csv")
        v("chi_reg_ms", "Energisa MS: CHI regulatório (Σ CHI × fração) contra chi_por_modo.csv", P["ms"].get("chi_reg_ano"),
          float(tot["chi_regulatorio"]), "reports/ems/diagnostico/chi_por_modo.csv")
        v("frac_exp_ms", "Energisa MS: fração expurgada contra chi_por_modo.csv", P["ms"].get("frac_exp"),
          float(tot["pct_expurgado"]), "reports/ems/diagnostico/chi_por_modo.csv")
    except (TypeError, IndexError, KeyError):
        for k in ("chi_total_ms", "chi_reg_ms", "frac_exp_ms"):
            v(k, "Energisa MS contra chi_por_modo.csv", None, None, "reports/ems/diagnostico/chi_por_modo.csv")
    return pd.DataFrame(linhas)


def tabela_fontes(F: Fontes) -> pd.DataFrame:
    linhas = []
    for (repo, rel), p in sorted(F.registro.items()):
        t = {"repositorio": repo, "arquivo": rel, "existe": p is not None, "bytes": None, "sha256": None}
        if p is not None:
            b = p.read_bytes()
            t["bytes"], t["sha256"] = len(b), hashlib.sha256(b).hexdigest()
        linhas.append(t)
    return pd.DataFrame(linhas, columns=["repositorio", "arquivo", "existe", "bytes", "sha256"])


# --------------------------------------------------------------------------------------------- figuras
def figuras(P: dict, T: dict, pasta: Path) -> list[str]:
    """Quatro figuras no estilo das de ``make_figures.py``. Devolve as que foram geradas."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    surface, ink, ink2, muted, grid, axis = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
    cor = {"mt": "#2a78d6", "ms": "#eb6834"}
    seq = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "axes.facecolor": surface, "figure.facecolor": surface,
        "axes.edgecolor": axis, "axes.labelcolor": ink2, "xtick.color": muted, "ytick.color": muted,
        "axes.grid": True, "grid.color": grid, "grid.linewidth": 1, "axes.spines.top": False,
        "axes.spines.right": False, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlecolor": ink,
        "axes.titlelocation": "left", "legend.frameon": False, "legend.labelcolor": ink2})
    pasta.mkdir(parents=True, exist_ok=True)
    geradas = []

    def salvar(fig, nome):
        fig.savefig(pasta / nome, dpi=180, bbox_inches="tight")
        plt.close(fig)
        geradas.append(nome)

    def pt(v, casas=1):
        return fmt(v, casas)

    # 1) falhas por 100 km por modo
    t = T["falhas_por_modo"]
    t = t[t["modo"] != "TOTAL"]
    if all(numerico(x) for x in list(t["falhas_100km_mt"]) + list(t["falhas_100km_ms"])) and len(t):
        t = t.assign(soma=t["falhas_100km_mt"].astype(float) + t["falhas_100km_ms"].astype(float)).sort_values("soma")
        fig, ax = plt.subplots(figsize=(8.6, 4.4))
        y = np.arange(len(t))
        for k, (d, desl) in enumerate((("mt", -0.19), ("ms", 0.19))):
            v = t[f"falhas_100km_{d}"].astype(float).to_numpy()
            ax.barh(y + desl, v, height=0.36, color=cor[d], label=NOME[d])
            for yi, vi in zip(y + desl, v, strict=True):
                ax.text(vi, yi, "  " + pt(vi), va="center", color=ink, fontsize=8.5)
        ax.set_yticks(y, [NOME_MODO[m] for m in t["modo"]], color=ink2)
        ax.grid(axis="y", visible=False)
        ax.set_xlim(0, max(t["falhas_100km_mt"].astype(float).max(), t["falhas_100km_ms"].astype(float).max()) * 1.18)
        ax.set_xlabel(f"Falhas na média tensão por 100 km de rede por ano (média {JANELA})")
        ax.set_title("Falhas por 100 km e por modo: Energisa MT e Energisa MS")
        ax.legend(loc="lower right")
        salvar(fig, "01_falhas_por_100km.png")
    # 2) CHI por consumidor, regulatório e expurgado, por modo
    t = T["chi_por_modo"]
    t = t[t["modo"] != "TOTAL"]
    cols = [f"{k}_{d}" for k in ("chi_uc", "chi_reg_uc") for d in DIST]
    if len(t) and all(numerico(x) for c in cols for x in t[c]):
        t = t.assign(soma=t["chi_uc_mt"].astype(float) + t["chi_uc_ms"].astype(float)).sort_values("soma")
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharex=True, sharey=True)
        xmax = max(t["chi_uc_mt"].astype(float).max(), t["chi_uc_ms"].astype(float).max()) * 1.2
        for ax, d in zip(axes, DIST, strict=True):
            tot = t[f"chi_uc_{d}"].astype(float).to_numpy()
            reg = t[f"chi_reg_uc_{d}"].astype(float).to_numpy()
            y = np.arange(len(t))
            ax.barh(y, reg, height=0.55, color=seq[5], label="CHI regulatório (entra no DEC)")
            gap = xmax * 0.004
            ax.barh(y, tot - reg - gap, left=reg + gap, height=0.55, color=seq[2], label="CHI expurgado")
            for yi, vi in zip(y, tot, strict=True):
                ax.text(vi, yi, "  " + pt(vi), va="center", color=ink, fontsize=8.5)
            ax.set_yticks(y, [NOME_MODO[m] for m in t["modo"]], color=ink2)
            ax.grid(axis="y", visible=False)
            ax.set_xlim(0, xmax)
            ax.set_title(f"{NOME[d]}: {pt(P[d].get('frac_exp'), 0)}% do CHI expurgado", fontsize=10.5)
            ax.set_xlabel("Horas de interrupção por consumidor por ano")
        axes[1].legend(loc="lower right")
        fig.suptitle(f"CHI das falhas por consumidor (média {JANELA}): a regra de expurgo pesa diferente", x=0.01, ha="left",
                     color=ink, fontweight="bold", y=1.03)
        salvar(fig, "02_chi_por_consumidor.png")
    # 3) DEC oficial e recalculado (sem o ano parcial)
    t = T["dec_fec_oficial"]
    if "DEC_oficial_mt" in t.columns and "DEC_oficial_ms" in t.columns and len(t):
        t = t[t["ano"].astype(int) < ANO_PARCIAL]
        fig, ax = plt.subplots(figsize=(8.6, 4.2))
        for d in DIST:
            anos = t["ano"].astype(int).to_numpy()
            of = pd.to_numeric(t[f"DEC_oficial_{d}"], errors="coerce").to_numpy()
            ca = pd.to_numeric(t[f"DEC_calculado_{d}"], errors="coerce").to_numpy()
            ax.plot(anos, of, color=cor[d], lw=2, marker="o", ms=6, mec=surface, mew=2, label=f"{NOME[d]}: oficial")
            ax.plot(anos, ca, color=cor[d], lw=0, marker="o", ms=8, mfc="none", mew=1.5, label=f"{NOME[d]}: recalculado")
            for a, o, c in zip(anos, of, ca, strict=True):
                if np.isfinite(o) and np.isfinite(c) and abs(c - o) / o > TOLERANCIA_DEC:
                    ax.annotate(f"recalculado {pt(c)}", (a, c), textcoords="offset points", xytext=(0, -16), ha="center",
                                fontsize=8, color=ink2)
        ax.set_xticks(sorted(set(t["ano"].astype(int))))
        ax.set_xlabel(f"Ano (o ano parcial, {ANO_PARCIAL}, fica fora da figura; ver a tabela)")
        ax.set_ylabel("DEC (horas por consumidor)")
        ax.set_ylim(bottom=0)
        ax.set_title("DEC oficial da ANEEL e DEC recalculado das interrupções")
        ax.legend(loc="upper right", ncol=2, fontsize=8.5)
        salvar(fig, "03_dec_oficial_e_recalculado.png")
    # 4) carteira por orçamento (visão social)
    t = T["carteira_por_orcamento"]
    if len(t) and "razao_otimo_tradicional_mt" in t.columns:
        s = t[t["visao"] == "social"].sort_values("orcamento")
        if len(s):
            fig, axes = plt.subplots(1, 2, figsize=(11, 4.0))
            orc = s["orcamento"].astype(float).to_numpy() / 1e6
            for d in DIST:
                r = pd.to_numeric(s[f"razao_otimo_tradicional_{d}"], errors="coerce").to_numpy()
                axes[0].plot(orc, r, color=cor[d], lw=2, marker="o", ms=6, mec=surface, mew=2, label=NOME[d])
                inv = pd.to_numeric(s[f"investido_otimo_{d}"], errors="coerce").to_numpy() / 1e6
                axes[1].plot(orc, inv, color=cor[d], lw=2, marker="o", ms=6, mec=surface, mew=2, label=NOME[d])
            axes[0].axhline(1, color=axis, lw=1)
            axes[0].set_ylim(bottom=0)
            axes[0].set_ylabel("razão")
            axes[0].set_title("VPL da carteira ótima ÷ VPL da regra tradicional\nvisão social, premissas ilustrativas",
                              fontsize=10.5)
            axes[0].legend(loc="upper right")
            axes[1].plot(orc, orc, color=axis, lw=1, ls="--", label="orçamento")
            axes[1].set_ylabel("R$ mi investidos")
            axes[1].set_title("Quanto a carteira ótima investe\n(para quando não há pacote de VPL positivo)", fontsize=10.5)
            axes[1].legend(loc="upper left")
            for ax in axes:
                ax.set_xticks(orc, [fmt(o, 0) for o in orc])
                ax.set_xlabel("Orçamento de investimento (R$ mi)")
            fig.subplots_adjust(wspace=0.25)
            salvar(fig, "04_carteira_otima_contra_tradicional.png")
    return geradas


# --------------------------------------------------------------------------------------------- documento
def md_tabela(cab: list[str], linhas: list[list[str]]) -> str:
    def cel(x):
        return str(x).replace("|", "\\|").replace("\n", " ")

    out = ["| " + " | ".join(cel(c) for c in cab) + " |", "|" + "|".join("---" for _ in cab) + "|"]
    out += ["| " + " | ".join(cel(c) for c in ln) + " |" for ln in linhas]
    return "\n".join(out)


def valor_fmt(e: Espec, v) -> str:
    if v is None:
        return ND
    if isinstance(v, str):
        return v
    return fmt(v, e.casas, e.pct)


def tabela_bloco(P: dict, bloco: str, so: tuple[str, ...] | None = None) -> str:
    linhas = []
    for e in (x for x in ESPECS if x.bloco == bloco and (so is None or x.chave in so)):
        mt, ms = P["mt"].get(e.chave), P["ms"].get(e.chave)
        r = razao(ms, mt) if e.com_razao else None
        dif = e.diferenca + (f": {e.nota}" if e.nota and e.diferenca != "Não" else "")
        if e.diferenca == "Não" and e.nota:
            dif = f"Não. {e.nota}"
        linhas.append([e.nome, e.unidade, valor_fmt(e, mt), valor_fmt(e, ms), "" if r is None else fmt(r, 2), dif])
    return md_tabela(["Métrica", "Unidade", NOME["mt"], NOME["ms"], "Razão MS ÷ MT", "A diferença pode vir de definição?"],
                     linhas)


def detalhes_bloco(bloco: str) -> str:
    linhas = []
    for e in (x for x in ESPECS if x.bloco == bloco):
        linhas.append([e.nome, e.definicao, e.numerador, e.denominador, origem(e.fontes, "mt"), origem(e.fontes, "ms")])
    corpo = md_tabela(["Métrica", "Definição", "Numerador", "Denominador", "Arquivo (Energisa MT)", "Arquivo (Energisa MS)"], linhas)
    return f"<details>\n<summary>Definições, numerador, denominador e arquivos de origem</summary>\n\n{corpo}\n\n</details>"


def rz(P: dict, chave: str, casas: int = 1) -> str:
    return fmt(razao(P["ms"].get(chave), P["mt"].get(chave)), casas)


def par_txt(P: dict, chave: str, casas: int = 1, pct: bool = False) -> tuple[str, str]:
    return fmt(P["mt"].get(chave), casas, pct), fmt(P["ms"].get(chave), casas, pct)


def figura_md(res: Resultado, nome: str, legenda: str) -> str:
    if nome in res.figuras:
        return f"![{legenda}](../reports/comparativo_mt_ms/figures/{nome})"
    return f"_Figura `{nome}` não gerada: faltam dados nos arquivos publicados._"


def renderizar_doc(res: Resultado) -> str:
    P, T = res.P, res.T
    a = []
    w = a.append

    def defin(txt):
        w(f"**A diferença pode vir de definição?** {txt}\n")

    w("# Comparativo descritivo: Energisa MT × Energisa MS\n")
    w("> Projeto independente, sem vínculo com a Energisa ou com a ANEEL. Só dados abertos (ANEEL e IBGE).\n")
    w("Este documento compara, **só de forma descritiva**, a Energisa Mato Grosso (EMT, \"Energisa MT\") e a Energisa Mato "
      "Grosso do Sul (EMS, \"Energisa MS\"), com os números por consumidor e por km de rede de média tensão. Ele **não "
      "afirma causas**: onde aparece \"compatível com\", é uma hipótese, e está marcada como tal. Neste texto, \"MT\" é "
      "sempre a empresa Energisa MT; a tensão é escrita \"média tensão\".\n")
    w("Todo número daqui sai de [`scripts/comparativo_mt_ms.py`](../scripts/comparativo_mt_ms.py), que lê **só arquivos já "
      "publicados** (`reports/`, `reports/ems/`, `app/data/` e `app/data/ems/` deste repositório e os `reports/` e "
      "`reports/ems/` dos quatro repositórios irmãos). Ele não roda pipeline, não baixa nada e não regenera resultado de "
      "MT nem de MS. Quando a métrica comparável não existe nos arquivos publicados, a célula diz \"não disponível\"; "
      "nada foi recalculado por outro caminho. Os CSVs e as figuras ficam em "
      "[`reports/comparativo_mt_ms/`](../reports/comparativo_mt_ms/).\n")
    w("## Como ler\n")
    w(f"* **Razão MS ÷ MT** é o valor da Energisa MS dividido pelo da Energisa MT.\n"
      f"* **Janela.** \"Por ano\", sem ano, é a média de {JANELA}, a janela dos arquivos publicados. {ANO_PARCIAL} é "
      f"parcial; meses com registro de interrupção: Energisa MT, {P['mt'].get('meses_parcial', ND)}; Energisa MS, "
      f"{P['ms'].get('meses_parcial', ND)}.\n"
      f"* **Denominadores.** Toda taxa por consumidor ou por km usa o cadastro (BDGD) de 31/12/{ANO_REF}, somado de "
      f"`risco_alimentador.parquet`. Nas séries por ano o denominador também é o de {ANO_REF} (**denominador fixo**).\n"
      "* **\"A diferença pode vir de definição?\"** *Não*: mesma definição e mesma origem nos dois lados. *Possível*: há uma "
      "diferença documentada que pode mexer no número. *Sim*: a definição é diferente, e a diferença não deve ser lida como "
      "diferença de rede.\n"
      f"* **Conferências.** `reports/comparativo_mt_ms/verificacoes.csv` compara {len(res.verificacoes)} números derivados aqui "
      f"com os publicados em outros arquivos ({res.n_verificacoes_ok} dentro de {fmt(100 * TOLERANCIA_VERIFICACAO, 0)}%); `fontes.csv` lista cada arquivo lido, "
      "com SHA-256.\n")
    # resumo
    w("## Resumo\n")
    linhas_resumo = [
        ("Falhas na média tensão por 100 km por ano", "falhas_100km", 1, False),
        ("CHI das falhas por consumidor por ano (h)", "chi_uc", 1, False),
        ("Fração do CHI das falhas que é expurgada", "frac_exp", 1, True),
        (f"DEC oficial de {ANO_REF} (h)", "dec_of", 2, False),
        ("Parcela do risco social nos 10% de alimentadores de maior risco", "top10_social", 1, True),
        (f"Carteira ótima ÷ regra tradicional ({ORC}, visão social)", "razao_carteira", 2, False),
    ]
    w(md_tabela(["Indicador (descritivo)", NOME["mt"], NOME["ms"]],
                [[nome, *par_txt(P, k, c, p)] for nome, k, c, p in linhas_resumo]) + "\n")
    w("Diferenças de definição que mudam a leitura (seção 9): o expurgo pesa muito diferente nas duas empresas; a Energisa MT "
      "usa todos os circuitos do cadastro e a Energisa MS exclui os vazios; os meses sem registro de interrupção em "
      f"{ANO_PARCIAL} são {P['ms'].get('meses_faltando', ND)} na Energisa MS e {P['mt'].get('meses_faltando', ND)} na Energisa MT; "
      f"e o efeito do religador na Energisa MS é o da Energisa MT, não medido (origem_efeito = {P['ms'].get('origem_efeito', ND)}).\n")

    # (a)
    w("## 1. Tamanho\n")
    w(f"Cadastro de 31/12/{ANO_REF}. A Energisa MS tem {fmt(P['ms'].get('uc_por_km'), 1)} consumidores por km de rede de média "
      f"tensão e a Energisa MT, {fmt(P['mt'].get('uc_por_km'), 1)} (razão {rz(P, 'uc_por_km')}).\n")
    w(tabela_bloco(P, "a") + "\n")
    w(detalhes_bloco("a") + "\n")
    # (b)
    w("## 2. Falhas na média tensão por 100 km, por ano e por modo de falha\n")
    w(f"Falha = registro da ANEEL de interrupção interna, não programada, em média tensão, ligado a um circuito da BDGD. Média "
      f"anual de {JANELA}. Por 100 km, a Energisa MS tem {fmt(P['ms'].get('falhas_100km'), 1)} e a Energisa MT, "
      f"{fmt(P['mt'].get('falhas_100km'), 1)} falhas por ano (razão {rz(P, 'falhas_100km')}). Por mil consumidores, "
      f"{fmt(P['ms'].get('falhas_1000uc'), 1)} e {fmt(P['mt'].get('falhas_1000uc'), 1)}.\n")
    w(tabela_bloco(P, "b") + "\n")
    w("**Por modo de falha** (`falhas_por_modo.csv`; a coluna \"publicado\" é a taxa do `recloser-performance`, que divide pelo km da "
      "topologia reconstruída, e não pelo km do cadastro):\n")
    t = T["falhas_por_modo"]
    w(md_tabela(["Modo", "Falhas/100 km/ano MT", "Falhas/100 km/ano MS", "Razão MS ÷ MT", "% das falhas MT", "% das falhas MS",
                 "Publicado MT", "Publicado MS"],
                [[NOME_MODO.get(r["modo"], "Total"), fmt(r["falhas_100km_mt"], 1), fmt(r["falhas_100km_ms"], 1),
                  fmt(r["razao_ms_mt_100km"], 1), fmt(r["pct_das_falhas_mt"], 1, True), fmt(r["pct_das_falhas_ms"], 1, True),
                  fmt(r["falhas_100km_publicado_mt"], 1), fmt(r["falhas_100km_publicado_ms"], 1)] for _, r in t.iterrows()]) + "\n")
    w(figura_md(res, "01_falhas_por_100km.png", "Falhas por 100 km por modo") + "\n")
    defin("Possível. A contagem é de registros da ANEEL, não de eventos (seção 9); a rede e os consumidores são os do mesmo "
          "cadastro nas duas empresas.")
    w("**Por ano** (`falhas_por_ano.csv`): todas as falhas de média tensão de cada ano, ligadas ou não a um circuito, com "
      f"**denominador fixo de {ANO_REF}**. {ANO_PARCIAL} é parcial.\n")
    t = T["falhas_por_ano"]
    if len(t) and "falhas_100km_mt" in t.columns:
        w(md_tabela(["Ano", "Falhas/100 km MT", "Falhas/100 km MS", "CHI/consumidor MT (h)", "CHI/consumidor MS (h)",
                     "CHI por registro MT", "CHI por registro MS"],
                    [[f"{int(r['ano'])}" + (" (parcial)" if r["ano_parcial"] is True or r["ano_parcial"] == 1 else ""),
                      fmt(r["falhas_100km_mt"], 1), fmt(r["falhas_100km_ms"], 1), fmt(r["chi_uc_mt"], 1), fmt(r["chi_uc_ms"], 1),
                      fmt(r["chi_por_registro_mt"], 0), fmt(r["chi_por_registro_ms"], 0)] for _, r in t.iterrows()]) + "\n")
    else:
        w(f"Série por ano: {ND}.\n")
    defin("Possível, pelo mesmo motivo (registros). O número de falhas conta **registros** do arquivo da ANEEL, não eventos "
          "físicos; se as duas distribuidoras registram e dividem as ocorrências do mesmo jeito, é uma pergunta em aberto (seção 9).")
    w("A série **por ano e por modo** ao mesmo tempo não está publicada para a Energisa MT: por modo há só a média de "
      f"{JANELA}, e por ano só o total. Por isso as duas tabelas acima não se cruzam.\n")
    w(detalhes_bloco("b") + "\n")
    # (c)
    w("## 3. CHI por consumidor, total e regulatório\n")
    w(f"CHI é consumidor-hora interrompido. Na média de {JANELA}, as falhas na média tensão somam "
      f"{fmt(P['ms'].get('chi_uc'), 1)} h por consumidor por ano na Energisa MS e {fmt(P['mt'].get('chi_uc'), 1)} h na Energisa MT "
      f"(razão {rz(P, 'chi_uc', 2)}). O CHI regulatório, o que entra no DEC e nas compensações, é de "
      f"{fmt(P['ms'].get('chi_reg_uc'), 1)} h na Energisa MS e {fmt(P['mt'].get('chi_reg_uc'), 1)} h na Energisa MT. A fração "
      f"expurgada é de {fmt(P['ms'].get('frac_exp'), 1, True)} na Energisa MS e {fmt(P['mt'].get('frac_exp'), 1, True)} na Energisa MT.\n")
    w("> **Ressalva.** A regra de expurgo (dia crítico e situação de emergência) pesa muito diferente nas duas empresas. Por isso o "
      "CHI total é a medida mais comparável; o regulatório e a fração expurgada refletem também a definição do que se expurga.\n")
    w(tabela_bloco(P, "c") + "\n")
    t = T["chi_por_modo"]
    w("**Por modo de falha** (`chi_por_modo.csv`):\n")
    w(md_tabela(["Modo", "CHI total MT (h/consumidor)", "CHI total MS", "Regulatório MT", "Regulatório MS", "Expurgado MT", "Expurgado MS"],
                [[NOME_MODO.get(r["modo"], "Total"), fmt(r["chi_uc_mt"], 2), fmt(r["chi_uc_ms"], 2), fmt(r["chi_reg_uc_mt"], 2),
                  fmt(r["chi_reg_uc_ms"], 2), fmt(r["pct_expurgado_mt"], 0, True), fmt(r["pct_expurgado_ms"], 0, True)]
                 for _, r in t.iterrows()]) + "\n")
    w(figura_md(res, "02_chi_por_consumidor.png", "CHI por consumidor por modo") + "\n")
    defin("Não para o CHI total. Sim para o CHI regulatório e para a parcela expurgada: a regra de expurgo pesa muito diferente "
          "nas duas empresas, principalmente nos modos ligados ao tempo (descarga atmosférica, vento e vegetação).")
    w("Por ano, só a Energisa MS tem publicada a parcela sem expurgo (`falhas_por_ano.csv`, colunas `chi_sem_expurgo_uc_ms` e "
      f"`pct_chi_expurgado_ms`); para a Energisa MT a série por ano é {ND}. A fração expurgada da Energisa MS por ano, até {ANO_REF}: "
      f"{serie_expurgo_ms(T)}.\n")
    w(detalhes_bloco("c") + "\n")
    # (d)
    w("## 4. DEC e FEC oficiais e o DEC recalculado\n")
    w(f"DEC e FEC oficiais vêm dos indicadores coletivos da ANEEL, por consumidor, e são diretamente comparáveis. Em {ANO_REF}, "
      f"o DEC é de {fmt(P['ms'].get('dec_of'), 2)} h na Energisa MS e {fmt(P['mt'].get('dec_of'), 2)} h na Energisa MT; o FEC, "
      f"{fmt(P['ms'].get('fec_of'), 2)} e {fmt(P['mt'].get('fec_of'), 2)}. O \"recalculado\" refaz o DEC das interrupções individuais "
      f"(sem expurgo e com 3 minutos ou mais). Ele \"bate\" se difere do oficial em até {fmt(100 * TOLERANCIA_DEC, 0)}%. "
      f"Anos em que **não** bate: Energisa MT, {P['mt'].get('anos_nao_batem', ND)}; Energisa MS, {P['ms'].get('anos_nao_batem', ND)}.\n")
    t = T["dec_fec_oficial"]
    if "DEC_oficial_mt" in t.columns and "DEC_oficial_ms" in t.columns:
        w(md_tabela(["Ano", "DEC oficial MT", "DEC recalc. MT", "Bate MT", "DEC oficial MS", "DEC recalc. MS", "Bate MS",
                     "FEC oficial MT", "FEC recalc. MT", "FEC oficial MS", "FEC recalc. MS"],
                    [[f"{int(r['ano'])}" + (" (parcial)" if r["ano_parcial"] is True or r["ano_parcial"] == 1 else ""),
                      fmt(r.get("DEC_oficial_mt"), 2), fmt(r.get("DEC_calculado_mt"), 2), sim_nao(r.get("dec_bate_mt"), r.get("fec_bate_mt")),
                      fmt(r.get("DEC_oficial_ms"), 2), fmt(r.get("DEC_calculado_ms"), 2), sim_nao(r.get("dec_bate_ms"), r.get("fec_bate_ms")),
                      fmt(r.get("FEC_oficial_mt"), 2), fmt(r.get("FEC_calculado_mt"), 2), fmt(r.get("FEC_oficial_ms"), 2),
                      fmt(r.get("FEC_calculado_ms"), 2)] for _, r in t.iterrows()]) + "\n")
    else:
        w(f"Tabela por ano: {ND}.\n")
    w(f"A correlação mensal por conjunto (um valor único por arquivo, todos os meses) é {fmt(P['mt'].get('corr_mensal'), 4)} na Energisa MT "
      f"e {fmt(P['ms'].get('corr_mensal'), 4)} na Energisa MS; sem os meses com problema nos dados de MS "
      f"({P['ms'].get('meses_buraco', ND)}) ela é {fmt(P['ms'].get('corr_mensal_sem_buracos'), 4)}.\n")
    w(f"> **Ressalva sobre {ANO_PARCIAL}.** O DEC de {ANO_PARCIAL} da Energisa MT foi gerado sem alinhar os meses e de um download "
      "anterior do arquivo de indicadores (`docs/dados.md`); o da Energisa MS compara só os meses que existem nas interrupções "
      f"({P['ms'].get('meses_parcial', ND)}). O recorte de meses não é o mesmo, e o nível de {ANO_PARCIAL} não se compara.\n")
    w(figura_md(res, "03_dec_oficial_e_recalculado.png", "DEC oficial e recalculado") + "\n")
    defin("Não para o DEC e o FEC oficiais. Sim para o recalculado nos anos que não batem: a base de interrupções da Energisa MS "
          "tem meses com problema (seção 9).")
    w(tabela_bloco(P, "d") + "\n")
    w(detalhes_bloco("d") + "\n")
    # (e)
    w("## 5. Compensações por consumidor\n")
    w("**Compensações pagas.** Para a Energisa MS há a série por ano, lida sem as linhas repetidas da ANEEL (o arquivo da ANEEL "
      "traz linhas repetidas). Para a Energisa MT **não há série de compensações pagas nos arquivos publicados**: aparece como "
      f"\"{ND}\", e não foi recalculada. Média de {JANELA_COMP[0]} a {JANELA_COMP[1]} na Energisa MS: R$ "
      f"{fmt(P['ms'].get('comp_paga_uc'), 2)} por consumidor por ano.\n")
    t = T["compensacoes_por_ano"]
    w(md_tabela(["Ano", "R$ pagos MT", "R$/consumidor MT", "R$ pagos MS", "R$/consumidor MS"],
                [[f"{int(r['ano'])}" + (" (parcial)" if r["ano_parcial"] is True or r["ano_parcial"] == 1 else ""), ND, ND,
                  fmt_mi(r["pg_reais_ms"], 1) if numerico(r["pg_reais_ms"]) else ND, fmt(r["pg_por_consumidor_ms"], 2)]
                 for _, r in t.iterrows()]) + "\n" if len(t) else f"Série por ano: {ND}.\n")
    w("**O que existe para as duas empresas** é a previsão do modelo para 2026, que **não é compensação paga**: CHI regulatório previsto "
      f"vezes o R$ por CHI das compensações de {JANELA_COMP[0]} a {JANELA_COMP[1]}. Depende da fração regulatória de cada empresa.\n")
    w(tabela_bloco(P, "e") + "\n")
    defin("Não para o que foi pago (onde existe). Possível para a previsão do modelo: ela usa a fração regulatória e o R$ por CHI "
          "de cada empresa.")
    w(detalhes_bloco("e") + "\n")
    # (f)
    w("## 6. Concentração do risco\n")
    w(f"No risco previsto para {ANO_PARCIAL}, os 10% de alimentadores de maior risco social concentram "
      f"{fmt(P['ms'].get('top10_social'), 1, True)} do risco na Energisa MS e {fmt(P['mt'].get('top10_social'), 1, True)} na Energisa MT; os 20%, "
      f"{fmt(P['ms'].get('top20_social'), 1, True)} e {fmt(P['mt'].get('top20_social'), 1, True)}. Os grupos têm "
      f"{fmt(P['ms'].get('k10_social'), 0)} e {fmt(P['ms'].get('k20_social'), 0)} alimentadores na Energisa MS e "
      f"{fmt(P['mt'].get('k10_social'), 0)} e {fmt(P['mt'].get('k20_social'), 0)} na Energisa MT.\n")
    w(tabela_bloco(P, "f") + "\n")
    t = T["concentracao_risco"]
    defin("Possível: o número de alimentadores de cada grupo depende da contagem de alimentadores de cada empresa (circuitos vazios).")
    w("Conferência com `resumo_decisao.json` (risco social):\n")
    w(md_tabela(["Grupo", "Parcela MT (aqui)", "Publicada MT", "Parcela MS (aqui)", "Publicada MS"],
                [[f"{int(r['pct_alimentadores'])}% de maior {r['visao']}", fmt(r["parcela_do_risco_mt"], 1, True),
                  fmt(r["parcela_publicada_mt"], 1, True), fmt(r["parcela_do_risco_ms"], 1, True),
                  fmt(r["parcela_publicada_ms"], 1, True)] for _, r in t.iterrows()]) + "\n")
    w(detalhes_bloco("f") + "\n")
    # (g)
    w("## 7. Carteira ótima contra a regra tradicional\n")
    w("Mesmo método e mesmas premissas ilustrativas nas duas empresas (custos, eficácias e energia não suprida do catálogo da "
      f"Energisa MT, sem calibrar para MS). Com orçamento de {ORC} na visão social, a razão entre o VPL da carteira ótima e o da regra "
      f"tradicional é de {fmt(P['ms'].get('razao_carteira'), 2)} na Energisa MS e {fmt(P['mt'].get('razao_carteira'), 2)} na Energisa MT. "
      "A tabela mostra também quanto a carteira ótima de fato investe. A razão só é calculada quando o VPL da regra tradicional "
      f"passa de {fmt_mi(VPL_MIN_RAZAO, 0)} (\"não se aplica\" nos demais casos).\n")
    w(figura_md(res, "04_carteira_otima_contra_tradicional.png", "Carteira ótima contra a tradicional") + "\n")
    t = T["carteira_por_orcamento"]
    if len(t) and "vpl_otimo_mt" in t.columns:
        w(md_tabela(["Visão", "Orçamento", "VPL ótima MT", "Investido MT", "VPL trad. MT", "Razão MT", "VPL ótima MS", "Investido MS",
                     "VPL trad. MS", "Razão MS"],
                    [[r["visao"], fmt_mi(r["orcamento"], 0), fmt_mi(r["vpl_otimo_mt"]), fmt_mi(r["investido_otimo_mt"]), fmt_mi(r["vpl_tradicional_mt"]),
                      razao_ou_na(r["razao_otimo_tradicional_mt"], r["vpl_tradicional_mt"]), fmt_mi(r["vpl_otimo_ms"]),
                      fmt_mi(r["investido_otimo_ms"]), fmt_mi(r["vpl_tradicional_ms"]),
                      razao_ou_na(r["razao_otimo_tradicional_ms"], r["vpl_tradicional_ms"])] for _, r in t.iterrows()]) + "\n")
    else:
        w(f"Tabela por orçamento: {ND}.\n")
    defin("Possível. As premissas são ilustrativas e iguais, sem calibrar para a Energisa MS; a elegibilidade das intervenções "
          "(tabela abaixo) e o que a carteira ótima consegue investir mudam com o cadastro.")
    w(tabela_bloco(P, "g") + "\n")
    w("Elegibilidade das intervenções no cadastro de 2025 (muda com o cadastro de cada empresa):\n")
    el = T["elegibilidade_catalogo"]
    if len(el) and "EMT_pct" in el.columns:
        w(md_tabela(["Intervenção", "Alimentadores elegíveis MT", "% MT", "Alimentadores elegíveis MS", "% MS"],
                    [[r["intervencao"], fmt(r["EMT_elegiveis"], 0), fmt(r["EMT_pct"], 0, True), fmt(r["EMS_elegiveis"], 0),
                      fmt(r["EMS_pct"], 0, True)] for _, r in el.iterrows()]) + "\n")
    else:
        w(f"{ND}.\n")
    w(detalhes_bloco("g") + "\n")
    # (h)
    w("## 8. Subestações e religadores\n")
    w("Os números vêm dos arquivos publicados de `substation-health-index` e `recloser-performance`, cada um com a sua base. A "
      "linha de N-1 aparece duas vezes: na base de ventilação (a que a Energisa MT usa) e na base principal de cada publicação.\n")
    w(tabela_bloco(P, "h") + "\n")
    w(detalhes_bloco("h") + "\n")
    # (i)
    w("## 9. O que NÃO dá para comparar e por quê\n")
    w("Cada linha traz a evidência que sai dos arquivos publicados. Não é lista de causas: é lista de definições e lacunas que "
      "limitam a leitura dos números acima.\n")
    t = T["nao_comparavel"]
    w(md_tabela(["Tema", NOME["mt"], NOME["ms"], "O que limita a comparação", "Arquivos"],
                [[r["tema"], r["energisa_mt"], r["energisa_ms"], r["o_que_limita"], r["arquivos"]] for _, r in t.iterrows()]) + "\n")
    # reprodução
    w("## Como reproduzir\n")
    w("Clone `distribution-asset-risk` com os quatro repositórios irmãos na mesma pasta (`automation-impact`, `recloser-performance`, "
      "`substation-health-index` e `switchgear-survival`, já com os resultados de MS mesclados) e rode:\n")
    w("```bash\npip install -e \".[dev]\"\npython scripts/comparativo_mt_ms.py --atualizar-docs\n```\n")
    w("Use `--irmaos <pasta>` se os irmãos estiverem em outro lugar. O script grava `reports/comparativo_mt_ms/` e, com "
      "`--atualizar-docs`, este documento e o bloco do README; ele **se recusa a regravar os dois** se algum arquivo de origem "
      "faltar. Sem a opção, só escreve em `reports/comparativo_mt_ms/`.\n")
    if res.faltas:
        w("**Arquivos de origem não encontrados nesta execução:** " + ", ".join(f"`{f}`" for f in res.faltas) + ".\n")
    return "\n".join(a).rstrip() + "\n"


def sim_nao(*bates) -> str:
    vals = [b for b in bates if isinstance(b, (bool, numbers.Integral))]
    if not vals:
        return ND
    return "sim" if all(bool(b) for b in vals) else "não"


def razao_ou_na(r, vpl_trad) -> str:
    if numerico(r):
        return fmt(r, 2)
    return "não se aplica" if numerico(vpl_trad) else ND


def serie_expurgo_ms(T: dict) -> str:
    t = T["falhas_por_ano"]
    if "pct_chi_expurgado_ms" not in t.columns:
        return ND
    x = t[t["ano"].astype(int) <= ANO_REF]
    pares = [f"{int(a)}: {fmt(v, 0, True)}" for a, v in zip(x["ano"], x["pct_chi_expurgado_ms"], strict=True) if numerico(v)]
    return "; ".join(pares) if pares else ND


def renderizar_readme(res: Resultado) -> str:
    P = res.P
    linhas = [
        (f"Falhas na média tensão por 100 km por ano (média {JANELA})", "falhas_100km", 1, False),
        ("CHI das falhas por consumidor por ano, em horas", "chi_uc", 1, False),
        ("Fração do CHI das falhas que é expurgada", "frac_exp", 1, True),
        (f"DEC oficial de {ANO_REF}, em horas", "dec_of", 2, False),
        ("Parcela do risco social nos 10% de alimentadores de maior risco", "top10_social", 1, True),
        (f"Carteira ótima ÷ regra tradicional ({ORC}, visão social, premissas ilustrativas)", "razao_carteira", 2, False),
    ]
    tabela = md_tabela(["Indicador (descritivo)", NOME["mt"], NOME["ms"]], [[n, *par_txt(P, k, c, p)] for n, k, c, p in linhas])
    return (f"{MARCA_INI}\n"
            "## Comparativo MT × MS\n\n"
            "Comparação **só descritiva** entre a Energisa MT e a Energisa MS, por consumidor e por km de rede de média tensão. Ela "
            "não afirma causas, e várias diferenças podem vir de definições diferentes dos dados (expurgo, circuitos do cadastro, "
            "anos de cadastro, meses faltando em MS). O efeito do religador em MS é o de MT, não medido. Documento completo: "
            "[`docs/comparativo_mt_ms.md`](docs/comparativo_mt_ms.md); CSVs e figuras: "
            "[`reports/comparativo_mt_ms/`](reports/comparativo_mt_ms/); tudo sai de "
            "[`scripts/comparativo_mt_ms.py`](scripts/comparativo_mt_ms.py), que lê só arquivos já publicados.\n\n"
            f"{tabela}\n\n"
            "> Projeto independente, sem vínculo com a Energisa ou com a ANEEL. Só dados abertos (ANEEL e IBGE).\n"
            f"{MARCA_FIM}")


def trocar_bloco(texto: str, bloco: str) -> str:
    i, j = texto.find(MARCA_INI), texto.find(MARCA_FIM)
    if i < 0 or j < 0 or j < i:
        raise ValueError(f"o README não tem as marcas {MARCA_INI} e {MARCA_FIM}")
    return texto[:i] + bloco + texto[j + len(MARCA_FIM):]


# --------------------------------------------------------------------------------------------- orquestração
@dataclass
class Resultado:
    P: dict
    T: dict
    metricas: pd.DataFrame
    verificacoes: pd.DataFrame
    fontes: pd.DataFrame
    avisos: list[str]
    faltas: list[str]
    figuras: list[str]

    @property
    def n_verificacoes_ok(self) -> int:
        return int((self.verificacoes["passou"] == True).sum())


def gerar(raiz: Path, irmaos: Path, saida: Path, com_figuras: bool = True) -> Resultado:
    F = Fontes(raiz, irmaos)
    C, S = ler_arquivos(F)
    avisos = F.avisos
    P = derivar(C, S, avisos)
    T = tabelas(C, S, P, avisos)
    metricas, verif = montar_metricas(P), verificar(C, S, P)
    saida.mkdir(parents=True, exist_ok=True)
    fmt_csv = {"index": False, "float_format": "%.10g"}
    metricas.to_csv(saida / "metricas.csv", **fmt_csv)
    for nome, df in T.items():
        df.to_csv(saida / f"{nome}.csv", **fmt_csv)
    verif.to_csv(saida / "verificacoes.csv", **fmt_csv)
    fontes = tabela_fontes(F)
    fontes.to_csv(saida / "fontes.csv", **fmt_csv)
    geradas = figuras(P, T, saida / "figures") if com_figuras else []
    return Resultado(P, T, metricas, verif, fontes, avisos, F.faltas(), geradas)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Comparativo descritivo Energisa MT × Energisa MS (lê só arquivos publicados).")
    ap.add_argument("--raiz", type=Path, default=ROOT, help="raiz do distribution-asset-risk (padrão: este repositório)")
    ap.add_argument("--irmaos", type=Path, default=None, help="pasta com os quatro repositórios irmãos (padrão: a pasta acima da raiz)")
    ap.add_argument("--saida", type=Path, default=None, help="padrão: <raiz>/reports/comparativo_mt_ms")
    ap.add_argument("--atualizar-docs", action="store_true", help="regrava docs/comparativo_mt_ms.md e o bloco do README")
    ap.add_argument("--sem-figuras", action="store_true")
    a = ap.parse_args(argv)
    raiz = a.raiz.resolve()
    irmaos = (a.irmaos or raiz.parent).resolve()
    saida = a.saida or raiz / "reports" / "comparativo_mt_ms"
    res = gerar(raiz, irmaos, saida, com_figuras=not a.sem_figuras)
    print(f"{len(res.metricas)} métricas, {len(res.verificacoes)} verificações ({res.n_verificacoes_ok} dentro de {fmt(100 * TOLERANCIA_VERIFICACAO, 0)}%), "
          f"{len(res.figuras)} figuras, saída em {saida}")
    for aviso in res.avisos:
        print("aviso:", aviso, file=sys.stderr)
    if res.faltas:
        print("arquivos de origem ausentes:", file=sys.stderr)
        for f in res.faltas:
            print("  ", f, file=sys.stderr)
    if a.atualizar_docs:
        if res.faltas or res.avisos:
            print("NÃO regravei docs/comparativo_mt_ms.md nem o README: faltam arquivos de origem ou há arquivos ilegíveis.",
                  file=sys.stderr)
            return 2
        readme = raiz / "README.md"
        try:
            novo_readme = trocar_bloco(readme.read_text(encoding="utf-8"), renderizar_readme(res))
        except (OSError, ValueError) as e:
            print(f"NÃO regravei o documento nem o README: {e}", file=sys.stderr)
            return 2
        (raiz / "docs").mkdir(exist_ok=True)
        (raiz / "docs" / "comparativo_mt_ms.md").write_text(renderizar_doc(res), encoding="utf-8", newline="\n")
        readme.write_text(novo_readme, encoding="utf-8", newline="\n")
        print("docs/comparativo_mt_ms.md e o bloco do README atualizados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
