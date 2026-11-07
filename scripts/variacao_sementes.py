"""Quanto as métricas do backtest variam de uma semente do LightGBM para outra?

Treina o modelo da configuração (com ou sem clima, conforme ``modelo.usar_clima``) nas sementes 0 a N-1, no mesmo
backtest de origem móvel do ``run_pipeline.py``, e resume cada métrica pela média dos anos de teste. A variação entre
sementes é o desvio-padrão (n-1) dessas médias; é o número que o README de MT cita (62 em 16,2 mil de erro do CHI).

Pré-requisitos: ``build_interrupcoes.py`` e ``build_bdgd.py``.
Saídas: ``<reports>/variacao_sementes.csv`` (uma linha por semente x alvo x ano x método) e
``<reports>/variacao_sementes.json`` (média, desvio-padrão e coeficiente de variação por alvo e métrica).
"""
import json
import logging

import pandas as pd

from gridrisk import features as F
from gridrisk import model as M
from gridrisk.config import Config, parser
from gridrisk.reporting import normalizar_nan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("variacao_sementes")
ap = parser("Variação das métricas do backtest entre sementes do LightGBM.")
ap.add_argument("--sementes", type=int, default=10, help="número de sementes (0 a N-1); padrão 10")
args = ap.parse_args()
cfg = Config.load(args.config)
cfg.reports.mkdir(parents=True, exist_ok=True)

clima = F.carregar_clima(cfg.interim, cfg.usar_clima)
cortes = F.falhas_point_in_time(cfg.interrupcoes_parquet, cfg.interim)
painel = F.build_panel(cortes, cfg.interim, clima, list(range(cfg.ano_inicio_painel, max(cfg.anos_teste) + 1)))

fit_original = M.fit
linhas = []
try:
    for semente in range(args.sementes):
        M.fit = lambda p, a, s=semente: fit_original(p, a, seed=s)  # o backtest usa o fit do módulo
        for alvo in ["n_falhas", "chi"]:
            bt = M.backtest(painel, alvo, cfg.anos_teste)
            linhas.append(bt.resumo.assign(alvo=alvo, semente=semente))
        log.info("semente %d ok", semente)
finally:
    M.fit = fit_original

resumo = pd.concat(linhas, ignore_index=True)
resumo.to_csv(cfg.reports / "variacao_sementes.csv", index=False)
metricas = ["deviance_poisson", "mae_alimentador", "spearman_alimentador", "captura_top10", "captura_top20", "vies_total_pct"]
saida = {"sementes": args.sementes, "anos_teste": cfg.anos_teste, "com_clima": clima is not None, "modelo": {}, "baselines": {}}
for alvo, g in resumo.groupby("alvo"):
    metodo_cols = [c for c in metricas if c in g and g[c].notna().any()]
    modelo = g[g.metodo == "modelo"].groupby("semente")[metodo_cols].mean()
    saida["modelo"][alvo] = {
        c: {"media": float(modelo[c].mean()), "desvio_padrao": float(modelo[c].std(ddof=1)),
            "cv_pct": float(100 * modelo[c].std(ddof=1) / abs(modelo[c].mean())), "min": float(modelo[c].min()),
            "max": float(modelo[c].max())} for c in metodo_cols}
    base = g[g.metodo != "modelo"].groupby(["metodo", "ano_teste"])[metodo_cols].mean().groupby("metodo").mean()
    saida["baselines"][alvo] = {m: {c: float(v) for c, v in base.loc[m].items()} for m in base.index}
(cfg.reports / "variacao_sementes.json").write_text(
    json.dumps(normalizar_nan(saida), indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
print(json.dumps(saida["modelo"], indent=2, ensure_ascii=False))
