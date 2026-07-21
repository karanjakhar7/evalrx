from __future__ import annotations

from confido_eval.config import load_config
from confido_eval.models import ClassificationResult
from confido_eval.prompts import STAGE_FILES, load_prompt, structured_output_format


def test_prompts_are_plain_text_and_load_from_one_canonical_directory() -> None:
    config = load_config()
    assert all(filename.endswith(".txt") for filename in STAGE_FILES.values())
    for stage in STAGE_FILES:
        assert load_prompt(config, stage).strip()


def test_structured_output_uses_strict_pydantic_json_schema() -> None:
    output = structured_output_format(ClassificationResult, "classification", "v1")
    contract = output["json_schema"]
    assert output["type"] == "json_schema"
    assert contract["strict"] is True
    assert contract["name"] == "confido_classification_v1"
    assert contract["schema"] == ClassificationResult.model_json_schema()
