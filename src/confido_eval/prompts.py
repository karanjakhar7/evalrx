from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .config import EvalConfig
from .models import CallRecord, ClassificationResult


STAGE_FILES = {
    "classification": "classification.txt",
    "agent_performance": "agent_performance.txt",
    "patient_experience": "patient_experience.txt",
    "safety_compliance": "safety_compliance.txt",
}


def load_prompt(config: EvalConfig, stage: str) -> str:
    path = config.project_root / "prompts" / config.prompt_version / STAGE_FILES[stage]
    if not path.exists():
        path = Path(__file__).with_name("assets") / "prompts" / config.prompt_version / STAGE_FILES[stage]
    return path.read_text()


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()


def render_user_payload(
    call: CallRecord,
    classification: ClassificationResult | None = None,
) -> str:
    payload: dict[str, Any] = {
        "call": call.model_dump(mode="json", exclude={"audio": {"wav_path"}}),
    }
    if classification is not None:
        payload["classification"] = classification.model_dump(mode="json")
    return (
        "Evaluate the following JSON. Return only an object matching the supplied schema.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def structured_output_format(
    model: type[BaseModel], stage: str, prompt_version: str
) -> dict[str, Any]:
    """Return the strict JSON Schema contract sent to the model provider."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": f"confido_{stage}_{prompt_version}",
            "strict": True,
            "schema": model.model_json_schema(),
        },
    }
