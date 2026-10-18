"""Baixa e harmoniza as interrupções da ANEEL para a distribuidora configurada."""
import logging

from gridrisk.config import Config
from gridrisk.ingest import interrupcoes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
cfg = Config.load()
paths = interrupcoes.download(cfg.anos_interrupcoes, cfg.raw / "interrupcoes")
interrupcoes.harmonize(paths, cfg.sigla, cfg.interim / "interrupcoes_emt.parquet")
