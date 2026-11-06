"""Painel de modelagem: alimentador (CTMT) x ano x modo de falha.

Enquadramento do problema (planejamento anual de investimento):

* No fim do ano ``y-1`` a distribuidora conhece o cadastro da rede (BDGD de
  31/12/``y-1``), o histórico de falhas até ``y-1`` e a climatologia local.
* Ela quer prever, para cada alimentador e modo de falha, o número de falhas e
  o CHI (consumidor-hora interrompido) do ano ``y``.

Cortes temporais (point-in-time) para o ano alvo ``y``:

* atributos da rede: só o snapshot BDGD de 31/12/``y-1``;
* histórico de falhas: interrupções até ``y-1``, ligadas aos alimentadores só
  com crosswalks de snapshots até ``y-1`` (``falhas_point_in_time``);
* clima: só a climatologia de anos ``< y``, interpolada nas coordenadas do
  snapshot ``y-1``;
* alvo: interrupções do ano ``y``, ligadas com snapshots até ``y``. O alvo é a
  medição do resultado, feita depois do fim do ano, e nunca entra nas features.

O clima realizado do ano alvo não é usado.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

MODOS = ["EQUIPAMENTO", "DESCARGA_ATMOSFERICA", "VEGETACAO", "VENTO", "ANIMAIS", "TERCEIROS", "OUTRAS"]
_MODO_SQL = f"""case when grupo_causa in ({", ".join(repr(m) for m in MODOS[:-1])}) then grupo_causa
                     else 'OUTRAS' end"""


def carregar_clima(interim: Path, usar: bool) -> pd.DataFrame | None:
    """Clima mensal por alimentador, ou ``None`` com a chave ``modelo.usar_clima`` desligada.

    Ter o arquivo em ``interim`` não basta: o clima só entra no modelo se a chave estiver ligada.
    """
    if not usar:
        return None
    arq = interim / "clima_alimentador_mes.parquet"
    if not arq.exists():
        raise FileNotFoundError(f"modelo.usar_clima está ligado, mas falta {arq}: rode scripts/build_clima.py")
    return pd.read_parquet(arq)


def _nearest(anos_disp: list[int], ano: int) -> int:
    return min(anos_disp, key=lambda a: (abs(a - ano), -a))


def snapshot_ate(anos_disp, ano: int) -> int | None:
    """Snapshot mais recente disponível até ``ano`` (inclusive), ou ``None``."""
    ok = [a for a in anos_disp if a <= ano]
    return max(ok) if ok else None


def _crosswalk(interim: Path, ano: int) -> Path:
    """Tabela (codigo informado -> alimentador canônico) para um snapshot.

    O alimentador canônico é o nome operacional do CTMT (``CTMT.NOME``, ex.
    ``013014``), estável entre snapshots, ao contrário do ``COD_ID`` interno.
    Cobre os dois jeitos de identificar o alimentador nas interrupções: pelo
    código operacional (layout legado) e pelo ``COD_ID`` (layout novo).
    """
    out = interim / f"crosswalk_{ano}.parquet"
    duckdb.sql(f"""
        copy (
            select m.alimentador_nome as codigo, f.alimentador_nome as alimentador
            from read_parquet('{interim / f"bdgd_map_{ano}.parquet"}') m
            join read_parquet('{interim / f"bdgd_feeders_{ano}.parquet"}') f using (alimentador_cod_id)
            union
            select alimentador_cod_id, alimentador_nome
            from read_parquet('{interim / f"bdgd_feeders_{ano}.parquet"}')
        ) to '{out}' (format parquet)
    """)
    return out


def falhas_por_alimentador(interrupcoes: Path, interim: Path, max_snapshot: int | None = None) -> pd.DataFrame:
    """Falhas MT não programadas de origem interna, por alimentador x ano x mês x modo.

    Cada interrupção é ligada ao alimentador canônico pelo crosswalk do snapshot
    BDGD mais próximo do ano do evento, completado pelos demais em ordem de
    distância. Com ``max_snapshot``, só entram snapshots até esse ano: é assim que
    o painel evita usar cadastros que ainda não existiam na data da previsão.
    """
    snaps = sorted(int(p.stem.split("_")[-1]) for p in interim.glob("bdgd_map_*.parquet"))
    if max_snapshot is not None:
        snaps = [a for a in snaps if a <= max_snapshot]
    if not snaps:
        raise ValueError(f"nenhum snapshot BDGD disponível até {max_snapshot}")
    cw = {a: _crosswalk(interim, a) for a in snaps}
    con = duckdb.connect()
    anos = [r[0] for r in con.sql(f"select distinct ano from read_parquet('{interrupcoes}')").fetchall()]
    sel = []
    for ano in sorted(anos):
        ordem = sorted(snaps, key=lambda a: (abs(a - ano), -a))
        partes = " union all ".join(
            f"select *, {k} as prioridade from read_parquet('{cw[a]}')" for k, a in enumerate(ordem))
        c = f"(select codigo, arg_min(alimentador, prioridade) as alimentador from ({partes}) group by codigo)"
        sel.append(f"""
        select c.alimentador, i.ano, i.mes, {_MODO_SQL} as modo, i.chi, i.uc_afetadas, i.duracao_h,
               i.expurgo = 'NAO HOUVE EXPURGO' and i.duracao_h >= 3.0/60 as conta_dec
        from read_parquet('{interrupcoes}') i
        left join {c} c on coalesce(i.alimentador_cod_id, i.alimentador_nome) = c.codigo
        where i.ano = {ano} and i.origem_mt and i.origem = 'INTERNA' and i.tipo = 'NAO PROGRAMADA'
        """)
    return con.sql(f"""
        select alimentador, ano, mes, modo,
               count(*)                                  as n_falhas,
               sum(chi)                                  as chi,
               sum(case when conta_dec then chi end)     as chi_regulatorio,
               sum(uc_afetadas)                          as ci,
               median(duracao_h)                         as duracao_mediana_h
        from ({" union all ".join(sel)})
        where alimentador is not null
        group by all
    """).df()


def falhas_point_in_time(interrupcoes: Path, interim: Path) -> dict[int, pd.DataFrame]:
    """Falhas de todos os anos ligadas com cada corte: ``{snapshot: falhas}``.

    No corte ``a`` só entram crosswalks de snapshots até ``a``. Cabe ao chamador
    filtrar os anos de evento (``build_panel`` usa só anos ``< y`` nas features).
    """
    snaps = sorted(int(p.stem.split("_")[-1]) for p in interim.glob("bdgd_map_*.parquet"))
    return {a: falhas_por_alimentador(interrupcoes, interim, max_snapshot=a) for a in snaps}


def _historico(falhas: pd.DataFrame, ano_alvo: int) -> pd.DataFrame:
    """Features de histórico por alimentador x modo usando apenas anos < ano_alvo."""
    h = falhas[falhas.ano < ano_alvo]
    anual = h.groupby(["alimentador", "modo", "ano"], as_index=False)[["n_falhas", "chi"]].sum()
    out = []
    for janela in (1, 3):
        w = anual[anual.ano >= ano_alvo - janela]
        g = w.groupby(["alimentador", "modo"])[["n_falhas", "chi"]].sum() / janela
        g.columns = [f"{c}_media_{janela}a" for c in g.columns]
        out.append(g)
    hist = pd.concat(out, axis=1).reset_index()
    # tendência: último ano contra média dos 3 anteriores
    tot = anual.groupby(["alimentador", "ano"]).n_falhas.sum().unstack()
    last = tot.get(ano_alvo - 1)
    prev = tot[[a for a in tot.columns if ano_alvo - 4 <= a < ano_alvo - 1]].mean(axis=1)
    tend = (np.log1p(last) - np.log1p(prev)).rename("tendencia_falhas_total") if last is not None else None
    total = (anual[anual.ano >= ano_alvo - 3].groupby("alimentador")[["n_falhas", "chi"]].sum() / 3)
    total.columns = ["n_falhas_total_media_3a", "chi_total_media_3a"]
    hist = hist.merge(total.reset_index(), on="alimentador", how="left")
    if tend is not None:
        hist = hist.merge(tend.reset_index(), on="alimentador", how="left")
    # duração típica de restabelecimento do alimentador (logística/acesso)
    dur = h[h.ano >= ano_alvo - 3].groupby("alimentador").duracao_mediana_h.median()
    hist = hist.merge(dur.rename("duracao_mediana_3a_h").reset_index(), on="alimentador", how="left")
    return hist


def _climatologia(clima_feeder: pd.DataFrame, ano_alvo: int, anos: int = 5) -> pd.DataFrame:
    """Médias climáticas anuais por alimentador nos ``anos`` anteriores ao alvo.

    Se ``clima_feeder`` tiver ``ano_snapshot`` (clima interpolado nas coordenadas
    de cada snapshot), usa as coordenadas do snapshot mais recente até ``ano_alvo - 1``.
    """
    if "ano_snapshot" in clima_feeder.columns:
        snap = snapshot_ate(clima_feeder.ano_snapshot.unique(), ano_alvo - 1)
        if snap is None:
            return pd.DataFrame({"alimentador": pd.Series(dtype=str)})
        clima_feeder = clima_feeder[clima_feeder.ano_snapshot == snap].drop(columns="ano_snapshot")
    c = clima_feeder[(clima_feeder.ano < ano_alvo) & (clima_feeder.ano >= ano_alvo - anos)]
    anual = c.groupby(["alimentador", "ano"]).agg(
        precip_anual_mm=("precip_total_mm", "sum"),
        horas_chuva_forte_ano=("horas_chuva_forte", "sum"),
        dias_chuva_50mm_ano=("dias_chuva_50mm", "sum"),
        dias_rajada_15ms_ano=("dias_rajada_15ms", "sum"),
        rajada_max_ano_ms=("rajada_max_ms", "max"),
        temp_max_ano_c=("temp_max_c", "max"),
        umid_media_pct=("umid_media_pct", "mean"),
        dist_estacao_km=("dist_estacao_km", "mean"),
    )
    return anual.groupby("alimentador").mean().add_prefix("clim_").reset_index()


def build_panel(falhas: pd.DataFrame | Mapping[int, pd.DataFrame], interim: Path,
                clima_feeder: pd.DataFrame | None, anos_alvo: list[int]) -> pd.DataFrame:
    """Uma linha por alimentador x ano alvo x modo, com alvo e features (snapshot y-1).

    ``falhas`` pode ser um único DataFrame (sem cortes temporais no vínculo de
    circuitos) ou o dicionário de ``falhas_point_in_time``. No segundo caso, as
    features do ano ``y`` vêm do corte ``y-1`` e o alvo, do corte ``y``.
    """
    snaps = {int(p.stem.split("_")[-1]): p for p in interim.glob("bdgd_feeders_*.parquet")}
    cortes = falhas if isinstance(falhas, Mapping) else None
    linhas = []
    for ano in anos_alvo:
        if ano - 1 not in snaps:
            continue
        if cortes is None:
            f_feat = f_alvo = falhas
        else:
            c_feat, c_alvo = snapshot_ate(cortes, ano - 1), snapshot_ate(cortes, ano)
            if c_feat is None:
                continue
            f_feat = cortes[c_feat]
            f_feat = f_feat[f_feat.ano < ano]
            f_alvo = cortes[c_alvo]
        alvo = f_alvo[f_alvo.ano == ano].groupby(["alimentador", "ano", "modo"], as_index=False)[
            ["n_falhas", "chi", "chi_regulatorio", "ci"]].sum()
        feat = (pd.read_parquet(snaps[ano - 1])
                .drop(columns=["alimentador_cod_id"])
                .rename(columns={"alimentador_nome": "alimentador"})
                .drop_duplicates("alimentador"))
        grid = feat[["alimentador"]].merge(pd.DataFrame({"modo": MODOS}), how="cross")
        grid["ano"] = ano
        df = grid.merge(feat.drop(columns=["ano_snapshot"]), on="alimentador", how="left")
        df = df.merge(_historico(f_feat, ano), on=["alimentador", "modo"], how="left")
        if clima_feeder is not None:
            df = df.merge(_climatologia(clima_feeder, ano), on="alimentador", how="left")
        df = df.merge(alvo, on=["alimentador", "ano", "modo"], how="left")
        linhas.append(df)
    panel = pd.concat(linhas, ignore_index=True)
    zero = ["n_falhas", "chi", "chi_regulatorio", "ci", "n_falhas_media_1a", "chi_media_1a",
            "n_falhas_media_3a", "chi_media_3a", "n_falhas_total_media_3a", "chi_total_media_3a"]
    panel[zero] = panel[zero].fillna(0)
    panel["modo"] = pd.Categorical(panel.modo, categories=MODOS)
    return panel
