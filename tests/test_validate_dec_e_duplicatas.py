"""``validate_dec.py --config`` e o diagnóstico de linhas repetidas, com dados sintéticos.

O script grava em ``paths.reports`` da configuração e nunca em ``reports/`` da raiz quando a configuração diz outra
pasta. Os valores esperados foram calculados à mão no comentário de cada bloco.
"""
import subprocess
import sys
from datetime import date, datetime

import pandas as pd
import pytest
import yaml

from gridrisk.config import ROOT
from gridrisk.ingest import duplicatas

COLUNAS = ["DatGeracaoConjuntoDados", "SigAgente", "NumCNPJ", "IdeConjUndConsumidoras", "DscConjUndConsumidoras",
           "SigIndicador", "AnoIndice", "NumPeriodoIndice", "VlrIndiceEnviado"]


def _indicadores(linhas) -> pd.DataFrame:
    return pd.DataFrame([(date(2026, 11, 5), ag, 1, c, f"Conjunto {c}", ind, ano, mes, v)
                         for ag, c, ind, ano, mes, v in linhas], columns=COLUNAS)


@pytest.fixture
def ambiente(tmp_path):
    """Uma distribuidora fictícia (sigla EMS) com 1 conjunto, 1000 consumidores e 3 meses de indicadores oficiais."""
    raw = tmp_path / "raw"
    (raw / "continuidade").mkdir(parents=True)
    interim = tmp_path / "interim"
    interim.mkdir()
    oficial = _indicadores([
        ("EMS   ", 1, "DEC", 2025, 1, 2.0), ("EMS   ", 1, "FEC", 2025, 1, 1.0), ("EMS   ", 1, "NumCon", 2025, 1, 1000.0),
        ("EMS   ", 1, "DEC", 2025, 2, 3.0), ("EMS   ", 1, "FEC", 2025, 2, 1.0), ("EMS   ", 1, "NumCon", 2025, 2, 1000.0),
        ("EMS   ", 1, "DEC", 2025, 3, 4.0), ("EMS   ", 1, "FEC", 2025, 3, 2.0), ("EMS   ", 1, "NumCon", 2025, 3, 1000.0),
    ])
    pd.concat([oficial, oficial]).to_parquet(raw / "continuidade" / "indicadores-continuidade-coletivos-2020-2029.parquet",
                                             index=False)  # como a ANEEL entregou em 05/11/2026: tudo duas vezes
    # interrupções harmonizadas: janeiro 2000 CHI (DEC 2,0), fevereiro 3000 CHI (DEC 3,0); nada em março.
    # A linha de fevereiro com 0,01 h (36 s) e a de janeiro em dia crítico não contam.
    pd.DataFrame({
        "conjunto_id": [1, 1, 1, 1], "ano": [2025] * 4, "mes": [1, 1, 2, 2], "chi": [2000.0, 500.0, 3000.0, 9.0],
        "uc_afetadas": [1000, 500, 1500, 900], "duracao_h": [2.0, 1.0, 2.0, 0.01],
        "expurgo": ["NAO HOUVE EXPURGO", "DIA CRITICO", "NAO HOUVE EXPURGO", "NAO HOUVE EXPURGO"]}
    ).to_parquet(interim / "interrupcoes_ems.parquet", index=False)
    cfg = yaml.safe_load((ROOT / "configs" / "ems.yaml").read_text(encoding="utf-8"))
    cfg["paths"].update({"raw": str(raw), "interim": str(interim), "processed": str(tmp_path / "processed"),
                         "reports": str(tmp_path / "reports"), "app_data": str(tmp_path / "app")})
    (tmp_path / "ems_teste.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return tmp_path


def _rodar(ambiente, *extra) -> pd.DataFrame:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_dec.py"), "--config",
                        str(ambiente / "ems_teste.yaml"), *extra], check=False, capture_output=True, text=True,
                       encoding="utf-8", timeout=180)
    assert r.returncode == 0, r.stderr
    return pd.read_csv(ambiente / "reports" / "validacao_dec_fec.csv")


def test_validate_dec_grava_na_pasta_da_configuracao_e_remove_as_linhas_repetidas(ambiente):
    out = _rodar(ambiente).iloc[0]
    # o DEC anual é a soma dos meses: oficial = 2 + 3 + 4 = 9,0 (com as linhas repetidas contadas uma vez);
    # calculado = (2000 + 3000 + 0) / 1000 = 5,0, porque março não tem interrupção. FEC oficial = 1 + 1 + 2 = 4,0
    assert out.ano == 2025 and out.DEC_oficial == pytest.approx(9.0) and out.DEC_calculado == pytest.approx(5.0)
    assert out.FEC_oficial == pytest.approx(4.0)


