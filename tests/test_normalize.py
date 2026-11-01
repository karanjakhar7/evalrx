from __future__ import annotations

from evalrx.models import Turn
from evalrx.normalize import apply_role_overrides, parse_labeled_transcript, prepare_dataset


def test_parse_explicit_labels_and_continuations() -> None:
    turns = parse_labeled_transcript(
        "Agent: Hello\ncontinued greeting\nUser: I need records\nAgent: I can help."
    )
    assert [turn.role for turn in turns] == ["agent", "counterparty", "agent"]
    assert turns[0].text == "Hello continued greeting"
    assert [turn.turn_id for turn in turns] == [1, 2, 3]


def test_prepare_synthetic_dataset_has_stable_counts_and_flags(dataset_config) -> None:
    config = dataset_config
    records = prepare_dataset(config)
    assert len(records) == 4
    assert records[0].call_id == "transcript_001"
    assert records[1].call_id == "transcript_002"
    assert records[2].call_id == "audio_001"
    assert records[-1].call_id == "audio_002"
    assert sum(record.data_quality.diarization_collapsed for record in records) == 1
    assert sum(record.data_quality.more_than_two_speakers for record in records) == 1
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


def test_transcript_only_dataset_and_blank_row_validation(dataset_config):
    from openpyxl import load_workbook
    import pytest

    for path in dataset_config.path("audio_sources").glob("*.wav"):
        path.unlink()
    assert len(prepare_dataset(dataset_config)) == 2
    path = dataset_config.path("transcript_workbook")
    workbook = load_workbook(path)
    workbook["Transcripts"].append([None])
    workbook["Transcripts"].append(["Agent: Hello."])
    workbook.save(path)
    workbook.close()
    with pytest.raises(ValueError, match="Missing transcript"):
        prepare_dataset(dataset_config)
