"""Teste de fumaça de Mato Grosso do Sul com dados sintéticos: interrupções -> circuitos -> falhas -> R$/CHI -> carteira.

Cobre o que muda de MT para MS: a sigla ``EMS``, os códigos de alimentador alfanuméricos (``AJO51``), o arquivo
``interrupcoes_ems.parquet`` e o layout novo de 2026, que identifica o circuito pelo ``CTMT.COD_ID``. Sem rede e sem
modelo. O cenário (a BDGD sintética está em ``conftest.py``):

* o circuito 9001 se chama ``AJO51`` e tem um segundo código operacional, ``AJO52``; o 9002 é ``MIM01``;
* o conjunto 1 atende o circuito 9001 e o conjunto 2, o 9002.
"""
from datetime import datetime

import pandas as pd
import pytest

from gridrisk import features as F
from gridrisk import otimizacao as O
from gridrisk import risco as R
from gridrisk.config import ROOT, Config
from gridrisk.ingest import bdgd, diagnostico_vinculo
from gridrisk.ingest import interrupcoes as it

EQUIP = "INTERNA-NAO PROGRAMADA-PROPRIAS DO SISTEMA-FALHA DE MATERIAL OU EQUIPAMENTO"
DESCARGA = "INTERNA-NAO PROGRAMADA-MEIO AMBIENTE-DESCARGA ATMOSFERICA"
VEGETACAO = "INTERNA-NAO PROGRAMADA-MEIO AMBIENTE-ARVORE"
MT_V = 13800
SEM_EXPURGO, DIA_CRITICO = 0, 6


def _ev(ordem, inicio, fim, conjunto, alimentador, fato, expurgo, uc, agente="EMS"):
    return {"NumOrdemInterrupcao": ordem, "DatInicioInterrupcao": inicio, "DatFimInterrupcao": fim,
            "IdeConjuntoUnidadeConsumidora": conjunto, "DscConjuntoUnidadeConsumidora": f"Conjunto {conjunto}",
            "DscAlimentadorSubestacao": alimentador, "DscSubestacaoDistribuicao": "AJO",
            "DscFatoGeradorInterrupcao": fato, "IdeMotivoInterrupcao": expurgo, "NumNivelTensao": MT_V,
            "NumUnidadeConsumidora": uc, "NumConsumidorConjunto": 1000, "SigAgente": f"{agente}                 "}


def _legado() -> pd.DataFrame:
    d = datetime
    return pd.DataFrame([
        # 200 CHI no circuito 0AJO51
        _ev("e1", d(2024, 3, 10, 10), d(2024, 3, 10, 12), 1, "AJO51", EQUIP, SEM_EXPURGO, 100),
        # 50 CHI, segundo código operacional do circuito 9001
        _ev("e2", d(2024, 4, 1, 8), d(2024, 4, 1, 9), 1, "AJO52", DESCARGA, SEM_EXPURGO, 50),
        # 60 CHI no circuito 0MIM01
        _ev("e3", d(2024, 5, 2, 9), d(2024, 5, 2, 11), 2, "MIM01", VEGETACAO, SEM_EXPURGO, 30),
        # 20 CHI em um código que não existe na BDGD
        _ev("e4", d(2024, 6, 3, 9), d(2024, 6, 3, 10), 2, "XYZ99", EQUIP, SEM_EXPURGO, 20),
        # outra distribuidora (EMT): ignorada
        _ev("e5", d(2024, 7, 4, 9), d(2024, 7, 4, 13), 2, "MIM01", EQUIP, SEM_EXPURGO, 999, "EMT"),
        # 2023, dia crítico: 40 CHI que não contam para o DEC
        _ev("e6", d(2023, 2, 5, 9), d(2023, 2, 5, 10), 1, "AJO51", EQUIP, DIA_CRITICO, 40),
    ])


