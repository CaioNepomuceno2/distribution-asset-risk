"""Diagnóstico de linhas repetidas nos arquivos da ANEEL.

Para cada arquivo lido, compara ``count(*)`` com ``count(distinct *)``. Registros idênticos em todas as colunas
foram vistos nos indicadores de continuidade (regenerados em 05/11/2026) e, em poucas linhas, nas interrupções.
O diagnóstico só mede; quem decide o que fazer com as repetidas é o leitor de cada arquivo
(``ingest/continuidade.py`` remove; ``ingest/interrupcoes.py`` mantém, como nos números publicados de MT).
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def _colunas(con: duckdb.DuckDBPyConnection, path: Path) -> set[str]:
    return {c[0] for c in con.sql(f"describe select * from read_parquet('{path}')").fetchall()}


def contar(path: Path, sigla: str | None = None, memoria: str = "6GB") -> dict:
    """Linhas, linhas distintas e (para interrupções) o CHI das cópias a mais, do arquivo inteiro ou de uma distribuidora."""
    con = duckdb.connect()
    con.execute(f"set memory_limit='{memoria}'")
    onde = f" where trim(SigAgente) = '{sigla}'" if sigla else ""
    base = f"select t from (select * from read_parquet('{path}'){onde}) t"
    linhas, distintas = con.execute(f"select count(*), count(distinct t) from ({base})").fetchall()[0]
    out = {"arquivo": Path(path).name, "escopo": sigla or "nacional", "linhas": linhas, "distintas": distintas,
           "repetidas": linhas - distintas, "pct_repetidas": 100.0 * (linhas - distintas) / max(linhas, 1)}
    cols = _colunas(con, path)
    if {"DatInicioInterrupcao", "DatFimInterrupcao"} <= cols and sigla:
        uc = "NumUnidadeConsumidora" if "NumUnidadeConsumidora" in cols else "QtdConsumidoresAfetados"
        chi = f"date_diff('second', DatInicioInterrupcao, DatFimInterrupcao) / 3600.0 * {uc}"
        total, a_mais = con.execute(f"""
            select sum(chi_linha), sum(chi_linha * (n - 1) / n)
            from (select {chi} as chi_linha, count(*) over (partition by t) as n
                  from (select t, t.DatInicioInterrupcao as DatInicioInterrupcao, t.DatFimInterrupcao as DatFimInterrupcao,
                               t.{uc} as {uc}
                        from ({base})))
        """).fetchall()[0]
        out["chi_repetido_pct"] = 100.0 * (a_mais or 0.0) / total if total else 0.0
    return out


def chaves_com_valores_diferentes(path: Path, chave: list[str], valor: str, sigla: str | None = None) -> int:
    """Quantas chaves têm mais de um valor distinto depois de remover as linhas idênticas."""
    onde = f" where trim(SigAgente) = '{sigla}'" if sigla else ""
    cols = ", ".join(chave)
    return duckdb.execute(f"""
        select count(*) from (
            select {cols} from (select distinct * from read_parquet('{path}'){onde}) group by {cols}
            having count(distinct {valor}) > 1)
    """).fetchall()[0][0]


def tabela(arquivos: list[Path], sigla: str, nacional: bool = False) -> pd.DataFrame:
    linhas = []
    for p in arquivos:
        linhas.append(contar(p, sigla))
        if nacional:
            linhas.append(contar(p))
    return pd.DataFrame(linhas)
