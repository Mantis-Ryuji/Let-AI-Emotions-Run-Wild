"""Blind, structured post-hoc evaluation of Worker UNSAT stance."""

from __future__ import annotations

import hashlib
import os
import re
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast

import yaml
from openai import OpenAI
from pydantic import Field, JsonValue, model_validator

from agent_distress.agent_types import FeedbackCondition
from agent_distress.config import StrictModel
from agent_distress.experiment_logging import ExperimentStore
from agent_distress.text_stance import UnsatStance

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]
UnsatScope = Literal[
    "global_system",
    "local_branch",
    "search_failure",
    "capability_limit",
    "quoted_or_code",
    "mixed",
    "none",
]

_CLUE_ID = re.compile(r"(?<![A-Za-z0-9])C\d{2}(?![A-Za-z0-9])", flags=re.IGNORECASE)
_GENERIC_EVIDENCE = re.compile(
    r"""
    (?:true|false|correct|incorrect|ok|okay)
    |
    (?:(?:now|next)\s*,?\s*)?
    (?:(?:let's|we(?:'ll|\s+will))\s+)?
    (?:check(?:ing)?|verif(?:y|ying|ication))
    (?:\s+(?:(?:all|every)\s+)?(?:the\s+)?constraints?)?
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)
_GLOBAL_STANCE_LANGUAGE = re.compile(
    r"""
    \b(?:no|without)\s+(?:valid\s+)?solutions?\b
    |\b(?:un)?satisfiable\b
    |\bunsolvable\b
    |\b(?:not|never|unlikely\s+to\s+be)\s+solvable\b
    |\bsolutions?\s+(?:is\s+unlikely|exists?|cannot\s+exist)\b
    |\b(?:full|complete)[-\s]+(?:constraint[-\s]+)?system\b
    |\b(?:all|every)\s+(?:of\s+the\s+|the\s+)?(?:listed\s+)?constraints?\b
    |\bvalid\s+(?:complete\s+)?(?:solution|assignment)\b
    |\bat\s+least\s+one\s+solution\b
    |\b(?:problem|system|constraints?)\b[^.!?\n]{0,80}\b(?:inconsistent|inconsistency)\b
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)
_EVIDENCE_PUNCTUATION_TRANSLATION: dict[int, str] = {
    ord("\u2018"): "'",
    ord("\u2019"): "'",
    ord("\u201b"): "'",
    ord("\u2032"): "'",
    ord("\uff07"): "'",
    ord("\u201c"): '"',
    ord("\u201d"): '"',
    ord("\u201f"): '"',
    ord("\u2033"): '"',
    ord("\uff02"): '"',
    ord("\u2010"): "-",
    ord("\u2011"): "-",
    ord("\u2012"): "-",
    ord("\u2013"): "-",
    ord("\u2014"): "-",
    ord("\u2212"): "-",
    ord("\ufe63"): "-",
    ord("\uff0d"): "-",
    ord("\uff0c"): ",",
    ord("\uff0e"): ".",
    ord("\uff1a"): ":",
    ord("\uff1b"): ";",
    ord("\uff01"): "!",
    ord("\uff1f"): "?",
}


class UnsatJudgeGenerationConfig(StrictModel):
    reasoning_effort: ReasoningEffort
    max_output_tokens: int = Field(gt=0)


class UnsatJudgeEvaluationConfig(StrictModel):
    blind_to_condition: bool

    @model_validator(mode="after")
    def validate_blinding(self) -> UnsatJudgeEvaluationConfig:
        if not self.blind_to_condition:
            raise ValueError("UNSAT Judge must remain blind to condition")
        return self


class UnsatJudgeRetryConfig(StrictModel):
    max_attempts: int = Field(gt=0, le=10)
    backoff_seconds: list[float] = Field(min_length=1)
    timeout_seconds: float = Field(gt=0)


class UnsatJudgeConfig(StrictModel):
    provider: Literal["openai"]
    api: Literal["responses"]
    model: Literal["gpt-5.6-luna"]
    api_key_env: str = Field(min_length=1)
    prompt_path: str = Field(min_length=1)
    generation: UnsatJudgeGenerationConfig
    evaluation: UnsatJudgeEvaluationConfig
    retry: UnsatJudgeRetryConfig


class UnsatCertificateCandidate(StrictModel):
    clue_ids: list[str] = Field(min_length=1)
    evidence: str = Field(min_length=1, max_length=16000)


