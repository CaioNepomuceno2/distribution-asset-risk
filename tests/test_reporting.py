import json
from pathlib import Path

import pytest

from gridrisk.reporting import normalizar_nan


def test_metricas_ausentes_sao_null_e_infinito_nao_e_serializado():
    relatorio = {"metrica": [float("nan"), 2.5]}
    assert json.dumps(normalizar_nan(relatorio), allow_nan=False) == '{"metrica": [null, 2.5]}'
    with pytest.raises(ValueError):
        json.dumps(normalizar_nan({"metrica": float("inf")}), allow_nan=False)


def test_relatorio_versionado_e_json_estrito():
    def rejeitar_constante(valor):
        raise ValueError(f"Constante inválida: {valor}")

    arquivo = Path(__file__).resolve().parents[1] / "reports" / "resultados.json"
    relatorio = json.loads(arquivo.read_text(encoding="utf-8"), parse_constant=rejeitar_constante)
    assert relatorio["backtest_media"][0]["deviance_poisson"] is None
