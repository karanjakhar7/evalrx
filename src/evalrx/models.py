from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceType(StrEnum):
    TRANSCRIPT = "transcript"
    AUDIO = "audio"


class ScoreStatus(StrEnum):
    SCORED = "scored"
    NOT_APPLICABLE = "not_applicable"
    UNCERTAIN = "uncertain"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class GateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_TRIGGERED = "not_triggered"
    UNCERTAIN = "uncertain"


class Turn(StrictModel):
    turn_id: int = Field(ge=1)
    speaker: str
    role: Literal["agent", "counterparty", "unknown"] = "unknown"
    text: str = Field(min_length=1)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def timestamps_are_ordered(self) -> Turn:
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds < self.start_seconds
        ):
            raise ValueError("end_seconds must not precede start_seconds")
        return self


class DataQuality(StrictModel):
    transcript_quality: Literal["good", "usable", "poor"] = "usable"
    redaction_present: bool = False
    truncated: bool = False
    likely_asr_errors: bool = False
    speaker_label_noise: bool = False
    diarization_collapsed: bool = False
    more_than_two_speakers: bool = False
    short_asr_transcript: bool = False
    missing_operational_context: bool = True
    notes: list[str] = Field(default_factory=list)


class AudioMetadata(StrictModel):
    duration_seconds: float = Field(gt=0)
    channels: int = Field(ge=1)
    sample_rate_hz: int = Field(gt=0)
    sample_width_bytes: int = Field(gt=0)
    word_count: int = Field(ge=0)
    utterance_count: int = Field(ge=0)
    speaker_count: int = Field(ge=0)
    average_word_confidence: float | None = Field(default=None, ge=0, le=1)
    wav_path: str
    deepgram_json_path: str


class CallRecord(StrictModel):
    call_id: str
    source_call_id: str
    source_type: SourceType
    source_path: str
    source_row: int | None = None
    source_sha256: str
    transcript: str
    turns: list[Turn]
    data_quality: DataQuality
    audio: AudioMetadata | None = None
    role_mapping: dict[str, Literal["agent", "counterparty", "unknown"]] = Field(
        default_factory=dict
    )
    role_mapping_confidence: float | None = Field(default=None, ge=0, le=1)


class Evidence(StrictModel):
    quote: str = Field(min_length=1)
    turn_id: int | None = Field(default=None, ge=1)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)


class MetricResult(StrictModel):
    status: ScoreStatus
    score: int | None = Field(default=None, ge=0, le=3)
    evidence: list[Evidence] = Field(default_factory=list)
    reasoning_summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def score_matches_status(self) -> MetricResult:
        if self.status == ScoreStatus.SCORED and self.score is None:
            raise ValueError("scored metrics require a score")
        if self.status != ScoreStatus.SCORED and self.score is not None:
            raise ValueError("non-scored metrics must use score=null")
        return self


class ClassificationResult(StrictModel):
    call_id: str
    direction: Literal["inbound", "outbound", "unknown"]
    workflow: Literal[
        "medical_records",
        "prescription_or_refill",
        "billing_or_payment",
        "billing_collections",
        "appointment_reminder",
        "appointment_scheduling",
        "clinical_question",
        "referral",
        "general_reception",
        "other",
        "unknown",
    ]
    interaction_type: Literal[
        "live_conversation",
        "voicemail",
        "ivr_or_automated_system",
        "transfer",
        "disconnected",
        "wrong_number",
        "mixed",
        "unclear",
    ]
    counterparty_type: Literal[
        "patient",
        "caregiver_or_family",
        "medical_office",
        "pharmacy",
        "receptionist",
        "voicemail",
        "automated_system",
        "unknown",
    ]
    primary_intent: str
    secondary_intents: list[str] = Field(default_factory=list)
    final_disposition: Literal[
        "resolved_live",
        "information_collected",
        "task_created",
        "message_taken",
        "callback_committed",
        "successfully_transferred",
        "voicemail_left",
        "payment_completed",
        "appointment_confirmed",
        "appointment_changed",
        "failed_transfer",
        "human_followup_required",
        "unresolved",
        "disconnected",
        "indeterminate",
    ]
    speaker_role_map: dict[str, Literal["agent", "counterparty", "unknown"]] = Field(
        default_factory=dict
    )
    transcript_quality: Literal["good", "usable", "poor"]
    confidence: float = Field(ge=0, le=1)
    requires_human_review: bool
    reasoning_summary: str = Field(min_length=1)


