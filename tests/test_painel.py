"""Configuração de publicação do painel (Streamlit Community Cloud).

O Cloud instala só o ``requirements.txt`` e roda ``app/app.py`` a partir da raiz do repositório,
sem instalar o pacote ``gridrisk``. Estes testes garantem que o que o painel importa está declarado.
"""
import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "app.py"
SRC = ROOT / "src"
PARQUETS_DO_PAINEL = ["risco_alimentador", "previsao_2026", "candidatos_social", "candidatos_compensacao"]
# nome do módulo -> nome do pacote no PyPI, quando diferem
PYPI = {"yaml": "pyyaml"}
# instalado sem ser importado: motor de leitura de Parquet do pandas
SO_RUNTIME = {"pyarrow"}


def _norm(nome: str) -> str:
    return re.sub(r"[-_.]+", "-", nome).lower()


def _terceiros(path: Path, vistos: set[Path] | None = None) -> set[str]:
    """Pacotes de terceiros importados por ``path`` e, recursivamente, pelos módulos ``gridrisk`` que ele usa."""
    vistos = set() if vistos is None else vistos
    if path in vistos:
        return set()
    vistos.add(path)
    achados: set[str] = set()
    for no in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            modulos = [a.name for a in no.names]
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            modulos = [no.module]
        else:
            continue
        for modulo in modulos:
            topo = modulo.split(".")[0]
            if topo == "gridrisk":
                arq = SRC.joinpath(*modulo.split("."))
                alvo = arq.with_suffix(".py") if arq.with_suffix(".py").exists() else arq / "__init__.py"
                achados |= _terceiros(alvo, vistos)
            elif topo not in sys.stdlib_module_names:
                achados.add(_norm(PYPI.get(topo, topo)))
    return achados


def _requirements() -> dict[str, str]:
    """nome normalizado -> especificador, ignorando comentários e linhas vazias."""
    out = {}
    for linha in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        linha = linha.split("#")[0].strip()
        if linha:
            m = re.match(r"([A-Za-z0-9_.-]+)\s*(.*)", linha)
            out[_norm(m.group(1))] = m.group(2)
    return out


def test_requirements_cobre_o_que_o_painel_importa():
    reqs = _requirements()
    faltando = _terceiros(APP) - set(reqs)
    assert not faltando, f"app/app.py importa (direto ou via gridrisk) o que não está em requirements.txt: {faltando}"
    assert set(reqs) - _terceiros(APP) <= SO_RUNTIME, "requirements.txt traz pacote que o painel não usa"


def test_requirements_com_versoes_fixas():
    solto = {nome: spec for nome, spec in _requirements().items() if not spec.startswith("==")}
    assert not solto, f"fixe a versão testada com == para o deploy ser reprodutível: {solto}"


def test_dados_do_painel_estao_no_repositorio_e_sao_pequenos():
    for nome in PARQUETS_DO_PAINEL:
        assert (ROOT / "app" / "data" / f"{nome}.parquet").is_file(), nome
    total = sum(p.stat().st_size for p in (ROOT / "app" / "data").rglob("*") if p.is_file())
    assert total < 25e6, f"app/data tem {total / 1e6:.1f} MB; confira os limites do Community Cloud"


def test_config_do_streamlit_sem_telemetria():
    cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert cfg["browser"]["gatherUsageStats"] is False
    assert cfg["server"]["headless"] is True


def test_painel_executa_sem_excecao():
    pytest.importorskip("streamlit")
    pytest.importorskip("plotly")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=180).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 3
