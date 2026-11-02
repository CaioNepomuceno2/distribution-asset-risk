"""Baixa os indicadores coletivos de continuidade (DEC/FEC) e as compensações pagas da ANEEL.

Usados em ``validate_dec.py`` (DEC/FEC oficiais) e em ``run_pipeline.py`` (R$ pagos por violação).
"""
import logging

import requests

from gridrisk.config import Config

CKAN = "https://dadosabertos.aneel.gov.br/api/3/action/package_show"
DATASET = "indicadores-coletivos-de-continuidade-dec-e-fec"
ARQUIVOS = ["indicadores-continuidade-coletivos-2020-2029.parquet",
            "indicadores-continuidade-coletivos-compensacao-2020-2029.parquet"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("continuidade")
cfg = Config.load()
dest = cfg.raw / "continuidade"
dest.mkdir(parents=True, exist_ok=True)

recursos = requests.get(CKAN, params={"id": DATASET}, timeout=60).json()["result"]["resources"]
urls = {r["url"].rsplit("/", 1)[-1]: r["url"] for r in recursos}
for nome in ARQUIVOS:
    if nome not in urls:
        raise SystemExit(f"{nome} não encontrado no dataset {DATASET}")
    out = dest / nome
    log.info("baixando %s", nome)
    with requests.get(urls[nome], stream=True, timeout=1200) as r:
        r.raise_for_status()
        tmp = out.with_suffix(".part")
        with open(tmp, "wb") as f:
            f.writelines(r.iter_content(1 << 20))
        tmp.replace(out)
    log.info("%s: %.1f MB", nome, out.stat().st_size / 1e6)