def _novo() -> pd.DataFrame:
    """Layout de 2026: o circuito vem pelo CTMT.COD_ID (9002 = MIM01), 1 h x 80 UC = 80 CHI, sem expurgo."""
    return pd.DataFrame({
        "CodInterrupcao": ["e7"], "DatInicioInterrupcao": [datetime(2026, 1, 10, 8)],
        "DatFimInterrupcao": [datetime(2026, 1, 10, 9)], "CodConjUnidadeConsumidora": ["2"],
        "DscConjuntoUnidadeConsumidora": ["Conjunto 2"], "CodAlimentador": ["9002"], "CodSubestacao": ["S2"],
        "DscFatoGeradorOrigem": ["Interna"], "DscFatoGeradorTipo": ["Não Programada"],
        "DscFatoGeradorCausa": ["Próprias do Sistema"], "DscFatoGeradorDetalhe": ["Falha de Material ou Equipamento"],
        "NumNivelTensao": [MT_V], "QtdConsumidoresAfetados": [80], "QtdConsumidoresAtivos": [1000],
        "DscMotivoExpurgo": ["Não houve Expurgo"], "DscTipoElementoInterrompido": ["Chave Fusível"],
        "DscLocalizacaoInterrupcao": ["Área Rural"], "SigAgente": ["EMS"]})


@pytest.fixture(scope="module")
def mundo(tmp_path_factory, gdb_ms):
    raiz = tmp_path_factory.mktemp("ems")
    interim = raiz / "interim"
    interim.mkdir()
    cfg = Config.load(ROOT / "configs" / "ems.yaml")
    _legado().to_parquet(raiz / "legado.parquet", index=False)
    _novo().to_parquet(raiz / "novo.parquet", index=False)
    for ano in (2023, 2024):
        bdgd.feeder_features(gdb_ms, ano).to_parquet(interim / f"bdgd_feeders_{ano}.parquet", index=False)
        bdgd.feeder_map(gdb_ms).assign(ano_snapshot=ano).to_parquet(interim / f"bdgd_map_{ano}.parquet", index=False)
    saida = interim / cfg.interrupcoes_parquet.name  # interrupcoes_ems.parquet
    it.harmonize([raiz / "legado.parquet", raiz / "novo.parquet"], cfg.sigla, saida)
    return {"raiz": raiz, "interim": interim, "interrupcoes": saida, "cfg": cfg,
            "cortes": F.falhas_point_in_time(saida, interim)}


def test_o_arquivo_de_interrupcoes_de_ms_leva_o_nome_da_sigla(mundo):
    assert mundo["interrupcoes"].name == "interrupcoes_ems.parquet"


def test_ingestao_filtra_a_ems_e_ignora_outra_distribuidora(mundo):
    df = pd.read_parquet(mundo["interrupcoes"]).set_index("cod_interrupcao")
    assert sorted(df.index) == ["e1", "e2", "e3", "e4", "e6", "e7"]  # e5 é da EMT
    assert df.loc["e1"].alimentador_nome == "0AJO51"   # AJO51 completado com zero à esquerda até 6 caracteres
    assert df.loc["e7"].alimentador_cod_id == "9002"
    assert df.chi.to_dict() == pytest.approx({"e1": 200.0, "e2": 50.0, "e3": 60.0, "e4": 20.0, "e6": 40.0, "e7": 80.0})


def test_falhas_ligam_codigos_alfanumericos_e_o_cod_id_ao_circuito_canonico(mundo):
    f = mundo["cortes"][2024]
    f24 = f[f.ano == 2024].groupby(["alimentador", "modo"])[["n_falhas", "chi", "chi_regulatorio"]].sum()
    esperado = {("0AJO51", "EQUIPAMENTO"): (1, 200.0),               # e1
                ("0AJO51", "DESCARGA_ATMOSFERICA"): (1, 50.0),       # e2: AJO52 pertence ao circuito AJO51
                ("0MIM01", "VEGETACAO"): (1, 60.0)}                  # e3; e4 não tem circuito
    assert set(f24.index) == set(esperado)
    for chave, (n, chi) in esperado.items():
        assert f24.loc[chave, "n_falhas"] == n and f24.loc[chave, "chi"] == pytest.approx(chi)
    # 2026 (layout novo) liga pelo COD_ID 9002 -> 0MIM01
    f26 = f[f.ano == 2026]
    assert list(f26.alimentador) == ["0MIM01"] and f26.chi.iloc[0] == pytest.approx(80.0)
    # dia crítico (e6): é falha, entra no CHI, mas não no CHI regulatório
    e6 = f[(f.ano == 2023) & (f.alimentador == "0AJO51")]
    assert e6.chi.sum() == pytest.approx(40.0) and e6.chi_regulatorio.isna().all()


