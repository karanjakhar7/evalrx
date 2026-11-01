from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CHECKOUT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = CHECKOUT_ROOT if (CHECKOUT_ROOT / "pyproject.toml").exists() else Path.cwd()
PACKAGED_CONFIG_PATH = Path(__file__).with_name("assets") / "config" / "eval.toml"
DEFAULT_CONFIG_PATH = (
    PROJECT_ROOT / "config" / "eval.toml"
    if (PROJECT_ROOT / "config" / "eval.toml").exists()
    else PACKAGED_CONFIG_PATH
)


@dataclass(frozen=True)
class EvalConfig:
    raw: dict[str, Any]
    project_root: Path = PROJECT_ROOT

    @property
    def model_by_stage(self) -> dict[str, str]:
        return dict(self.raw["models"])

    @property
    def prompt_version(self) -> str:
        return str(self.raw["prompts"]["version"])

    @property
    def concurrency(self) -> int:
        return int(self.raw["runtime"]["concurrency"])

    @property
    def max_retries(self) -> int:
        return int(self.raw["runtime"]["max_retries"])

    @property
    def temperature(self) -> float:
        return float(self.raw["runtime"]["temperature"])

    @property
    def mandatory_confidence_below(self) -> float:
        return float(self.raw["audit"]["mandatory_confidence_below"])

    @property
    def classification_review_below(self) -> float:
        return float(self.raw["audit"]["classification_review_below"])

    def path(self, key: str) -> Path:
        return self.project_root / self.raw["paths"][key]

    def max_tokens(self, stage: str) -> int:
        key = "classifier_max_tokens" if stage == "classification" else "judge_max_tokens"
        return int(self.raw["runtime"][key])


def load_config(path: Path | None = None) -> EvalConfig:
    selected = path or DEFAULT_CONFIG_PATH
    with selected.open("rb") as handle:
        raw = tomllib.load(handle)
    return EvalConfig(raw=raw)
