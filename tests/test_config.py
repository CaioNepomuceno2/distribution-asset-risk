"""Configuração por distribuidora: o padrão é MT, exatamente como publicado, e MS só escreve em subpastas ems.

Estes testes protegem duas promessas: (1) quem não passa ``--config`` continua gravando nos mesmos caminhos de
antes da refatoração multi-distribuidora; (2) a configuração de MS nunca aponta para ``reports/`` nem para
``app/data/`` da raiz, onde estão os resultados publicados de MT.
"""
import re
import subprocess
import sys

import pytest

from gridrisk.config import CONFIG_PADRAO, ENV_CONFIG, ROOT, Config

SCRIPTS = ROOT / "scripts"
# os 8 snapshots de MT publicados (31/12 de cada ano)
SNAPSHOTS_EMT = {2018: "b6900e72a13946b6a2dc015aaf6d6ccd", 2019: "f15e84cabd564d31869c3af5d7855376",
                 2020: "bc9ef518725a416a99e08c99e2d979d1", 2021: "13d6ff510a4c4a7fac64f0e119beb245",
                 2022: "94a1b3fa56e3442fb8a2b3a8a3dc4df8", 2023: "f6095aa7e5c64119ab46e3efe46b77d5",
                 2024: "8fed7443387d4d04a361e7f4d1edea64", 2025: "02a120db1b5149709f8d371c21635adc"}
# idem para MS, a versão mais recente de cada ano
SNAPSHOTS_EMS = {2018: "5382c59d7cc7494a9a1f8cd865187457", 2019: "b83ad867a35b43189f41b68988f7f0b6",
                 2020: "fe56dce0714f4b6795d3b23130f5898a", 2021: "933af69c57dd41ea8f6048118b8d07e7",
                 2022: "ff5242147c86428e88971941a35c7cd1", 2023: "975f18dfdb0c479cb237893c5b296ca9",
                 2024: "b7fad4cd388845a08a01643599ec747b", 2025: "9a1ce360865f4358b31e9fb2d016aac9"}
FORA_DE_MS = {"c3585ae516f340b596617827d60da5ef",   # item avulso EMS_404_2022-10-31
              "b8c585ae35224ac8aa0648587ec61bcb"}   # snapshot de 2023 de 17/12/2024, que não é o mais recente


@pytest.fixture(autouse=True)
def sem_variavel_de_ambiente(monkeypatch):
    monkeypatch.delenv(ENV_CONFIG, raising=False)


def test_configuracao_padrao_resolve_para_os_caminhos_atuais_de_mt():
    cfg = Config.load()
    assert cfg.origem == ROOT / "configs" / "emt.yaml" == CONFIG_PADRAO
    assert (cfg.sigla, cfg.cod_aneel) == ("EMT", 405)
    assert cfg.raw == ROOT / "data" / "raw"
    assert cfg.interim == ROOT / "data" / "interim"
    assert cfg.processed == ROOT / "data" / "processed"
    assert cfg.reports == ROOT / "reports"
    assert cfg.figuras == ROOT / "reports" / "figures"
    assert cfg.app_data == ROOT / "app" / "data"
    assert cfg.malha_ibge == ROOT / "data" / "ref" / "mt_ibge.geojson"
    assert cfg.catalogo == ROOT / "configs" / "intervencoes.yaml"
    assert cfg.interrupcoes_parquet == ROOT / "data" / "interim" / "interrupcoes_emt.parquet"
    assert cfg.bdgd_snapshots == SNAPSHOTS_EMT
    assert cfg.anos_interrupcoes == list(range(2018, 2027))
    assert cfg.usar_clima is False and cfg.clima_uf == "MT"
    assert cfg.excluir_circuitos_vazios is False  # em MT o painel usa todos os circuitos
    assert (cfg.nome, cfg.nome_curto) == ("Energisa Mato Grosso", "Energisa MT")


def test_janelas_padrao_sao_as_publicadas_para_mt():
    cfg = Config.load()
    assert cfg.anos_teste == [2023, 2024, 2025]
    assert cfg.ano_previsao == 2026
    assert cfg.anos_compensacao == [2022, 2023, 2024, 2025]
    assert (cfg.ano_inicio_painel, cfg.ano_inicio_pesos_conjunto, cfg.ano_inicio_shap) == (2019, 2022, 2023)


def test_yaml_antigo_sem_as_chaves_novas_cai_no_padrao_de_mt(tmp_path):
    """Um emt.yaml de antes da refatoração (sem reports, janelas etc.) continua valendo, com os caminhos de MT."""
    yml = (ROOT / "configs" / "emt.yaml").read_text(encoding="utf-8")
    antigo = re.sub(r"(?m)^  (reports|app_data|malha_ibge|catalogo):.*\n", "", yml)
    antigo = re.sub(r"(?ms)^# Anos do backtest.*?^bdgd:", "bdgd:", antigo)
    assert "janelas" not in antigo and "reports:" not in antigo
    (tmp_path / "antigo.yaml").write_text(antigo, encoding="utf-8")
    cfg = Config.load(tmp_path / "antigo.yaml")
    ref = Config.load()
    for campo in ("reports", "app_data", "malha_ibge", "catalogo", "anos_teste", "ano_previsao",
                  "anos_compensacao", "ano_inicio_painel", "ano_inicio_pesos_conjunto", "ano_inicio_shap"):
        assert getattr(cfg, campo) == getattr(ref, campo), campo


