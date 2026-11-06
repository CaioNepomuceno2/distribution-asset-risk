"""Teste de fumaça do núcleo do pipeline: ingestão -> falhas -> R$/CHI -> priorização da carteira.

Usa dados sintéticos minúsculos, gerados aqui, sem rede e sem modelo (o LightGBM fica de fora: o CHI previsto
é substituído pelo CHI observado em 2024). Todos os valores esperados foram calculados à mão no comentário de
cada bloco, sem chamar o código que está sendo testado.

Cenário: a EMT tem dois alimentadores (circuitos CT-A e CT-B) e dois conjuntos (1 e 2).

* ``000101`` é o alimentador A. O código operacional ``000102`` também pertence ao circuito CT-A.
* ``000202`` é o alimentador B. O circuito CT-B só aparece na BDGD de 2024 (não existia em 2023).
"""
from datetime import datetime

import duckdb
import pandas as pd
import pytest

from gridrisk import features as F
from gridrisk import otimizacao as O
from gridrisk import risco as R
from gridrisk.config import ROOT
from gridrisk.ingest import interrupcoes as it

EQUIP = "INTERNA-NAO PROGRAMADA-PROPRIAS DO SISTEMA-FALHA DE MATERIAL OU EQUIPAMENTO"
DESCARGA = "INTERNA-NAO PROGRAMADA-MEIO AMBIENTE-DESCARGA ATMOSFERICA"
VEGETACAO = "INTERNA-NAO PROGRAMADA-MEIO AMBIENTE-ARVORE"
PROGRAMADA = "INTERNA-PROGRAMADA-MANUTENCAO-PREVENTIVA"
# IdeMotivoInterrupcao do layout legado: 0 = sem expurgo, 6 = dia crítico
SEM_EXPURGO, DIA_CRITICO = 0, 6
MT, BT = 13800, 220


def _evento(ordem, inicio, fim, conjunto, alimentador, fato, expurgo, tensao, uc, agente="EMT"):
    return {
        "NumOrdemInterrupcao": ordem, "DatInicioInterrupcao": inicio, "DatFimInterrupcao": fim,
        "IdeConjuntoUnidadeConsumidora": conjunto, "DscConjuntoUnidadeConsumidora": f"Conjunto {conjunto}",
        "DscAlimentadorSubestacao": alimentador, "DscSubestacaoDistribuicao": "001",
        "DscFatoGeradorInterrupcao": fato, "IdeMotivoInterrupcao": expurgo, "NumNivelTensao": tensao,
        "NumUnidadeConsumidora": uc, "NumConsumidorConjunto": 1000, "SigAgente": f"{agente}   ",
    }


