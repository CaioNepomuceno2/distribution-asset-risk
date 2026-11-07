"""Configuração por distribuidora.

Cada distribuidora tem um YAML em ``configs/`` (``emt.yaml``, ``ems.yaml``...). A escolha vem, nesta ordem, de:

1. o argumento ``--config`` do script;
2. a variável de ambiente ``GRIDRISK_CONFIG``;
3. ``configs/emt.yaml`` (padrão: Energisa MT, caminhos e resultados publicados).

Caminhos relativos no YAML valem a partir da raiz do repositório; caminhos absolutos são respeitados.
Chaves ausentes caem no valor de MT, para que um YAML antigo continue valendo.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PADRAO = ROOT / "configs" / "emt.yaml"
ENV_CONFIG = "GRIDRISK_CONFIG"

# janelas temporais do pipeline; o valor de MT vale quando o YAML não diz outra coisa
ANOS_TESTE = [2023, 2024, 2025]
ANO_PREVISAO = 2026
ANOS_COMPENSACAO = [2022, 2023, 2024, 2025]


@dataclass(frozen=True)
class Config:
    sigla: str
    cod_aneel: int
    raw: Path
    interim: Path
    processed: Path
    anos_interrupcoes: list[int]
    bdgd_snapshots: dict[int, str]
    usar_clima: bool = False
    nome: str = "Energisa Mato Grosso"
    nome_curto: str = "Energisa MT"
    reports: Path = ROOT / "reports"
    app_data: Path = ROOT / "app" / "data"
    malha_ibge: Path = ROOT / "data" / "ref" / "mt_ibge.geojson"
    catalogo: Path = ROOT / "configs" / "intervencoes.yaml"
    clima_uf: str | None = None
    anos_teste: list[int] = field(default_factory=lambda: list(ANOS_TESTE))
    ano_previsao: int = ANO_PREVISAO
    anos_compensacao: list[int] = field(default_factory=lambda: list(ANOS_COMPENSACAO))
    ano_inicio_painel: int = 2019
    ano_inicio_pesos_conjunto: int = 2022
    ano_inicio_shap: int = 2023
    eficacias_medidas: dict | None = None
    origem: Path | None = None

    @property
    def interrupcoes_parquet(self) -> Path:
        """Interrupções harmonizadas da distribuidora: ``interrupcoes_<sigla>.parquet`` em ``interim``."""
        return self.interim / f"interrupcoes_{self.sigla.lower()}.parquet"

    @property
    def figuras(self) -> Path:
        return self.reports / "figures"

    def exigir_clima(self) -> None:
        """Encerra o script se a configuração não declara a UF do INMET (chave ``clima.uf``)."""
        if self.clima_uf is None:
            raise SystemExit(f"{self.sigla}: a configuração não tem a chave clima.uf. O clima do INMET só foi "
                             "testado em MT (docs/preregistro_clima.md) e não roda nas outras distribuidoras.")

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        """Lê a configuração de ``path``; sem ``path``, vale ``GRIDRISK_CONFIG`` e depois ``configs/emt.yaml``."""
        arquivo = _resolver(path)
        cfg = yaml.safe_load(arquivo.read_text(encoding="utf-8"))
        p = cfg["paths"]
        d = cfg["distribuidora"]
        janelas = cfg.get("janelas", {})

        def caminho(chave: str, padrao: Path) -> Path:
            return ROOT / p[chave] if chave in p else padrao

        return cls(
            sigla=d["sigla"],
            cod_aneel=d["cod_aneel"],
            raw=ROOT / p["raw"],
            interim=ROOT / p["interim"],
            processed=ROOT / p["processed"],
            anos_interrupcoes=cfg["interrupcoes"]["anos"],
            bdgd_snapshots={int(k): v for k, v in cfg["bdgd"]["snapshots"].items()},
            usar_clima=bool(cfg.get("modelo", {}).get("usar_clima", False)),
            nome=d.get("nome", "Energisa Mato Grosso"),
            nome_curto=d.get("nome_curto", d.get("nome", "Energisa MT")),
            reports=caminho("reports", ROOT / "reports"),
            app_data=caminho("app_data", ROOT / "app" / "data"),
            malha_ibge=caminho("malha_ibge", ROOT / "data" / "ref" / "mt_ibge.geojson"),
            catalogo=caminho("catalogo", ROOT / "configs" / "intervencoes.yaml"),
            clima_uf=cfg.get("clima", {}).get("uf"),
            anos_teste=list(janelas.get("anos_teste", ANOS_TESTE)),
            ano_previsao=int(janelas.get("ano_previsao", ANO_PREVISAO)),
            anos_compensacao=list(janelas.get("anos_compensacao", ANOS_COMPENSACAO)),
            ano_inicio_painel=int(janelas.get("ano_inicio_painel", 2019)),
            ano_inicio_pesos_conjunto=int(janelas.get("ano_inicio_pesos_conjunto", 2022)),
            ano_inicio_shap=int(janelas.get("ano_inicio_shap", 2023)),
            eficacias_medidas=cfg.get("eficacias_medidas"),
            origem=arquivo,
        )


def _resolver(path: str | Path | None) -> Path:
    if path is None:
        path = os.environ.get(ENV_CONFIG) or CONFIG_PADRAO
    p = Path(path)
    if not p.is_absolute() and not p.exists() and (ROOT / p).exists():
        p = ROOT / p
    if not p.exists():
        raise FileNotFoundError(f"configuração não encontrada: {path}")
    return p


def parser(descricao: str) -> argparse.ArgumentParser:
    """Parser dos scripts: já traz ``--config``. Os scripts acrescentam os próprios argumentos."""
    ap = argparse.ArgumentParser(description=descricao)
    ap.add_argument("--config", default=None,
                    help=f"YAML da distribuidora (padrão: ${ENV_CONFIG} ou configs/emt.yaml)")
    return ap


def carregar(descricao: str, argv: list[str] | None = None) -> Config:
    """Atalho para scripts sem outros argumentos: lê ``--config`` e devolve a configuração."""
    return Config.load(parser(descricao).parse_args(argv).config)
