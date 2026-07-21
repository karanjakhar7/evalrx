from __future__ import annotations

from confido_eval.config import load_config
from confido_eval.models import Turn
from confido_eval.normalize import apply_role_overrides, parse_labeled_transcript, prepare_dataset


def test_parse_explicit_labels_and_continuations() -> None:
    turns = parse_labeled_transcript(
        "Agent: Hello\ncontinued greeting\nUser: I need records\nAgent: I can help."
    )
    assert [turn.role for turn in turns] == ["agent", "counterparty", "agent"]
    assert turns[0].text == "Hello continued greeting"
    assert [turn.turn_id for turn in turns] == [1, 2, 3]


def test_prepare_real_dataset_has_stable_counts_and_flags() -> None:
    config = load_config()
    records = prepare_dataset(config)
    assert len(records) == 60
    assert records[0].call_id == "transcript_001"
    assert records[49].call_id == "transcript_050"
    assert records[50].call_id == "audio_001"
    assert records[-1].call_id == "audio_010"
    assert sum(record.data_quality.diarization_collapsed for record in records) >= 2
    assert sum(record.data_quality.more_than_two_speakers for record in records) >= 3
    assert sum(record.data_quality.short_asr_transcript for record in records) == 1
    assert all(record.data_quality.redaction_present for record in records)
    assert all(record.data_quality.truncated for record in records)
    repeated = prepare_dataset(config)
    assert [record.source_sha256 for record in repeated] == [
        record.source_sha256 for record in records
    ]
    assert not list(config.path("normalized").parent.glob("*.wav"))


def test_speaker_role_override_preserves_numeric_label() -> None:
    turns = [Turn(turn_id=1, speaker="Speaker 0", text="Hello")]
    updated, mapping, confidence = apply_role_overrides(
        turns, {"Speaker 0": "unknown"}, {"Speaker 0": "agent"}
    )
    assert updated[0].speaker == "Speaker 0"
    assert updated[0].role == "agent"
    assert mapping == {"Speaker 0": "agent"}
    assert confidence == 1.0
