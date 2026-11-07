"""Diagnóstico de qualidade dos snapshots da BDGD (camadas, códigos de alimentador, TIP_UNID, DAT_IMO, coordenadas).

Lê o .gdb já extraído em ``<raw>/bdgd/<ano>/`` (o mesmo lugar que ``build_bdgd.py`` usa) e grava
``<reports>/diagnostico/bdgd_<ano>.json``. Rode antes de confiar nas suposições herdadas de outra distribuidora;
as decisões que saem daqui ficam em ``docs/decisoes_ems.md``.
"""
import json
import logging

from gridrisk.config import Config, parser
from gridrisk.ingest import diagnostico_bdgd as D

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("diagnostico_bdgd")
ap = parser("Diagnóstico de qualidade dos snapshots da BDGD.")
ap.add_argument("anos", nargs="*", type=int, help="anos a diagnosticar (padrão: todos os que têm .gdb extraído)")
args = ap.parse_args()
cfg = Config.load(args.config)

malha = json.loads(cfg.malha_ibge.read_text())
pontos = [p for f in malha["features"] for anel in f["geometry"]["coordinates"] for p in anel]
bbox = (min(p[0] for p in pontos), min(p[1] for p in pontos), max(p[0] for p in pontos), max(p[1] for p in pontos))
destino = cfg.reports / "diagnostico"
destino.mkdir(parents=True, exist_ok=True)
for ano in args.anos or sorted(cfg.bdgd_snapshots):
    gdbs = sorted((cfg.raw / "bdgd" / str(ano)).rglob("*.gdb"))
    if not gdbs:
        log.warning("sem .gdb extraído para %s em %s", ano, cfg.raw / "bdgd" / str(ano))
        continue
    res = D.diagnosticar(gdbs[0], ano, bbox)
    (destino / f"bdgd_{ano}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    log.info("diagnóstico %s gravado", ano)
