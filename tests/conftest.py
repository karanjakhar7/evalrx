"""Synthetic sources keep tests independent of private datasets and credentials."""

from __future__ import annotations

import json
import shutil
import wave

import pytest
from openpyxl import Workbook

from evalrx.config import EvalConfig, load_config


@pytest.fixture
def dataset_config(tmp_path) -> EvalConfig:
    base = load_config()
    raw = {**base.raw, "paths": dict(base.raw["paths"])}
    config = EvalConfig(raw=raw, project_root=tmp_path)
    shutil.copytree(base.project_root / "prompts", tmp_path / "prompts")
    source = config.path("transcript_workbook")
    source.parent.mkdir(parents=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Transcripts"
    sheet.append(["transcript_redacted"])
    sheet.append(
        [
            "Agent: Hello [PATIENT], how can I help?\nUser: I need medical records.\nAgent: Let me verify your identity."
        ]
    )
    sheet.append(
        ["Agent: Hello.\nUser: Please reschedule my appointment.\nAgent: Which date works for you?"]
    )
    workbook.save(source)
    workbook.close()
    config.path("audio_sources").mkdir(parents=True)
    config.path("asr_sources").mkdir(parents=True)
    for index, speaker_count in enumerate([1, 3], 1):
        name = f"synthetic_{index:03d}"
        audio = config.path("audio_sources") / f"{name}.wav"
        with wave.open(str(audio), "wb") as handle:
            handle.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            handle.writeframes(b"\x00\x00" * 8000 * 61)
        words = [
            {"word": "hello", "speaker": i % speaker_count, "confidence": 0.99}
            for i in range(8 if index == 1 else 24)
        ]
        payload = {
            "results": {
                "utterances": [
                    {
                        "speaker": i,
                        "transcript": "Hello [PATIENT].",
                        "start": float(i),
                        "end": float(i + 1),
                    }
                    for i in range(speaker_count)
                ],
                "channels": [{"alternatives": [{"words": words}]}],
            }
        }
        (config.path("asr_sources") / f"{name}.json").write_text(json.dumps(payload))
    return config