def test_configuracao_de_ms_so_escreve_em_subpastas_ems():
    cfg = Config.load(ROOT / "configs" / "ems.yaml")
    assert (cfg.sigla, cfg.cod_aneel) == ("EMS", 404)
    assert (cfg.nome, cfg.nome_curto) == ("Energisa Mato Grosso do Sul", "Energisa MS")
    for pasta in (cfg.raw, cfg.interim, cfg.processed):
        assert pasta.is_relative_to(ROOT / "data" / "ems"), pasta
    assert cfg.reports == ROOT / "reports" / "ems"
    assert cfg.figuras == ROOT / "reports" / "ems" / "figures"
    assert cfg.app_data == ROOT / "app" / "data" / "ems"
    assert cfg.interrupcoes_parquet == ROOT / "data" / "ems" / "interim" / "interrupcoes_ems.parquet"
    assert cfg.malha_ibge == ROOT / "data" / "ref" / "ms_ibge.geojson" and cfg.malha_ibge.is_file()
    assert cfg.usar_clima is False
    assert cfg.clima_uf is None  # o clima do INMET não roda em MS
    assert cfg.excluir_circuitos_vazios is True  # 105 de 423 circuitos do snapshot de 2019 estão vazios
    assert cfg.eficacias_medidas is None  # as de MT não valem para MS


def test_snapshots_de_ms_sao_os_8_mais_recentes_e_nenhum_dos_excluidos():
    cfg = Config.load(ROOT / "configs" / "ems.yaml")
    assert cfg.bdgd_snapshots == SNAPSHOTS_EMS
    assert not FORA_DE_MS & set(cfg.bdgd_snapshots.values())
    assert not set(SNAPSHOTS_EMT.values()) & set(cfg.bdgd_snapshots.values())


def test_nenhuma_pasta_de_ms_coincide_com_as_de_mt():
    mt, ms = Config.load(), Config.load(ROOT / "configs" / "ems.yaml")
    for campo in ("raw", "interim", "processed", "reports", "app_data", "malha_ibge", "interrupcoes_parquet"):
        assert getattr(mt, campo) != getattr(ms, campo), campo


def test_variavel_de_ambiente_escolhe_a_configuracao(monkeypatch):
    monkeypatch.setenv(ENV_CONFIG, str(ROOT / "configs" / "ems.yaml"))
    assert Config.load().sigla == "EMS"
    monkeypatch.setenv(ENV_CONFIG, "configs/ems.yaml")  # relativo à raiz do repositório
    assert Config.load().sigla == "EMS"


def test_argumento_vence_a_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv(ENV_CONFIG, str(ROOT / "configs" / "ems.yaml"))
    assert Config.load(ROOT / "configs" / "emt.yaml").sigla == "EMT"


def test_configuracao_inexistente_falha_com_mensagem_clara(tmp_path):
    with pytest.raises(FileNotFoundError, match="configuração não encontrada"):
        Config.load(tmp_path / "nao_existe.yaml")


def test_clima_so_roda_onde_a_configuracao_declara_a_uf():
    Config.load().exigir_clima()  # MT: ok
    with pytest.raises(SystemExit, match="clima.uf"):
        Config.load(ROOT / "configs" / "ems.yaml").exigir_clima()


# ------------------------------------------------------------------ os scripts

def _scripts_com_config():
    return sorted(p for p in SCRIPTS.glob("*.py") if "carregar(" in p.read_text(encoding="utf-8")
                  or "parser(" in p.read_text(encoding="utf-8"))


def test_todos_os_scripts_de_pipeline_aceitam_config():
    esperados = {"ablacao_point_in_time", "build_bdgd", "build_clima", "build_continuidade", "build_interrupcoes",
                 "diagnostico_bdgd", "diagnostico_duplicatas", "diagnostico_vinculo", "experimento_clima", "make_figures", "resumo_decisao",
                 "run_pipeline", "sensibilidade_eficacias", "validate_dec", "variacao_sementes"}
    assert {p.stem for p in _scripts_com_config()} == esperados
    assert {p.stem for p in SCRIPTS.glob("*.py")} == esperados


def test_nenhum_script_fixa_caminho_ou_nome_de_mt():
    proibidos = [r"interrupcoes_emt", r"mt_ibge", r'ROOT\s*/\s*"reports"', r'ROOT\s*/\s*"app"', r"Config\.load\(\)",
                 r'ROOT\s*/\s*"configs"\s*/\s*"intervencoes', r'"MT"', r"Energisa MT", r"Mato Grosso"]
    achados = []
    for p in SCRIPTS.glob("*.py"):
        for n, linha in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            achados += [f"{p.name}:{n}: {linha.strip()}" for pad in proibidos if re.search(pad, linha)]
    assert not achados, "\n".join(achados)


@pytest.mark.parametrize("script", ["build_interrupcoes", "build_bdgd", "validate_dec", "diagnostico_bdgd"])
def test_ajuda_do_script_lista_a_opcao_config(script):
    r = subprocess.run([sys.executable, str(SCRIPTS / f"{script}.py"), "--help"], check=False, capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    assert "--config" in r.stdout and ENV_CONFIG in r.stdout
