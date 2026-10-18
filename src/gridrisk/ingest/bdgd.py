"""Extração de atributos de ativos por alimentador a partir da BDGD (PRODIST Módulo 10).

Cada snapshot da BDGD é um File Geodatabase de ~1 GB (zip) com o cadastro completo
da rede em 31/12 do ano. Aqui ele é reduzido a uma linha por circuito de média
tensão (CTMT) com atributos físicos, de proteção, de carga e de idade.

Domínios de código seguem o Manual de Instruções da BDGD (Rev. 5, Anexo II).
"""
from __future__ import annotations

import logging
import shutil
import time
import zipfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyogrio
import requests

log = logging.getLogger(__name__)

ARCGIS_DATA = "https://www.arcgis.com/sharing/rest/content/items/{item}/data"

# TUNI: tipos de unidade seccionadora de MT
TUNI_RELIGADOR = {"32"}
TUNI_SECCIONALIZADOR = {"35", "36"}
TUNI_CHAVE_FUSIVEL = {"22", "23", "24", "25", "26", "27"}
TUNI_DISJUNTOR = {"29", "30", "53"}
# TCABOGTCEOM: geometria do cabo
GEOM_COMPACTA = "1"
GEOM_SUBTERRANEA = "5"
# TCABOISO: isolação
ISO_NU = "12"
# Data-padrão usada no cadastro quando a data real de conexão é desconhecida
DATA_DESCONHECIDA = "01/01/1980"


def download(item: str, dest: Path, retries: int = 4) -> Path:
    """Baixa e descompacta um snapshot; devolve o caminho do .gdb."""
    dest.mkdir(parents=True, exist_ok=True)
    existing = [p for p in dest.glob("*.gdb") if p.is_dir()]
    if existing:
        return existing[0]
    zpath = dest / f"{item}.gdb.zip"
    for attempt in range(retries):
        try:
            with requests.get(ARCGIS_DATA.format(item=item), stream=True, timeout=3000) as r:
                r.raise_for_status()
                with open(zpath, "wb") as f:
                    f.writelines(r.iter_content(1 << 22))
            break
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    with zipfile.ZipFile(zpath) as z:
        z.extractall(dest)
    zpath.unlink()
    return next(p for p in dest.rglob("*.gdb") if p.is_dir())


# Nomes que mudaram entre o modelo antigo da BDGD (M10, até 2020) e o atual (V10/V11)
LAYER_ALIASES = {"UNTRMT": ["UNTRMT", "UNTRD"]}
FIELD_ALIASES = {"NOME": ["NOME", "NOM"]}


def _layer(gdb: Path, layer: str) -> str:
    disponiveis = {name for name, _ in pyogrio.list_layers(gdb)}
    return next(c for c in LAYER_ALIASES.get(layer, [layer]) if c in disponiveis)


def _read(gdb: Path, layer: str, columns: list[str], geometry: bool = False) -> pd.DataFrame:
    layer = _layer(gdb, layer)
    fields = set(pyogrio.read_info(gdb, layer=layer)["fields"])
    origem = {}
    for c in columns:
        alt = next((a for a in FIELD_ALIASES.get(c, [c]) if a in fields), None)
        if alt:
            origem[c] = alt
    df = pyogrio.read_dataframe(gdb, layer=layer, read_geometry=geometry, columns=list(origem.values()),
                                use_arrow=True)
    df = df.rename(columns={v: k for k, v in origem.items()})
    for c in set(columns) - set(origem):
        df[c] = None
    return df


