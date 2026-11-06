"""Regra de decisão pré-registrada para o clima (docs/preregistro_clima.md), aplicada a números sintéticos."""
import pandas as pd
import pytest

from gridrisk import regra_clima as RC

# valores por ano de teste (2023, 2024, 2025) do modelo sem clima
SEM = {"deviance_poisson": [7.0, 5.5, 5.9], "mae_alimentador": [17200.0, 17000.0, 14300.0],
       "spearman_alimentador": [0.910, 0.914, 0.893], "captura_top10": [0.464, 0.445, 0.4615]}


def _resumo(com: dict, ruido: float = 0.002) -> pd.DataFrame:
    """Uma linha por modo x semente x alvo x ano; a semente muda o valor em +-0,2% (o mesmo nos dois modos)."""
    linhas = []
    for modo, valores in (("semclima", SEM), ("clima", {**SEM, **com})):
        for semente in range(10):
            f = 1 + ruido * (1 if semente % 2 else -1)
            for k, ano in enumerate([2023, 2024, 2025]):
                for alvo, cols in (("n_falhas", ["deviance_poisson"]),
                                   ("chi", ["mae_alimentador", "spearman_alimentador", "captura_top10"])):
                    linha = {"modo": modo, "semente": semente, "alvo": alvo, "ano_teste": ano, "metodo": "modelo"}
                    linha.update({c: valores[c][k] * f for c in cols})
                    linhas.append(linha)
    return pd.DataFrame(linhas)


def _melhora(deviance: float, mae: float, **extra) -> dict:
    """Melhora relativa de deviance e MAE em todos os anos (ex.: 0,02 = 2% menor)."""
    out = {"deviance_poisson": [v * (1 - deviance) for v in SEM["deviance_poisson"]],
           "mae_alimentador": [v * (1 - mae) for v in SEM["mae_alimentador"]]}
    out.update(extra)
    return out


def test_sem_nenhuma_diferenca_o_clima_nao_entra():
    r = RC.avaliar(_resumo({}))
    assert r["clima_entra_no_modelo"] is False
    assert r["criterios"]["deviance"]["melhora"] == pytest.approx(0.0)


def test_melhora_de_2_por_cento_em_todos_os_anos_entra():
    r = RC.avaliar(_resumo(_melhora(0.02, 0.02)))
    assert r["clima_entra_no_modelo"] is True
    c = r["criterios"]["deviance"]
    assert c["melhora"] == pytest.approx(0.02 * 6.1333, rel=0.02)
    assert c["limiar"] == pytest.approx(0.01 * c["sem_clima"])  # 1% pesa mais que 2 desvios-padrão
    assert c["anos_com_melhora"] == 3 and c["semente0_melhora"] is True


def test_melhora_menor_que_1_por_cento_nao_basta():
    r = RC.avaliar(_resumo(_melhora(0.005, 0.02)))
    assert r["criterios"]["deviance"]["criterio_ok"] is False
    assert r["clima_entra_no_modelo"] is False


def test_melhora_so_na_media_de_um_unico_ano_nao_basta():
    # deviance: -5% em 2023 e +0,5% (pior) nos outros dois anos; a média melhora 1,3%, mas só em 1 ano de 3
    dev = [SEM["deviance_poisson"][0] * 0.95, SEM["deviance_poisson"][1] * 1.005, SEM["deviance_poisson"][2] * 1.005]
    r = RC.avaliar(_resumo({**_melhora(0.02, 0.02), "deviance_poisson": dev}))
    c = r["criterios"]["deviance"]
    assert c["passa_limiar"] is True and c["anos_com_melhora"] == 1
    assert c["criterio_ok"] is False and r["clima_entra_no_modelo"] is False


def test_piora_do_ranking_alem_do_ruido_veta_mesmo_com_deviance_e_mae_melhores():
    spearman = [v - 0.01 for v in SEM["spearman_alimentador"]]
    r = RC.avaliar(_resumo(_melhora(0.03, 0.03, spearman_alimentador=spearman)))
    assert r["criterios"]["deviance"]["criterio_ok"] and r["criterios"]["mae"]["criterio_ok"]
    assert r["criterios"]["spearman"]["criterio_ok"] is False
    assert r["clima_entra_no_modelo"] is False


def test_oscilacao_dentro_do_ruido_nao_veta_spearman_nem_top10():
    spearman = [v - 0.0005 for v in SEM["spearman_alimentador"]]  # abaixo de 2 desvios-padrão
    top10 = [v - 0.001 for v in SEM["captura_top10"]]
    r = RC.avaliar(_resumo(_melhora(0.03, 0.03, spearman_alimentador=spearman, captura_top10=top10)))
    assert r["criterios"]["spearman"]["criterio_ok"] and r["criterios"]["top10"]["criterio_ok"]
    assert r["clima_entra_no_modelo"] is True
