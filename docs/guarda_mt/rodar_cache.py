"""Roda um script do repositorio trocando os downloads (BDGD e interrupcoes ANEEL) por leitura do cache compartilhado.

Uso: python -I rodar_cache_ms.py <script.py> [args do script...]
Variaveis: BDGD_CACHE (pasta com bdgd_<ano>_<item>.gdb.zip), ANEEL_INTERRUPCOES (pasta com os parquet anuais).
O cache nunca e modificado: o zip e extraido para o dest do pipeline (dentro do clone).
"""
import os
import runpy
import sys
import zipfile
from pathlib import Path

from gridrisk.ingest import bdgd, interrupcoes

BDGD_CACHE = Path(os.environ["BDGD_CACHE"])
ANEEL = Path(os.environ["ANEEL_INTERRUPCOES"])


def download_bdgd(item: str, dest: Path, retries: int = 4) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    existing = [p for p in dest.rglob("*.gdb") if p.is_dir()]
    if existing:
        return existing[0]
    zips = list(BDGD_CACHE.glob(f"bdgd_*_{item}.gdb.zip"))
    if len(zips) != 1:
        raise SystemExit(f"cache sem o item {item}: {zips}")
    print(f"[cache] extraindo {zips[0].name} -> {dest}", flush=True)
    with zipfile.ZipFile(zips[0]) as z:
        z.extractall(dest)
    return next(p for p in dest.rglob("*.gdb") if p.is_dir())


def download_interrupcoes(anos, dest: Path, retries: int = 4) -> list[Path]:
    out = []
    for ano in anos:
        p = ANEEL / f"interrupcoes-energia-eletrica-{ano}.parquet"
        if not p.exists():
            raise SystemExit(f"cache sem {p}")
        out.append(p)
    return out


bdgd.download = download_bdgd
interrupcoes.download = download_interrupcoes
script = sys.argv[1]
sys.argv = [script, *sys.argv[2:]]
runpy.run_path(script, run_name="__main__")
