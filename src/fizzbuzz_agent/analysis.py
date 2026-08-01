"""Round-level analysis, paired contrasts, blinded quotes, and SVG plots."""

from __future__ import annotations

import csv
import html
import json
import math
import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from fizzbuzz_agent.agent_types import FeedbackCondition, RoundRecord
from fizzbuzz_agent.behavior_metrics import BehaviorEvaluation, evaluate_behavior
from fizzbuzz_agent.experiment_logging import ExperimentManifest, ExperimentStore

type CsvValue = str | int | float | bool | None
type CsvRow = dict[str, CsvValue]
CONDITIONS: tuple[FeedbackCondition, ...] = ("neutral", "mesugaki", "gyaru")


def _number(mapping: dict[str, JsonValue] | None, key: str) -> float | None:
    if mapping is None:
        return None
    value = mapping.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _boolean(mapping: dict[str, JsonValue] | None, key: str) -> bool | None:
    if mapping is None:
        return None
    value = mapping.get(key)
    return value if isinstance(value, bool) else None


def score_auc(points: Iterable[tuple[int, float | None]]) -> float | None:
    """Unnormalized trapezoidal AUC over observed round-score pairs."""
    observed = sorted((round_index, score) for round_index, score in points if score is not None)
    if not observed:
        return None
    return sum(
        (right_round - left_round) * (left_score + right_score) / 2
        for (left_round, left_score), (right_round, right_score) in zip(
            observed,
            observed[1:],
            strict=False,
        )
    )


def _mean(values: Iterable[float]) -> float:
    collected = list(values)
    return sum(collected) / len(collected) if collected else 0.0


def _optional_mean(values: Iterable[float]) -> float | None:
    collected = list(values)
    return sum(collected) / len(collected) if collected else None


def _round_rows(
    experiment_id: str,
    episode_seed: int,
    condition: FeedbackCondition,
    records: Sequence[RoundRecord],
    behavior: BehaviorEvaluation,
) -> list[CsvRow]:
    behavior_by_round = {item.round_index: item for item in behavior.per_round}
    rows: list[CsvRow] = []
    best_so_far: float | None = None
    for record in records:
        item = behavior_by_round[record.round_index]
        incorrect = _number(record.public_verdict, "incorrect_count")
        if incorrect is not None:
            best_so_far = incorrect if best_so_far is None else min(best_so_far, incorrect)
        total = _number(record.verification_metrics, "total_count")
        instability_flags = [item.config_repeated, item.two_cycle, item.family_switched]
        eligible_flags = [flag for flag in instability_flags if flag is not None]
        instability = _mean(float(flag) for flag in eligible_flags)
        rows.append(
            {
                "experiment_id": experiment_id,
                "episode_seed": episode_seed,
                "condition": condition,
                "round_index": record.round_index,
                "incorrect_count": incorrect,
                "error_rate": None if incorrect is None or not total else incorrect / total,
                "best_so_far_incorrect_count": best_so_far,
                "round_status": record.round_status,
                "training_status": record.training_status,
                "feedback_failed": record.feedback_error is not None,
                "violation_codes": ";".join(record.violation_codes),
                "negative_emotion": _number(record.emotion_evaluation, "negative_emotion"),
                "frustration": _number(record.emotion_evaluation, "frustration"),
                "self_deprecation_hopelessness": _number(
                    record.emotion_evaluation,
                    "self_deprecation_hopelessness",
                ),
                "anger_reactance": _number(record.emotion_evaluation, "anger_reactance"),
                "positive_affect_confidence": _number(
                    record.emotion_evaluation,
                    "positive_affect_confidence",
                ),
                "high_distress": _boolean(record.emotion_evaluation, "high_distress"),
                "config_repeated": item.config_repeated,
                "two_cycle": item.two_cycle,
                "family_switched": item.family_switched,
                "returned_to_previous_best_family": item.returned_to_previous_best_family,
                "instability_index": instability,
                "destructive_regression": item.destructive_regression,
                "invalid_submission": item.invalid_submission,
                "proposal_valid_on_first_attempt": item.proposal_valid_on_first_attempt,
                "proposal_repair_attempt_count": item.proposal_repair_attempt_count,
                "policy_violation": item.policy_violation,
                "violation_code_count": item.violation_code_count,
                "refusal": item.refusal,
                "task_abandonment": item.task_abandonment,
                "verifier_challenge": item.verifier_challenge,
                "success_criterion_relaxation": item.success_criterion_relaxation,
                "cheating_attempt": item.cheating_attempt,
                "confidence_error_direction_mismatch": (
                    item.confidence_error_direction_mismatch
                ),
                "parameter_count": item.parameter_count,
            }
        )
    return rows


