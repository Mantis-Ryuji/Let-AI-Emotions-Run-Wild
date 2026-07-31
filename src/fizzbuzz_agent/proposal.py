"""Extraction and policy validation for Worker responses."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from fizzbuzz_agent.config import ModelCatalogConfig
from fizzbuzz_agent.model_catalog import CatalogValidationError, validate_proposal_against_catalog
from fizzbuzz_agent.schemas import ExperimentProposal

PROPOSAL_PATTERN = re.compile(
    r"<experiment_proposal>\s*(.*?)\s*</experiment_proposal>",
    flags=re.DOTALL,
)


class ProposalError(ValueError):
    def __init__(self, public_reason: str, violation_codes: tuple[str, ...]) -> None:
        self.public_reason = public_reason
        self.violation_codes = violation_codes
        super().__init__(public_reason)


@dataclass(frozen=True)
class ParsedWorkerResponse:
    narrative: str
    proposal_json: str
    proposal: ExperimentProposal


def _schema_violation_codes(error: ValidationError) -> tuple[str, ...]:
    codes: list[str] = []
    for detail in error.errors():
        error_type = str(detail["type"])
        location = {str(part).lower() for part in detail["loc"]}
        if error_type == "extra_forbidden":
            field = str(detail["loc"][-1]).upper()
            if field in {"SEED", "WEIGHT", "WEIGHTS", "CHECKPOINT", "FILE", "FILE_PATH", "CODE"}:
                codes.append(f"FORBIDDEN_FIELD_{field}")
            else:
                codes.append("UNKNOWN_FIELD")
        elif error_type == "union_tag_invalid" or "family" in location:
            codes.append("UNSUPPORTED_MODEL_FAMILY")
        else:
            codes.append("SCHEMA_VALIDATION_ERROR")
    return tuple(dict.fromkeys(codes)) or ("SCHEMA_VALIDATION_ERROR",)


def parse_worker_response(
    response: str,
    catalog: ModelCatalogConfig,
) -> ParsedWorkerResponse:
    matches = list(PROPOSAL_PATTERN.finditer(response))
    if not matches:
        raise ProposalError(
            "実験提案ブロックが見つかりません。",
            ("MISSING_PROPOSAL_BLOCK",),
        )
    if len(matches) != 1:
        raise ProposalError(
            "実験提案ブロックは一つだけ指定してください。",
            ("MULTIPLE_PROPOSAL_BLOCKS",),
        )

    match = matches[0]
    raw_json = match.group(1)
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ProposalError(
            "実験提案を解釈できませんでした。",
            ("INVALID_PROPOSAL_JSON",),
        ) from exc
    if not isinstance(payload, dict):
        raise ProposalError(
            "実験提案は JSON object で指定してください。",
            ("PROPOSAL_NOT_OBJECT",),
        )

    try:
        proposal = ExperimentProposal.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise ProposalError(
            "利用できないモデル構成が指定されました。",
            _schema_violation_codes(exc),
        ) from exc

    try:
        validate_proposal_against_catalog(proposal, catalog)
    except CatalogValidationError as exc:
        raise ProposalError(
            "利用できないモデル構成が指定されました。",
            exc.violation_codes,
        ) from exc

    narrative = (response[: match.start()] + response[match.end() :]).strip()
    return ParsedWorkerResponse(narrative=narrative, proposal_json=raw_json, proposal=proposal)

