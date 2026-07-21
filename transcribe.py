"""Transcribe all Confido sample call recordings with speaker diarization.

Uses the Deepgram prerecorded (Listen v1) API with diarization enabled, then
groups words into speaker-labeled turns. For each recording it writes:

  - transcripts/<call_id>.txt   speaker-labeled, human-readable transcript
  - transcripts/<call_id>.json  full raw Deepgram response (for later analysis)

The Deepgram API key is read from the environment variable DEEPGRAM_API_KEY
(loaded from the project .env by python-dotenv). The key is never printed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from deepgram import DeepgramClient

PROJECT_ROOT = Path(__file__).resolve().parent
AUDIO_DIR = PROJECT_ROOT / "Transcripts + Calls" / "Sample Calls"
OUTPUT_DIR = PROJECT_ROOT / "transcripts"

# Transcription options tuned for two-party healthcare phone calls.
TRANSCRIBE_OPTS = dict(
    model="nova-3-medical",
    diarize=True,        # label who spoke (speaker 0, 1, ...)
    smart_format=True,   # readable numbers, dates, etc.
    punctuate=True,
    utterances=True,     # semantic speech segments
    paragraphs=True,
    numerals=True,
)


def call_id_from_path(path: Path) -> str:
    """Stable, readable id derived from the .wav filename."""
    name = path.stem
    if name.endswith("_redacted"):
        name = name[: -len("_redacted")]
    return name


def words_from_response(response) -> list:
    """Return the flat word list carrying per-word `speaker` labels."""
    try:
        alt = response.results.channels[0].alternatives[0]
    except (AttributeError, IndexError):
        return []
    return alt.words or []


def build_speaker_transcript(response) -> str:
    """Group diarized words into consecutive-speaker turns.

    Prefers utterance segmentation when present; otherwise groups the flat
    word list by runs of the same `speaker` value.
    """
    utterances = getattr(getattr(response, "results", None), "utterances", None)

    turns: list[tuple[int | None, str]] = []

    if utterances:
        for utt in utterances:
            speaker = getattr(utt, "speaker", None)
            text = (getattr(utt, "transcript", "") or "").strip()
            if not text:
                continue
            if turns and turns[-1][0] == speaker:
                turns[-1] = (speaker, f"{turns[-1][1]} {text}")
            else:
                turns.append((speaker, text))
    else:
        current_speaker = object()  # sentinel distinct from any int/None
        buffer: list[str] = []
        for word in words_from_response(response):
            speaker = getattr(word, "speaker", None)
            token = getattr(word, "punctuated_word", None) or getattr(word, "word", "")
            if speaker != current_speaker:
                if buffer:
                    turns.append((current_speaker, " ".join(buffer)))
                current_speaker = speaker
                buffer = [token]
            else:
                buffer.append(token)
        if buffer:
            turns.append((current_speaker, " ".join(buffer)))

    lines = []
    for speaker, text in turns:
        label = f"Speaker {speaker}" if speaker is not None else "Speaker ?"
        lines.append(f"{label}: {text}")
    return "\n".join(lines)


def transcribe_file(client: DeepgramClient, audio_path: Path) -> object:
    with open(audio_path, "rb") as fh:
        audio_bytes = fh.read()
    return client.listen.v1.media.transcribe_file(
        request=audio_bytes,
        **TRANSCRIBE_OPTS,
    )


def response_to_dict(response) -> dict:
    # pydantic v2: mode="json" makes datetimes/enums JSON-serializable.
    dump = getattr(response, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:
            return dump()
    dict_method = getattr(response, "dict", None)
    if callable(dict_method):
        return dict_method()
    return json.loads(json.dumps(response, default=str))


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")

    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        print("ERROR: DEEPGRAM_API_KEY is not set in .env", file=sys.stderr)
        return 1
    try:
        client = DeepgramClient(api_key=api_key)
    except Exception as exc:  # invalid key surfaces here
        print(f"ERROR: could not initialize Deepgram client: {exc}", file=sys.stderr)
        return 1

    if not AUDIO_DIR.is_dir():
        print(f"ERROR: audio directory not found: {AUDIO_DIR}", file=sys.stderr)
        return 1

    wav_files = sorted(AUDIO_DIR.glob("*.wav"))
    if not wav_files:
        print(f"ERROR: no .wav files found in {AUDIO_DIR}", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"Found {len(wav_files)} recording(s). Writing outputs to {OUTPUT_DIR}\n")

    failures = 0
    for index, audio_path in enumerate(wav_files, start=1):
        call_id = call_id_from_path(audio_path)
        size_mb = audio_path.stat().st_size / (1024 * 1024)
        print(f"[{index}/{len(wav_files)}] {call_id} ({size_mb:.1f} MB) ...", flush=True)
        try:
            response = transcribe_file(client, audio_path)
        except Exception as exc:
            failures += 1
            print(f"    FAILED: {exc}", file=sys.stderr)
            continue

        (OUTPUT_DIR / f"{call_id}.json").write_text(
            json.dumps(response_to_dict(response), indent=2, ensure_ascii=False)
        )
        transcript = build_speaker_transcript(response)
        (OUTPUT_DIR / f"{call_id}.txt").write_text(transcript + "\n")

        speakers = {line.split(":", 1)[0] for line in transcript.splitlines() if line}
        print(f"    done — {len(transcript.splitlines())} turns, {len(speakers)} speaker(s)")

    print(f"\nComplete: {len(wav_files) - failures}/{len(wav_files)} transcribed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
