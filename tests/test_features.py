"""Cortes temporais do painel: nada posterior à data da previsão entra nas features."""
import pandas as pd
import pytest

from gridrisk import features as F


def _feeders(ano: int, nomes: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"alimentador_cod_id": [f"ID{ano}_{n}" for n in nomes], "alimentador_nome": nomes,
                         "rede_mt_km": 10.0, "lat": -15.0, "lon": -56.0, "ano_snapshot": ano})


def _evento(ano: int, codigo: str, chi: float = 100.0) -> dict:
    return {"alimentador_cod_id": None, "alimentador_nome": codigo, "ano": ano, "mes": 6,
            "grupo_causa": "VEGETACAO", "chi": chi, "uc_afetadas": 10, "duracao_h": 1.0,
            "expurgo": "NAO HOUVE EXPURGO", "origem_mt": True, "origem": "INTERNA", "tipo": "NAO PROGRAMADA"}


@pytest.fixture
def interim(tmp_path):
    """Snapshots 2020 e 2021. O código operacional ``900001`` só passa a ser mapeado
    para o alimentador ``A`` no snapshot de 2021 (ex.: recadastramento)."""
    for ano in (2020, 2021):
        _feeders(ano, ["A", "B"]).to_parquet(tmp_path / f"bdgd_feeders_{ano}.parquet", index=False)
    mapas = {
        2020: [("A", "ID2020_A"), ("B", "ID2020_B")],
        2021: [("A", "ID2021_A"), ("B", "ID2021_B"), ("900001", "ID2021_A")],
    }
    for ano, pares in mapas.items():
        pd.DataFrame(pares, columns=["alimentador_nome", "alimentador_cod_id"]).assign(ano_snapshot=ano) \
            .to_parquet(tmp_path / f"bdgd_map_{ano}.parquet", index=False)
    eventos = [_evento(2019, "A"), _evento(2020, "900001", chi=500.0), _evento(2021, "B"),
               _evento(2022, "900001", chi=700.0)]
    pd.DataFrame(eventos).to_parquet(tmp_path / "interrupcoes.parquet", index=False)
    return tmp_path


def test_snapshot_ate():
    assert F.snapshot_ate([2018, 2020, 2022], 2021) == 2020
    assert F.snapshot_ate([2018, 2020, 2022], 2022) == 2022
    assert F.snapshot_ate([2018, 2020], 2017) is None


def test_max_snapshot_ignora_cadastros_futuros(interim):
    sem_corte = F.falhas_por_alimentador(interim / "interrupcoes.parquet", interim)
    corte_2020 = F.falhas_por_alimentador(interim / "interrupcoes.parquet", interim, max_snapshot=2020)
    # sem corte, o evento de 2020 com código 900001 é ligado ao A pelo snapshot de 2021
    assert sem_corte.query("ano == 2020").chi.sum() == 500.0
    # com corte em 2020, o mapeamento de 2021 não existe e o evento fica sem alimentador
    assert corte_2020.query("ano == 2020").empty
    # o corte não descarta anos de evento: o alvo de anos posteriores continua disponível
    assert set(corte_2020.ano) == {2019, 2021}


def test_painel_point_in_time(interim):
    cortes = F.falhas_point_in_time(interim / "interrupcoes.parquet", interim)
    assert sorted(cortes) == [2020, 2021]
    painel = F.build_panel(cortes, interim, None, [2021, 2022])
    veg = painel[painel.modo == "VEGETACAO"].set_index(["ano", "alimentador"])
    # alvo 2021: features com snapshot 2020, então o evento de 2020 (900001) não entra no histórico
    assert veg.loc[(2021, "A"), "chi_media_1a"] == 0.0
    # alvo 2022: o snapshot de 2021 já é conhecido e liga o evento de 2020 ao A
    assert veg.loc[(2022, "A"), "chi_media_3a"] == pytest.approx(500.0 / 3 + 100.0 / 3)
    # alvo do ano 2022, ligado com o snapshot mais recente até 2022
    assert veg.loc[(2022, "A"), "chi"] == 700.0
    # o histórico nunca inclui o próprio ano alvo
    assert veg.loc[(2021, "B"), "chi_media_1a"] == 0.0 and veg.loc[(2021, "B"), "chi"] == 100.0


def test_painel_sem_cortes_continua_funcionando(interim):
    falhas = F.falhas_por_alimentador(interim / "interrupcoes.parquet", interim)
    painel = F.build_panel(falhas, interim, None, [2021])
    veg = painel[painel.modo == "VEGETACAO"].set_index("alimentador")
    # comportamento antigo: o crosswalk de 2021 vaza para as features do alvo 2021
    assert veg.loc["A", "chi_media_1a"] == 500.0


def test_climatologia_usa_coordenadas_do_snapshot_anterior():
    linhas = []
    for snap, precip in ((2020, 100.0), (2021, 999.0)):
        for ano in (2019, 2020):
            linhas.append({"alimentador": "A", "ano": ano, "mes": 1, "precip_total_mm": precip,
                           "horas_chuva_forte": 0, "dias_chuva_50mm": 0, "dias_rajada_15ms": 0,
                           "rajada_max_ms": 10.0, "temp_max_c": 35.0, "umid_media_pct": 70.0,
                           "dist_estacao_km": 5.0, "ano_snapshot": snap})
    clim = F._climatologia(pd.DataFrame(linhas), ano_alvo=2021)
    assert clim.clim_precip_anual_mm.iloc[0] == 100.0
