"""Leitura dos Parquet de continuidade da ANEEL (indicadores coletivos e compensações pagas).

Em 05/11/2026 a ANEEL regenerou os dois arquivos com quase todas as linhas repetidas: a compensação passou
de 10,3 para 20,7 milhões de linhas. Somar ``VlrIndiceEnviado`` sem tratar isso dobra o R$ pago e o R$/CHI.
Toda leitura desses arquivos passa por aqui: registros idênticos em todas as colunas contam uma vez.
Ver "Compensações" em ``docs/dados.md``.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def leitura_sem_duplicatas(path: Path, filtro: str = "") -> str:
    """Subconsulta SQL que lê o Parquet contando uma vez cada linha idêntica em todas as colunas.

    ``filtro`` (condição SQL) é aplicado antes do ``distinct`` para não deduplicar o país inteiro. O resultado é
    o mesmo, porque linhas idênticas têm o mesmo valor em qualquer coluna usada no filtro.
    """
    onde = f" where {filtro}" if filtro else ""
    return f"(select distinct * from read_parquet('{path}'){onde})"


def dec_fec_oficial(indicadores: Path, sigla: str) -> pd.DataFrame:
    """DEC, FEC e nº de consumidores oficiais da distribuidora, uma linha por conjunto x ano x mês."""
    filtro = f"trim(SigAgente) = '{sigla}' and SigIndicador in ('DEC', 'FEC', 'NumCon')"
    fonte = leitura_sem_duplicatas(indicadores, filtro)
    return duckdb.sql(f"""
        pivot (select IdeConjUndConsumidoras c, AnoIndice ano, NumPeriodoIndice mes, SigIndicador s, VlrIndiceEnviado v
               from {fonte})
        on s using first(v)
    """).df()
