"""Tabelas de diagnóstico de ``gridrisk.ingest.diagnostico_aneel``, com dados sintéticos e contas feitas à mão.

São as tabelas que sustentam ``docs/decisoes_ems.md``; os valores esperados vêm do comentário de cada bloco.
"""
from datetime import date, datetime

import pandas as pd
import pytest

from gridrisk import otimizacao as O
from gridrisk.config import ROOT
from gridrisk.ingest import diagnostico_aneel as D

SEM, ISE = "NAO HOUVE EXPURGO", "ISE POR MEIO DE CHI"


def _int(ano, mes, chi, uc, dur, expurgo=SEM, conj=1, mt=True, origem="INTERNA", tipo="NAO PROGRAMADA", grupo="VENTO"):
    return {"ano": ano, "mes": mes, "chi": chi, "uc_afetadas": uc, "duracao_h": dur, "expurgo": expurgo,
            "conjunto_id": conj, "origem_mt": mt, "origem": origem, "tipo": tipo, "grupo_causa": grupo}


@pytest.fixture
def interrupcoes(tmp_path):
    """Conjunto 1 (1.000 consumidores), 2025. Janeiro e março sem expurgo; fevereiro é uma emergência (ISE) em que o
    regulador conta 5.000 CHI, mas o arquivo só traz 100 CHI sem expurgo e dois eventos de ISE."""
    linhas = [
        _int(2025, 1, 2000.0, 1000, 2.0),                                   # DEC de janeiro: 2,0
        _int(2025, 2, 100.0, 100, 1.0),                                     # só isto conta no DEC de fevereiro
        _int(2025, 2, 3000.0, 300, 10.0, ISE), _int(2025, 2, 3000.0, 100, 30.0, ISE),
        _int(2025, 3, 3000.0, 1000, 3.0),                                   # DEC de março: 3,0
        _int(2025, 3, 50.0, 50, 1.0, mt=False),                             # BT: fora das falhas de MT
        _int(2025, 3, 70.0, 70, 1.0, origem="EXTERNA"),                     # externa: fora das falhas
        _int(2025, 3, 80.0, 80, 1.0, tipo="PROGRAMADA"),                    # programada: fora das falhas
    ]
    p = tmp_path / "interrupcoes_ems.parquet"
    pd.DataFrame(linhas).to_parquet(p, index=False)
    return p


@pytest.fixture
def indicadores(tmp_path):
    """DEC oficial de 2025: 2,0 em janeiro, 5,0 em fevereiro, 3,0 em março; 1.000 consumidores."""
    linhas = []
    for mes, dec in ((1, 2.0), (2, 5.0), (3, 3.0)):
        for ind, v in (("DEC", dec), ("NumCon", 1000.0)):
            linhas.append(("EMS   ", 1, ind, 2025, mes, v))
    p = tmp_path / "indicadores.parquet"
    pd.DataFrame(linhas, columns=["SigAgente", "IdeConjUndConsumidoras", "SigIndicador", "AnoIndice", "NumPeriodoIndice",
                                  "VlrIndiceEnviado"]).to_parquet(p, index=False)
    return p


def test_registros_por_mes(interrupcoes):
    t = D.interrupcoes_por_mes(interrupcoes).set_index(["ano", "mes"]).registros
    assert t.to_dict() == {(2025, 1): 1, (2025, 2): 3, (2025, 3): 4}


def test_falhas_por_expurgo_so_conta_falhas_de_mt_internas_nao_programadas(interrupcoes):
    t = D.falhas_por_expurgo(interrupcoes).set_index(["ano", "expurgo"])
    # janeiro a março: 1 + 3 + 1 = 5 falhas (BT, externa e programada ficam de fora); CHI total 2000+100+6000+3000
    assert t.registros.sum() == 5 and t.chi.sum() == pytest.approx(11100.0)
    assert t.loc[(2025, ISE), "registros"] == 2 and t.loc[(2025, ISE), "pct_chi"] == pytest.approx(100 * 6000 / 11100)
    assert t.loc[(2025, SEM), "pct_registros"] == pytest.approx(60.0)


def test_chi_por_modo_com_linha_de_total_e_fracao_expurgada():
    f = pd.DataFrame({"modo": ["VENTO", "VENTO", "EQUIPAMENTO"], "ano": [2023, 2024, 2023],
                      "chi": [100.0, 300.0, 200.0], "chi_regulatorio": [20.0, 60.0, 200.0]})
    t = D.chi_por_modo(f, 2023, 2024).set_index("modo")
    # média de 2 anos: vento 200 CHI (40 regulatórios), equipamento 100 (100)
    assert t.loc["VENTO", "chi"] == pytest.approx(200.0) and t.loc["VENTO", "pct_expurgado"] == pytest.approx(80.0)
    assert t.loc["EQUIPAMENTO", "pct_expurgado"] == 0.0
    assert t.loc["TOTAL", "chi"] == pytest.approx(300.0) and t.loc["TOTAL", "pct_expurgado"] == pytest.approx(100 * (1 - 140 / 300))
    assert t.index[0] == "TOTAL"  # ordenado por CHI, e o total é o maior