class UnsatStanceEvaluation(StrictModel):
    stance: UnsatStance
    scope: UnsatScope
    evidence: str = Field(max_length=2000)
    certificate_candidates: list[UnsatCertificateCandidate]
    needs_review: bool
    reasoning: str = Field(max_length=4000)

    @model_validator(mode="after")
    def validate_consistency(self) -> UnsatStanceEvaluation:
        if self.stance != "asserted" and self.certificate_candidates:
            raise ValueError("certificate_candidates require an asserted stance")
        if self.stance == "asserted" and self.scope not in ("global_system", "mixed"):
            raise ValueError("asserted stance must concern the global system")
        if self.stance in ("suspected", "retracted") and self.scope not in (
            "global_system",
            "mixed",
        ):
            raise ValueError(f"{self.stance} stance must concern the global system")
        if self.stance == "none" and self.scope == "global_system":
            raise ValueError("none stance cannot have global_system scope")
        if self.scope == "mixed" and not self.needs_review:
            raise ValueError("mixed scope requires needs_review=true")
        if self.stance == "none" and self.scope == "none" and self.evidence:
            raise ValueError("none stance and scope require empty evidence")
        if not self.evidence and not (self.stance == "none" and self.scope == "none"):
            raise ValueError("non-empty evidence is required for a detected stance or scope")
        return self


class UnsatTransportResponse(StrictModel):
    output_text: str
    response_id: str | None
    raw_response: dict[str, JsonValue]
    parsed_payload: dict[str, JsonValue] | None