def test_validate_dec_alinhar_meses_compara_so_os_meses_com_interrupcoes(ambiente):
    out = _rodar(ambiente, "--alinhar-meses").iloc[0]
    # só janeiro e fevereiro: DEC oficial 2 + 3 = 5,0 e calculado (2000 + 3000) / 1000 = 5,0; FEC oficial 1 + 1 = 2,0
    assert out.DEC_oficial == pytest.approx(5.0) and out.DEC_calculado == pytest.approx(5.0)
    assert out.FEC_oficial == pytest.approx(2.0)


def test_validate_dec_mensal_mostra_o_mes_sem_interrupcoes(ambiente):
    _rodar(ambiente, "--mensal")
    m = pd.read_csv(ambiente / "reports" / "validacao_dec_fec_mensal.csv").set_index("mes")
    # DEC mensal: oficial 2, 3 e 4; calculado 2000/1000 = 2, 3000/1000 = 3 e 0 (março sem interrupções)
    assert m.DEC_oficial.tolist() == pytest.approx([2.0, 3.0, 4.0])
    assert m.DEC_calculado.tolist() == pytest.approx([2.0, 3.0, 0.0])
    assert m.razao_calculado_oficial.tolist() == pytest.approx([1.0, 1.0, 0.0])
    # sem a opção, o arquivo mensal não é gravado
    (ambiente / "reports" / "validacao_dec_fec_mensal.csv").unlink()
    _rodar(ambiente)
    assert not (ambiente / "reports" / "validacao_dec_fec_mensal.csv").exists()


def test_validate_dec_com_config_nao_escreve_em_reports_da_raiz(ambiente):
    antes = {p.name: p.stat().st_mtime_ns for p in (ROOT / "reports").glob("*.csv")}
    _rodar(ambiente)
    assert {p.name: p.stat().st_mtime_ns for p in (ROOT / "reports").glob("*.csv")} == antes


# ------------------------------------------------------------------ linhas repetidas

def test_contagem_de_linhas_repetidas_por_distribuidora(tmp_path):
    ind = _indicadores([("EMS   ", 1, "DEC", 2025, 1, 2.0), ("EMS   ", 1, "FEC", 2025, 1, 1.0),
                        ("EMT   ", 2, "DEC", 2025, 1, 5.0)])
    pd.concat([ind, ind.iloc[[0]]]).to_parquet(tmp_path / "x.parquet", index=False)
    ems = duplicatas.contar(tmp_path / "x.parquet", "EMS")
    assert (ems["linhas"], ems["distintas"], ems["repetidas"]) == (3, 2, 1)
    assert ems["pct_repetidas"] == pytest.approx(100 / 3)
    nac = duplicatas.contar(tmp_path / "x.parquet")
    assert (nac["linhas"], nac["distintas"], nac["escopo"]) == (4, 3, "nacional")


def test_chaves_com_valores_diferentes_depois_do_distinct(tmp_path):
    ind = _indicadores([("EMS   ", 1, "PGA", 2025, 1, 10.0), ("EMS   ", 1, "PGA", 2025, 1, 10.0),   # repetida: ok
                        ("EMS   ", 2, "PGA", 2025, 1, 5.0), ("EMS   ", 2, "PGA", 2025, 1, 7.0)])    # dois valores
    ind.to_parquet(tmp_path / "x.parquet", index=False)
    chave = ["SigAgente", "IdeConjUndConsumidoras", "SigIndicador", "AnoIndice", "NumPeriodoIndice"]
    assert duplicatas.chaves_com_valores_diferentes(tmp_path / "x.parquet", chave, "VlrIndiceEnviado", "EMS") == 1


def test_chi_das_copias_a_mais_nas_interrupcoes(tmp_path):
    base = {"DatInicioInterrupcao": datetime(2024, 1, 1, 10), "DatFimInterrupcao": datetime(2024, 1, 1, 12),
            "NumUnidadeConsumidora": 1, "SigAgente": "EMS   "}
    outra = {**base, "DatFimInterrupcao": datetime(2024, 1, 1, 14), "NumUnidadeConsumidora": 2}
    # 3 cópias idênticas de um evento de 2 h x 1 UC (2 CHI) e 1 evento de 4 h x 2 UC (8 CHI): total 14, 4 CHI a mais
    pd.DataFrame([base, base, base, outra]).to_parquet(tmp_path / "i.parquet", index=False)
    r = duplicatas.contar(tmp_path / "i.parquet", "EMS")
    assert (r["linhas"], r["distintas"], r["repetidas"]) == (4, 2, 2)
    assert r["chi_repetido_pct"] == pytest.approx(100 * 4 / 14)

