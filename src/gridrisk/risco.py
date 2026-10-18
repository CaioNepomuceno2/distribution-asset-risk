"""Consequência monetária de uma hora de interrupção por alimentador.

Duas visões, que o planejador pode combinar:

* **Caixa da distribuidora**: compensações pagas por violação de DIC/FIC/DMIC/
  DICRI no conjunto (dados abertos ANEEL) divididas pelo CHI regulatório do
  conjunto -> R$/CHI empírico.
* **Custo social** (cenário): energia não suprida x custo da energia não suprida,
  com a carga média por UC do alimentador vinda da BDGD.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


def compensacao_por_chi(compensacao: Path, interrupcoes: Path, sigla: str, anos: list[int]) -> pd.DataFrame:
    """R$/CHI regulatório por conjunto, média dos anos informados."""
    anos_sql = ", ".join(map(str, anos))
    return duckdb.sql(f"""
        with comp as (
            select IdeConjUndConsumidoras as conjunto_id, AnoIndice as ano, sum(VlrIndiceEnviado) as compensacao
            from read_parquet('{compensacao}')
            where trim(SigAgente) = '{sigla}' and SigIndicador like 'PG%' and AnoIndice in ({anos_sql})
            group by all
        ), chi as (
            select conjunto_id, ano, sum(chi) as chi_regulatorio
            from read_parquet('{interrupcoes}')
            where expurgo = 'NAO HOUVE EXPURGO' and duracao_h >= 3.0/60 and ano in ({anos_sql})
            group by all
        )
        select conjunto_id, sum(compensacao) as compensacao, sum(chi_regulatorio) as chi_regulatorio,
               sum(compensacao) / nullif(sum(chi_regulatorio), 0) as rs_por_chi
        from chi left join comp using (conjunto_id, ano)
        group by conjunto_id
    """).df()


def conjunto_do_alimentador(interrupcoes: Path, crosswalk: Path) -> pd.DataFrame:
    """Participação de cada conjunto no CHI de cada alimentador (eventos MT)."""
    return duckdb.sql(f"""
        with a as (
            select c.alimentador, i.conjunto_id, sum(i.chi) as chi
            from read_parquet('{interrupcoes}') i
            join read_parquet('{crosswalk}') c on coalesce(i.alimentador_cod_id, i.alimentador_nome) = c.codigo
            where i.origem_mt and i.ano >= 2022
            group by all
        )
        select alimentador, conjunto_id, chi / sum(chi) over (partition by alimentador) as peso from a
    """).df()


def valor_chi_alimentador(comp_conj: pd.DataFrame, pesos: pd.DataFrame, feeders: pd.DataFrame,
                          custo_ens_rs_mwh: float = 0.0) -> pd.DataFrame:
    """R$/CHI por alimentador: compensação (média ponderada dos conjuntos) + custo social opcional."""
    c = comp_conj.copy()
    lo, hi = c.rs_por_chi.quantile([0.05, 0.95])
    c["rs_por_chi"] = c.rs_por_chi.clip(lo, hi).fillna(c.rs_por_chi.median())
    v = pesos.merge(c[["conjunto_id", "rs_por_chi"]], on="conjunto_id", how="left")
    v["rs_por_chi"] = v.rs_por_chi.fillna(c.rs_por_chi.median())
    comp = (v.rs_por_chi * v.peso).groupby(v.alimentador).sum().rename("rs_chi_compensacao")
    out = feeders[["alimentador", "energia_mwh_ano", "n_uc"]].set_index("alimentador").join(comp)
    out["rs_chi_compensacao"] = out.rs_chi_compensacao.fillna(c.rs_por_chi.median())
    kw_uc = (out.energia_mwh_ano.clip(lower=0) * 1e3 / 8760) / out.n_uc.replace(0, np.nan)
    # teto de 5 kW: alimentadores industriais distorcem a média e a UC MT costuma ter proteção própria
    out["kw_medio_uc"] = kw_uc.clip(0, 5).fillna(kw_uc.median())
    out["rs_chi_social"] = out.kw_medio_uc / 1e3 * custo_ens_rs_mwh
    out["rs_por_chi"] = out.rs_chi_compensacao + out.rs_chi_social
    return out.reset_index()[["alimentador", "rs_chi_compensacao", "kw_medio_uc", "rs_chi_social", "rs_por_chi"]]
