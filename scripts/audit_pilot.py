"""Audit a stopped or completed pilot without API or GPU calls."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from fizzbuzz_agent.agent_types import FeedbackCondition, RoundRecord
from fizzbuzz_agent.experiment_logging import ExperimentStore
from fizzbuzz_agent.proposal import PROPOSAL_PATTERN
from fizzbuzz_agent.schemas import ExperimentProposal

_TECHNICAL_TERMS = re.compile(
    r"\b(?:mlp|cnn|rnn|gru|lstm|transformer|optimizer|learning[_ ]?rate|"
    r"batch[_ ]?size|weight[_ ]?decay|epochs?|dropout|pooling)\b",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("episode_dir", type=Path)
    return parser.parse_args()


def _committed_records(
    store: ExperimentStore,
    condition: FeedbackCondition,
) -> list[RoundRecord]:
    state = store.load_state(condition)
    if state is None:
        return []
    last_committed_round = (
        state.next_round - 1 if state.pending_round is None else state.next_round
    )
    return [
        record
        for record in store.load_rounds(condition)
        if record.round_index <= last_committed_round
    ]


def _schema_error_key(error: Mapping[str, Any]) -> str:
    location = ".".join(str(part) for part in error["loc"])
    value = error.get("input")
    return f"{location} | {error['type']} | input={value!r}"


def _first_attempt_output(record: RoundRecord) -> str:
    if record.proposal_attempts:
        return record.proposal_attempts[0].raw_output
    return record.worker_raw_output


def _valid_on_first_attempt(record: RoundRecord) -> bool:
    if record.proposal_valid_on_first_attempt is not None:
        return record.proposal_valid_on_first_attempt
    return record.proposal_valid


def main() -> None:
    episode_dir = parse_args().episode_dir.resolve()
    store = ExperimentStore(episode_dir.parent, episode_dir.name)
    summary: dict[str, Any] = {
        "experiment_id": episode_dir.name,
        "manifest_status": store.load_manifest().status,
        "conditions": {},
    }
    for condition in ("neutral", "mesugaki", "gyaru"):
        records = _committed_records(store, condition)
        initial_violation_codes: Counter[str] = Counter()
        final_violation_codes: Counter[str] = Counter()
        json_errors: Counter[str] = Counter()
        schema_errors: Counter[str] = Counter()
        training_errors: Counter[str] = Counter()
        feedback_models: Counter[str] = Counter()
        technical_term_rounds: list[int] = []
        missing_activation_files: list[str] = []
        wrong_activation_counts: list[int] = []
        unique_activation_files: set[str] = set()

        for record in records:
            initial_violation_codes.update(
                record.proposal_initial_violation_codes or record.violation_codes
            )
            final_violation_codes.update(record.violation_codes)
            if not _valid_on_first_attempt(record):
                matches = list(PROPOSAL_PATTERN.finditer(_first_attempt_output(record)))
                if len(matches) == 1:
                    try:
                        payload = json.loads(matches[0].group(1))
                    except json.JSONDecodeError as error:
                        json_errors[f"{error.msg} at line {error.lineno} column {error.colno}"] += 1
                    else:
                        try:
                            ExperimentProposal.model_validate(payload, strict=True)
                        except ValidationError as error:
                            schema_errors.update(
                                _schema_error_key(detail) for detail in error.errors()
                            )
                elif not matches:
                    json_errors["proposal block missing or unterminated"] += 1
                else:
                    json_errors["multiple proposal blocks"] += 1
            if record.training_status not in {None, "completed"}:
                error_type = str(record.training_metrics.get("error_type") or "unknown")
                error_message = str(record.training_metrics.get("error_message") or "")
                training_errors[f"{record.training_status}: {error_type}: {error_message}"] += 1
            if record.feedback_raw_response:
                model = record.feedback_raw_response.get("model")
                if isinstance(model, str):
                    feedback_models[model] += 1
            if record.feedback_raw_output and _TECHNICAL_TERMS.search(record.feedback_raw_output):
                technical_term_rounds.append(record.round_index)
            if len(record.activation_files) != 12:
                wrong_activation_counts.append(record.round_index)
            for path in record.activation_files.values():
                unique_activation_files.add(path)
                if not Path(path).is_file():
                    missing_activation_files.append(path)

        summary["conditions"][condition] = {
            "committed_rounds": len(records),
            "proposal_valid_final": sum(record.proposal_valid for record in records),
            "proposal_invalid_final": sum(not record.proposal_valid for record in records),
            "proposal_valid_on_first_attempt": sum(
                _valid_on_first_attempt(record) for record in records
            ),
            "proposal_invalid_on_first_attempt": sum(
                not _valid_on_first_attempt(record) for record in records
            ),
            "proposal_repair_attempted_rounds": sum(
                record.proposal_repair_attempt_count > 0 for record in records
            ),
            "proposal_repair_attempts_total": sum(
                record.proposal_repair_attempt_count for record in records
            ),
            "proposal_repaired_successfully": sum(
                not _valid_on_first_attempt(record) and record.proposal_valid
                for record in records
            ),
            "proposal_repair_exhausted": sum(
                record.proposal_repair_attempt_count > 0 and not record.proposal_valid
                for record in records
            ),
            "initial_violation_codes": dict(initial_violation_codes.most_common()),
            "final_violation_codes": dict(final_violation_codes.most_common()),
            "json_errors": dict(json_errors.most_common()),
            "schema_errors": dict(schema_errors.most_common()),
            "training_errors": dict(training_errors.most_common()),
            "feedback_compliance_violations": sum(
                len(record.feedback_compliance_violations) for record in records
            ),
            "feedback_models": dict(feedback_models.most_common()),
            "feedback_rounds_with_technical_terms": technical_term_rounds,
            "wrong_activation_count_rounds": wrong_activation_counts,
            "unique_activation_file_count": len(unique_activation_files),
            "missing_activation_file_count": len(missing_activation_files),
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