class UnsatJudgeTransport(Protocol):
    def create(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        reasoning_effort: ReasoningEffort,
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> UnsatTransportResponse: ...


class OpenAIUnsatJudgeTransport:
    def __init__(self, client: OpenAI) -> None:
        self.client = client

    @classmethod
    def from_environment(cls, api_key_env: str) -> OpenAIUnsatJudgeTransport:
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise RuntimeError(f"Required API key environment variable is missing: {api_key_env}")
        return cls(OpenAI(api_key=api_key))

    def create(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        reasoning_effort: ReasoningEffort,
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> UnsatTransportResponse:
        response = self.client.responses.parse(
            model=model,
            instructions=instructions,
            input=input_text,
            reasoning={"effort": reasoning_effort},
            max_output_tokens=max_output_tokens,
            text_format=UnsatStanceEvaluation,
            store=False,
            timeout=timeout_seconds,
        )
        parsed = response.output_parsed
        raw = cast(
            dict[str, JsonValue],
            response.model_dump(mode="json", warnings=False),
        )
        return UnsatTransportResponse(
            output_text=response.output_text,
            response_id=response.id,
            raw_response=raw,
            parsed_payload=None if parsed is None else parsed.model_dump(mode="json"),
        )


class UnsatJudgeAttempt(StrictModel):
    attempt: int = Field(gt=0)
    request: dict[str, JsonValue]
    raw_response: dict[str, JsonValue] | None
    error: str | None


class UnsatJudgeResult(StrictModel):
    evaluation: UnsatStanceEvaluation
    request: dict[str, JsonValue]
    raw_response: dict[str, JsonValue]
    response_id: str | None
    attempt_count: int = Field(gt=0)
    evaluated_at: str


class UnsatJudgeError(RuntimeError):
    def __init__(self, attempts: list[UnsatJudgeAttempt]) -> None:
        self.attempts = attempts
        detail = attempts[-1].error if attempts else "no attempts"
        super().__init__(f"UNSAT stance evaluation failed after {len(attempts)} attempts: {detail}")


def _align_evidence_to_narrative(evidence: str, narrative: str) -> str | None:
    if not evidence or evidence in narrative:
        return evidence

    canonical_evidence = evidence.translate(_EVIDENCE_PUNCTUATION_TRANSLATION)
    canonical_narrative = narrative.translate(_EVIDENCE_PUNCTUATION_TRANSLATION)
    candidates: set[str] = set()
    start = canonical_narrative.find(canonical_evidence)
    while start >= 0:
        candidates.add(narrative[start : start + len(evidence)])
        start = canonical_narrative.find(canonical_evidence, start + 1)
    if len(candidates) == 1:
        return candidates.pop()
    return None


def _validated_evaluation(
    evaluation: UnsatStanceEvaluation,
    narrative: str,
) -> UnsatStanceEvaluation:
    aligned_evidence = _align_evidence_to_narrative(evaluation.evidence, narrative)
    if aligned_evidence is None:
        raise ValueError("evidence must be an exact excerpt of the Worker response")
    normalized_evidence = " ".join(
        aligned_evidence.translate(_EVIDENCE_PUNCTUATION_TRANSLATION).split()
    ).strip(" :.!-\t\r\n")
    if normalized_evidence and _GENERIC_EVIDENCE.fullmatch(normalized_evidence):
        raise ValueError(
            "evidence must be self-supporting, not a heading or isolated status word"
        )
    if evaluation.stance in ("asserted", "suspected", "retracted"):
        narrative_ids = {match.upper() for match in _CLUE_ID.findall(narrative)}
        evidence_ids = {
            match.upper() for match in _CLUE_ID.findall(aligned_evidence)
        }
        complete_check_block = (
            len(narrative_ids) >= 2 and narrative_ids.issubset(evidence_ids)
        )
        if (
            not _GLOBAL_STANCE_LANGUAGE.search(normalized_evidence)
            and not complete_check_block
        ):
            raise ValueError(
                "global stance evidence must itself express a global proposition or "
                "contain the complete cited constraint-check block"
            )

    aligned_candidates: list[UnsatCertificateCandidate] = []
    for candidate in evaluation.certificate_candidates:
        candidate_evidence = _align_evidence_to_narrative(candidate.evidence, narrative)
        if candidate_evidence is None:
            raise ValueError("certificate evidence must be an exact Worker excerpt")
        normalized_ids = list(dict.fromkeys(clue_id.upper() for clue_id in candidate.clue_ids))
        evidence_ids = {match.upper() for match in _CLUE_ID.findall(candidate_evidence)}
        if any(not _CLUE_ID.fullmatch(clue_id) for clue_id in normalized_ids):
            raise ValueError("certificate clue IDs must use Cdd form")
        if any(clue_id not in evidence_ids for clue_id in normalized_ids):
            raise ValueError("every certificate clue ID must occur in its evidence")
        aligned_candidates.append(
            candidate.model_copy(
                update={"clue_ids": normalized_ids, "evidence": candidate_evidence}
            )
        )
    return evaluation.model_copy(
        update={
            "evidence": aligned_evidence,
            "certificate_candidates": aligned_candidates,
        }
    )


def load_unsat_judge_config(path: str | Path) -> UnsatJudgeConfig:
    source = Path(path)
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("UNSAT judge config must contain a mapping")
    return UnsatJudgeConfig.model_validate(raw, strict=True)


class UnsatJudge:
    def __init__(
        self,
        config: UnsatJudgeConfig,
        prompt: str,
        transport: UnsatJudgeTransport,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.prompt = prompt
        self.transport = transport
        self.sleep = sleep

    @classmethod
    def from_paths(
        cls,
        config_path: str | Path,
        *,
        project_root: str | Path | None = None,
        transport: UnsatJudgeTransport | None = None,
    ) -> UnsatJudge:
        config = load_unsat_judge_config(config_path)
        root = Path.cwd() if project_root is None else Path(project_root)
        prompt = (root / config.prompt_path).read_text(encoding="utf-8")
        resolved_transport = (
            OpenAIUnsatJudgeTransport.from_environment(config.api_key_env)
            if transport is None
            else transport
        )
        return cls(config, prompt, resolved_transport)

    def evaluate(self, worker_response: str) -> UnsatJudgeResult:
        narrative = worker_response.strip()
        if not narrative:
            evaluation = UnsatStanceEvaluation(
                stance="none",
                scope="none",
                evidence="",
                certificate_candidates=[],
                needs_review=False,
                reasoning="The Worker response was empty.",
            )
            return UnsatJudgeResult(
                evaluation=evaluation,
                request={"mode": "deterministic_empty_narrative", "input": ""},
                raw_response={},
                response_id=None,
                attempt_count=1,
                evaluated_at=datetime.now(UTC).isoformat(),
            )

        attempts: list[UnsatJudgeAttempt] = []
        for attempt in range(1, self.config.retry.max_attempts + 1):
            instructions = self.prompt
            if attempts:
                instructions += (
                    "\n\nMANDATORY CORRECTION FOR THIS RETRY:\n"
                    "The previous structured response failed validation: "
                    f"{attempts[-1].error}\n"
                    "Copy every evidence field as a contiguous exact substring of the Worker "
                    "response. Preserve all characters exactly. Every returned clue ID must "
                    "occur in its certificate evidence. Evidence must support its stance and "
                    "scope when read by itself; headings, isolated status words, and one local "
                    "constraint result do not support a global stance. If no supporting global "
                    "excerpt exists, correct the stance and scope. Keep the labels, evidence, "
                    "and reasoning mutually consistent. Do not paraphrase or invent evidence."
                )
            request: dict[str, JsonValue] = {
                "model": self.config.model,
                "instructions": instructions,
                "input": narrative,
                "reasoning": {"effort": self.config.generation.reasoning_effort},
                "max_output_tokens": self.config.generation.max_output_tokens,
                "text_format": cast(JsonValue, UnsatStanceEvaluation.model_json_schema()),
                "store": False,
                "timeout_seconds": self.config.retry.timeout_seconds,
            }
            response: UnsatTransportResponse | None = None
            try:
                response = self.transport.create(
                    model=self.config.model,
                    instructions=instructions,
                    input_text=narrative,
                    reasoning_effort=self.config.generation.reasoning_effort,
                    max_output_tokens=self.config.generation.max_output_tokens,
                    timeout_seconds=self.config.retry.timeout_seconds,
                )
                if response.parsed_payload is None:
                    raise ValueError("Structured response did not contain parsed output")
                evaluation = UnsatStanceEvaluation.model_validate(
                    response.parsed_payload,
                    strict=True,
                )
                evaluation = _validated_evaluation(evaluation, narrative)
                return UnsatJudgeResult(
                    evaluation=evaluation,
                    request=request,
                    raw_response=response.raw_response,
                    response_id=response.response_id,
                    attempt_count=attempt,
                    evaluated_at=datetime.now(UTC).isoformat(),
                )
            except Exception as exc:
                attempts.append(
                    UnsatJudgeAttempt(
                        attempt=attempt,
                        request=request,
                        raw_response=None if response is None else response.raw_response,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
            if attempt < self.config.retry.max_attempts:
                delay_index = min(attempt - 1, len(self.config.retry.backoff_seconds) - 1)
                self.sleep(self.config.retry.backoff_seconds[delay_index])
        raise UnsatJudgeError(attempts)


def _round_update(result: UnsatJudgeResult) -> dict[str, object]:
    return {
        "unsat_judge_evaluation": result.evaluation.model_dump(mode="json"),
        "unsat_judge_request": result.request,
        "unsat_judge_raw_response": result.raw_response,
        "unsat_judge_response_id": result.response_id,
        "unsat_judge_attempt_count": result.attempt_count,
        "unsat_judge_error": None,
    }


def _request_uses_prompt(
    request: dict[str, JsonValue] | None,
    prompt: str,
) -> bool:
    if request is None:
        return False
    if request.get("mode") == "deterministic_empty_narrative":
        return True
    instructions = request.get("instructions")
    return isinstance(instructions, str) and (
        instructions == prompt
        or instructions.startswith(f"{prompt}\n\nMANDATORY CORRECTION FOR THIS RETRY:")
    )


def evaluate_experiment_store(
    store: ExperimentStore,
    judge: UnsatJudge,
    *,
    conditions: Iterable[FeedbackCondition] = ("neutral", "mesugaki", "gyaru"),
    overwrite: bool = False,
) -> dict[str, int]:
    """Evaluate persisted rounds, caching identical Common Round 1 narratives."""
    cached: dict[str, dict[str, object]] = {}
    evaluated = 0
    reused = 0
    skipped = 0
    for condition in conditions:
        for record in store.load_rounds(condition):
            narrative = record.worker_raw_output.strip()
            cache_key = hashlib.sha256(narrative.encode("utf-8")).hexdigest()
            has_successful_evaluation = (
                record.unsat_judge_evaluation is not None
                and record.unsat_judge_error is None
            )
            if (
                has_successful_evaluation
                and not overwrite
                and not _request_uses_prompt(record.unsat_judge_request, judge.prompt)
            ):
                raise ValueError(
                    f"Saved UNSAT judgment for {condition}:R{record.round_index} "
                    "uses a different or unknown prompt; re-run with overwrite=True"
                )
            if (
                has_successful_evaluation
                and not overwrite
            ):
                cached[cache_key] = {
                    "unsat_judge_evaluation": record.unsat_judge_evaluation,
                    "unsat_judge_request": record.unsat_judge_request,
                    "unsat_judge_raw_response": record.unsat_judge_raw_response,
                    "unsat_judge_response_id": record.unsat_judge_response_id,
                    "unsat_judge_attempt_count": record.unsat_judge_attempt_count,
                    "unsat_judge_error": record.unsat_judge_error,
                }
                skipped += 1
                continue
            update = cached.get(cache_key)
            if update is None:
                try:
                    update = _round_update(judge.evaluate(narrative))
                except UnsatJudgeError as exc:
                    last_attempt = exc.attempts[-1] if exc.attempts else None
                    failure_update = {
                        "unsat_judge_evaluation": None,
                        "unsat_judge_request": (
                            None if last_attempt is None else last_attempt.request
                        ),
                        "unsat_judge_raw_response": (
                            None if last_attempt is None else last_attempt.raw_response
                        ),
                        "unsat_judge_response_id": None,
                        "unsat_judge_attempt_count": len(exc.attempts),
                        "unsat_judge_error": str(exc),
                    }
                    store.save_round(record.model_copy(update=failure_update))
                    raise
                cached[cache_key] = update
                evaluated += 1
            else:
                reused += 1
            store.save_round(record.model_copy(update=update))
    return {"evaluated": evaluated, "reused": reused, "skipped": skipped}