def test_cobertura_do_vinculo_de_circuitos(mundo):
    c = diagnostico_vinculo.cobertura_vinculo(mundo["interrupcoes"], mundo["interim"])
    c = c[c.escopo == "mt"].set_index(["ano", "corte"])
    # 2024: 4 eventos de MT da EMS (e1 a e4); e4 (XYZ99) não casa -> 3/4 em eventos e 310/330 em CHI
    assert c.loc[(2024, "todos"), "eventos"] == 4 and c.loc[(2024, "todos"), "eventos_ligados"] == 3
    assert c.loc[(2024, "todos"), "pct_chi"] == pytest.approx(100 * 310 / 330)
    # o corte y-1 de 2024 é 2023, que também tem o mapa completo; para 2023, y-1 = 2022 não tem snapshot
    assert c.loc[(2024, "y-1"), "eventos_ligados"] == 3
    assert c.loc[(2023, "y-1"), "eventos_ligados"] == 0 and c.loc[(2023, "y"), "eventos_ligados"] == 1
    # 2026 (COD_ID): 1 de 1 com os snapshots disponíveis
    assert c.loc[(2026, "todos"), "pct_eventos"] == 100.0


def test_compensacao_de_ms_conta_so_a_ems(mundo, tmp_path):
    comp = pd.DataFrame({"SigAgente": ["EMS   ", "EMS   ", "EMT   "], "IdeConjUndConsumidoras": [1, 1, 1],
                         "SigIndicador": ["PGUCBTU", "QTUCBTU", "PGUCBTU"], "AnoIndice": [2024, 2024, 2024],
                         "VlrIndiceEnviado": [550.0, 9999.0, 7777.0]})
    comp.to_parquet(tmp_path / "comp.parquet", index=False)
    c = R.compensacao_por_chi(tmp_path / "comp.parquet", mundo["interrupcoes"], "EMS", [2024]).set_index("conjunto_id")
    # conjunto 1 em 2024: CHI regulatório = e1 200 + e2 50 = 250; compensação = só o PG da EMS (550)
    assert c.loc[1, "compensacao"] == pytest.approx(550.0) and c.loc[1, "chi_regulatorio"] == pytest.approx(250.0)
    assert c.loc[1, "rs_por_chi"] == pytest.approx(2.2)


def test_pesos_de_conjunto_respeitam_o_ano_minimo(mundo):
    cw = mundo["interim"] / "crosswalk_2024.parquet"
    p = R.conjunto_do_alimentador(mundo["interrupcoes"], cw).set_index(["alimentador", "conjunto_id"]).peso
    assert p[("0AJO51", 1)] == pytest.approx(1.0) and p[("0MIM01", 2)] == pytest.approx(1.0)
    # com ano mínimo 2024 o e6 (2023) sai; sem ele, o 0AJO51 só tem CHI de 2024 (250), todo do conjunto 1
    q = R.conjunto_do_alimentador(mundo["interrupcoes"], cw, ano_min=2024)
    assert q.set_index(["alimentador", "conjunto_id"]).peso[("0AJO51", 1)] == pytest.approx(1.0)
    # com ano mínimo 2027 não sobra evento nenhum
    assert R.conjunto_do_alimentador(mundo["interrupcoes"], cw, ano_min=2027).empty


def test_carteira_priorizada_para_ms_com_o_catalogo_real(mundo):
    fin, catalogo = O.carregar_catalogo(mundo["cfg"].catalogo)
    feeders = (pd.read_parquet(mundo["interim"] / "bdgd_feeders_2024.parquet")
               .rename(columns={"alimentador_nome": "alimentador"}).set_index("alimentador"))
    chi = pd.DataFrame(0.0, index=feeders.index, columns=F.MODOS)
    chi.loc["0AJO51", "EQUIPAMENTO"] = 5000.0
    chi.loc["0MIM01", "VEGETACAO"] = 8000.0
    c = O.pacotes(feeders, chi, pd.Series({"0AJO51": 20.0, "0MIM01": 20.0}), catalogo, fin)
    assert set(c.alimentador) <= {"0AJO51", "0MIM01"}
    sel = O.otimizar(c, 5e6)
    assert sel.custo_inicial.sum() <= 5e6 and sel.alimentador.is_unique