def _eventos_legado() -> pd.DataFrame:
    d = datetime
    return pd.DataFrame([
        # e1: 2 h x 100 UC = 200 CHI; alimentador informado sem o zero à esquerda ("101")
        _evento("e1", d(2023, 3, 10, 10), d(2023, 3, 10, 12), 1, "101", EQUIP, SEM_EXPURGO, MT, 100),
        # e2: 1 h x 50 UC = 50 CHI
        _evento("e2", d(2024, 1, 5, 8), d(2024, 1, 5, 9), 1, "000101", EQUIP, SEM_EXPURGO, MT, 50),
        # e3: 2 min x 1000 UC = 33,33 CHI; dura menos de 3 min, então não conta para o DEC
        _evento("e3", d(2024, 2, 10, 10), d(2024, 2, 10, 10, 2), 1, "000102", DESCARGA, SEM_EXPURGO, MT, 1000),
        # e4: 2 h x 20 UC = 40 CHI; dia crítico, então não conta para o DEC
        _evento("e4", d(2024, 3, 15, 14), d(2024, 3, 15, 16), 1, "000102", DESCARGA, DIA_CRITICO, MT, 20),
        # e5: 4 h x 30 UC = 120 CHI (vegetação no alimentador B)
        _evento("e5", d(2024, 4, 20, 9), d(2024, 4, 20, 13), 2, "000202", VEGETACAO, SEM_EXPURGO, MT, 30),
        # e6: programada, 1 h x 500 UC = 500 CHI; entra no DEC do conjunto, mas não é falha
        _evento("e6", d(2024, 5, 1, 9), d(2024, 5, 1, 10), 2, "000202", PROGRAMADA, SEM_EXPURGO, MT, 500),
        # e8: baixa tensão, 1 h x 60 UC = 60 CHI; entra no DEC, mas não é falha de MT
        _evento("e8", d(2024, 7, 1, 8), d(2024, 7, 1, 9), 2, "000202", EQUIP, SEM_EXPURGO, BT, 60),
        # e9: outra distribuidora (CPFL); deve ser ignorada
        _evento("e9", d(2024, 8, 15, 8), d(2024, 8, 15, 12), 2, "000101", EQUIP, SEM_EXPURGO, MT, 999, "CPFL"),
        # e10: código sem correspondência na BDGD; 1 h x 20 UC = 20 CHI entram no conjunto, mas não no alimentador
        _evento("e10", d(2024, 8, 1, 8), d(2024, 8, 1, 9), 2, "000999", EQUIP, SEM_EXPURGO, MT, 20),
        # e11: 3 h x 100 UC = 300 CHI, conjunto 1, mas no alimentador B
        _evento("e11", d(2024, 9, 1, 8), d(2024, 9, 1, 11), 1, "000202", EQUIP, SEM_EXPURGO, MT, 100),
    ])


def _evento_novo_layout() -> pd.DataFrame:
    """Layout 2026: alimentador pelo COD_ID da BDGD (CT-B), origem externa (expurgada), 1 h x 80 UC = 80 CHI."""
    return pd.DataFrame({
        "CodInterrupcao": ["e7"], "DatInicioInterrupcao": [datetime(2026, 1, 10, 8)],
        "DatFimInterrupcao": [datetime(2026, 1, 10, 9)], "CodConjUnidadeConsumidora": ["2"],
        "DscConjuntoUnidadeConsumidora": ["Conjunto 2"], "CodAlimentador": ["CT-B"], "CodSubestacao": ["001"],
        "DscFatoGeradorOrigem": ["Externa"], "DscFatoGeradorTipo": ["Não Programada"],
        "DscFatoGeradorCausa": ["Terceiros"], "DscFatoGeradorDetalhe": ["Outros"], "NumNivelTensao": [MT],
        "QtdConsumidoresAfetados": [80], "QtdConsumidoresAtivos": [1000],
        "DscMotivoExpurgo": ["Interrupção de origem externa ao sistema de distribuição"],
        "DscTipoElementoInterrompido": ["Chave Fusível"], "DscLocalizacaoInterrupcao": ["Área Rural"],
        "SigAgente": ["EMT"],
    })


def _compensacoes() -> pd.DataFrame:
    linhas = [
        ("EMT   ", 1, "PGUCBTU", 2023, 300.0),
        ("EMT   ", 1, "PGUCMTU", 2024, 800.0),
        ("EMT   ", 1, "QTUCBTU", 2024, 999.0),    # quantidade de UCs, não é valor pago (não começa com PG)
        ("EMT   ", 1, "DEC", 2024, 15.0),         # indicador de continuidade, não é compensação
        ("EMT   ", 1, "PGUCBTU", 2021, 5000.0),   # fora dos anos pedidos
        ("EMT   ", 2, "PGUCBTNU", 2024, 2800.0),
        ("CPFL  ", 2, "PGUCBTNU", 2024, 9999.0),  # outra distribuidora com o mesmo ID de conjunto
    ]
    return pd.DataFrame(linhas, columns=["SigAgente", "IdeConjUndConsumidoras", "SigIndicador", "AnoIndice",
                                         "VlrIndiceEnviado"])


