"""Extração e diagnóstico da BDGD com códigos de alimentador alfanuméricos (Mato Grosso do Sul).

Em MT o ``CTMT.NOME`` tem 6 dígitos (``013014``); em MS tem 5 caracteres alfanuméricos (``AJO51``). O extrator
completa à esquerda com zeros até 6 caracteres nos dois lados do vínculo (a BDGD e as interrupções), então ``AJO51``
vira ``0AJO51`` em todo lugar. A BDGD sintética vem de ``conftest.py``; os valores esperados foram contados à mão.
"""
import pytest

from gridrisk.ingest import bdgd
from gridrisk.ingest import diagnostico_bdgd as D

BBOX_MS = (-58.17, -24.07, -50.92, -17.17)


def test_codigos_alfanumericos_viram_seis_caracteres_com_zero_a_esquerda(gdb_ms):
    f = bdgd.feeder_features(gdb_ms, 2025).set_index("alimentador_cod_id")
    assert f.alimentador_nome.to_dict() == {"9001": "0AJO51", "9002": "0MIM01"}


def test_atributos_de_rede_e_protecao_de_ms(gdb_ms):
    f = bdgd.feeder_features(gdb_ms, 2025).set_index("alimentador_nome")
    a = f.loc["0AJO51"]
    assert a.rede_mt_km == pytest.approx(1.5)                       # 1000 m + 500 m
    assert a.frac_rural == pytest.approx(1000 / 1500)               # ARE_LOC == NU
    assert a.frac_cabo_nu == pytest.approx(1000 / 1500)             # ISO_FAS_1 == 12 só no condutor C1
    assert a.frac_compacta == pytest.approx(500 / 1500)             # GEOM_CAB == 1 só no condutor C2
    assert (a.n_religadores, a.n_chaves_fusiveis, a.n_chaves_telecomandadas) == (1, 1, 1)  # TIP_UNID 32 / 22; TLCD 1
    assert a.n_uc == 2 and a.n_gd == 1 and a.frac_trafos_sem_data == pytest.approx(0.5)    # 01/01/1980 = desconhecida
    assert f.loc["0MIM01"].frac_trafos_mrt == pytest.approx(1.0)


def test_mapa_de_codigos_liga_o_codigo_operacional_ao_circuito(gdb_ms):
    mp = bdgd.feeder_map(gdb_ms).set_index("alimentador_nome").alimentador_cod_id
    # AJO52 é um segundo código operacional do circuito 9001, que se chama AJO51
    assert mp.to_dict() == {"0AJO51": "9001", "0MIM01": "9002", "0AJO52": "9001"}


def test_diagnostico_do_formato_dos_codigos_e_do_vinculo(gdb_ms):
    d = D.diagnosticar(gdb_ms, 2025, BBOX_MS)
    assert d["camadas_chave_ausentes"] == []
    assert d["ctmt"]["linhas"] == 2 and d["ctmt"]["cod_id_distintos"] == 2
    assert d["ctmt"]["nome"]["pct_so_digitos"] == 0.0 and d["ctmt"]["nome"]["comprimentos"] == {"5": 2}
    assert d["ctmt"]["nome_com_zfill6"]["comprimentos"] == {"6": 2}
    assert d["ssdmt"]["ct_cod_op"]["distintos"] == 3 and d["ssdmt"]["pct_ctmt_existe_em_ctmt"] == 100.0
    assert d["ssdmt"]["segcon_cod_id_duplicados"] == 0 and d["ssdmt"]["km"] == pytest.approx(3.5)
    assert d["ssdmt"]["pct_km_cabo_nu"] == pytest.approx(100 * 3000 / 3500, abs=1e-3)
    assert d["feeder_map"] == {"codigos": 3, "pct_codigo_igual_ao_nome_ctmt": pytest.approx(66.667, abs=1e-3),
                               "ctmt_distintos": 2}


def test_diagnostico_do_dominio_de_tip_unid(gdb_ms):
    u = D.diagnosticar(gdb_ms, 2025, BBOX_MS)["unsemt"]
    assert u["tip_unid"] == {"32": 2, "22": 1, "19": 1}
    assert (u["n_religador_32"], u["n_chave_fusivel_22_27"], u["n_seccionalizador_35_36"]) == (2, 1, 0)
    assert u["pct_codigos_no_mapeamento"] == 75.0                   # o código 19 não está no mapeamento
    assert u["perfil_por_tip_unid"]["32"]["pct_telecomandado"] == 50.0
    assert u["pac_1_comprimentos"] == {"19": 3, "9": 1}


def test_diagnostico_de_dat_imo_e_dat_con(gdb_ms):
    d = D.diagnosticar(gdb_ms, 2025, BBOX_MS)
    imo = d["datas"]["EQSE"]["DAT_IMO"]
    assert imo["n"] == 4 and imo["pct_preenchido"] == 75.0 and imo["ano_min"] == 2000 and imo["ano_max"] == 2015
    con = d["datas"]["UNTRMT"]["DAT_CON"]
    assert con["pct_01_01_1980"] == pytest.approx(33.333, abs=1e-3)
    assert con["pct_depois_do_snapshot"] == 0.0
    assert con["pct_ano_mais_frequente"] == pytest.approx(33.333, abs=1e-3)  # cada ano aparece uma vez entre 3 trafos
    # EQSE x UNSEMT: S9 não existe em UNSEMT
    assert d["eqse"]["pct_un_se_existe_em_unsemt"] == 75.0
    assert d["eqse"]["por_tip_unid"] == {}  # só mostra TIP_UNID com 100 equipamentos ou mais


def test_diagnostico_de_coordenadas(gdb_ms):
    c = D.diagnosticar(gdb_ms, 2025, BBOX_MS)["coordenadas"]
    assert c["crs"] == "EPSG:4674" and c["pct_dentro_do_estado_bbox"] == 100.0 and c["pct_sem_geometria"] == 0.0
    fora = D.diagnosticar(gdb_ms, 2025, (-62.0, -18.0, -50.0, -9.0))["coordenadas"]  # caixa de MT
    assert fora["pct_dentro_do_estado_bbox"] == 0.0