def _str(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip()


def _ano_conexao(s: pd.Series) -> pd.Series:
    s = _str(s)
    anos = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce").dt.year
    return anos.where(s != DATA_DESCONHECIDA)


def feeder_features(gdb: Path, ano_ref: int) -> pd.DataFrame:
    """Uma linha por alimentador (CTMT.COD_ID) com atributos de ativos."""
    con = duckdb.connect()

    ct = _read(gdb, "CTMT", ["COD_ID", "NOME", "SUB", "TEN_NOM", *[f"ENE_{m:02d}" for m in range(1, 13)]])
    ct["COD_ID"], ct["NOME"], ct["SUB"] = _str(ct.COD_ID), _str(ct.NOME), _str(ct.SUB)
    ene = ct[[f"ENE_{m:02d}" for m in range(1, 13)]].apply(pd.to_numeric, errors="coerce")
    base = pd.DataFrame({
        "alimentador_cod_id": ct.COD_ID,
        "alimentador_nome": ct.NOME.str.zfill(6),
        "subestacao_bdgd": ct.SUB,
        "ten_nom_cod": _str(ct.TEN_NOM),
        "energia_mwh_ano": ene.sum(axis=1) / 1e3,
        "pico_sazonal_energia": ene.max(axis=1) / ene.mean(axis=1).replace(0, np.nan),
    })

    # --- Rede MT: comprimento, ruralidade, tipo de condutor
    seg = _read(gdb, "SSDMT", ["CTMT", "ARE_LOC", "TIP_CND", "FAS_CON", "COMP"])
    cond = _read(gdb, "SEGCON", ["COD_ID", "GEOM_CAB", "ISO_FAS_1", "MAT_FAS_1"])
    for c in ["CTMT", "ARE_LOC", "TIP_CND", "FAS_CON"]:
        seg[c] = _str(seg[c])
    for c in ["COD_ID", "GEOM_CAB", "ISO_FAS_1", "MAT_FAS_1"]:
        cond[c] = _str(cond[c])
    seg["COMP"] = pd.to_numeric(seg.COMP, errors="coerce")
    rede = con.sql(f"""
        select s.CTMT as alimentador_cod_id,
               sum(COMP) / 1e3                                                   as rede_mt_km,
               count(*)                                                          as n_segmentos_mt,
               coalesce(sum(case when ARE_LOC = 'NU' then COMP end), 0) / sum(COMP)           as frac_rural,
               coalesce(sum(case when length(FAS_CON) <= 2 then COMP end), 0) / sum(COMP)     as frac_monofasica,
               coalesce(sum(case when GEOM_CAB = '{GEOM_COMPACTA}' then COMP end), 0) / sum(COMP)    as frac_compacta,
               coalesce(sum(case when GEOM_CAB = '{GEOM_SUBTERRANEA}' then COMP end), 0) / sum(COMP) as frac_subterranea,
               coalesce(sum(case when ISO_FAS_1 = '{ISO_NU}' then COMP end), 0) / sum(COMP)   as frac_cabo_nu,
               max(COMP) / 1e3                                                   as maior_vao_km
        from seg s left join cond c on s.TIP_CND = c.COD_ID
        group by 1
    """).df()

    # --- Transformadores de distribuição: quantidade, potência, idade
    tr = _read(gdb, "UNTRMT", ["CTMT", "POT_NOM", "DAT_CON", "MRT", "ARE_LOC"])
    tr["CTMT"] = _str(tr.CTMT)
    tr["POT_NOM"] = pd.to_numeric(tr.POT_NOM, errors="coerce")
    tr["ano_con"] = _ano_conexao(tr.DAT_CON)
    tr["idade"] = ano_ref - tr.ano_con
    tr["MRT"] = pd.to_numeric(tr.MRT, errors="coerce")
    trafo = con.sql("""
        select CTMT as alimentador_cod_id,
               count(*)                                   as n_trafos,
               sum(POT_NOM) / 1e3                         as kva_instalado_mva,
               median(POT_NOM)                            as kva_mediano,
               avg(MRT)                                   as frac_trafos_mrt,
               avg(idade)                                 as idade_media_trafos,
               quantile_cont(idade, 0.9)                  as idade_p90_trafos,
               avg(case when idade >= 25 then 1.0 else 0.0 end) filter (where idade is not null) as frac_trafos_25anos,
               avg(case when ano_con is null then 1.0 else 0.0 end) as frac_trafos_sem_data
        from tr group by 1
    """).df()

    # --- Equipamentos de manobra e proteção
    sw = _read(gdb, "UNSEMT", ["CTMT", "TIP_UNID", "TLCD", "DAT_CON"])
    sw["CTMT"], sw["TIP_UNID"], sw["TLCD"] = _str(sw.CTMT), _str(sw.TIP_UNID), _str(sw.TLCD)
    sw["idade"] = ano_ref - _ano_conexao(sw.DAT_CON)
    prot = sw.groupby("CTMT").agg(
        n_religadores=("TIP_UNID", lambda s: s.isin(TUNI_RELIGADOR).sum()),
        n_seccionalizadores=("TIP_UNID", lambda s: s.isin(TUNI_SECCIONALIZADOR).sum()),
        n_chaves_fusiveis=("TIP_UNID", lambda s: s.isin(TUNI_CHAVE_FUSIVEL).sum()),
        n_chaves_telecomandadas=("TLCD", lambda s: (s == "1").sum()),
        idade_media_chaves=("idade", "mean"),
    ).reset_index().rename(columns={"CTMT": "alimentador_cod_id"})

    # --- Clientes e geração distribuída
    ucbt = _read(gdb, "UCBT_tab", ["CTMT", "CLAS_SUB"])
    ucmt = _read(gdb, "UCMT_tab", ["CTMT"])
    uc = pd.concat([_str(ucbt.CTMT), _str(ucmt.CTMT)]).value_counts().rename("n_uc").reset_index()
    uc.columns = ["alimentador_cod_id", "n_uc"]
    rural = ucbt.assign(CTMT=_str(ucbt.CTMT), rural=_str(ucbt.CLAS_SUB).str.startswith("RU"))
    rural = rural.groupby("CTMT").rural.mean().rename("frac_uc_rurais").reset_index()
    rural.columns = ["alimentador_cod_id", "frac_uc_rurais"]
    gd = pd.concat([_read(gdb, "UGBT_tab", ["CTMT", "POT_INST"]), _read(gdb, "UGMT_tab", ["CTMT", "POT_INST"])])
    gd["CTMT"] = _str(gd.CTMT)
    gd["POT_INST"] = pd.to_numeric(gd.POT_INST, errors="coerce")
    gd = gd.groupby("CTMT").agg(n_gd=("POT_INST", "size"), gd_mw=("POT_INST", lambda s: s.sum() / 1e3))
    gd = gd.reset_index().rename(columns={"CTMT": "alimentador_cod_id"})

    # --- Geografia: centróide e extensão a partir dos transformadores
    pts = _read(gdb, "UNTRMT", ["CTMT"], geometry=True).to_crs(4326)
    pts["CTMT"] = _str(pts.CTMT)
    pts["lon"], pts["lat"] = pts.geometry.x, pts.geometry.y
    geo = pts.groupby("CTMT").agg(lat=("lat", "median"), lon=("lon", "median"),
                                  lat_min=("lat", "min"), lat_max=("lat", "max"),
                                  lon_min=("lon", "min"), lon_max=("lon", "max")).reset_index()
    km_lat = 111.0
    km_lon = 111.0 * np.cos(np.radians(geo.lat))
    geo["extensao_km"] = np.hypot((geo.lat_max - geo.lat_min) * km_lat, (geo.lon_max - geo.lon_min) * km_lon)
    geo = geo[["CTMT", "lat", "lon", "extensao_km"]].rename(columns={"CTMT": "alimentador_cod_id"})

    df = base
    for part in [rede, trafo, prot, uc, rural, gd, geo]:
        df = df.merge(part, on="alimentador_cod_id", how="left")
    fill0 = ["n_religadores", "n_seccionalizadores", "n_chaves_fusiveis", "n_chaves_telecomandadas",
             "n_gd", "gd_mw", "n_uc"]
    df[fill0] = df[fill0].fillna(0)
    km = df.rede_mt_km.replace(0, np.nan)
    df["religadores_por_100km"] = df.n_religadores / km * 100
    df["fusiveis_por_km"] = df.n_chaves_fusiveis / km
    df["uc_por_km"] = df.n_uc / km
    df["carga_media_mw"] = df.energia_mwh_ano / 8760
    df["ano_snapshot"] = ano_ref
    log.info("BDGD %s: %d alimentadores", ano_ref, len(df))
    return df


def feeder_map(gdb: Path) -> pd.DataFrame:
    """Mapa código operacional do alimentador -> CTMT.COD_ID.

    O dataset de interrupções (layout legado) identifica o alimentador pelo código
    operacional (ex.: ``092011``), mas um mesmo CTMT da BDGD pode agrupar vários
    códigos operacionais. O vínculo vem de ``SSDMT.CT_COD_OP``: cada código vai
    para o CTMT que concentra a maior extensão de rede com aquele código.
    """
    seg = _read(gdb, "SSDMT", ["CTMT", "CT_COD_OP", "COMP"])
    seg["CTMT"] = _str(seg.CTMT)
    seg = seg.dropna(subset=["CT_COD_OP"])  # campo inexistente no modelo M10
    seg["op"] = _str(seg.CT_COD_OP).str.zfill(6)
    seg["COMP"] = pd.to_numeric(seg.COMP, errors="coerce")
    pares = seg.groupby(["op", "CTMT"], as_index=False).COMP.sum()
    via_seg = pares.sort_values("COMP", ascending=False).drop_duplicates("op")[["op", "CTMT"]]
    ct = _read(gdb, "CTMT", ["COD_ID", "NOME"])
    via_ct = pd.DataFrame({"op": _str(ct.NOME).str.zfill(6), "CTMT": _str(ct.COD_ID)})
    mp = pd.concat([via_ct, via_seg]).drop_duplicates("op")
    return mp.rename(columns={"op": "alimentador_nome", "CTMT": "alimentador_cod_id"})


def build_snapshot(item: str, ano: int, raw: Path, interim: Path, keep_gdb: bool = False) -> tuple[Path, Path]:
    """Baixa, extrai atributos + mapa de códigos e (opcionalmente) apaga o .gdb."""
    dest = raw / "bdgd" / str(ano)
    gdb = download(item, dest)
    interim.mkdir(parents=True, exist_ok=True)
    out_feat = interim / f"bdgd_feeders_{ano}.parquet"
    out_map = interim / f"bdgd_map_{ano}.parquet"
    feeder_features(gdb, ano).to_parquet(out_feat, index=False)
    feeder_map(gdb).assign(ano_snapshot=ano).to_parquet(out_map, index=False)
    if not keep_gdb:
        shutil.rmtree(dest, ignore_errors=True)
    return out_feat, out_map