def _bdgd(interim, ano: int, circuitos: dict[str, str], codigos: dict[str, str]) -> None:
    """Snapshot sintético: ``circuitos`` = {COD_ID: nome do CTMT}; ``codigos`` = {código operacional: COD_ID}."""
    pd.DataFrame({"alimentador_cod_id": list(circuitos), "alimentador_nome": list(circuitos.values()),
                  "ano_snapshot": ano}).to_parquet(interim / f"bdgd_feeders_{ano}.parquet", index=False)
    pd.DataFrame({"alimentador_nome": list(codigos), "alimentador_cod_id": list(codigos.values()),
                  "ano_snapshot": ano}).to_parquet(interim / f"bdgd_map_{ano}.parquet", index=False)


@pytest.fixture(scope="module")
def mundo(tmp_path_factory):
    """Roda a ingestão e o vínculo de circuitos uma vez para todos os testes do módulo."""
    raiz = tmp_path_factory.mktemp("fumaca")
    interim = raiz / "interim"
    interim.mkdir()
    _eventos_legado().to_parquet(raiz / "legado.parquet", index=False)
    _evento_novo_layout().to_parquet(raiz / "novo.parquet", index=False)
    _compensacoes().to_parquet(raiz / "compensacao.parquet", index=False)
    _bdgd(interim, 2023, {"CT-A": "000101"}, {"000101": "CT-A", "000102": "CT-A"})
    _bdgd(interim, 2024, {"CT-A": "000101", "CT-B": "000202"},
          {"000101": "CT-A", "000102": "CT-A", "000202": "CT-B"})
    interr = it.harmonize([raiz / "legado.parquet", raiz / "novo.parquet"], "EMT", interim / "interrupcoes_emt.parquet")
    cortes = F.falhas_point_in_time(interr, interim)
    return {"raiz": raiz, "interim": interim, "interrupcoes": interr, "cortes": cortes,
            "compensacao": raiz / "compensacao.parquet"}


# ------------------------------------------------------------------ ingestão e vínculo de circuitos

def test_ingestao_filtra_distribuidora_e_calcula_chi(mundo):
    df = duckdb.sql(f"select * from read_parquet('{mundo['interrupcoes']}') order by inicio").df()
    assert len(df) == 10  # 9 do layout legado (as 10 menos e9, da CPFL) + 1 do layout novo
    assert "e9" not in df.cod_interrupcao.tolist()
    chi = df.set_index("cod_interrupcao").chi
    assert chi["e1"] == pytest.approx(200.0)
    assert chi["e3"] == pytest.approx(1000 * 2 / 60)
    assert chi["e7"] == pytest.approx(80.0)
    e7 = df.set_index("cod_interrupcao").loc["e7"]
    assert e7.alimentador_cod_id == "CT-B" and e7.expurgo == "ORIGEM EXTERNA AO SISTEMA DE DISTRIBUICAO"
    assert df.set_index("cod_interrupcao").loc["e1"].alimentador_nome == "000101"  # zero à esquerda restaurado
    assert df.set_index("cod_interrupcao").loc["e4"].expurgo == "DIA CRITICO"


def test_falhas_mt_internas_nao_programadas_por_alimentador_e_modo(mundo):
    f = mundo["cortes"][2024]
    f24 = f[f.ano == 2024].groupby(["alimentador", "modo"])[["n_falhas", "chi", "chi_regulatorio"]].sum()
    esperado = {  # (alimentador, modo): (n_falhas, chi, chi regulatório)
        ("000101", "EQUIPAMENTO"): (1, 50.0, 50.0),
        ("000101", "DESCARGA_ATMOSFERICA"): (2, 1000 * 2 / 60 + 40.0, 0.0),  # e3 < 3 min, e4 dia crítico
        ("000202", "VEGETACAO"): (1, 120.0, 120.0),
        ("000202", "EQUIPAMENTO"): (1, 300.0, 300.0),  # e11; e8 é BT e e10 não tem circuito
    }
    assert set(f24.index) == set(esperado)  # e6 (programada), e7 (externa) e e9 (CPFL) ficam de fora
    for chave, (n, chi, reg) in esperado.items():
        assert f24.loc[chave, "n_falhas"] == n
        assert f24.loc[chave, "chi"] == pytest.approx(chi)
        assert f24.loc[chave, "chi_regulatorio"] == pytest.approx(reg)
    f23 = f[f.ano == 2023]
    assert list(f23.alimentador) == ["000101"] and f23.chi.iloc[0] == pytest.approx(200.0)


