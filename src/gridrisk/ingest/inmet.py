"""Clima: estações automáticas do INMET (dados históricos horários).

Os arquivos anuais (``portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip``)
trazem um CSV por estação. Aqui são lidos apenas os da UF de interesse,
agregados por mês e interpolados para o centróide de cada alimentador por
inverso da distância (IDW) das estações mais próximas.
"""
from __future__ import annotations

import io
import logging
import re
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

log = logging.getLogger(__name__)

URL = "https://portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip"
NA = -9999

COLS = {
    "precip_mm": "PRECIPITA",
    "temp_c": "TEMPERATURA DO AR - BULBO SECO",
    "umid_pct": "UMIDADE RELATIVA DO AR, HORARIA",
    "rajada_ms": "VENTO, RAJADA MAXIMA",
    "vento_ms": "VENTO, VELOCIDADE HORARIA",
}


def download(anos: list[int], dest: Path, retries: int = 4) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for ano in anos:
        path = dest / f"{ano}.zip"
        if path.exists() and zipfile.is_zipfile(path):
            out.append(path)
            continue
        for attempt in range(retries):
            try:
                with requests.get(URL.format(ano=ano), stream=True, timeout=1800,
                                  headers={"User-Agent": "Mozilla/5.0"}) as r:
                    r.raise_for_status()
                    with open(path, "wb") as f:
                        f.writelines(r.iter_content(1 << 20))
                break
            except requests.RequestException:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** (attempt + 1))
        out.append(path)
    return out


def _num(s: pd.Series) -> pd.Series:
    v = pd.to_numeric(s.astype(str).str.replace(",", ".", regex=False), errors="coerce")
    return v.where(v != NA)


def _parse_station(raw: bytes) -> tuple[dict, pd.DataFrame]:
    text = raw.decode("latin-1")
    lines = text.splitlines()
    meta = {}
    for ln in lines[:8]:
        k, _, v = ln.partition(":")
        meta[k.strip().upper()] = v.strip().strip(";").strip()
    df = pd.read_csv(io.StringIO("\n".join(lines[8:])), sep=";", dtype=str)
    df.columns = [c.strip().upper() for c in df.columns]
    data_col = next(c for c in df.columns if c.startswith("DATA"))
    hora_col = next(c for c in df.columns if c.startswith("HORA"))
    data = pd.to_datetime(df[data_col].str.replace("/", "-", regex=False), format="%Y-%m-%d", errors="coerce")
    hora = df[hora_col].str.extract(r"(\d{2}):?(\d{2})")[0].astype(float)
    out = pd.DataFrame({"ts": data + pd.to_timedelta(hora, unit="h")})
    for name, prefix in COLS.items():
        col = next((c for c in df.columns if c.startswith(prefix)), None)
        out[name] = _num(df[col]) if col else np.nan
    return meta, out


def _coord(v: str) -> float:
    return float(v.replace(",", "."))


def monthly_by_station(zips: list[Path], uf: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Agrega as estações da UF por mês. Devolve (clima_mensal, estacoes)."""
    pat = re.compile(rf"_{uf}_", re.IGNORECASE)
    frames, stations = [], {}
    for zp in zips:
        with zipfile.ZipFile(zp) as z:
            for name in z.namelist():
                if not name.upper().endswith(".CSV") or not pat.search(Path(name).name):
                    continue
                meta, h = _parse_station(z.read(name))
                cod = meta.get("CODIGO (WMO)") or meta.get("CÓDIGO (WMO)") or Path(name).name.split("_")[3]
                stations[cod] = {
                    "estacao": cod,
                    "nome": meta.get("ESTACAO") or meta.get("ESTAÇÃO"),
                    "lat": _coord(meta.get("LATITUDE")),
                    "lon": _coord(meta.get("LONGITUDE")),
                }
                h = h.dropna(subset=["ts"])
                h["ano"], h["mes"] = h.ts.dt.year, h.ts.dt.month
                h["dia"] = h.ts.dt.floor("D")
                d = h.groupby(["ano", "mes", "dia"]).agg(
                    precip_dia=("precip_mm", lambda s: s.sum(min_count=12)),
                    rajada_dia=("rajada_ms", "max"),
                ).reset_index()
                m = h.groupby(["ano", "mes"]).agg(
                    precip_total_mm=("precip_mm", "sum"),
                    precip_max_1h_mm=("precip_mm", "max"),
                    horas_chuva_forte=("precip_mm", lambda s: (s >= 10).sum()),
                    rajada_max_ms=("rajada_ms", "max"),
                    rajada_p95_ms=("rajada_ms", lambda s: s.quantile(0.95)),
                    temp_max_c=("temp_c", "max"),
                    temp_media_c=("temp_c", "mean"),
                    umid_media_pct=("umid_pct", "mean"),
                    cobertura_horas=("precip_mm", lambda s: s.notna().mean()),
                ).reset_index()
                dm = d.groupby(["ano", "mes"]).agg(
                    dias_chuva_50mm=("precip_dia", lambda s: (s >= 50).sum()),
                    dias_rajada_15ms=("rajada_dia", lambda s: (s >= 15).sum()),
                ).reset_index()
                m = m.merge(dm, on=["ano", "mes"], how="left")
                m["estacao"] = cod
                frames.append(m)
    clima = pd.concat(frames, ignore_index=True)
    # meses com menos de 60% das horas válidas viram ausentes
    vars_ = [c for c in clima.columns if c not in {"ano", "mes", "estacao", "cobertura_horas"}]
    clima.loc[clima.cobertura_horas < 0.6, vars_] = np.nan
    log.info("INMET %s: %d estações, %d estação-mês", uf, len(stations), len(clima))
    return clima, pd.DataFrame(stations.values())


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def idw_to_feeders(clima: pd.DataFrame, estacoes: pd.DataFrame, feeders: pd.DataFrame,
                   k: int = 3, max_km: float = 250.0) -> pd.DataFrame:
    """Interpola o clima mensal para cada alimentador (IDW das k estações com dado no mês)."""
    vars_ = [c for c in clima.columns if c not in {"ano", "mes", "estacao", "cobertura_horas"}]
    f = feeders.dropna(subset=["lat", "lon"])[["alimentador_cod_id", "lat", "lon"]]
    dist = haversine_km(f.lat.values[:, None], f.lon.values[:, None],
                        estacoes.lat.values[None, :], estacoes.lon.values[None, :])
    dist = pd.DataFrame(dist, index=f.alimentador_cod_id.values, columns=estacoes.estacao.values)
    out = []
    for (ano, mes), g in clima.groupby(["ano", "mes"]):
        g = g.set_index("estacao")[vars_]
        cols = [c for c in dist.columns if c in g.index]
        d = dist[cols]
        res = {}
        for v in vars_:
            vals = g.loc[cols, v]
            ok = vals.notna().values
            dv = d.values[:, ok]
            if dv.shape[1] == 0:
                res[v] = np.full(len(d), np.nan)
                continue
            idx = np.argsort(dv, axis=1)[:, :k]
            dk = np.take_along_axis(dv, idx, axis=1)
            vk = vals.values[ok][idx]
            w = np.where(dk <= max_km, 1 / np.maximum(dk, 1.0) ** 2, 0)
            res[v] = np.where(w.sum(1) > 0, (w * vk).sum(1) / np.maximum(w.sum(1), 1e-12), np.nan)
        r = pd.DataFrame(res, index=d.index)
        r["dist_estacao_km"] = d.min(axis=1)
        r["ano"], r["mes"] = ano, mes
        out.append(r.reset_index(names="alimentador_cod_id"))
    return pd.concat(out, ignore_index=True)
