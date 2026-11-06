"""Experimento pré-registrado: o clima do INMET melhora o backtest? (ver docs/preregistro_clima.md)

Treina o mesmo modelo com e sem as colunas de clima, nas sementes 0 a 9 do LightGBM, no backtest de origem móvel
2023-2025, e aplica a regra de decisão de ``gridrisk.regra_clima`` sem ajuste nenhum.

Pré-requisitos: ``scripts/build_interrupcoes.py``, ``scripts/build_bdgd.py`` e ``scripts/build_clima.py``.
Saídas: ``reports/experimento_clima_sementes.csv`` (uma linha por modo x semente x alvo x ano) e
``reports/experimento_clima.json`` (a decisão e a conta de cada critério).
"""
import json
import logging

import pandas as pd

from gridrisk import features as F
from gridrisk import model as M
from gridrisk import regra_clima
from gridrisk.config import ROOT, Config
from gridrisk.reporting import normalizar_nan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("experimento_clima")
cfg = Config.load()
OUT = ROOT / "reports"
ANOS_TESTE = [2023, 2024, 2025]
SEMENTES = range(10)

clima = pd.read_parquet(cfg.interim / "clima_alimentador_mes.parquet")
cortes = F.falhas_point_in_time(cfg.interim / "interrupcoes_emt.parquet", cfg.interim)
paineis = {"semclima": F.build_panel(cortes, cfg.interim, None, list(range(2019, max(ANOS_TESTE) + 1))),
           "clima": F.build_panel(cortes, cfg.interim, clima, list(range(2019, max(ANOS_TESTE) + 1)))}
for modo, painel in paineis.items():
    log.info("%s: %d linhas, %d colunas clim_*", modo, len(painel), sum(c.startswith("clim_") for c in painel.columns))

fit_original = M.fit
linhas = []
try:
    for modo, painel in paineis.items():
        for semente in SEMENTES:
            M.fit = lambda p, a, s=semente: fit_original(p, a, seed=s)  # backtest usa o fit do módulo
            for alvo in ["n_falhas", "chi"]:
                bt = M.backtest(painel, alvo, ANOS_TESTE)
                linhas.append(bt.resumo.assign(alvo=alvo, semente=semente, modo=modo))
            log.info("%s semente %d ok", modo, semente)
finally:
    M.fit = fit_original

resumo = pd.concat(linhas, ignore_index=True)
resumo.to_csv(OUT / "experimento_clima_sementes.csv", index=False)
decisao = regra_clima.avaliar(resumo)
(OUT / "experimento_clima.json").write_text(
    json.dumps(normalizar_nan(decisao), indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
print(json.dumps(decisao, indent=2, ensure_ascii=False))
