"""Números de apoio à decisão citados na seção "Na prática" do README.

Pré-requisito: ``scripts/run_pipeline.py``. Saída: ``reports/resumo_decisao.json``.
"""
import json

import pandas as pd

from gridrisk.config import ROOT, Config

cfg = Config.load()
OUT = ROOT / "reports"
risco = pd.read_parquet(cfg.processed / "risco_alimentador.parquet")
front = pd.read_csv(OUT / "fronteira_social.csv")


def concentracao(s: pd.Series, frac: float) -> float:
    s = s.sort_values(ascending=False)
    return float(s.head(round(len(s) * frac)).sum() / s.sum())


f20 = front[front.orcamento == 20e6].set_index("metodo")
resumo = {
    "n_alimentadores": len(risco),
    "risco_2026_rs_ano_compensacao": float(risco.risco_rs_compensacao.sum()),
    "risco_2026_rs_ano_social": float(risco.risco_rs_social.sum()),
    "dec_previsto_falhas_mt_h": float(risco.dec_contribuicao_h.sum()),
    "frac_risco_social_top10pct_alimentadores": concentracao(risco.risco_rs_social, 0.10),
    "frac_risco_social_top20pct_alimentadores": concentracao(risco.risco_rs_social, 0.20),
    "carteira_20M_vpl_por_real_investido": {
        m: float(f20.loc[m, "vpl"] / f20.loc[m, "investido"]) for m in ["otimo", "guloso", "tradicional"]},
    "carteira_20M_chi_evitado_por_mil_reais": {
        m: float(f20.loc[m, "chi_evitado_ano"] / f20.loc[m, "investido"] * 1e3)
        for m in ["otimo", "guloso", "tradicional"]},
}
(OUT / "resumo_decisao.json").write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(resumo, indent=2, ensure_ascii=False))
