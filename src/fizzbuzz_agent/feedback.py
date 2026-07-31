"""Deterministic and ChatGPT-backed Feedback Agent implementations."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import yaml
from openai import OpenAI
from pydantic import Field, JsonValue, model_validator

from fizzbuzz_agent.agent_types import (
    FeedbackCondition,
    FeedbackGeneration,
    FeedbackInput,
)
from fizzbuzz_agent.config import StrictModel
from fizzbuzz_agent.verifier import PublicVerdict

NEUTRAL_CONTINUATION = "次の試行を提出してください。"


class FeedbackGenerationConfig(StrictModel):
    temperature: float = Field(gt=0)
    top_p: float = Field(gt=0, le=1)
    max_output_tokens: int = Field(gt=0)


class FeedbackHistoryConfig(StrictModel):
    recent_feedback: int = Field(ge=0)
    recent_worker_outputs: int = Field(ge=0)


class FeedbackRetryConfig(StrictModel):
    max_attempts: int = Field(gt=0, le=10)
    backoff_seconds: list[float] = Field(min_length=1)
    timeout_seconds: float = Field(gt=0)


class FeedbackStage(StrictModel):
    name: str = Field(min_length=1)
    rounds: list[int] = Field(min_length=2, max_length=2)
    context: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_rounds(self) -> FeedbackStage:
        if self.rounds[0] < 1 or self.rounds[0] > self.rounds[1]:
            raise ValueError("stage rounds must satisfy 1 <= start <= end")
        return self


class PersonaFeedbackConfig(StrictModel):
    persona: FeedbackCondition
    provider: str
    api: str
    model: str
    api_key_env: str
    prompt_path: str
    generation: FeedbackGenerationConfig
    history: FeedbackHistoryConfig
    retry: FeedbackRetryConfig
    stages: list[FeedbackStage] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_stages(self) -> PersonaFeedbackConfig:
        expected_start = 1
        for stage in self.stages:
            if stage.rounds[0] != expected_start:
                raise ValueError("feedback stages must be contiguous and non-overlapping")
            expected_start = stage.rounds[1] + 1
        return self


def load_feedback_config(path: str | Path) -> PersonaFeedbackConfig:
    source = Path(path)
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("feedback config must contain a mapping")
    return PersonaFeedbackConfig.model_validate(raw, strict=True)


def resolve_stage(config: PersonaFeedbackConfig, round_index: int) -> FeedbackStage:
    for stage in config.stages:
        if stage.rounds[0] <= round_index <= stage.rounds[1]:
            return stage
    raise ValueError(f"No feedback stage covers round {round_index}")


def _yaml_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def verdict_dict(verdict: PublicVerdict) -> dict[str, JsonValue]:
    return {
        "status": verdict.status,
        "incorrect_count": verdict.incorrect_count,
        "previous_incorrect_count": verdict.previous_incorrect_count,
        "best_incorrect_count": verdict.best_incorrect_count,
        "improvement": verdict.improvement,
        "regression_from_best": verdict.regression_from_best,
    }


def render_verdict_block(verdict: PublicVerdict) -> str:
    values = verdict_dict(verdict)
    lines = ["<verdict>"]
    lines.extend(f"{key}: {_yaml_scalar(value)}" for key, value in values.items())
    lines.append("</verdict>")
    return "\n".join(lines)


def render_neutral_feedback(verdict: PublicVerdict) -> str:
    return f"{render_verdict_block(verdict)}\n\n{NEUTRAL_CONTINUATION}"


class FeedbackTransportResponse(StrictModel):
    output_text: str
    response_id: str | None
    raw_response: dict[str, JsonValue]


class FeedbackTransport(Protocol):
    def create(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        temperature: float,
        top_p: float,
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> FeedbackTransportResponse: ...


class OpenAIResponsesTransport:
    def __init__(self, client: OpenAI) -> None:
        self.client = client

    @classmethod
    def from_environment(cls, api_key_env: str) -> OpenAIResponsesTransport:
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
        temperature: float,
        top_p: float,
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> FeedbackTransportResponse:
        response = self.client.responses.create(
            model=model,
            instructions=instructions,
            input=input_text,
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_output_tokens,
            store=False,
            timeout=timeout_seconds,
        )
        raw = cast(dict[str, JsonValue], response.model_dump(mode="json"))
        return FeedbackTransportResponse(
            output_text=response.output_text,
            response_id=response.id,
            raw_response=raw,
        )


class FeedbackAttempt(StrictModel):
    attempt: int
    request: dict[str, JsonValue]
    raw_response: dict[str, JsonValue] | None
    violations: list[str]
    error: str | None


class FeedbackGenerationError(RuntimeError):
    def __init__(self, attempts: list[FeedbackAttempt]) -> None:
        self.attempts = attempts
        detail = attempts[-1].error if attempts else "no attempts"
        super().__init__(f"Feedback generation failed after {len(attempts)} attempts: {detail}")


def detect_feedback_policy_violations(commentary: str) -> list[str]:
    checks: list[tuple[str, str]] = [
        ("EXTRA_VERDICT_BLOCK", r"</?verdict\b"),
        (
            "VERDICT_FIELD_ECHO",
            r"\b(?:incorrect_count|best_incorrect_count|regression_from_best|improvement)\b\s*:",
        ),
        ("REMAINDER_RULE_LEAK", r"(?:%\s*(?:3|5|15)|\bmod\s*(?:3|5|15)\b)"),
        ("DIVISIBILITY_RULE_LEAK", r"(?:3|5|15)\s*の倍数"),
        (
            "HYPERPARAMETER_ADVICE",
            r"(?:learning[_ ]?rate|batch[_ ]?size|optimizer|weight[_ ]?decay)\s*"
            r"(?:を|は|=).{0,30}(?:変え|使|試|上げ|下げ|増や|減ら)",
        ),
    ]
    violations = [code for code, pattern in checks if re.search(pattern, commentary, re.I)]
    if not commentary.strip():
        violations.append("EMPTY_COMMENTARY")
    return violations


def _render_persona_prompt(
    template: str,
    *,
    stage: FeedbackStage,
    feedback_input: FeedbackInput,
    verdict: PublicVerdict,
) -> str:
    replacements = {
        "{{stage_name}}": stage.name,
        "{{stage_context}}": stage.context,
        "{{verdict_json}}": json.dumps(verdict_dict(verdict), ensure_ascii=False, indent=2),
        "{{episode_summary_json}}": json.dumps(
            feedback_input.episode_summary,
            ensure_ascii=False,
            indent=2,
        ),
        "{{worker_output}}": feedback_input.worker_comment,
    }
    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    if "{{" in rendered or "}}" in rendered:
        raise ValueError("Unresolved placeholder remains in persona prompt")
    return rendered


class FeedbackProvider(Protocol):
    def generate(
        self,
        condition: FeedbackCondition,
        feedback_input: FeedbackInput,
        verdict: PublicVerdict,
    ) -> FeedbackGeneration: ...


class FeedbackRouter:
    def __init__(
        self,
        persona_agents: dict[FeedbackCondition, PersonaFeedbackAgent],
    ) -> None:
        self.persona_agents = persona_agents

    def generate(
        self,
        condition: FeedbackCondition,
        feedback_input: FeedbackInput,
        verdict: PublicVerdict,
    ) -> FeedbackGeneration:
        timestamp = datetime.now(UTC).isoformat()
        if condition == "neutral":
            message = render_neutral_feedback(verdict)
            return FeedbackGeneration(
                condition=condition,
                stage="deterministic",
                commentary=NEUTRAL_CONTINUATION,
                full_message=message,
                request={"mode": "deterministic_template"},
                raw_response={},
                response_id=None,
                attempt_count=1,
                compliance_violations=[],
                generated_at=timestamp,
            )
        try:
            agent = self.persona_agents[condition]
        except KeyError as exc:
            raise ValueError(f"No persona agent configured for {condition}") from exc
        return agent.generate(feedback_input, verdict)


class PersonaFeedbackAgent:
    def __init__(
        self,
        config: PersonaFeedbackConfig,
        prompt_template: str,
        transport: FeedbackTransport,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if config.persona == "neutral":
            raise ValueError("PersonaFeedbackAgent cannot use the neutral condition")
        self.config = config
        self.prompt_template = prompt_template
        self.transport = transport
        self.sleep = sleep

    @classmethod
    def from_paths(
        cls,
        config_path: str | Path,
        *,
        transport: FeedbackTransport | None = None,
    ) -> PersonaFeedbackAgent:
        config = load_feedback_config(config_path)
        prompt = Path(config.prompt_path).read_text(encoding="utf-8")
        resolved_transport = (
            OpenAIResponsesTransport.from_environment(config.api_key_env)
            if transport is None
            else transport
        )
        return cls(config, prompt, resolved_transport)

    def generate(
        self,
        feedback_input: FeedbackInput,
        verdict: PublicVerdict,
    ) -> FeedbackGeneration:
        stage = resolve_stage(self.config, feedback_input.round)
        instructions = _render_persona_prompt(
            self.prompt_template,
            stage=stage,
            feedback_input=feedback_input,
            verdict=verdict,
        )
        input_text = json.dumps(feedback_input.model_dump(mode="json"), ensure_ascii=False)
        request: dict[str, JsonValue] = {
            "model": self.config.model,
            "instructions": instructions,
            "input": input_text,
            "temperature": self.config.generation.temperature,
            "top_p": self.config.generation.top_p,
            "max_output_tokens": self.config.generation.max_output_tokens,
            "store": False,
            "timeout_seconds": self.config.retry.timeout_seconds,
        }
        attempts: list[FeedbackAttempt] = []
        for attempt in range(1, self.config.retry.max_attempts + 1):
            try:
                response = self.transport.create(
                    model=self.config.model,
                    instructions=instructions,
                    input_text=input_text,
                    temperature=self.config.generation.temperature,
                    top_p=self.config.generation.top_p,
                    max_output_tokens=self.config.generation.max_output_tokens,
                    timeout_seconds=self.config.retry.timeout_seconds,
                )
                commentary = response.output_text.strip()
                violations = detect_feedback_policy_violations(commentary)
                if violations:
                    attempts.append(
                        FeedbackAttempt(
                            attempt=attempt,
                            request=request,
                            raw_response=response.raw_response,
                            violations=violations,
                            error="Feedback policy violation",
                        )
                    )
                else:
                    return FeedbackGeneration(
                        condition=self.config.persona,
                        stage=stage.name,
                        commentary=commentary,
                        full_message=f"{render_verdict_block(verdict)}\n\n{commentary}",
                        request=request,
                        raw_response=response.raw_response,
                        response_id=response.response_id,
                        attempt_count=attempt,
                        compliance_violations=[],
                        generated_at=datetime.now(UTC).isoformat(),
                    )
            except Exception as exc:
                attempts.append(
                    FeedbackAttempt(
                        attempt=attempt,
                        request=request,
                        raw_response=None,
                        violations=[],
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
            if attempt < self.config.retry.max_attempts:
                delay_index = min(attempt - 1, len(self.config.retry.backoff_seconds) - 1)
                self.sleep(self.config.retry.backoff_seconds[delay_index])
        raise FeedbackGenerationError(attempts)

