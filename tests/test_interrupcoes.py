from datetime import datetime

import duckdb
import pandas as pd

from gridrisk.ingest import interrupcoes as it


def _legado(path):
    pd.DataFrame({
        "NumOrdemInterrupcao": ["a", "b", "c"],
        "DatInicioInterrupcao": [datetime(2024, 1, 1, 10), datetime(2024, 2, 1, 10), datetime(2024, 3, 1, 10)],
        "DatFimInterrupcao": [datetime(2024, 1, 1, 12), datetime(2024, 2, 1, 10, 1), datetime(2024, 3, 1, 11)],
        "IdeConjuntoUnidadeConsumidora": [1, 1, 2],
        "DscConjuntoUnidadeConsumidora": ["Cuiabá ", "Cuiabá", "Sinop"],
        "DscAlimentadorSubestacao": ["13014", "013014", "093002"],
        "DscSubestacaoDistribuicao": ["013", "013", "093"],
        "DscFatoGeradorInterrupcao": [
            "INTERNA-NAO PROGRAMADA-PROPRIAS DO SISTEMA-FALHA DE MATERIAL OU EQUIPAMENTO",
            "INTERNA-NAO PROGRAMADA-MEIO AMBIENTE-DESCARGA ATMOSFERICA",
            "INTERNA-PROGRAMADA-MANUTENCAO-PREVENTIVA",
        ],
        "IdeMotivoInterrupcao": [0, 6, 0],
        "NumNivelTensao": [13800, 34500, 220],
        "NumUnidadeConsumidora": [100, 10, 5],
        "NumConsumidorConjunto": [1000, 1000, 500],
        "SigAgente": ["EMT   ", "EMT", "EMT"],
    }).to_parquet(path)


def _novo(path):
    pd.DataFrame({
        "CodInterrupcao": ["x"],
        "DatInicioInterrupcao": [datetime(2026, 1, 5, 8)],
        "DatFimInterrupcao": [datetime(2026, 1, 5, 9, 30)],
        "CodConjUnidadeConsumidora": ["1"],
        "DscConjuntoUnidadeConsumidora": ["CUIABA"],
        "CodAlimentador": ["764512"],
        "CodSubestacao": ["14"],
        "DscFatoGeradorOrigem": ["Interna"],
        "DscFatoGeradorTipo": ["Não Programada"],
        "DscFatoGeradorCausa": ["Meio Ambiente"],
        "DscFatoGeradorDetalhe": ["Árvore ou vegetação"],
        "NumNivelTensao": [13800],
        "QtdConsumidoresAfetados": [40],
        "QtdConsumidoresAtivos": [1000],
        "DscMotivoExpurgo": ["Interrupção ocorrida em Dia Crítico"],
        "DscTipoElementoInterrompido": ["Chave Fusível"],
        "DscLocalizacaoInterrupcao": ["Área Rural"],
        "SigAgente": ["EMT"],
    }).to_parquet(path)


def test_harmonize_dois_layouts(tmp_path):
    _legado(tmp_path / "leg.parquet")
    _novo(tmp_path / "novo.parquet")
    out = it.harmonize([tmp_path / "leg.parquet", tmp_path / "novo.parquet"], "EMT", tmp_path / "out.parquet")
    df = duckdb.sql(f"select * from '{out}' order by inicio").df()

    assert len(df) == 4
    assert df.alimentador_nome.iloc[0] == "013014"  # zero à esquerda restaurado
    assert df.conjunto_nome.iloc[0] == "CUIABA"  # sem acento, sem espaço
    assert list(df.grupo_causa) == ["EQUIPAMENTO", "DESCARGA_ATMOSFERICA", "PROGRAMADA", "VEGETACAO"]
    assert list(df.expurgo) == ["NAO HOUVE EXPURGO", "DIA CRITICO", "NAO HOUVE EXPURGO", "DIA CRITICO"]
    assert df.chi.iloc[0] == 200  # 2 h x 100 UC
    assert list(df.origem_mt) == [True, True, False, True]
    assert df.alimentador_cod_id.iloc[3] == "764512"
