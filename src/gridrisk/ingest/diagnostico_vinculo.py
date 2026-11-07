"""Quantas interrupções de média tensão encontram um circuito (CTMT) na BDGD?

O dataset de interrupções identifica o alimentador pelo código operacional (layout legado, até 2025) ou pelo
``CTMT.COD_ID`` (layout novo, 2026). Uma interrupção "casa" se esse código aparece no crosswalk de algum snapshot
da BDGD permitido pelo corte. Três cortes por ano de evento ``y``:

* ``todos``: todos os snapshots disponíveis (a cobertura mais favorável);
* ``y-1``: só snapshots até 31/12 de ``y-1`` (o que o planejador conhecia; usado nas features do ano ``y``);
* ``y``: snapshots até 31/12 de ``y`` (usado no alvo do ano ``y``).

Sem snapshot permitido, nada casa. A cobertura vem em número de eventos e em CHI, para eventos de MT e só para as
falhas que alimentam o painel (internas, não programadas).
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from gridrisk import features as F


def _codigos(interim: Path, snaps: list[int]) -> str:
    if not snaps:
        return "(select cast(null as varchar) as codigo where false)"
    return "(" + " union ".join(f"select codigo from read_parquet('{F._crosswalk(interim, a)}')" for a in snaps) + ")"


def cobertura_vinculo(interrupcoes: Path, interim: Path) -> pd.DataFrame:
    snaps = sorted(int(p.stem.split("_")[-1]) for p in interim.glob("bdgd_map_*.parquet"))
    con = duckdb.connect()
    anos = [r[0] for r in con.execute(f"select distinct ano from read_parquet('{interrupcoes}') order by 1").fetchall()]
    linhas = []
    for ano in anos:
        cortes = {"todos": snaps, "y-1": [a for a in snaps if a <= ano - 1], "y": [a for a in snaps if a <= ano]}
        for nome, ate in cortes.items():
            for escopo, filtro in {"mt": "i.origem_mt",
                                   "falhas": "i.origem_mt and i.origem = 'INTERNA' and i.tipo = 'NAO PROGRAMADA'"}.items():
                n, ligados, chi, chi_lig = con.execute(f"""
                    select count(*), count(c.codigo), sum(i.chi), sum(case when c.codigo is not null then i.chi end)
                    from read_parquet('{interrupcoes}') i
                    left join (select distinct codigo from {_codigos(interim, ate)}) c
                      on coalesce(i.alimentador_cod_id, i.alimentador_nome) = c.codigo
                    where i.ano = {ano} and {filtro}
                """).fetchall()[0]
                linhas.append({"ano": ano, "corte": nome, "escopo": escopo, "eventos": n, "eventos_ligados": ligados,
                               "pct_eventos": 100.0 * ligados / n if n else float("nan"), "chi": chi or 0.0,
                               "chi_ligado": chi_lig or 0.0,
                               "pct_chi": 100.0 * (chi_lig or 0.0) / chi if chi else float("nan")})
    return pd.DataFrame(linhas)
