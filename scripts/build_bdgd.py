"""Processa todos os snapshots da BDGD configurados (um por vez, para poupar disco)."""
import logging

from gridrisk.config import Config, parser
from gridrisk.ingest import bdgd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
ap = parser("Processa os snapshots da BDGD configurados (um por vez, para poupar disco).")
ap.add_argument("anos", nargs="*", type=int, help="anos a processar (padrão: todos os da configuração)")
args = ap.parse_args()
cfg = Config.load(args.config)
anos = args.anos or sorted(cfg.bdgd_snapshots, reverse=True)
for ano in anos:
    feat = cfg.interim / f"bdgd_feeders_{ano}.parquet"
    mp = cfg.interim / f"bdgd_map_{ano}.parquet"
    if feat.exists() and mp.exists():
        continue
    bdgd.build_snapshot(cfg.bdgd_snapshots[ano], ano, cfg.raw, cfg.interim, keep_gdb=(ano == max(cfg.bdgd_snapshots)))
