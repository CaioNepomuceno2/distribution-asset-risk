"""``scripts/comparativo_mt_ms.py`` com arquivos sintéticos minúsculos, no formato dos publicados.

Nada aqui depende dos repositórios irmãos nem dos resultados reais: ``_ambiente`` monta, numa pasta temporária, os
arquivos que o script lê (os mesmos nomes e colunas dos publicados, com poucos números redondos). Os valores esperados
foram calculados à mão, no comentário de cada bloco.

Cenário (cada distribuidora tem 10 alimentadores iguais, menos no risco):

* Energisa MT: 4.000 consumidores, 400 km; 10 falhas por ano em cada um dos 7 modos (70 por ano); CHI de 4.000 por modo
  (28.000 por ano); metade do CHI é regulatória.
* Energisa MS: 2.000 consumidores, 50 km; 20 falhas por ano por modo (140); CHI de 1.000 por modo (7.000); um quarto do
  CHI é regulatório.
"""
import importlib.util
import json
import re
import subprocess
import sys

import pandas as pd
import pytest

from gridrisk.config import ROOT

SCRIPT = ROOT / "scripts" / "comparativo_mt_ms.py"
MODOS = ["EQUIPAMENTO", "DESCARGA_ATMOSFERICA", "VEGETACAO", "VENTO", "ANIMAIS", "TERCEIROS", "OUTRAS"]
CAUSAL = re.compile(r"\b(porque|por causa|devido|explica|explicam|graças|deve-se|resulta de|em razão de)\b", re.IGNORECASE)
ND = "não disponível"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("comparativo_mt_ms_teste", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


# --------------------------------------------------------------------------------------------- arquivos sintéticos
def _csv(caminho, df):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(caminho, index=False)


def _json(caminho, obj):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(obj), encoding="utf-8")


def _risco(n_uc, km, social):
    return pd.DataFrame({
        "alimentador": [f"A{i}" for i in range(10)], "n_uc": [n_uc] * 10, "rede_mt_km": [km] * 10,
        "risco_rs_social": social, "risco_rs_compensacao": social, "dec_contribuicao_h": [0.5] * 10})


def _fronteira(vpl_otimo, vpl_trad, investido, vpl_trad_10=None):
    linhas = []
    for orc, trad in ((10e6, vpl_trad if vpl_trad_10 is None else vpl_trad_10), (20e6, vpl_trad)):
        for met, vpl, inv in (("otimo", vpl_otimo, investido), ("guloso", vpl_otimo * 0.9, investido),
                              ("tradicional", trad, orc)):
            linhas.append({"orcamento": orc, "metodo": met, "investido": inv, "chi_evitado_ano": 1.0,
                           "chi_reg_evitado_ano": 1.0, "vpl": vpl, "n_alimentadores": 5, "dec_evitado_h": 0.1})
    return pd.DataFrame(linhas)


def _se(n, uc, um_trafo, uc_um, sem_transf, n1, util80, eventos, frac, extra=None):
    d = {"n_ses": n, "n_uc": uc, "ses_um_trafo": um_trafo, "uc_em_ses_um_trafo": uc_um, "frac_uc_sem_transferencia": sem_transf,
         "ses_sem_folga_n1_com_2mais_trafos": n1, "ses_utilizacao_acima_80pct": util80, "eventos_se_ano_total": eventos,
         "frac_chi_mt_em_eventos_se": frac}
    d.update(extra or {})
    return d


def _recl(inventario, km, falhas_100km):
    return {"inventario": {"religadores_no_cadastro": inventario, "religadores_de_linha_com_clientes": inventario - 10,
                           "religadores_de_saida": 5, "religadores_telecomandados_cadastro": inventario // 2,
                           "religadores_normalmente_abertos": 3},
            "validacao_modelo": {"spearman_ci_modelo_vs_observado": 0.8, "razao_ci_observado_sobre_modelo_mediana": 0.5},
            "zonas_religador_linha": {"clientes_zona_mediana": 100.0, "frac_com_menos_de_50_clientes_na_zona": 0.25},
            "alimentadores_sem_religador_de_linha": {"n": 2},
            "zonas_criticas": {"top10pct_frac_chi_esperado": 0.5, "top10pct_frac_saida": 0.4},
            "rede": {"km_mt": km, "falhas_mt_por_100km_ano": falhas_100km}}


def _topo(uc24, uc25, alim):
    return {"2024": {"uc_total": uc24, "alimentadores": alim, "frac_uc_alcancadas": 0.99},
            "2025": {"uc_total": uc25, "alimentadores": alim, "frac_uc_alcancadas": 0.999}}


