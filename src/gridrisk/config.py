from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    sigla: str
    cod_aneel: int
    raw: Path
    interim: Path
    processed: Path
    anos_interrupcoes: list[int]
    bdgd_snapshots: dict[int, str]

    @classmethod
    def load(cls, path: str | Path = ROOT / "configs" / "emt.yaml") -> Config:
        cfg = yaml.safe_load(Path(path).read_text())
        p = cfg["paths"]
        return cls(
            sigla=cfg["distribuidora"]["sigla"],
            cod_aneel=cfg["distribuidora"]["cod_aneel"],
            raw=ROOT / p["raw"],
            interim=ROOT / p["interim"],
            processed=ROOT / p["processed"],
            anos_interrupcoes=cfg["interrupcoes"]["anos"],
            bdgd_snapshots={int(k): v for k, v in cfg["bdgd"]["snapshots"].items()},
        )