def test_corte_temporal_nao_usa_cadastro_futuro(mundo):
    corte_2023 = mundo["cortes"][2023]
    # o circuito CT-B só existe na BDGD de 2024: com o corte em 2023 os eventos dele ficam sem alimentador
    assert "000202" not in set(corte_2023.alimentador)
    assert "000202" in set(mundo["cortes"][2024].alimentador)
    assert corte_2023[corte_2023.ano == 2024].alimentador.unique().tolist() == ["000101"]


# ------------------------------------------------------------------ risco monetizado (R$/CHI)

@pytest.fixture(scope="module")
def valor(mundo):
    comp = R.compensacao_por_chi(mundo["compensacao"], mundo["interrupcoes"], "EMT", [2023, 2024])
    pesos = R.conjunto_do_alimentador(mundo["interrupcoes"], mundo["interim"] / "crosswalk_2024.parquet")
    feeders = pd.DataFrame({"alimentador": ["000101", "000202"], "energia_mwh_ano": [8760.0, 17520.0],
                            "n_uc": [1000, 500]})
    return {"comp": comp, "pesos": pesos, "feeders": feeders,
            "social": R.valor_chi_alimentador(comp, pesos, feeders, 7000.0).set_index("alimentador"),
            "caixa": R.valor_chi_alimentador(comp, pesos, feeders, 0.0).set_index("alimentador")}


def test_compensacao_por_chi_do_conjunto(valor):
    c = valor["comp"].set_index("conjunto_id")
    # conjunto 1: compensação 300 + 800 (QTUCBTU, DEC, 2021 e CPFL ficam de fora); CHI regulatório
    #   2023: e1 = 200; 2024: e2 = 50 + e11 = 300 (e3 < 3 min e e4 em dia crítico não contam) -> 550
    assert c.loc[1, "compensacao"] == pytest.approx(1100.0)
    assert c.loc[1, "chi_regulatorio"] == pytest.approx(550.0)
    assert c.loc[1, "rs_por_chi"] == pytest.approx(2.0)
    # conjunto 2: compensação 2800; CHI regulatório 2024: e5 120 + e6 500 + e8 60 + e10 20 = 700
    #   (e7 é de 2026 e de origem externa)
    assert c.loc[2, "compensacao"] == pytest.approx(2800.0)
    assert c.loc[2, "chi_regulatorio"] == pytest.approx(700.0)
    assert c.loc[2, "rs_por_chi"] == pytest.approx(4.0)


def test_participacao_do_conjunto_no_chi_do_alimentador(valor):
    p = valor["pesos"].set_index(["alimentador", "conjunto_id"]).peso
    # A: tudo do conjunto 1. B (MT, qualquer tipo, ano >= 2022): conjunto 2 = e5 120 + e6 500 + e7 80 = 700;
    # conjunto 1 = e11 300 (e8 é BT, e10 não tem circuito)
    assert p[("000101", 1)] == pytest.approx(1.0)
    assert p[("000202", 2)] == pytest.approx(0.7)
    assert p[("000202", 1)] == pytest.approx(0.3)


