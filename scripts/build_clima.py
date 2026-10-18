"""Clima mensal do INMET interpolado para cada alimentador."""
import logging

import pandas as pd

from gridrisk.config import Config
from gridrisk.ingest import inmet

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
cfg = Config.load()
anos = [a for a in cfg.anos_interrupcoes if a < max(cfg.anos_interrupcoes)]
zips = inmet.download(anos, cfg.raw / "inmet")
clima, estacoes = inmet.monthly_by_station(zips, "MT")
clima.to_parquet(cfg.interim / "inmet_estacao_mes.parquet", index=False)
estacoes.to_parquet(cfg.interim / "inmet_estacoes.parquet", index=False)

# coordenadas do alimentador: snapshot mais recente em que ele aparece
snaps = sorted(cfg.interim.glob("bdgd_feeders_*.parquet"))
coords = pd.concat([pd.read_parquet(p, columns=["alimentador_nome", "lat", "lon", "ano_snapshot"]) for p in snaps])
coords = (coords.dropna(subset=["lat"]).sort_values("ano_snapshot")
          .drop_duplicates("alimentador_nome", keep="last")
          .rename(columns={"alimentador_nome": "alimentador_cod_id"}))
cf = inmet.idw_to_feeders(clima, estacoes, coords).rename(columns={"alimentador_cod_id": "alimentador"})
cf.to_parquet(cfg.interim / "clima_alimentador_mes.parquet", index=False)
print(cf.describe().T.round(2).to_string())