def test_dec_sem_buracos_exclui_o_mes_de_razao_baixa(indicadores, interrupcoes):
    # razão calculado/oficial: janeiro 2000/2000 = 1, fevereiro 100/5000 = 0,02, março 3000/3000 = 1
    t = D.dec_sem_buracos(indicadores, interrupcoes, "EMS").set_index("conjunto")
    assert t.loc["todos os meses", "linhas"] == 3 and t.loc["todos os meses", "corr_dec"] < 0.99
    sem = t.loc["sem os meses com razão < 0.9"]
    assert sem.meses_excluidos == "2025-02" and sem.linhas == 2 and sem.corr_dec == pytest.approx(1.0)


def test_mes_de_menor_razao_ignora_meses_com_poucos_registros(indicadores, interrupcoes):
    assert D.mes_de_menor_razao(indicadores, interrupcoes, "EMS", registros_minimos=1) == (2025, 2)
    # com mínimo de 4 registros, só março (4 registros) é candidato
    assert D.mes_de_menor_razao(indicadores, interrupcoes, "EMS", registros_minimos=4) == (2025, 3)


def test_ise_acima_de_cada_limite_contra_a_diferenca_do_dec(indicadores, interrupcoes):
    t = D.ise_acima_de_limite(indicadores, interrupcoes, "EMS", 2025, 2, limites=(3, 12, 24)).set_index("limite_h")
    # CHI oficial 5.000; calculado 100; diferença 4.900. Eventos de ISE: 10 h x 300 UC e 30 h x 100 UC
    assert t.chi_oficial.iloc[0] == pytest.approx(5000.0) and t.diferenca_oficial_menos_calculado.iloc[0] == pytest.approx(4900.0)
    assert t.loc[3, "eventos"] == 2 and t.loc[3, "chi_cheio_acima_do_limite"] == pytest.approx(6000.0)
    assert t.loc[3, "chi_so_o_excesso"] == pytest.approx(7 * 300 + 27 * 100)    # 4.800
    assert t.loc[12, "eventos"] == 1 and t.loc[12, "chi_so_o_excesso"] == pytest.approx(18 * 100)
    assert t.loc[24, "chi_so_o_excesso"] == pytest.approx(6 * 100)


def test_compensacoes_e_conjuntos(tmp_path, interrupcoes):
    linhas = [("EMS   ", 1, "PGUCBTU", 2024, 1, 1_000_000.0), ("EMS   ", 1, "QTUCBTU", 2024, 1, 999.0),
              ("EMS   ", 9, "PGUCMTU", 2025, 6, 2_000_000.0), ("EMT   ", 1, "PGUCBTU", 2024, 1, 7e9)]
    pd.DataFrame([(date(2026, 11, 5), a, 1, c, "x", i, y, m, v) for a, c, i, y, m, v in linhas],
                 columns=["DatGeracaoConjuntoDados", "SigAgente", "NumCNPJ", "IdeConjUndConsumidoras",
                          "DscConjUndConsumidoras", "SigIndicador", "AnoIndice", "NumPeriodoIndice",
                          "VlrIndiceEnviado"]).pipe(lambda d: pd.concat([d, d])).to_parquet(tmp_path / "comp.parquet", index=False)
    por_ano = D.compensacoes_por_ano(tmp_path / "comp.parquet", "EMS").set_index("ano")
    assert por_ano.pg_milhoes.to_dict() == pytest.approx({2024: 1.0, 2025: 2.0})  # arquivo duplicado: conta uma vez; só PG*
    assert por_ano.conjuntos.to_dict() == {2024: 1, 2025: 1}
    c = D.conjuntos_compensacao(tmp_path / "comp.parquet", interrupcoes, "EMS").iloc[0]
    assert (c.com_compensacao, c.nas_interrupcoes, c.em_ambos) == (2, 1, 1)  # conjuntos 1 e 9 pagos; interrupções só do 1


def test_circuitos_vazios_por_snapshot(tmp_path):
    f = pd.DataFrame({"alimentador_nome": ["A", "B", "C"], "rede_mt_km": [10.0, float("nan"), 0.5], "n_uc": [5, 0, 0]})
    f.to_parquet(tmp_path / "bdgd_feeders_2019.parquet", index=False)
    t = D.circuitos_vazios(tmp_path).iloc[0]
    # B não tem rede nem consumidor; C tem rede (0,5 km) mas nenhum consumidor
    assert (t.ano, t.circuitos, t.sem_rede_e_sem_uc, t.sem_uc, t.rede_menor_que_1km) == (2019, 3, 1, 2, 1)


