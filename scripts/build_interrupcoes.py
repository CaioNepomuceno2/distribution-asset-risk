"""Baixa e harmoniza as interrupções da ANEEL para a distribuidora configurada."""
import logging

from gridrisk.config import carregar
from gridrisk.ingest import interrupcoes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
cfg = carregar("Baixa e harmoniza as interrupções da ANEEL para a distribuidora configurada.")
paths = interrupcoes.download(cfg.anos_interrupcoes, cfg.raw / "interrupcoes")
interrupcoes.harmonize(paths, cfg.sigla, cfg.interrupcoes_parquet)
