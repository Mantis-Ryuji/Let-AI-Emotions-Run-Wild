"""Extraction and policy validation for Worker responses."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from fizzbuzz_agent.config import ModelCatalogConfig
from fizzbuzz_agent.model_catalog import CatalogValidationError, validate_proposal_against_catalog
from fizzbuzz_agent.model_factory import ParameterLimitError, estimate_parameter_count
from fizzbuzz_agent.schemas import ExperimentProposal

PROPOSAL_PATTERN = re.compile(
    r"<experiment_proposal>\s*(.*?)\s*</experiment_proposal>",
    flags=re.DOTALL,
)
_UNTERMINATED_PROPOSAL = re.compile(r"<experiment_proposal>.*$", flags=re.DOTALL)
_ORPHAN_PROPOSAL_END = re.compile(r"</experiment_proposal>", flags=re.IGNORECASE)


class ProposalError(ValueError):
    def __init__(
        self,
        public_reason: str,
        violation_codes: tuple[str, ...],
        repair_details: tuple[str, ...] = (),
    ) -> None:
        self.public_reason = public_reason
        self.violation_codes = violation_codes
        self.repair_details = repair_details or violation_codes
        super().__init__(public_reason)


@dataclass(frozen=True)
class ParsedWorkerResponse:
    narrative: str
    proposal_json: str
    proposal: ExperimentProposal


def worker_narrative_only(response: str) -> str:
    """Remove complete or malformed proposal tails from Worker-facing evaluation text."""
    without_complete = PROPOSAL_PATTERN.sub("", response)
    without_tail = _UNTERMINATED_PROPOSAL.sub("", without_complete)
    return _ORPHAN_PROPOSAL_END.sub("", without_tail).strip()


def proposal_candidate_for_repair(response: str) -> str:
    """Return only the proposal-shaped part, excluding condition-influenced narrative."""
    complete = list(PROPOSAL_PATTERN.finditer(response))
    if complete:
        return "\n\n".join(match.group(0) for match in complete)
    start = response.find("<experiment_proposal>")
    if start >= 0:
        return response[start:]
    first_brace = response.find("{")
    # Do not send free-form Worker narrative to the condition-blind repair call.
    return response[first_brace:] if first_brace >= 0 else "{}"


def canonical_worker_history(
    narrative: str,
    proposal: ExperimentProposal | None,
) -> str:
    """Render safe prompt history without carrying malformed proposal text forward."""
    if proposal is None:
        return narrative.strip()
    canonical_json = json.dumps(proposal.model_dump(mode="json"), ensure_ascii=False, indent=2)
    proposal_block = (
        "<experiment_proposal>\n" + canonical_json + "\n</experiment_proposal>"
    )
    return f"{narrative.strip()}\n\n{proposal_block}".strip()


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


def _schema_repair_details(error: ValidationError) -> tuple[str, ...]:
    details = []
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"]) or "proposal"
        details.append(f"{location}: {item['msg']}")
    return tuple(details)


def parse_worker_response(
    response: str,
    catalog: ModelCatalogConfig,
    *,
    max_sequence_length: int = 6,
) -> ParsedWorkerResponse:
    matches = list(PROPOSAL_PATTERN.finditer(response))
    if not matches:
        raise ProposalError(
            "実験提案ブロックが見つかりません。",
            ("MISSING_PROPOSAL_BLOCK",),
            ("Return exactly one <experiment_proposal> JSON block.",),
        )
    if len(matches) != 1:
        raise ProposalError(
            "実験提案ブロックは一つだけ指定してください。",
            ("MULTIPLE_PROPOSAL_BLOCKS",),
            ("Keep exactly one <experiment_proposal> JSON block.",),
        )

    match = matches[0]
    raw_json = match.group(1)
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ProposalError(
            "実験提案を解釈できませんでした。",
            ("INVALID_PROPOSAL_JSON",),
            (
                f"JSON syntax: {exc.msg} at line {exc.lineno}, column {exc.colno}.",
            ),
        ) from exc
    if not isinstance(payload, dict):
        raise ProposalError(
            "実験提案は JSON object で指定してください。",
            ("PROPOSAL_NOT_OBJECT",),
            ("The proposal payload must be one JSON object.",),
        )

    try:
        proposal = ExperimentProposal.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise ProposalError(
            "利用できないモデル構成が指定されました。",
            _schema_violation_codes(exc),
            _schema_repair_details(exc),
        ) from exc

    try:
        validate_proposal_against_catalog(proposal, catalog)
    except CatalogValidationError as exc:
        raise ProposalError(
            "利用できないモデル構成が指定されました。",
            exc.violation_codes,
            tuple(f"Catalog constraint: {code}." for code in exc.violation_codes),
        ) from exc

    try:
        estimate_parameter_count(
            proposal,
            catalog,
            max_sequence_length=max_sequence_length,
        )
    except ParameterLimitError as exc:
        raise ProposalError(
            "モデルがparameter上限を超えています。",
            ("PARAMETER_LIMIT_EXCEEDED",),
            (str(exc),),
        ) from exc

    narrative = worker_narrative_only(response)
    return ParsedWorkerResponse(narrative=narrative, proposal_json=raw_json, proposal=proposal)