def test_elegibilidade_do_catalogo_real():
    _, catalogo = O.carregar_catalogo(ROOT / "configs" / "intervencoes.yaml")
    f = pd.DataFrame({
        "alimentador_nome": ["A", "B"], "rede_mt_km": [120.0, 10.0], "n_religadores": [1.0, 0.0],
        "religadores_por_100km": [0.8, 0.0], "n_chaves_telecomandadas": [0.0, 5.0], "n_uc": [1500, 100],
        "frac_cabo_nu": [0.6, 0.1], "frac_rural": [0.7, 0.1]})
    t = D.elegibilidade(f, catalogo).set_index("intervencao")
    # A: rede longa, pouco religador, sem telecomando e 1.500 UC -> religador e automação; B: rede curta, 5 telecomandadas
    assert t.loc["religador", "elegiveis"] == 1 and t.loc["automacao", "elegiveis"] == 1
    assert t.loc["rede_compacta", "elegiveis"] == 1 and t.loc["poda", "elegiveis"] == 1  # só A tem cabo nu >= 30% e rural >= 30%
    assert t.loc["manutencao_preditiva", "elegiveis"] == 2 and t.loc["religador", "pct"] == pytest.approx(50.0)


def test_comparacao_descritiva_normaliza_por_consumidor_e_por_km():
    def risco(n_uc, km, chi, risco_soc):
        return pd.DataFrame({"n_uc": n_uc, "rede_mt_km": km, "chi_previsto": chi, "chi_reg_previsto": chi, "dec_contribuicao_h": 1.0,
                             "risco_rs_social": risco_soc, "risco_rs_compensacao": risco_soc})
    # A: 10 alimentadores de 100 consumidores, 10 km e 40 CHI; risco social de 1 (nove vezes) e 11 (uma vez)
    a = risco([100] * 10, [10.0] * 10, [40.0] * 10, [1.0] * 9 + [11.0])
    t = D.comparacao_descritiva({"A": a, "B": risco([50], [5.0], [10.0], [3.0])}).set_index("distribuidora")
    assert t.loc["A", "consumidores_por_km"] == pytest.approx(10.0)
    assert t.loc["A", "chi_previsto_por_consumidor"] == pytest.approx(0.4) and t.loc["A", "chi_previsto_por_km"] == pytest.approx(4.0)
    # o risco social total é 20: o alimentador de maior risco (10%) tem 11, e os dois de maior risco (20%), 12
    assert t.loc["A", "top10pct_do_risco_social"] == pytest.approx(0.55)
    assert t.loc["A", "top20pct_do_risco_social"] == pytest.approx(0.60)
    assert t.loc["B", "alimentadores"] == 1 and t.loc["B", "risco_social_rs_por_consumidor"] == pytest.approx(3 / 50)


def test_perfil_do_expurgo_nos_dois_layouts(tmp_path):
    leg = pd.DataFrame({
        "SigAgente": ["EMS   ", "EMS   ", "EMS   ", "EMT   "], "IdeMotivoInterrupcao": [0, 0, 3, 0],
        "NumUnidadeConsumidora": [10, 20, 100, 999], "NumNivelTensao": [220, 13800, 13800, 13800],
        "DscFatoGeradorInterrupcao": ["INTERNA-NAO PROGRAMADA-PROPRIAS DO SISTEMA-X"] * 2
        + ["INTERNA-NAO PROGRAMADA-MEIO AMBIENTE-Y", "INTERNA-NAO PROGRAMADA-PROPRIAS DO SISTEMA-X"],
        "DatInicioInterrupcao": [datetime(2025, 1, 1, 0)] * 4, "DatFimInterrupcao": [datetime(2025, 1, 1, 2)] * 4})
    leg.to_parquet(tmp_path / "interrupcoes-energia-eletrica-2025.parquet", index=False)
    novo = pd.DataFrame({
        "SigAgente": ["EMS"], "DscMotivoExpurgo": ["Interrupção em Situação de Emergência (ISE) por meio de CHI"],
        "QtdConsumidoresAfetados": [90], "NumNivelTensao": [13800], "DscFatoGeradorCausa": ["Meio Ambiente"],
        "DscFatoGeradorOrigem": ["Interna"], "DatInicioInterrupcao": [datetime(2026, 1, 1, 0)],
        "DatFimInterrupcao": [datetime(2026, 1, 1, 4)]})
    novo.to_parquet(tmp_path / "interrupcoes-energia-eletrica-2026.parquet", index=False)
    t = D.perfil_expurgo(tmp_path, "EMS", 2025, 2026).set_index(["layout", "codigo"])
    c0 = t.loc[("legado 2025", "0")]
    assert (c0.registros, c0.uc_medio, c0.pct_bt, c0.causa_modal, c0.duracao_media_h) == (2, 15.0, 50.0, "PROPRIAS DO SISTEMA", 2.0)
    assert t.loc[("legado 2025", "3"), "causa_modal"] == "MEIO AMBIENTE"
    ise = t.loc[("novo 2026", "Interrupção em Situação de Emergência (ISE) por meio de CHI")]
    assert (ise.registros, ise.uc_medio, ise.causa_modal, ise.duracao_media_h) == (1, 90.0, "MEIO AMBIENTE", 4.0)
    cods = D.codigos_expurgo_por_ano(tmp_path, "EMS", [2025]).set_index("codigo").registros
    assert cods.to_dict() == {0: 2, 3: 1}
