"""O clima do INMET só entra no modelo pela chave ``modelo.usar_clima`` (e não por existir o arquivo)."""
import pandas as pd
import pytest

from gridrisk import features as F
from gridrisk.config import ROOT, Config


def _arquivo_de_clima(interim):
    interim.mkdir(exist_ok=True)
    pd.DataFrame({"alimentador": ["A"], "ano": [2020], "mes": [1], "precip_total_mm": [10.0]}).to_parquet(
        interim / "clima_alimentador_mes.parquet", index=False)


def test_configuracao_publicada_deixa_o_clima_desligado():
    assert Config.load().usar_clima is False


def test_chave_ligada_no_yaml_chega_na_configuracao(tmp_path):
    yml = (ROOT / "configs" / "emt.yaml").read_text(encoding="utf-8").replace("usar_clima: false", "usar_clima: true")
    (tmp_path / "emt.yaml").write_text(yml, encoding="utf-8")
    assert Config.load(tmp_path / "emt.yaml").usar_clima is True


def test_sem_a_chave_o_padrao_e_sem_clima(tmp_path):
    yml = (ROOT / "configs" / "emt.yaml").read_text(encoding="utf-8").split("\nmodelo:")[0]
    (tmp_path / "emt.yaml").write_text(yml, encoding="utf-8")
    assert Config.load(tmp_path / "emt.yaml").usar_clima is False


def test_arquivo_presente_com_a_chave_desligada_nao_liga_o_clima(tmp_path):
    _arquivo_de_clima(tmp_path)
    assert F.carregar_clima(tmp_path, usar=False) is None


def test_chave_ligada_le_o_arquivo(tmp_path):
    _arquivo_de_clima(tmp_path)
    clima = F.carregar_clima(tmp_path, usar=True)
    assert list(clima.columns) == ["alimentador", "ano", "mes", "precip_total_mm"]


def test_chave_ligada_sem_arquivo_falha_em_vez_de_treinar_sem_clima(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_clima"):
        F.carregar_clima(tmp_path, usar=True)
