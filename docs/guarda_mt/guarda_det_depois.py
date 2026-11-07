"""Parte DETERMINISTICA de run_pipeline.py para a guarda de MT, agora pelas propriedades da Config refatorada.
Uso (cwd = raiz do repo): python -I guarda_det_depois.py <pasta_saida>   (sem --config: configuracao padrao de MT)
"""
import sys
from pathlib import Path

import pandas as pd

from gridrisk import features as F
from gridrisk import otimizacao as O
from gridrisk import risco as R
from gridrisk.config import Config

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
cfg = Config.load()
assert cfg.sigla == "EMT"
inter = cfg.interrupcoes_parquet
falhas_cortes = F.falhas_point_in_time(inter, cfg.interim)
for a, df in falhas_cortes.items():
    df.to_parquet(out / f"falhas_corte_{a}.parquet", index=False)
falhas = falhas_cortes[max(falhas_cortes)]
falhas.to_parquet(out / "falhas.parquet", index=False)
panel = F.build_panel(falhas_cortes, cfg.interim, F.carregar_clima(cfg.interim, cfg.usar_clima),
                      list(range(cfg.ano_inicio_painel, cfg.ano_previsao + 1)))
panel.to_parquet(out / "panel.parquet", index=False)
fin, catalogo = O.carregar_catalogo(cfg.catalogo)
ult = max(int(p.stem.split("_")[-1]) for p in cfg.interim.glob("bdgd_feeders_*.parquet"))
feeders = (pd.read_parquet(cfg.interim / f"bdgd_feeders_{ult}.parquet")
           .rename(columns={"alimentador_nome": "alimentador"}).drop_duplicates("alimentador"))
comp = R.compensacao_por_chi(cfg.raw / "continuidade" / "indicadores-continuidade-coletivos-compensacao-2020-2029.parquet",
                             inter, cfg.sigla, cfg.anos_compensacao)
pesos = R.conjunto_do_alimentador(inter, cfg.interim / f"crosswalk_{ult}.parquet", cfg.ano_inicio_pesos_conjunto)
comp.to_parquet(out / "comp.parquet", index=False)
pesos.to_parquet(out / "pesos.parquet", index=False)
R.valor_chi_alimentador(comp, pesos, feeders, 0.0).to_parquet(out / "valor_compensacao.parquet", index=False)
R.valor_chi_alimentador(comp, pesos, feeders, fin["custo_ens_rs_mwh"]).to_parquet(out / "valor_social.parquet", index=False)
print("guarda_det_depois ok", flush=True)