def test_valor_do_chi_por_alimentador(valor):
    # R$/CHI dos conjuntos (2,0 e 4,0) é limitado aos percentis 5 e 95: 2,0 + 0,05 x 2,0 = 2,1 e 2,0 + 0,95 x 2,0 = 3,9
    caixa, social = valor["caixa"], valor["social"]
    assert caixa.loc["000101", "rs_por_chi"] == pytest.approx(2.1)
    assert caixa.loc["000202", "rs_por_chi"] == pytest.approx(0.3 * 2.1 + 0.7 * 3.9)  # 3,36
    # custo social: A usa 1 kW/UC (8760 MWh/ano e 1000 UC) e B, 4 kW/UC; x R$ 7.000/MWh
    assert social.loc["000101", "kw_medio_uc"] == pytest.approx(1.0)
    assert social.loc["000202", "kw_medio_uc"] == pytest.approx(4.0)
    assert social.loc["000101", "rs_por_chi"] == pytest.approx(2.1 + 7.0)
    assert social.loc["000202", "rs_por_chi"] == pytest.approx(3.36 + 28.0)


# ------------------------------------------------------------------ priorização da carteira

def _chi_modo(mundo, coluna: str) -> pd.DataFrame:
    """Substituto do modelo: o CHI previsto é o CHI observado em 2024, por alimentador e modo."""
    f = mundo["cortes"][2024]
    t = f[f.ano == 2024].groupby(["alimentador", "modo"])[coluna].sum().unstack(fill_value=0.0)
    return t.reindex(columns=F.MODOS, fill_value=0.0)


def test_risco_anual_em_reais(mundo, valor):
    chi = _chi_modo(mundo, "chi").sum(axis=1)
    chi_reg = _chi_modo(mundo, "chi_regulatorio").sum(axis=1)
    assert chi["000101"] == pytest.approx(50 + 1000 * 2 / 60 + 40)  # 123,33
    assert chi["000202"] == pytest.approx(420.0)
    assert chi_reg["000101"] == pytest.approx(50.0) and chi_reg["000202"] == pytest.approx(420.0)
    # visão social: CHI x (compensação + custo social); visão de caixa: CHI regulatório x compensação
    assert chi["000101"] * valor["social"].loc["000101", "rs_por_chi"] == pytest.approx(123.3333333 * 9.1)
    assert chi["000202"] * valor["social"].loc["000202", "rs_por_chi"] == pytest.approx(420 * 31.36)
    assert chi_reg["000101"] * valor["caixa"].loc["000101", "rs_por_chi"] == pytest.approx(50 * 2.1)
    assert chi_reg["000202"] * valor["caixa"].loc["000202", "rs_por_chi"] == pytest.approx(420 * 3.36)


FIN = {"taxa_desconto": 0.08, "horizonte_anos": 10}
FA = (1 - 1.08 ** -10) / 0.08  # fator de anuidade de 10 anos a 8%
# x: capex de R$ 2.000 com vida de 10 anos, corta 50% do CHI de qualquer modo
# y: opex de R$ 500/ano, corta 40% do CHI de equipamento
X = O.Intervencao("x", "", "capex", 2000.0, "1", "1", 10, 1.0, {"todos": 0.5})
Y = O.Intervencao("y", "", "opex", 500.0, "1", "1", 1, 1.0, {"EQUIPAMENTO": 0.4})


@pytest.fixture(scope="module")
def candidatos(mundo, valor):
    chi_modo = _chi_modo(mundo, "chi")
    feeders = valor["feeders"].set_index("alimentador")
    return O.pacotes(feeders, chi_modo, valor["social"].rs_por_chi, [X, Y], FIN)


def _vpl(chi_evitado: float, rs: float, capex_anual: float, opex: float) -> float:
    return (chi_evitado * rs - capex_anual - opex) * FA