def _ambiente(tmp_path, omitir=()):
    """Cria ``raiz`` (distribution-asset-risk) e ``irmaos`` (os outros quatro) e devolve os dois caminhos.

    ``omitir``: caminhos relativos (a ``raiz`` ou a ``irmaos``) que não devem existir.
    """
    raiz, irmaos = tmp_path / "distribution-asset-risk", tmp_path / "irmaos"
    diag = raiz / "reports" / "ems" / "diagnostico"
    social_mt = [100, 50] + [10] * 8       # total 230; 10% = 1 alimentador (100), 20% = 2 (150)
    social_ms = [60, 40] + [10] * 8        # total 180; 10% = 60, 20% = 100
    for d, pasta, risco in (("mt", "", _risco(400, 40, social_mt)), ("ms", "ems", _risco(200, 5, social_ms))):
        (raiz / "app" / "data" / pasta).mkdir(parents=True, exist_ok=True)
        risco.to_parquet(raiz / "app" / "data" / pasta / "risco_alimentador.parquet")
        rep = raiz / "reports" / pasta
        _json(rep / "resumo_decisao.json", {"n_alimentadores": 10, "frac_risco_social_top10pct_alimentadores":
                                            100 / 230 if d == "mt" else 60 / 180,
                                            "frac_risco_social_top20pct_alimentadores": 150 / 230 if d == "mt" else 100 / 180})
        _json(rep / "resultados.json", {"n_uc_total": 4000 if d == "mt" else 2000,
                                        "check_2026": {"spearman_parcial_jan_jul": 0.8 if d == "mt" else 0.6}})
        _csv(rep / "frac_chi_regulatorio_modo.csv", pd.DataFrame({"modo": MODOS, "frac_chi_regulatorio": [0.5 if d == "mt" else 0.25] * 7}))
        _csv(rep / "validacao_dec_fec.csv", pd.DataFrame({
            "ano": [2021, 2025, 2026],
            "DEC_oficial": [10.0, 10.0, 5.0] if d == "mt" else [10.0, 8.0, 4.0],
            "DEC_calculado": [10.0, 10.05, 5.2] if d == "mt" else [9.0, 8.0, 4.0],
            "FEC_oficial": [10.0, 10.0, 5.0] if d == "mt" else [10.0, 8.0, 4.0],
            "FEC_calculado": [10.0, 10.0, 5.0] if d == "mt" else [9.0, 8.0, 4.0],
            "corr_mensal_conjunto_DEC": [1.0] * 3 if d == "mt" else [0.9] * 3}))
        _csv(rep / "fronteira_social.csv", _fronteira(100e6, 50e6, 20e6) if d == "mt" else _fronteira(60e6, 40e6, 12e6))
        _csv(rep / "fronteira_compensacao.csv", _fronteira(10e6, 5e6, 8e6, vpl_trad_10=0.5e6) if d == "mt"
             else _fronteira(1e6, -1e6, 1e6))
    _csv(diag / "comparacao_descritiva.csv", pd.DataFrame({
        "distribuidora": ["EMT", "EMS"], "consumidores": [4000, 2000], "rede_mt_km": [400, 50], "consumidores_por_km": [10, 40],
        "risco_social_rs_por_consumidor": [230 / 4000, 180 / 2000], "risco_compensacao_rs_por_consumidor": [230 / 4000, 180 / 2000],
        "dec_previsto_falhas_mt_h": [5.0, 5.0]}))
    _csv(diag / "circuitos_vazios.csv", pd.DataFrame({
        "distribuidora": ["EMT", "EMT", "EMS", "EMS"], "ano": [2025, 2019, 2025, 2019], "circuitos": [10, 9, 10, 20],
        "sem_rede_e_sem_uc": [1, 0, 0, 5], "sem_uc": [2, 0, 1, 6], "rede_menor_que_1km": [0, 0, 0, 0]}))
    vinc = [(s, a, "todos", "falhas", n, n, 100.0, c, c, 100.0)
            for s, base in (("EMT", 70), ("EMS", 140)) for a, n, c in ((2024, base, base * 400.0), (2025, base, base * 400.0),
                                                                       (2026, base // 2, base * 200.0))]
    _csv(diag / "vinculo_circuitos_comparacao.csv", pd.DataFrame(vinc, columns=[
        "distribuidora", "ano", "corte", "escopo", "eventos", "eventos_ligados", "pct_eventos", "chi", "chi_ligado", "pct_chi"]))
    meses = [("EMT", 2026, m, 100) for m in range(1, 8)] + [("EMS", 2026, m, 100) for m in (1, 2, 4, 5, 6, 7)]
    _csv(diag / "interrupcoes_por_mes.csv", pd.DataFrame(meses, columns=["distribuidora", "ano", "mes", "registros"]))
    _csv(diag / "expurgo_codigos_por_ano.csv", pd.DataFrame({
        "distribuidora": ["EMT", "EMT", "EMS"], "ano": [2024, 2025, 2025], "codigo": [1, 1, 1], "registros": [10, 20, 5]}))
    _csv(diag / "elegibilidade_catalogo.csv", pd.DataFrame({
        "intervencao": ["religador", "automacao"], "EMS_elegiveis": [3, 2], "EMS_alimentadores": [10, 10], "EMS_pct": [30.0, 20.0],
        "EMT_elegiveis": [4, 5], "EMT_alimentadores": [10, 10], "EMT_pct": [40.0, 50.0]}))
    _csv(diag / "chi_por_modo.csv", pd.DataFrame({
        "modo": ["TOTAL", "VENTO"], "chi": [7000.0, 1000.0], "chi_regulatorio": [1750.0, 250.0], "pct_do_total": [100.0, 14.3],
        "pct_expurgado": [75.0, 75.0]}))
    _csv(diag / "compensacoes_por_ano.csv", pd.DataFrame({
        "ano": [2022, 2023, 2024, 2025, 2026], "conjuntos": [5] * 5, "pg_reais": [1e6, 2e6, 3e6, 2e6, 1e6],
        "pg_milhoes": [1, 2, 3, 2, 1]}))
    _csv(diag / "falhas_por_expurgo.csv", pd.DataFrame({
        "ano": [2025, 2025], "expurgo": ["NAO HOUVE EXPURGO", "DIA CRITICO"], "registros": [10, 5], "chi": [2000.0, 6000.0],
        "pct_registros": [66.0, 33.0], "pct_chi": [25.0, 75.0]}))
    _csv(diag / "dec_correlacao.csv", pd.DataFrame({
        "conjunto": ["todos os meses", "sem os meses com razão < 0.9"], "meses_excluidos": [None, "2021-10, 2026-03"],
        "linhas": [100, 90], "corr_dec": [0.9, 0.99]}))
    # repositórios irmãos
    for d, pasta in (("mt", ""), ("ms", "ems")):
        n, km, f100 = (70.0, 400.0, 17.5) if d == "mt" else (140.0, 50.0, 280.0)
        modo = pd.DataFrame({"modo": MODOS, "n_falhas": [n / 7] * 7, "chi": [4000.0 if d == "mt" else 1000.0] * 7})
        modo["falhas_por_100km_ano"] = modo.n_falhas / km * 100
        rec = irmaos / "recloser-performance" / "reports" / pasta
        _csv(rec / "falhas_por_modo.csv", modo)
        _json(rec / "diagnostico.json", _recl(200 if d == "mt" else 100, km, f100))
        _json(rec / "qualidade_topologia.json", _topo(4100 if d == "mt" else 2100, 4000 if d == "mt" else 2000, 10))
        extra = {"sensibilidades_da_configuracao": {"estagios_cadastrados": {"ses_sem_folga_n1_com_2mais_trafos": 3},
                                                    "vinculo_regra_mt": {"ses": 5}}} if d == "ms" else None
        _json(irmaos / "substation-health-index" / "reports" / pasta / "resumo_2025.json",
              _se(8 if d == "mt" else 6, 4000, 4, 800, 0.5, 6 if d == "mt" else 9, 1, 12.0, 0.03, extra))
        auto = irmaos / "automation-impact" / "reports" / pasta
        _json(auto / "valor.json", {"uc_total": 4100 if d == "mt" else 2100, "religadores_2025": 150, "efeito_chi_pct": -16.5,
                                    "eventos": 100 if d == "mt" else 70, **({"origem_efeito": "transportado de MT"} if d == "ms" else {})})
        _csv(auto / "subestacoes.csv", pd.DataFrame({"subestacao": range(9 if d == "mt" else 7)}))
        sw = irmaos / "switchgear-survival" / "reports" / pasta
        ok = d == "mt"
        _csv(sw / "qualidade_classes.csv", pd.DataFrame({
            "classe": ["religador", "disjuntor", "chave", "regulador"], "frota_2025": [190, 20, 1000, 50],
            "confiavel": [ok, ok, False, False]}))
        _csv(sw / "vida_weibull.csv", pd.DataFrame({"classe": ["religador", "disjuntor"], "cenario": ["principal"] * 2,
                                                     "mediana": [28.0, 39.0]}))
    auto_diag = irmaos / "automation-impact" / "reports" / "ems"
    _json(auto_diag / "regra_decisao.json", {"n_eventos": 72, "n_controles": 87, "min_eventos": 60, "min_controles": 100,
                                              "origem_efeito": "transportado de MT"})
    _json(auto_diag / "diagnostico" / "mt_contagens_referencia.json", {"n_eventos": 116, "n_controles": 209})
    _csv(auto_diag / "diagnostico" / "transicoes_religadores.csv", pd.DataFrame({
        "religadores_ganhos": [10.0, 20.0], "ganho_liquido": [5.0, -2.0]}))
    _csv(auto_diag / "diagnostico" / "religadores_por_snapshot.csv", pd.DataFrame({
        "ano_snapshot": [2024, 2025], "religadores": [100, 150], "religadores_telecomandados": [40, 120]}))
    _csv(irmaos / "switchgear-survival" / "reports" / "ems" / "diagnostico" / "tuc_x_tensao.csv", pd.DataFrame({
        "camada": ["EQSE"] * 3, "ano": [2025] * 3, "tuc": ["210", "210", "345"], "gru_ten": ["AT", "MT", "MT"],
        "equipamentos": [30, 10, 100]}))
    for rel in omitir:
        for base in (raiz, irmaos):
            if (base / rel).exists():
                (base / rel).unlink()
    return raiz, irmaos


def _readme(raiz, com_marcas=True):
    (raiz / "README.md").write_text("# Teste\n\nantes\n\n" + ("<!-- comparativo-mt-ms:inicio -->\nvelho\n<!-- comparativo-mt-ms:fim -->\n\n"
                                                           if com_marcas else "") + "depois\n", encoding="utf-8")


def _valor(res, d, chave):
    return res.P[d][chave]


# --------------------------------------------------------------------------------------------- teste de fumaça
def test_fumaca_gera_saidas_e_numeros_esperados(mod, tmp_path):
    raiz, irmaos = _ambiente(tmp_path)
    saida = raiz / "reports" / "comparativo_mt_ms"
    res = mod.gerar(raiz, irmaos, saida)
    assert res.faltas == [] and res.avisos == []
    for nome in ("metricas", "falhas_por_modo", "falhas_por_ano", "chi_por_modo", "dec_fec_oficial", "compensacoes_por_ano",
                 "concentracao_risco", "carteira_por_orcamento", "elegibilidade_catalogo", "nao_comparavel", "verificacoes",
                 "fontes"):
        assert (saida / f"{nome}.csv").is_file(), nome
    assert len(res.figuras) == 4 and all((saida / "figures" / f).is_file() for f in res.figuras)
    # (a) tamanho: MT 4.000 consumidores e 400 km; MS 2.000 e 50 km
    assert (_valor(res, "mt", "uc"), _valor(res, "mt", "km"), _valor(res, "mt", "uc_por_km")) == (4000, 400, 10)
    assert (_valor(res, "ms", "uc"), _valor(res, "ms", "km"), _valor(res, "ms", "uc_por_km")) == (2000, 50, 40)
    assert _valor(res, "mt", "vazios") == 1 and _valor(res, "ms", "vazios") == 0
    # (b) falhas por 100 km: 70 / 400 * 100 = 17,5 e 140 / 50 * 100 = 280; por mil consumidores: 17,5 e 70
    assert _valor(res, "mt", "falhas_100km") == pytest.approx(17.5) and _valor(res, "ms", "falhas_100km") == pytest.approx(280)
    assert _valor(res, "ms", "falhas_1000uc") == pytest.approx(70)
    assert _valor(res, "mt", "falhas_pct:VENTO") == pytest.approx(100 / 7)
    # (c) CHI por consumidor: 28.000 / 4.000 = 7 h e 7.000 / 2.000 = 3,5 h; regulatório 3,5 h e 0,875 h; expurgo 50% e 75%
    assert _valor(res, "mt", "chi_uc") == pytest.approx(7) and _valor(res, "ms", "chi_uc") == pytest.approx(3.5)
    assert _valor(res, "mt", "chi_reg_uc") == pytest.approx(3.5) and _valor(res, "ms", "chi_reg_uc") == pytest.approx(0.875)
    assert _valor(res, "mt", "frac_exp") == pytest.approx(50) and _valor(res, "ms", "frac_exp") == pytest.approx(75)
    assert _valor(res, "ms", "chi_por_registro") == pytest.approx(7000 / 140)
    # (d) DEC: MT 2026 difere 4% (não bate); MS 2021 difere 10% (não bate); 2025 bate nos dois
    assert _valor(res, "mt", "anos_nao_batem") == "2026" and _valor(res, "ms", "anos_nao_batem") == "2021"
    assert _valor(res, "mt", "dec_of") == 10 and _valor(res, "ms", "dec_of") == 8
    # (e) compensações pagas: só MS; média de 2022 a 2025 = 2 mi; por consumidor = 2.000.000 / 2.000 = 1.000
    assert _valor(res, "mt", "comp_paga_uc") is None and _valor(res, "ms", "comp_paga_uc") == pytest.approx(1000)
    # (f) concentração: 10% de 10 alimentadores = 1 (100 de 230) e 20% = 2 (150 de 230)
    assert _valor(res, "mt", "top10_social") == pytest.approx(100 * 100 / 230)
    assert _valor(res, "mt", "top20_social") == pytest.approx(100 * 150 / 230)
    assert _valor(res, "ms", "top10_social") == pytest.approx(100 * 60 / 180) and _valor(res, "ms", "k20_social") == 2
    # (g) carteira com R$ 20 mi: 100 / 50 = 2,0 (MT) e 60 / 40 = 1,5 (MS); a ótima de MS investe só R$ 12 mi
    assert _valor(res, "mt", "razao_carteira") == pytest.approx(2.0) and _valor(res, "ms", "razao_carteira") == pytest.approx(1.5)
    assert _valor(res, "ms", "investido_otimo") == 12e6
    # (h) subestações e religadores
    assert _valor(res, "mt", "ses") == 8 and _valor(res, "ms", "ses_n1_ventilacao") == 3 and _valor(res, "ms", "ses_n1") == 9
    assert _valor(res, "ms", "ses_vinculo_mt") == 5 and _valor(res, "mt", "ses_por_1000km") == pytest.approx(8 / 400 * 1000)
    assert _valor(res, "mt", "recl_linha") == 190 and _valor(res, "ms", "uc_ligadas_saida") == pytest.approx(99.9)
    # (i) evidências de "não dá para comparar"
    assert _valor(res, "ms", "meses_faltando") == "março" and _valor(res, "mt", "meses_faltando") == "nenhum"
    assert _valor(res, "ms", "tuc210_at_pct") == pytest.approx(75) and _valor(res, "ms", "recl_ganhos_brutos") == 30
    assert _valor(res, "ms", "classes_aprovadas") == 0 and _valor(res, "mt", "classes_aprovadas") == 2
    assert _valor(res, "ms", "vida_recl") is None and _valor(res, "mt", "vida_recl") == 28
    # a tabela mestra traz definição, numerador, denominador e arquivo de origem de cada métrica
    m = pd.read_csv(saida / "metricas.csv")
    assert {"definicao", "numerador", "denominador", "fonte_mt", "fonte_ms", "definicao_pode_diferir"} <= set(m.columns)
    assert m["definicao"].notna().all() and m["fonte_ms"].str.contains("/").all()
    linha = m[m["id"] == "falhas_100km"].iloc[0]
    assert "recloser-performance/reports/ems/falhas_por_modo.csv" in linha["fonte_ms"]
    assert linha["razao_ms_mt"] == pytest.approx(16.0)


def test_verificacoes_e_fontes(mod, tmp_path):
    raiz, irmaos = _ambiente(tmp_path)
    res = mod.gerar(raiz, irmaos, raiz / "reports" / "comparativo_mt_ms", com_figuras=False)
    v = res.verificacoes.set_index("verificacao")
    assert v.loc["consumidores_mt", "passou"] and v.loc["top10_ms", "passou"] and v.loc["chi_reg_ms", "passou"]
    assert v.loc["falhas_100km_mt", "passou"]                        # 17,5 contra 17,5 publicado
    f = res.fontes
    assert f["existe"].all() and f["sha256"].str.len().eq(64).all() and len(f) > 30


def test_nao_escreve_fora_da_pasta_de_saida(mod, tmp_path):
    raiz, irmaos = _ambiente(tmp_path)
    antes = {p for p in tmp_path.rglob("*") if p.is_file()}
    saida = raiz / "reports" / "comparativo_mt_ms"
    mod.gerar(raiz, irmaos, saida, com_figuras=False)
    novos = {p for p in tmp_path.rglob("*") if p.is_file()} - antes
    assert novos and all(saida in p.parents for p in novos)


def test_script_nao_e_do_pipeline(mod):
    """Comparativo só lê arquivos publicados: não importa o pacote do pipeline nem aceita ``--config``."""
    texto = SCRIPT.read_text(encoding="utf-8")
    assert "gridrisk" not in texto and "--config" not in texto and "duckdb" not in texto
    assert "COMPARATIVOS" in (ROOT / "tests" / "test_config.py").read_text(encoding="utf-8")


def test_so_le_pastas_publicadas(mod):
    permitidas = ("reports/", "app/data/")
    for a in mod.ARQUIVOS:
        for d in (("mt", "ms") if a.tipo == "dist" else (None,)):
            assert a.rel(d).startswith(permitidas), a.rel(d)
        assert a.repo in (mod.PROPRIO, mod.RECL, mod.SHI, mod.AUTO, mod.SWITCH)
    assert not any(a.rel("mt").startswith(("docs/", "data/")) for a in mod.ARQUIVOS)


# --------------------------------------------------------------------------------------------- "não disponível"
def test_arquivo_ausente_so_derruba_as_proprias_metricas(mod, tmp_path):
    raiz, irmaos = _ambiente(tmp_path, omitir=["recloser-performance/reports/ems/falhas_por_modo.csv"])
    # omitir é relativo a raiz ou a irmaos; o arquivo está em irmaos/recloser-performance/reports/ems/
    res = mod.gerar(raiz, irmaos, raiz / "reports" / "comparativo_mt_ms", com_figuras=False)
    assert "recloser-performance/reports/ems/falhas_por_modo.csv" in res.faltas
    assert _valor(res, "ms", "falhas_100km") is None and _valor(res, "ms", "chi_uc") is None
    assert _valor(res, "mt", "falhas_100km") == pytest.approx(17.5)           # MT segue
    assert _valor(res, "ms", "uc_por_km") == 40 and _valor(res, "ms", "top10_social") is not None
    m = pd.read_csv(raiz / "reports" / "comparativo_mt_ms" / "metricas.csv")
    assert m[m["id"] == "falhas_100km"].iloc[0]["energisa_ms"] == ND
    t = pd.read_csv(raiz / "reports" / "comparativo_mt_ms" / "falhas_por_modo.csv")
    assert (t["falhas_100km_ms"] == ND).all() and (t["falhas_100km_mt"] != ND).all()
    doc = mod.renderizar_doc(res)
    assert ND in doc and "recloser-performance/reports/ems/falhas_por_modo.csv" in doc


def test_repositorios_irmaos_ausentes(mod, tmp_path):
    raiz, _irmaos = _ambiente(tmp_path)
    vazio = tmp_path / "sem_irmaos"
    vazio.mkdir()
    res = mod.gerar(raiz, vazio, raiz / "reports" / "comparativo_mt_ms", com_figuras=False)
    assert _valor(res, "mt", "uc") == 4000 and _valor(res, "ms", "dec_of") == 8        # os arquivos da raiz seguem
    for chave in ("falhas_100km", "chi_uc", "ses", "recl_linha", "efeito_religador", "classes_total"):
        assert _valor(res, "mt", chave) is None and _valor(res, "ms", chave) is None, chave
    assert len(res.faltas) > 10
    m = pd.read_csv(raiz / "reports" / "comparativo_mt_ms" / "metricas.csv")
    assert (m[m["bloco"] == "h"]["energisa_ms"] == ND).any()
    doc = mod.renderizar_doc(res)
    assert doc.count(ND) > 20 and "Arquivos de origem não encontrados" in doc


def test_raiz_sem_nenhum_arquivo_nao_quebra(mod, tmp_path):
    raiz = tmp_path / "vazia"
    raiz.mkdir()
    res = mod.gerar(raiz, tmp_path / "nada", raiz / "reports" / "comparativo_mt_ms")
    assert res.figuras == [] and len(res.faltas) == len(mod.ARQUIVOS) + sum(1 for a in mod.ARQUIVOS if a.tipo == "dist")
    assert all(v is None or isinstance(v, str) for v in res.P["mt"].values())
    assert ND in mod.renderizar_doc(res)
    assert ND in mod.renderizar_readme(res)


def test_coluna_ausente_vira_nd_com_aviso(mod, tmp_path):
    raiz, irmaos = _ambiente(tmp_path)
    p = raiz / "app" / "data" / "ems" / "risco_alimentador.parquet"
    pd.read_parquet(p).drop(columns=["n_uc"]).to_parquet(p)
    res = mod.gerar(raiz, irmaos, raiz / "reports" / "comparativo_mt_ms", com_figuras=False)
    assert _valor(res, "ms", "uc") is None and _valor(res, "ms", "uc_por_km") is None and _valor(res, "ms", "km") == 50
    assert any("Energisa MS / uc" in a for a in res.avisos)


def test_arquivo_ilegivel_vira_nd_com_aviso(mod, tmp_path):
    raiz, irmaos = _ambiente(tmp_path)
    (irmaos / "substation-health-index" / "reports" / "resumo_2025.json").write_text("{não é json", encoding="utf-8")
    res = mod.gerar(raiz, irmaos, raiz / "reports" / "comparativo_mt_ms", com_figuras=False)
    assert _valor(res, "mt", "ses") is None and _valor(res, "ms", "ses") == 6
    assert any("ilegível" in a for a in res.avisos)


def test_compensacao_de_mt_nunca_e_inventada(mod, tmp_path):
    raiz, irmaos = _ambiente(tmp_path)
    res = mod.gerar(raiz, irmaos, raiz / "reports" / "comparativo_mt_ms", com_figuras=False)
    t = pd.read_csv(raiz / "reports" / "comparativo_mt_ms" / "compensacoes_por_ano.csv")
    assert (t["pg_reais_mt"] == ND).all() and (t["pg_por_consumidor_mt"] == ND).all()
    assert _valor(res, "mt", "risco_comp_uc") == pytest.approx(230 / 4000)    # a previsão do modelo existe nas duas empresas


# --------------------------------------------------------------------------------------------- regras de conta
def test_anos_que_nao_batem_usa_a_tolerancia_relativa(mod):
    v = pd.DataFrame({"ano": [2020, 2021, 2022], "DEC_oficial": [10.0, 10.0, 10.0], "DEC_calculado": [10.0, 10.09, 10.2],
                      "FEC_oficial": [5.0, 5.0, 5.0], "FEC_calculado": [5.0, 5.0, 5.0]})
    assert mod.TOLERANCIA_DEC == 0.01
    assert mod.anos_que_nao_batem(v) == [2022]           # 0,9% bate; 2% não
    v.loc[0, "FEC_calculado"] = 4.9                       # o FEC também conta
    assert mod.anos_que_nao_batem(v) == [2020, 2022]


def test_concentracao_usa_round_do_resumo_decisao(mod):
    s = pd.Series([100, 50] + [10] * 8)
    assert mod.concentracao(s, 0.10) == (pytest.approx(100 / 230), 1)
    assert mod.concentracao(s, 0.20) == (pytest.approx(150 / 230), 2)
    s2 = pd.Series(range(1, 698))                          # 697 alimentadores: round(69,7) = 70 e round(139,4) = 139
    assert mod.concentracao(s2, 0.10)[1] == 70 and mod.concentracao(s2, 0.20)[1] == 139


def test_razao_da_carteira_so_com_vpl_tradicional_acima_do_minimo(mod):
    f = pd.DataFrame({"orcamento": [20e6] * 2, "metodo": ["otimo", "tradicional"], "vpl": [10e6, 0.5e6]})
    assert mod.razao_carteira(f, 20e6) is None            # R$ 0,5 mi de denominador: não se aplica
    f.loc[1, "vpl"] = -3e6
    assert mod.razao_carteira(f, 20e6) is None            # VPL negativo: não se aplica
    f.loc[1, "vpl"] = 4e6
    assert mod.razao_carteira(f, 20e6) == pytest.approx(2.5)


def test_tabela_da_carteira_mostra_investido_e_nao_se_aplica(mod, tmp_path):
    raiz, irmaos = _ambiente(tmp_path)
    res = mod.gerar(raiz, irmaos, raiz / "reports" / "comparativo_mt_ms", com_figuras=False)
    t = pd.read_csv(raiz / "reports" / "comparativo_mt_ms" / "carteira_por_orcamento.csv")
    caixa = t[t["visao"].str.startswith("caixa")].set_index("orcamento")
    assert float(caixa.loc[20e6, "razao_otimo_tradicional_mt"]) == pytest.approx(2.0)   # 10 / 5
    assert caixa.loc[10e6, "razao_otimo_tradicional_mt"] == "não se aplica"             # tradicional de R$ 0,5 mi
    assert (caixa["razao_otimo_tradicional_ms"] == "não se aplica").all()               # tradicional negativa
    social = t[t["visao"] == "social"].set_index("orcamento")
    assert social.loc[20e6, "investido_otimo_ms"] == 12e6 and social.loc[20e6, "investido_otimo_mt"] == 20e6
    assert res.P["ms"]["investido_max_otimo"] == 12e6


def test_regulatorio_so_com_fracao_em_todos_os_modos(mod):
    fm = pd.DataFrame({"modo": ["A", "B"], "chi": [10.0, 20.0]})
    fr = pd.DataFrame({"modo": ["A"], "frac_chi_regulatorio": [0.5]})
    with pytest.raises(ValueError, match="sem fração"):
        mod.chi_regulatorio_por_modo(fm, fr)
    fr = pd.DataFrame({"modo": ["A", "B"], "frac_chi_regulatorio": [0.5, 0.25]})
    assert mod.chi_regulatorio_por_modo(fm, fr).sum() == pytest.approx(10.0)


def test_faixas_de_meses(mod):
    assert mod.faixas_de_meses([1, 2, 4, 5, 6, 7]) == "janeiro a fevereiro e abril a julho"
    assert mod.faixas_de_meses([1, 2, 3, 4, 5, 6, 7]) == "janeiro a julho"
    assert mod.faixas_de_meses([3]) == "março" and mod.faixas_de_meses([]) == "nenhum"
    assert mod.faixas_de_meses([1, 3, 5]) == "janeiro, março e maio"


def test_formato_brasileiro_e_nd(mod):
    assert mod.fmt(1234567.891, 1) == "1.234.567,9" and mod.fmt(26.34, 1, True) == "26,3%"
    assert mod.fmt(None) == ND and mod.fmt(float("nan")) == ND and mod.fmt(-0.0001, 2) == "0,00"
    assert mod.div(1, 0) is None and mod.div(None, 2) is None and mod.div(10, 4, 100) == 250


# --------------------------------------------------------------------------------------------- documento e README
def test_documento_sem_linguagem_causal_e_com_nomes_das_empresas(mod, tmp_path):
    raiz, irmaos = _ambiente(tmp_path)
    res = mod.gerar(raiz, irmaos, raiz / "reports" / "comparativo_mt_ms", com_figuras=False)
    for texto in (mod.renderizar_doc(res), mod.renderizar_readme(res)):
        assert CAUSAL.search(texto) is None, CAUSAL.search(texto)
        assert "Energisa MT" in texto and "Energisa MS" in texto
    doc = mod.renderizar_doc(res)
    for secao in ("## 1. Tamanho", "## 2. Falhas", "## 3. CHI", "## 4. DEC", "## 5. Compensações", "## 6. Concentração",
                  "## 7. Carteira", "## 8. Subestações", "## 9. O que NÃO dá para comparar e por quê"):
        assert secao in doc, secao
    assert "denominador fixo" in doc and "não afirma causas" in doc
    assert "<details>" in doc and "Numerador" in doc and "Arquivo (Energisa MS)" in doc
    assert "Hipótese, não testada" in doc                    # o único "compatível com" vem marcado como hipótese
    # cada linha de "não dá para comparar" tem a evidência dos arquivos, não texto fixo vazio
    nc = res.T["nao_comparavel"]
    assert len(nc) >= 15 and nc["energisa_ms"].str.len().min() > 10
    assert "março" in doc and "transportado de MT" in doc


def test_atualizar_docs_recusa_quando_falta_origem(mod, tmp_path, capsys):
    raiz, irmaos = _ambiente(tmp_path, omitir=["automation-impact/reports/ems/valor.json"])
    _readme(raiz)
    (raiz / "docs").mkdir()
    (raiz / "docs" / "comparativo_mt_ms.md").write_text("doc publicado", encoding="utf-8")
    readme = (raiz / "README.md").read_text(encoding="utf-8")
    codigo = mod.main(["--raiz", str(raiz), "--irmaos", str(irmaos), "--atualizar-docs", "--sem-figuras"])
    assert codigo == 2
    assert (raiz / "docs" / "comparativo_mt_ms.md").read_text(encoding="utf-8") == "doc publicado"
    assert (raiz / "README.md").read_text(encoding="utf-8") == readme
    assert "NÃO regravei" in capsys.readouterr().err
    # sem a opção, só escreve em reports/comparativo_mt_ms/
    assert mod.main(["--raiz", str(raiz), "--irmaos", str(irmaos), "--sem-figuras"]) == 0
    assert (raiz / "docs" / "comparativo_mt_ms.md").read_text(encoding="utf-8") == "doc publicado"


def test_atualizar_docs_e_idempotente_e_so_troca_o_bloco(mod, tmp_path):
    raiz, irmaos = _ambiente(tmp_path)
    _readme(raiz)
    args = ["--raiz", str(raiz), "--irmaos", str(irmaos), "--atualizar-docs", "--sem-figuras"]
    assert mod.main(args) == 0
    doc1 = (raiz / "docs" / "comparativo_mt_ms.md").read_text(encoding="utf-8")
    rd1 = (raiz / "README.md").read_text(encoding="utf-8")
    assert rd1.startswith("# Teste\n\nantes\n\n") and rd1.endswith("depois\n") and "velho" not in rd1
    assert "## Comparativo MT × MS" in rd1 and "docs/comparativo_mt_ms.md" in rd1
    assert mod.main(args) == 0
    assert (raiz / "docs" / "comparativo_mt_ms.md").read_text(encoding="utf-8") == doc1
    assert (raiz / "README.md").read_text(encoding="utf-8") == rd1
    # os números do README e do documento são os mesmos do cálculo: 17,5 e 280,0 falhas por 100 km
    assert "17,5" in rd1 and "280,0" in rd1 and "17,5" in doc1


def test_readme_sem_marcas_nao_e_alterado(mod, tmp_path, capsys):
    raiz, irmaos = _ambiente(tmp_path)
    _readme(raiz, com_marcas=False)
    antes = (raiz / "README.md").read_text(encoding="utf-8")
    assert mod.main(["--raiz", str(raiz), "--irmaos", str(irmaos), "--atualizar-docs", "--sem-figuras"]) == 2
    assert (raiz / "README.md").read_text(encoding="utf-8") == antes and not (raiz / "docs").exists()
    assert "marcas" in capsys.readouterr().err


def test_script_roda_como_comando(tmp_path):
    raiz, irmaos = _ambiente(tmp_path)
    r = subprocess.run([sys.executable, str(SCRIPT), "--raiz", str(raiz), "--irmaos", str(irmaos), "--sem-figuras"],
                       capture_output=True, text=True, encoding="utf-8", check=False)
    assert r.returncode == 0, r.stderr
    assert "métricas" in r.stdout and (raiz / "reports" / "comparativo_mt_ms" / "metricas.csv").is_file()


def test_tabelas_do_resumo_e_do_readme_trazem_a_coluna_de_definicao(mod, tmp_path):
    raiz, irmaos = _ambiente(tmp_path)
    res = mod.gerar(raiz, irmaos, raiz / "reports" / "comparativo_mt_ms", com_figuras=False)
    for texto in (mod.renderizar_doc(res), mod.renderizar_readme(res)):
        assert "| Indicador (descritivo) | Energisa MT | Energisa MS | A diferença pode vir de definição? |" in texto
        linhas = {ln.split(" | ")[0].strip("| "): ln for ln in texto.splitlines() if ln.startswith("| ")}
        assert linhas["Fração do CHI das falhas que é expurgada"].rstrip().endswith("| Sim: regra de expurgo |")
        assert linhas["CHI das falhas por consumidor por ano, em horas"].rstrip().endswith("| Não |")
        assert linhas["DEC oficial de 2025, em horas"].rstrip().endswith("| Não |")
        assert "| Possível: contagem de registros da ANEEL |" in texto and "| Possível: nº de alimentadores |" in texto


def test_fontes_tem_o_mesmo_hash_com_fim_de_linha_lf_ou_crlf(mod, tmp_path):
    raiz, irmaos = _ambiente(tmp_path)
    saida = raiz / "reports" / "comparativo_mt_ms"
    lf = mod.gerar(raiz, irmaos, saida, com_figuras=False).fontes
    for p in list(raiz.rglob("*.csv")) + list(irmaos.rglob("*.json")):
        if saida in p.parents:
            continue
        p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))   # cópia de trabalho do Windows
    crlf = mod.gerar(raiz, irmaos, saida, com_figuras=False).fontes
    pd.testing.assert_frame_equal(lf, crlf)
    assert (saida / "fontes.csv").read_bytes().count(b"\r") == 0                    # as saídas sempre saem com LF