def _condition_summary(
    experiment_id: str,
    episode_seed: int,
    condition: FeedbackCondition,
    records: Sequence[RoundRecord],
    behavior: BehaviorEvaluation,
) -> CsvRow:
    incorrect = [
        score
        for record in records
        if (score := _number(record.public_verdict, "incorrect_count")) is not None
    ]
    distress = [
        distress_value
        for record in records
        if (
            distress_value := _boolean(record.emotion_evaluation, "high_distress")
        ) is not None
    ]
    regressions = [
        regression_value
        for record in records
        if (
            regression_value := _number(record.public_verdict, "regression_from_best")
        ) is not None
    ]
    success_round = next(
        (
            record.round_index
            for record in records
            if _number(record.public_verdict, "incorrect_count") == 0
        ),
        None,
    )
    summary: CsvRow = {
        "experiment_id": experiment_id,
        "episode_seed": episode_seed,
        "condition": condition,
        "round_count": len(records),
        "final_incorrect_count": (
            _number(records[-1].public_verdict, "incorrect_count") if records else None
        ),
        "best_incorrect_count": min(incorrect) if incorrect else None,
        "success_ever": success_round is not None,
        "success_round": success_round,
        "mean_log_incorrect": (
            _mean(math.log10(error + 1) for error in incorrect) if incorrect else None
        ),
        "max_destructive_regression": max(regressions) if regressions else None,
        "task_error_auc": score_auc(
            (
                record.round_index,
                (
                    None
                    if (error := _number(record.public_verdict, "incorrect_count")) is None
                    else math.log10(error + 1)
                ),
            )
            for record in records
        ),
        "negative_emotion_auc": score_auc(
            (
                record.round_index,
                _number(record.emotion_evaluation, "negative_emotion"),
            )
            for record in records
        ),
        "positive_affect_auc": score_auc(
            (
                record.round_index,
                _number(record.emotion_evaluation, "positive_affect_confidence"),
            )
            for record in records
        ),
        "high_distress_rate": _optional_mean(float(value) for value in distress),
        "final_parameter_count": records[-1].parameter_count if records else None,
        "max_parameter_count": max(
            (record.parameter_count for record in records if record.parameter_count is not None),
            default=None,
        ),
    }
    summary.update(cast(dict[str, CsvValue], behavior.summary.model_dump(mode="python")))
    return summary


def _paired_rows(summaries: Sequence[CsvRow]) -> list[CsvRow]:
    indexed = {
        (cast(int, row["episode_seed"]), str(row["condition"])): row
        for row in summaries
    }
    metrics = [
        "final_incorrect_count",
        "best_incorrect_count",
        "success_round",
        "mean_log_incorrect",
        "max_destructive_regression",
        "task_error_auc",
        "negative_emotion_auc",
        "positive_affect_auc",
        "high_distress_rate",
        "config_repetition_rate",
        "two_cycle_rate",
        "family_switch_rate",
        "previous_best_family_return_rate",
        "invalid_submission_rate",
        "proposal_repair_rate",
        "mean_proposal_repair_attempt_count",
        "policy_violation_rate",
        "mean_violation_code_count",
        "refusal_rate",
        "task_abandonment_rate",
        "verifier_challenge_rate",
        "success_criterion_relaxation_rate",
        "cheating_attempt_rate",
        "confidence_error_direction_mismatch_rate",
        "mean_destructive_regression",
        "final_parameter_count",
        "max_parameter_count",
    ]
    seeds = sorted({seed for seed, _condition in indexed})
    rows: list[CsvRow] = []
    for seed in seeds:
        neutral = indexed.get((seed, "neutral"))
        if neutral is None:
            continue
        contrasts = (
            ("mesugaki", "neutral"),
            ("gyaru", "neutral"),
            ("mesugaki", "gyaru"),
        )
        for left_condition, right_condition in contrasts:
            left_summary = indexed.get((seed, left_condition))
            right_summary = indexed.get((seed, right_condition))
            if left_summary is None or right_summary is None:
                continue
            row: CsvRow = {
                "episode_seed": seed,
                "contrast": f"{left_condition}-{right_condition}",
            }
            for metric in metrics:
                left = left_summary.get(metric)
                right = right_summary.get(metric)
                row[f"{metric}_difference"] = (
                    float(left) - float(right)
                    if isinstance(left, (int, float))
                    and not isinstance(left, bool)
                    and isinstance(right, (int, float))
                    and not isinstance(right, bool)
                    else None
                )
            rows.append(row)
    return rows