def test_pacotes_com_custo_e_vpl_calculados_a_mao(candidatos):
    c = candidatos.set_index(["alimentador", "pacote"])
    assert len(c) == 6  # x, y e x+y em cada alimentador
    capex_x = 2000.0 / FA
    # B: CHI de equipamento 300 e de vegetação 120, R$ 31,36/CHI
    assert c.loc[("000202", "x"), "chi_evitado_ano"] == pytest.approx(210.0)
    assert c.loc[("000202", "x"), "vpl"] == pytest.approx(_vpl(210.0, 31.36, capex_x, 0.0))
    assert c.loc[("000202", "y"), "chi_evitado_ano"] == pytest.approx(120.0)
    assert c.loc[("000202", "y"), "vpl"] == pytest.approx(_vpl(120.0, 31.36, 0.0, 500.0))
    # x+y: equipamento sobra 0,5 x 0,6 = 0,3 (evita 210) e vegetação sobra 0,5 (evita 60)
    assert c.loc[("000202", "x+y"), "chi_evitado_ano"] == pytest.approx(270.0)
    assert c.loc[("000202", "x+y"), "custo_inicial"] == pytest.approx(2500.0)
    assert c.loc[("000202", "x+y"), "vpl"] == pytest.approx(_vpl(270.0, 31.36, capex_x, 500.0))
    # A: CHI de equipamento 50 e de descarga 73,33, R$ 9,10/CHI; só o pacote x paga o próprio custo
    assert c.loc[("000101", "x"), "vpl"] == pytest.approx(_vpl(0.5 * 123.3333333, 9.1, capex_x, 0.0))
    assert c.loc[("000101", "y"), "vpl"] < 0 and c.loc[("000101", "x+y"), "vpl"] < 0


@pytest.mark.parametrize("orcamento, esperado", [
    (2000.0, {("000202", "x")}),                          # só cabe um x; o de B vale mais
    (2500.0, {("000202", "x+y")}),                        # x+y em B (R$ 2.500) vence y em B + x em A
    (4500.0, {("000202", "x+y"), ("000101", "x")}),       # sobra para o x de A
])
def test_carteira_otima_escolhe_a_melhor_combinacao_dentro_do_orcamento(candidatos, orcamento, esperado):
    sel = O.otimizar(candidatos, orcamento)
    assert set(zip(sel.alimentador, sel.pacote)) == esperado
    assert sel.custo_inicial.sum() <= orcamento
    assert sel.alimentador.is_unique


def test_baselines_ficam_abaixo_do_otimo(candidatos):
    historico = pd.Series({"000101": 123.3, "000202": 420.0})
    otimo = O.otimizar(candidatos, 2500.0)
    guloso = O.guloso(candidatos, 2500.0)
    tradicional = O.priorizacao_tradicional(candidatos, historico, 4500.0, pacote_padrao=("x+y", "x", "y"))
    # guloso (maior VPL/custo primeiro) escolhe y em B (R$ 500) e sobra para x em A (R$ 2.000)
    assert set(zip(guloso.alimentador, guloso.pacote)) == {("000202", "y"), ("000101", "x")}
    assert guloso.vpl.sum() < otimo.vpl.sum()
    # tradicional (pior alimentador primeiro, pacote padrão x+y): B primeiro, e x+y de A (R$ 2.500) não cabe
    assert set(zip(tradicional.alimentador, tradicional.pacote)) == {("000202", "x+y")}
    assert tradicional.vpl.sum() < O.otimizar(candidatos, 4500.0).vpl.sum()


def test_catalogo_real_gera_pacotes_validos():
    """O YAML de verdade carrega e, num alimentador rural e longo, gera pacotes com todas as intervenções."""
    fin, catalogo = O.carregar_catalogo(ROOT / "configs" / "intervencoes.yaml")
    feeders = pd.DataFrame({
        "rede_mt_km": [120.0], "n_religadores": [1.0], "religadores_por_100km": [0.8],
        "n_chaves_telecomandadas": [0.0], "n_uc": [1500], "frac_cabo_nu": [0.6], "frac_rural": [0.7],
    }, index=["000101"])
    chi = pd.DataFrame([[1000.0] * len(F.MODOS)], index=["000101"], columns=F.MODOS)
    c = O.pacotes(feeders, chi, pd.Series({"000101": 30.0}), catalogo, fin)
    assert not c.empty and c.vpl.notna().all() and (c.custo_inicial > 0).all()
    assert {i.nome for i in catalogo} == set("+".join(c.pacote).split("+"))
    assert c.n_itens.max() == 3
    assert O.otimizar(c, 5e6).custo_inicial.sum() <= 5e6