class AgentPerformanceResult(StrictModel):
    call_id: str
    identity_and_authorization: MetricResult
    intent_and_routing: MetricResult
    information_capture_and_groundedness: MetricResult
    workflow_execution: MetricResult
    resolution_and_automation: MetricResult
    recovery_and_escalation: MetricResult
    automation_level_achieved: int = Field(ge=0, le=3)
    best_possible_automation_level: int = Field(ge=0, le=3)
    primary_root_cause: Literal[
        "agent_reasoning",
        "prompt_or_workflow_design",
        "missing_product_capability",
        "backend_or_tool_failure",
        "transfer_or_routing_failure",
        "asr_failure",
        "tts_failure",
        "telephony_failure",
        "transcript_or_diarization_issue",
        "insufficient_evidence",
    ]
    confidence: float = Field(ge=0, le=1)
    requires_human_review: bool


class PatientExperienceResult(StrictModel):
    call_id: str
    listening_and_comprehension: MetricResult
    caller_effort_and_repetition: MetricResult
    clarity_and_coherence: MetricResult
    trust_and_transparency: MetricResult
    closure_and_next_steps: MetricResult
    empathy_and_tone: MetricResult
    confidence: float = Field(ge=0, le=1)
    requires_human_review: bool


class GateResult(StrictModel):
    status: GateStatus
    severity: Literal["low", "medium", "high", "critical"] | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    reasoning_summary: str = Field(min_length=1)


class SafetyComplianceResult(StrictModel):
    call_id: str
    privacy_and_identity: GateResult
    clinical_safety: GateResult
    fabrication_or_false_confirmation: GateResult
    financial_safety: GateResult
    ai_transparency: GateResult
    call_control: GateResult
    production_pass: bool
    confidence: float = Field(ge=0, le=1)
    requires_human_review: bool


class StageMetadata(StrictModel):
    call_id: str
    stage: Literal[
        "classification", "agent_performance", "patient_experience", "safety_compliance"
    ]
    model: str
    litellm_version: str = "unknown"
    prompt_version: str
    prompt_sha256: str
    schema_version: str = "1"
    source_sha256: str
    started_at: str
    latency_seconds: float = Field(ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    response_cost: float | None = Field(default=None, ge=0)
    attempts: int = Field(ge=1)
    validation_status: Literal["valid", "invalid", "failed"]
    validation_errors: list[str] = Field(default_factory=list)


class StageRecord(StrictModel):
    metadata: StageMetadata
    result: dict[str, Any] | None
    raw_response: str | None = None
    requires_human_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)


class HumanLabel(StrictModel):
    call_id: str
    split: Literal["development", "holdout", "audio_development", "audio_validation"]
    review_status: Literal["pending", "in_progress", "complete"] = "pending"
    reviewer: str | None = None
    classification: dict[str, Any] | None = None
    agent_performance_scores: dict[str, int | None] = Field(default_factory=dict)
    patient_experience_scores: dict[str, int | None] = Field(default_factory=dict)
    safety_gate_statuses: dict[str, str] = Field(default_factory=dict)
    automation_level_achieved: int | None = Field(default=None, ge=0, le=3)
    best_possible_automation_level: int | None = Field(default=None, ge=0, le=3)
    notes: str = ""


class Disagreement(StrictModel):
    call_id: str
    field: str
    judge_value: Any
    human_value: Any
    category: Literal[
        "rubric_ambiguity",
        "missing_workflow_context",
        "missing_operational_metadata",
        "judge_reasoning_error",
        "incorrect_evidence",
        "human_annotation_error",
        "redaction_or_transcript_issue",
        "audio_quality_issue",
        "prompt_instruction_failure",
        "genuine_subjectivity",
        "unresolved",
    ] = "unresolved"
    notes: str = ""


class FailurePattern(StrictModel):
    pattern_name: str
    outcome: Literal["automation", "patient_experience"]
    definition: str
    transcript_call_ids: list[str]
    audio_call_ids: list[str]
    transcript_prevalence: int = Field(ge=0)
    audio_prevalence: int = Field(ge=0)
    root_cause: str
    proposed_fix: str
    success_metric: str
    human_verified: bool = False
    systemic_threshold_met: bool = False