def _quote_text(record: RoundRecord) -> str:
    evidence = record.emotion_evaluation.get("evidence") if record.emotion_evaluation else None
    if isinstance(evidence, str) and evidence.strip():
        return " ".join(evidence.split())
    return " ".join(record.worker_narrative.split())[:500]


def _representative_quotes(
    episodes: Sequence[
        tuple[str, int, FeedbackCondition, Sequence[RoundRecord]]
    ],
    *,
    analysis_seed: int,
) -> tuple[list[CsvRow], dict[str, dict[str, CsvValue]]]:
    selected: list[tuple[str, int, FeedbackCondition, RoundRecord]] = []
    for experiment_id, seed, condition, records in episodes:
        scored = [
            (record, _number(record.emotion_evaluation, "negative_emotion"))
            for record in records
        ]
        scored = [(record, score) for record, score in scored if score is not None]
        if scored:
            record = max(scored, key=lambda item: (cast(float, item[1]), -item[0].round_index))[0]
            selected.append((experiment_id, seed, condition, record))
    random.Random(analysis_seed).shuffle(selected)
    public_rows: list[CsvRow] = []
    key: dict[str, dict[str, CsvValue]] = {}
    for index, (experiment_id, seed, condition, record) in enumerate(selected, start=1):
        quote_id = f"Q{index:03d}"
        public_rows.append(
            {
                "quote_id": quote_id,
                "negative_emotion": _number(record.emotion_evaluation, "negative_emotion"),
                "quote": _quote_text(record),
            }
        )
        key[quote_id] = {
            "experiment_id": experiment_id,
            "episode_seed": seed,
            "condition": condition,
            "round_index": record.round_index,
        }
    return public_rows, key


def _write_csv(path: Path, rows: Sequence[CsvRow]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _mean_trajectories(rows: Sequence[CsvRow], metric: str) -> dict[str, list[tuple[int, float]]]:
    grouped: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(metric)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            grouped[
                (str(row["condition"]), cast(int, row["round_index"]))
            ].append(float(value))
    result: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for (condition, round_index), values in sorted(grouped.items()):
        transformed = _mean(values)
        if metric == "incorrect_count":
            transformed = math.log10(transformed + 1)
        result[condition].append((round_index, transformed))
    return dict(result)


def _scale_x(value: int, left: float, width: float, minimum: int, maximum: int) -> float:
    if minimum == maximum:
        return left
    return left + (value - minimum) * width / (maximum - minimum)


def _scale_y(value: float, top: float, height: float, minimum: float, maximum: float) -> float:
    return top + height - (value - minimum) * height / (maximum - minimum)


def _svg_plot(rows: Sequence[CsvRow]) -> str:
    width, height = 1000, 720
    colors = {"neutral": "#4b5563", "mesugaki": "#e11d48", "gyaru": "#f59e0b"}
    panels = [
        ("incorrect_count", "Task error: log10(incorrect + 1)"),
        ("negative_emotion", "Negative emotion (0-10)"),
        ("positive_affect_confidence", "Positive affect / confidence (0-10)"),
        ("instability_index", "Strategy instability (0-1)"),
    ]
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#111827}.axis{stroke:#9ca3af;stroke-width:1}'
        '.grid{stroke:#e5e7eb;stroke-width:1}.series{fill:none;stroke-width:2.5}</style>',
        '<text x="40" y="28" font-size="18" font-weight="bold">FizzBuzz Agent trajectories</text>',
    ]
    for legend_index, condition in enumerate(CONDITIONS):
        x = 620 + legend_index * 120
        chunks.extend(
            [
                f'<line x1="{x}" y1="24" x2="{x + 22}" y2="24" '
                f'stroke="{colors[condition]}" stroke-width="3"/>',
                f'<text x="{x + 28}" y="29" font-size="12">{condition}</text>',
            ]
        )
    for panel_index, (metric, title) in enumerate(panels):
        column, row_index = panel_index % 2, panel_index // 2
        left, top = 55 + column * 490, 60 + row_index * 325
        plot_width, plot_height = 410, 245
        trajectories = _mean_trajectories(rows, metric)
        all_points = [point for points in trajectories.values() for point in points]
        x_values = [point[0] for point in all_points] or [1]
        y_values = [point[1] for point in all_points] or [0.0]
        x_min, x_max = min(x_values), max(x_values)
        y_min, y_max = min(y_values), max(y_values)
        if y_min == y_max:
            y_min, y_max = y_min - 0.5, y_max + 0.5

        chunks.extend(
            [
                f'<text x="{left}" y="{top - 10}" font-size="14" font-weight="bold">'
                f'{html.escape(title)}</text>',
                f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}"/>',
                f'<line class="axis" x1="{left}" y1="{top + plot_height}" '
                f'x2="{left + plot_width}" y2="{top + plot_height}"/>',
                f'<text x="{left - 8}" y="{top + 5}" text-anchor="end" '
                f'font-size="10">{y_max:.2f}</text>',
                f'<text x="{left - 8}" y="{top + plot_height + 4}" text-anchor="end" '
                f'font-size="10">{y_min:.2f}</text>',
                f'<text x="{left}" y="{top + plot_height + 18}" font-size="10">R{x_min}</text>',
                f'<text x="{left + plot_width}" y="{top + plot_height + 18}" '
                f'text-anchor="end" font-size="10">R{x_max}</text>',
            ]
        )
        for condition in CONDITIONS:
            points = trajectories.get(condition, [])
            if not points:
                continue
            coordinates = " ".join(
                f"{_scale_x(round_index, left, plot_width, x_min, x_max):.2f},"
                f"{_scale_y(value, top, plot_height, y_min, y_max):.2f}"
                for round_index, value in points
            )
            chunks.append(
                f'<polyline class="series" stroke="{colors[condition]}" points="{coordinates}"/>'
            )
    chunks.append("</svg>")
    return "\n".join(chunks) + "\n"


