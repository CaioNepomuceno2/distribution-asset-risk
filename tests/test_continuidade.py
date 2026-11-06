"""Arquivos de continuidade da ANEEL com linhas repetidas (regeneração de 05/11/2026).

Cada linha do arquivo original apareceu duas vezes. Somar ``VlrIndiceEnviado`` sem tratar isso dobra o R$
pago por violação de DIC/FIC/DMIC/DICRI e, com ele, o R$/CHI de todo o pipeline.
"""
from datetime import date

import duckdb
import pandas as pd
import pytest

from gridrisk import risco as R
from gridrisk.ingest import continuidade as C

COLUNAS = ["DatGeracaoConjuntoDados", "SigAgente", "NumCNPJ", "IdeConjUndConsumidoras", "DscConjUndConsumidoras",
           "SigIndicador", "AnoIndice", "NumPeriodoIndice", "VlrIndiceEnviado"]


def _linhas(rows) -> pd.DataFrame:
    return pd.DataFrame([(date(2026, 11, 5), ag, 1, c, f"Conjunto {c}", ind, ano, mes, v)
                         for ag, c, ind, ano, mes, v in rows], columns=COLUNAS)


def _dobrar(df: pd.DataFrame) -> pd.DataFrame:
    """Como o arquivo de 05/11/2026: cada linha duas vezes."""
    return pd.concat([df, df], ignore_index=True)


COMPENSACAO = _linhas([
    ("EMT   ", 1, "PGUCBTU", 2023, 3, 300.0),
    ("EMT   ", 1, "PGUCMTU", 2024, 6, 800.0),
    ("EMT   ", 1, "QTUCBTU", 2024, 6, 999.0),    # quantidade de UCs, não é valor pago
    ("EMT   ", 1, "PGUCBTU", 2021, 3, 5000.0),   # fora dos anos pedidos
    # mesma chave (conjunto, indicador, ano, mês) com dois valores diferentes: são dois registros e ambos contam
    ("EMT   ", 2, "PGUCBTNU", 2024, 1, 1500.0),
    ("EMT   ", 2, "PGUCBTNU", 2024, 1, 600.0),
    ("CPFL  ", 2, "PGUCBTNU", 2024, 1, 9999.0),  # outra distribuidora com o mesmo ID de conjunto
])

# CHI regulatório por conjunto e ano: sem expurgo e com 3 min ou mais
INTERRUPCOES = pd.DataFrame({
    "conjunto_id": [1, 1, 1, 1, 2],
    "ano": [2023, 2024, 2024, 2024, 2024],
    "chi": [200.0, 350.0, 999.0, 888.0, 700.0],
    "expurgo": ["NAO HOUVE EXPURGO", "NAO HOUVE EXPURGO", "DIA CRITICO", "NAO HOUVE EXPURGO", "NAO HOUVE EXPURGO"],
    "duracao_h": [2.0, 3.0, 2.0, 0.01, 4.0],  # 0,01 h = 36 s, abaixo do mínimo de 3 min
})


@pytest.fixture
def arquivos(tmp_path):
    INTERRUPCOES.to_parquet(tmp_path / "interrupcoes.parquet", index=False)
    COMPENSACAO.to_parquet(tmp_path / "limpo.parquet", index=False)
    _dobrar(COMPENSACAO).to_parquet(tmp_path / "dobrado.parquet", index=False)
    return tmp_path


def _comp(arquivos, nome: str) -> pd.DataFrame:
    return R.compensacao_por_chi(arquivos / nome, arquivos / "interrupcoes.parquet", "EMT", [2023, 2024]) \
        .set_index("conjunto_id").sort_index()


def test_compensacao_com_linhas_repetidas_nao_dobra_o_r_por_chi(arquivos):
    c = _comp(arquivos, "dobrado.parquet")
    # conjunto 1: 300 + 800 de compensação; CHI regulatório 200 + 350 = 550
    assert c.loc[1, "compensacao"] == pytest.approx(1100.0)
    assert c.loc[1, "chi_regulatorio"] == pytest.approx(550.0)
    assert c.loc[1, "rs_por_chi"] == pytest.approx(2.0)
    # conjunto 2: 1500 + 600 (dois registros distintos da mesma chave); CHI regulatório 700
    assert c.loc[2, "compensacao"] == pytest.approx(2100.0)
    assert c.loc[2, "rs_por_chi"] == pytest.approx(3.0)


def test_arquivo_dobrado_e_limpo_dao_o_mesmo_resultado(arquivos):
    pd.testing.assert_frame_equal(_comp(arquivos, "dobrado.parquet"), _comp(arquivos, "limpo.parquet"))


def test_leitura_sem_duplicatas_conta_cada_linha_identica_uma_vez(arquivos):
    def n(nome: str, filtro: str = "") -> int:
        return duckdb.sql(f"select count(*) n from {C.leitura_sem_duplicatas(arquivos / nome, filtro)}").df().n[0]

    assert n("dobrado.parquet") == len(COMPENSACAO) == n("limpo.parquet")
    # o filtro vale antes do distinct: só as 2 linhas do conjunto 2 da EMT
    assert n("dobrado.parquet", "trim(SigAgente) = 'EMT' and IdeConjUndConsumidoras = 2") == 2


def test_dec_fec_oficial_ignora_linhas_repetidas(tmp_path):
    ind = _linhas([
        ("EMT   ", 1, "DEC", 2024, 1, 1.5), ("EMT   ", 1, "FEC", 2024, 1, 0.5),
        ("EMT   ", 1, "NumCon", 2024, 1, 1000.0),
        ("EMT   ", 1, "DEC", 2024, 2, 2.5), ("EMT   ", 1, "FEC", 2024, 2, 0.7),
        ("EMT   ", 1, "NumCon", 2024, 2, 1010.0),
        ("EMT   ", 1, "DIC", 2024, 1, 9.0),       # outro indicador
        ("CPFL  ", 1, "DEC", 2024, 1, 7.0),       # outra distribuidora
    ])
    _dobrar(ind).to_parquet(tmp_path / "ind.parquet", index=False)
    oficial = C.dec_fec_oficial(tmp_path / "ind.parquet", "EMT").sort_values("mes").reset_index(drop=True)
    assert list(oficial.columns) == ["c", "ano", "mes", "DEC", "FEC", "NumCon"]
    assert oficial.mes.tolist() == [1, 2]
    assert oficial.DEC.tolist() == [1.5, 2.5] and oficial.FEC.tolist() == [0.5, 0.7]
    assert oficial.NumCon.tolist() == [1000.0, 1010.0]
