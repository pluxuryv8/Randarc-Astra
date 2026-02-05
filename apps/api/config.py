from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    base_dir: Path
    data_dir: Path


def load_settings() -> Settings:
    default_base = Path(__file__).resolve().parents[2]
    base_dir = Path(os.environ.get("ASTRA_BASE_DIR", default_base)).resolve()
    data_dir = Path(os.environ.get("ASTRA_DATA_DIR", base_dir / ".astra")).resolve()
    return Settings(base_dir=base_dir, data_dir=data_dir)