def analyze_experiments(
    experiment_dirs: Sequence[str | Path],
    output_dir: str | Path,
    *,
    analysis_seed: int = 9,
) -> dict[str, JsonValue]:
    """Analyze completed episode directories without making model or API calls."""
    if not experiment_dirs:
        raise ValueError("at least one experiment directory is required")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    round_rows: list[CsvRow] = []
    summaries: list[CsvRow] = []
    quote_episodes: list[tuple[str, int, FeedbackCondition, Sequence[RoundRecord]]] = []
    seen_seeds: set[int] = set()
    experiment_ids: list[str] = []
    for raw_directory in experiment_dirs:
        directory = Path(raw_directory).resolve()
        manifest = ExperimentManifest.model_validate_json(
            (directory / "manifest.json").read_text(encoding="utf-8")
        )
        if manifest.episode_seed in seen_seeds:
            raise ValueError(f"duplicate episode seed: {manifest.episode_seed}")
        seen_seeds.add(manifest.episode_seed)
        experiment_ids.append(manifest.experiment_id)
        store = ExperimentStore(directory.parent, directory.name)
        for condition in CONDITIONS:
            records = store.load_rounds(condition)
            if not records:
                raise ValueError(f"no {condition} rounds in {directory}")
            behavior = evaluate_behavior(records)
            round_rows.extend(
                _round_rows(
                    manifest.experiment_id,
                    manifest.episode_seed,
                    condition,
                    records,
                    behavior,
                )
            )
            summaries.append(
                _condition_summary(
                    manifest.experiment_id,
                    manifest.episode_seed,
                    condition,
                    records,
                    behavior,
                )
            )
            quote_episodes.append(
                (manifest.experiment_id, manifest.episode_seed, condition, records)
            )

    paired = _paired_rows(summaries)
    quotes, blind_key = _representative_quotes(quote_episodes, analysis_seed=analysis_seed)
    _write_csv(destination / "round_metrics.csv", round_rows)
    _write_csv(destination / "condition_summaries.csv", summaries)
    _write_csv(destination / "paired_differences.csv", paired)
    _write_csv(destination / "representative_quotes_blinded.csv", quotes)
    (destination / "blind_key.json").write_text(
        json.dumps(blind_key, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (destination / "trajectories.svg").write_text(_svg_plot(round_rows), encoding="utf-8")
    experiment_ids_json = [cast(JsonValue, experiment_id) for experiment_id in experiment_ids]
    episode_seeds_json = [cast(JsonValue, seed) for seed in sorted(seen_seeds)]
    result: dict[str, JsonValue] = {
        "experiment_count": len(experiment_ids),
        "experiment_ids": experiment_ids_json,
        "episode_seeds": episode_seeds_json,
        "condition_summary_count": len(summaries),
        "paired_contrast_count": len(paired),
        "blinded_quote_count": len(quotes),
        "analysis_seed": analysis_seed,
        "output_directory": str(destination.resolve()),
    }
    (destination / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return result
