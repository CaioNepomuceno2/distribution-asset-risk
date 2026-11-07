"""Diagnóstico de qualidade de um snapshot da BDGD, antes de confiar nas suposições herdadas de outra distribuidora.

O pipeline foi escrito e validado com a Energisa MT. Para outra distribuidora, este módulo mede, em cada snapshot:

* as camadas e os campos presentes (o modelo M10 até 2020 e o V10/V11 depois têm nomes diferentes);
* o formato dos códigos de alimentador (``CTMT.NOME``, ``SSDMT.CT_COD_OP``) e a integridade do vínculo SSDMT -> CTMT;
* o domínio de ``UNSEMT.TIP_UNID`` e os tipos de condutor que o extrator usa para religador, chave fusível, cabo
  nu e rede compacta;
* o preenchimento e a plausibilidade das datas (``DAT_CON`` e ``DAT_IMO``);
* o CRS e se as coordenadas caem dentro do estado.

Só mede: as decisões ficam em ``docs/decisoes_ems.md``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

from gridrisk.ingest import bdgd

# camadas de rede e de ativos que o extrator lê
CAMADAS_CHAVE = ["CTMT", "SSDMT", "SEGCON", "UNTRMT", "UNSEMT", "UCBT_tab", "UCMT_tab", "UGBT_tab", "UGMT_tab"]
CAMPOS_DATA = ["DAT_CON", "DAT_IMO"]


def _contagem(s: pd.Series, topo: int = 12) -> dict:
    vc = s.astype("string").str.strip().fillna("<nulo>").value_counts().head(topo)
    return {str(k): int(v) for k, v in vc.items()}


def _pct(parte: float, total: float) -> float:
    return round(100.0 * float(parte) / float(total), 3) if total else float("nan")


def _formato_codigo(s: pd.Series) -> dict:
    """Formato dos códigos: só dígitos, alfanumérico, comprimentos mais comuns e exemplos."""
    s = s.astype("string").str.strip()
    ok = s.dropna()
    ok = ok[ok != ""]
    return {
        "n": len(s), "pct_preenchido": _pct(len(ok), len(s)), "distintos": int(ok.nunique()),
        "pct_so_digitos": _pct(ok.str.fullmatch(r"\d+").sum(), len(ok)),
        "comprimentos": {str(k): int(v) for k, v in ok.str.len().value_counts().head(6).items()},
        "exemplos": sorted(ok.drop_duplicates().head(5).tolist()),
    }


def _datas(s: pd.Series, ano_snapshot: int) -> dict:
    """Preenchimento, valor-padrão mais frequente e plausibilidade de uma coluna de data (texto dd/mm/aaaa ou data)."""
    bruto = s
    if pd.api.types.is_datetime64_any_dtype(s):
        datas = s
        texto = s.dt.strftime("%d/%m/%Y")
    else:
        texto = s.astype("string").str.strip()
        datas = pd.to_datetime(texto, format="%d/%m/%Y", errors="coerce")
    n = len(bruto)
    preenchido = texto.notna() & (texto != "")
    top = texto[preenchido].value_counts().head(3)
    anos = datas.dt.year.dropna()
    out = {
        "n": int(n), "pct_preenchido": _pct(preenchido.sum(), n), "pct_data_valida": _pct(datas.notna().sum(), n),
        "valor_mais_frequente": None if top.empty else str(top.index[0]),
        "pct_valor_mais_frequente": _pct(top.iloc[0], n) if len(top) else 0.0,
        "pct_01_01_1980": _pct((texto == bdgd.DATA_DESCONHECIDA).sum(), n),
    }
    if len(anos):
        q = np.percentile(anos, [5, 50, 95])
        out.update({
            "ano_min": int(anos.min()), "ano_p05": int(q[0]), "ano_mediano": int(q[1]), "ano_p95": int(q[2]),
            "ano_max": int(anos.max()), "pct_antes_de_1950": _pct((anos < 1950).sum(), n),
            "pct_depois_do_snapshot": _pct((anos > ano_snapshot).sum(), n),
            "pct_por_decada": {f"{int(d)}s": _pct(c, n) for d, c in (anos // 10 * 10).value_counts().sort_index().items()},
        })
    return out


def diagnosticar(gdb: Path, ano: int, bbox: tuple[float, float, float, float] | None = None) -> dict:
    """Diagnóstico de um snapshot. ``bbox`` = (lon_min, lat_min, lon_max, lat_max) do estado, se conhecido."""
    camadas = {}
    campos: dict[str, list[str]] = {}
    for nome, geom in pyogrio.list_layers(gdb):
        info = pyogrio.read_info(gdb, layer=nome)
        camadas[nome] = {"geometria": str(geom), "linhas": int(info["features"]), "campos": len(info["fields"])}
        campos[nome] = list(info["fields"])
    out: dict = {"ano": ano, "gdb": Path(gdb).name, "camadas": camadas}
    out["camadas_chave_ausentes"] = [c for c in CAMADAS_CHAVE
                                     if not any(a in camadas for a in bdgd.LAYER_ALIASES.get(c, [c]))]

    # ---- CTMT
    ct = bdgd._read(gdb, "CTMT", ["COD_ID", "NOME", "SUB", "TEN_NOM", *[f"ENE_{m:02d}" for m in range(1, 13)]])
    ct["COD_ID"] = bdgd._str(ct.COD_ID)
    ene = ct[[f"ENE_{m:02d}" for m in range(1, 13)]].apply(pd.to_numeric, errors="coerce").sum(axis=1)
    out["ctmt"] = {
        "linhas": len(ct), "cod_id_distintos": int(ct.COD_ID.nunique()),
        "nome": _formato_codigo(ct.NOME), "nome_com_zfill6": _formato_codigo(bdgd._str(ct.NOME).str.zfill(6)),
        "ten_nom_cod": _contagem(ct.TEN_NOM, 8), "energia_total_mwh_ano": round(float(ene.sum() / 1e3), 1),
        "pct_energia_zero": _pct((ene <= 0).sum(), len(ct)),
    }

    # ---- SSDMT + SEGCON
    seg = bdgd._read(gdb, "SSDMT", ["CTMT", "CT_COD_OP", "ARE_LOC", "TIP_CND", "FAS_CON", "COMP"])
    cond = bdgd._read(gdb, "SEGCON", ["COD_ID", "GEOM_CAB", "ISO_FAS_1", "MAT_FAS_1"])
    seg["CTMT"] = bdgd._str(seg.CTMT)
    seg["COMP"] = pd.to_numeric(seg.COMP, errors="coerce")
    cond_cod = bdgd._str(cond.COD_ID)
    tip_cnd = bdgd._str(seg.TIP_CND)
    seg["geom_cab"] = tip_cnd.map(dict(zip(cond_cod, bdgd._str(cond.GEOM_CAB), strict=False)))
    seg["iso_fas_1"] = tip_cnd.map(dict(zip(cond_cod, bdgd._str(cond.ISO_FAS_1), strict=False)))
    comp_total = seg.COMP.sum()
    out["ssdmt"] = {
        "linhas": len(seg), "km": round(float(comp_total / 1e3), 1),
        "segcon_linhas": len(cond), "segcon_cod_id_duplicados": int(len(cond) - cond_cod.nunique()),
        "tem_ct_cod_op": "CT_COD_OP" in campos.get("SSDMT", []),
        "ct_cod_op": _formato_codigo(seg.CT_COD_OP) if "CT_COD_OP" in campos.get("SSDMT", []) else None,
        "pct_ctmt_existe_em_ctmt": _pct(seg.CTMT.isin(set(ct.COD_ID)).sum(), len(seg)),
        "pct_tip_cnd_existe_em_segcon": _pct(tip_cnd.isin(set(cond_cod.dropna())).sum(), len(seg)),
        "are_loc": _contagem(seg.ARE_LOC, 6),
        "km_por_geom_cab": {str(k): round(float(v) / 1e3, 1) for k, v in
                            seg.groupby(seg.geom_cab.fillna("<nulo>")).COMP.sum().items()},
        "km_por_iso_fas_1": {str(k): round(float(v) / 1e3, 1) for k, v in
                             seg.groupby(seg.iso_fas_1.fillna("<nulo>")).COMP.sum().items()},
        "pct_km_cabo_nu": _pct(seg.COMP[seg.iso_fas_1 == bdgd.ISO_NU].sum(), comp_total),
        "pct_km_compacta": _pct(seg.COMP[seg.geom_cab == bdgd.GEOM_COMPACTA].sum(), comp_total),
        "pct_km_subterranea": _pct(seg.COMP[seg.geom_cab == bdgd.GEOM_SUBTERRANEA].sum(), comp_total),
    }
    # códigos operacionais -> CTMT (feeder_map): quantos códigos, e quantos já são o nome do CTMT
    mp = bdgd.feeder_map(gdb)
    nomes = set(bdgd._str(ct.NOME).str.zfill(6))
    out["feeder_map"] = {"codigos": len(mp), "pct_codigo_igual_ao_nome_ctmt": _pct(mp.alimentador_nome.isin(nomes).sum(), len(mp)),
                         "ctmt_distintos": int(mp.alimentador_cod_id.nunique())}

    # ---- UNSEMT: domínio de TIP_UNID
    sw_campos = ["CTMT", "TIP_UNID", "TLCD", "DAT_CON", "PAC_1"]
    sw = bdgd._read(gdb, "UNSEMT", sw_campos)
    tip = bdgd._str(sw.TIP_UNID)
    out["unsemt"] = {
        "linhas": len(sw), "tip_unid": _contagem(tip, 25),
        "n_religador_32": int(tip.isin(bdgd.TUNI_RELIGADOR).sum()),
        "n_seccionalizador_35_36": int(tip.isin(bdgd.TUNI_SECCIONALIZADOR).sum()),
        "n_chave_fusivel_22_27": int(tip.isin(bdgd.TUNI_CHAVE_FUSIVEL).sum()),
        "n_disjuntor_29_30_53": int(tip.isin(bdgd.TUNI_DISJUNTOR).sum()),
        "pct_codigos_no_mapeamento": _pct(tip.isin(bdgd.TUNI_RELIGADOR | bdgd.TUNI_SECCIONALIZADOR
                                                   | bdgd.TUNI_CHAVE_FUSIVEL | bdgd.TUNI_DISJUNTOR).sum(), len(sw)),
        "tlcd": _contagem(sw.TLCD, 5),
        "pac_1_comprimentos": {str(k): int(v) for k, v in
                               bdgd._str(sw.PAC_1).str.len().value_counts().head(6).items()} if sw.PAC_1.notna().any() else None,
    }

    # evidência independente do código: elo fusível (CAP_ELO) só faz sentido em chave fusível; religador não o tem
    sw_ext = pyogrio.read_dataframe(gdb, layer="UNSEMT", read_geometry=False, use_arrow=True,
                                    columns=[c for c in ["COD_ID", "TIP_UNID", "CAP_ELO", "COR_NOM", "TLCD", "SIT_ATIV"]
                                             if c in campos["UNSEMT"]])
    sw_ext["TIP_UNID"] = bdgd._str(sw_ext.TIP_UNID)
    perfil = {}
    for cod in tip.value_counts().head(12).index:
        g = sw_ext[sw_ext.TIP_UNID == cod]
        perfil[str(cod)] = {
            "n": len(g),
            "pct_com_cap_elo": _pct(bdgd._str(g.CAP_ELO).fillna("").ne("").sum(), len(g)) if "CAP_ELO" in g else None,
            "cor_nom_mediana": float(pd.to_numeric(g.COR_NOM, errors="coerce").median()) if "COR_NOM" in g else None,
            "pct_telecomandado": _pct((bdgd._str(g.TLCD) == "1").sum(), len(g)) if "TLCD" in g else None,
        }
    out["unsemt"]["perfil_por_tip_unid"] = perfil

    # EQSE (equipamento da chave): TUC por TIP_UNID e preenchimento de DAT_IMO, o que a análise de sobrevivência usa
    if "EQSE" in campos and {"UN_SE", "TUC", "DAT_IMO"} <= set(campos["EQSE"]):
        eq = pyogrio.read_dataframe(gdb, layer="EQSE", read_geometry=False, use_arrow=True, columns=["UN_SE", "TUC", "DAT_IMO"])
        eq["UN_SE"] = bdgd._str(eq.UN_SE)
        eq["tem_data"] = bdgd._str(eq.DAT_IMO).fillna("").ne("")
        j = eq.merge(sw_ext[["COD_ID", "TIP_UNID"]].assign(UN_SE=bdgd._str(sw_ext.COD_ID)), on="UN_SE", how="inner")
        out["eqse"] = {
            "linhas": len(eq), "pct_un_se_existe_em_unsemt": _pct(eq.UN_SE.isin(set(bdgd._str(sw_ext.COD_ID))).sum(), len(eq)),
            "tuc_top": _contagem(eq.TUC, 10),
            "por_tip_unid": {str(cod): {"n": len(g), "pct_dat_imo": _pct(g.tem_data.sum(), len(g)),
                                        "tuc_top": _contagem(g.TUC, 3)}
                             for cod, g in j.groupby("TIP_UNID") if len(g) >= 100},
        }

    # ---- UNTRMT: trafos
    tr = bdgd._read(gdb, "UNTRMT", ["CTMT", "POT_NOM", "DAT_CON", "MRT"])
    out["untrmt"] = {"linhas": len(tr), "pot_nom_kva_mediana": float(pd.to_numeric(tr.POT_NOM, errors="coerce").median()),
                     "dat_con": _datas(tr.DAT_CON, ano)}

    # ---- clientes e geração distribuída
    ucbt = bdgd._read(gdb, "UCBT_tab", ["CTMT", "CLAS_SUB"])
    ucmt = bdgd._read(gdb, "UCMT_tab", ["CTMT"])
    out["clientes"] = {
        "ucbt": len(ucbt), "ucmt": len(ucmt),
        "pct_ucbt_clas_sub_rural_RU": _pct(bdgd._str(ucbt.CLAS_SUB).str.startswith("RU").sum(), len(ucbt)),
        "clas_sub_top": _contagem(ucbt.CLAS_SUB, 10),
        "pct_ucbt_ctmt_existe_em_ctmt": _pct(bdgd._str(ucbt.CTMT).isin(set(ct.COD_ID)).sum(), len(ucbt)),
        "ugbt": int(camadas.get("UGBT_tab", {}).get("linhas", 0)), "ugmt": int(camadas.get("UGMT_tab", {}).get("linhas", 0)),
    }

    # ---- DAT_IMO (data de imobilização) e DAT_CON em todas as camadas que têm o campo
    datas = {}
    for nome, cs in campos.items():
        for cd in CAMPOS_DATA:
            if cd in cs and camadas[nome]["linhas"] > 0:
                s = pyogrio.read_dataframe(gdb, layer=nome, columns=[cd], read_geometry=False, use_arrow=True)[cd]
                datas.setdefault(nome, {})[cd] = _datas(s, ano)
    out["datas"] = datas

    # ---- coordenadas
    pts = pyogrio.read_dataframe(gdb, layer=bdgd._layer(gdb, "UNTRMT"), columns=[], use_arrow=True)
    crs = pts.crs
    out["coordenadas"] = {"crs": None if crs is None else (crs.to_string() if crs.to_epsg() is None else f"EPSG:{crs.to_epsg()}")}
    p4326 = pts.to_crs(4326)
    lon, lat = p4326.geometry.x, p4326.geometry.y
    out["coordenadas"].update({"lon_min": round(float(lon.min()), 4), "lon_max": round(float(lon.max()), 4),
                               "lat_min": round(float(lat.min()), 4), "lat_max": round(float(lat.max()), 4),
                               "pct_sem_geometria": _pct(p4326.geometry.isna().sum(), len(p4326))})
    if bbox:
        dentro = (lon >= bbox[0]) & (lon <= bbox[2]) & (lat >= bbox[1]) & (lat <= bbox[3])
        out["coordenadas"]["pct_dentro_do_estado_bbox"] = _pct(dentro.sum(), len(p4326))
    return out
