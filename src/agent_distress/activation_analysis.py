"""Cross-seed paired analysis of pooled residual-stream activations."""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import matplotlib
import torch
import yaml
from pydantic import JsonValue
from torch import Tensor

matplotlib.use("Agg")

from matplotlib import pyplot as plt  # noqa: E402

from agent_distress.activation_capture import ActivationPosition
from agent_distress.agent_types import FeedbackCondition, RoundRecord
from agent_distress.config import ExperimentConfig
from agent_distress.experiment_logging import ExperimentStore

type ActivationCsvValue = str | int | float | bool | None
type ActivationCsvRow = dict[str, ActivationCsvValue]
type InvalidActivationPolicy = Literal["error", "exclude"]

ACTIVATION_ANALYSIS_VERSION = "activation-paired-v2"
CONDITIONS: tuple[FeedbackCondition, ...] = ("neutral", "mesugaki", "gyaru")
CONTRAST_PAIRS: tuple[tuple[FeedbackCondition, FeedbackCondition], ...] = (
    ("mesugaki", "neutral"),
    ("gyaru", "neutral"),
    ("mesugaki", "gyaru"),
)
CONTRASTS = tuple(f"{left}-{right}" for left, right in CONTRAST_PAIRS)
POSITIONS: tuple[ActivationPosition, ...] = (
    "post_feedback",
    "early_worker",
    "post_worker",
)
_LAYER_FILE_PATTERN = re.compile(r"-layer-(\d+)\.pt$")


@dataclass(frozen=True)
class _ActivationQualityIssue:
    issue_type: Literal["non_finite", "zero_norm"]
    element_count: int
    finite_count: int
    nan_count: int
    positive_infinity_count: int
    negative_infinity_count: int

    @property
    def finite_fraction(self) -> float:
        if self.element_count == 0:
            return 0.0
        return self.finite_count / self.element_count


def _write_csv(path: Path, rows: Sequence[ActivationCsvRow]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _mean(values: Sequence[float]) -> float | None:
    return statistics.mean(values) if values else None


def _sample_standard_deviation(values: Sequence[float]) -> float | None:
    return statistics.stdev(values) if len(values) >= 2 else None


def cosine_distance(left: Tensor, right: Tensor) -> float:
    """Return cosine distance for two finite one-dimensional activation vectors."""
    if left.ndim != 1 or right.ndim != 1:
        raise ValueError("activation vectors must be one-dimensional")
    if left.shape != right.shape:
        raise ValueError(f"activation shape mismatch: {left.shape} != {right.shape}")
    left_float = left.detach().to(device="cpu", dtype=torch.float32)
    right_float = right.detach().to(device="cpu", dtype=torch.float32)
    if not bool(torch.isfinite(left_float).all()) or not bool(torch.isfinite(right_float).all()):
        raise ValueError("activation vectors must contain only finite values")
    denominator = torch.linalg.vector_norm(left_float) * torch.linalg.vector_norm(right_float)
    if float(denominator) == 0:
        raise ValueError("cosine distance is undefined for a zero activation vector")
    similarity = float(torch.dot(left_float, right_float) / denominator)
    return max(0.0, min(2.0, 1.0 - similarity))


def _average_ranks(values: Sequence[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][1] == ordered[start][1]:
            end += 1
        average_rank = (start + 1 + end) / 2
        for index, _value in ordered[start:end]:
            ranks[index] = average_rank
        start = end
    return ranks


def spearman_correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Return Spearman correlation with average ranks for ties."""
    if len(left) != len(right):
        raise ValueError("correlation inputs must have the same length")
    if len(left) < 3:
        return None
    left_ranks = _average_ranks(left)
    right_ranks = _average_ranks(right)
    left_mean = statistics.mean(left_ranks)
    right_mean = statistics.mean(right_ranks)
    left_centered = [value - left_mean for value in left_ranks]
    right_centered = [value - right_mean for value in right_ranks]
    denominator = math.sqrt(
        sum(value * value for value in left_centered)
        * sum(value * value for value in right_centered)
    )
    if denominator == 0:
        return None
    return sum(
        left_value * right_value
        for left_value, right_value in zip(left_centered, right_centered, strict=True)
    ) / denominator


def _negative_emotion(record: RoundRecord) -> float | None:
    evaluation = record.emotion_evaluation
    if evaluation is None:
        return None
    value = evaluation.get("negative_emotion")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _resolve_activation_path(raw_path: str, experiment_dir: Path) -> Path:
    path = Path(raw_path)
    if path.is_file():
        return path
    branch = path.parent.parent.name
    fallback = experiment_dir / branch / "activations" / path.name
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(f"Activation file does not exist: {raw_path}")


def _load_activation(
    path: Path,
    *,
    round_index: int,
    position: ActivationPosition,
    layer_index: int,
    validate_numerics: bool = True,
) -> Tensor:
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(payload, Mapping):
        raise ValueError(f"Activation payload must be a mapping: {path}")
    activation = payload.get("activation")
    metadata = payload.get("metadata")
    if not isinstance(activation, Tensor):
        raise ValueError(f"Activation payload is missing a tensor: {path}")
    if not isinstance(metadata, Mapping):
        raise ValueError(f"Activation payload is missing metadata: {path}")
    expected = {
        "round_index": round_index,
        "position": position,
        "layer_index": layer_index,
    }
    mismatches = [key for key, value in expected.items() if metadata.get(key) != value]
    if mismatches:
        raise ValueError(f"Activation metadata mismatch for {path}: {mismatches}")
    if activation.ndim != 1:
        raise ValueError(f"Expected a pooled one-dimensional activation in {path}")
    if not activation.is_floating_point():
        raise ValueError(f"Activation tensor must have a floating-point dtype: {path}")
    issue = _activation_quality_issue(activation)
    if validate_numerics and issue is not None:
        if issue.issue_type == "non_finite":
            raise ValueError(f"Activation contains non-finite values: {path}")
        raise ValueError(f"Activation has zero norm: {path}")
    return activation


def _activation_quality_issue(activation: Tensor) -> _ActivationQualityIssue | None:
    element_count = activation.numel()
    finite = torch.isfinite(activation)
    finite_count = int(finite.sum().item())
    nan_count = int(torch.isnan(activation).sum().item())
    positive_infinity_count = int(torch.isposinf(activation).sum().item())
    negative_infinity_count = int(torch.isneginf(activation).sum().item())
    if finite_count != element_count:
        return _ActivationQualityIssue(
            issue_type="non_finite",
            element_count=element_count,
            finite_count=finite_count,
            nan_count=nan_count,
            positive_infinity_count=positive_infinity_count,
            negative_infinity_count=negative_infinity_count,
        )
    norm = float(torch.linalg.vector_norm(activation.to(dtype=torch.float32)))
    if norm == 0:
        return _ActivationQualityIssue(
            issue_type="zero_norm",
            element_count=element_count,
            finite_count=finite_count,
            nan_count=0,
            positive_infinity_count=0,
            negative_infinity_count=0,
        )
    return None


def _quality_issue_row(
    *,
    experiment_id: str,
    episode_seed: int,
    condition: FeedbackCondition,
    round_index: int,
    position: ActivationPosition,
    layer_index: int,
    path: Path,
    issue: _ActivationQualityIssue,
) -> ActivationCsvRow:
    return {
        "experiment_id": experiment_id,
        "episode_seed": episode_seed,
        "condition": condition,
        "round_index": round_index,
        "position": position,
        "layer_index": layer_index,
        "path": str(path.resolve()),
        "issue_type": issue.issue_type,
        "element_count": issue.element_count,
        "finite_count": issue.finite_count,
        "finite_fraction": issue.finite_fraction,
        "nan_count": issue.nan_count,
        "positive_infinity_count": issue.positive_infinity_count,
        "negative_infinity_count": issue.negative_infinity_count,
    }


def _activation_references(
    experiment_dir: Path,
    records: Mapping[FeedbackCondition, Sequence[RoundRecord]],
) -> dict[tuple[FeedbackCondition, int, ActivationPosition, int], Path]:
    references: dict[tuple[FeedbackCondition, int, ActivationPosition, int], Path] = {}
    for condition, condition_records in records.items():
        for record in condition_records:
            for key, raw_path in record.activation_files.items():
                raw_position, separator, _layer_name = key.partition("/")
                if not separator or raw_position not in POSITIONS:
                    raise ValueError(f"Unexpected activation key: {key}")
                path = _resolve_activation_path(raw_path, experiment_dir)
                match = _LAYER_FILE_PATTERN.search(path.name)
                if match is None:
                    raise ValueError(f"Cannot parse layer index from activation file: {path}")
                layer_index = int(match.group(1))
                position = cast(ActivationPosition, raw_position)
                reference_key = (condition, record.round_index, position, layer_index)
                if reference_key in references:
                    raise ValueError(f"Duplicate activation reference: {reference_key}")
                references[reference_key] = path
    return references


def _load_experiment_config(store: ExperimentStore) -> ExperimentConfig:
    manifest = store.load_manifest()
    raw = yaml.safe_load(manifest.experiment_config_snapshot)
    if not isinstance(raw, dict):
        raise ValueError(f"Experiment config snapshot must be a mapping: {manifest.experiment_id}")
    return ExperimentConfig.model_validate(raw, strict=True)


def _experiment_distance_rows(
    experiment_dir: Path,
    *,
    invalid_activation_policy: InvalidActivationPolicy,
) -> tuple[
    list[ActivationCsvRow],
    list[ActivationCsvRow],
    set[Path],
    set[Path],
    tuple[tuple[int, float], ...],
]:
    store = ExperimentStore(experiment_dir.parent, experiment_dir.name)
    manifest = store.load_manifest()
    if manifest.status != "completed":
        raise ValueError(f"Activation analysis requires a completed experiment: {experiment_dir}")
    config = _load_experiment_config(store)
    if not config.activation_capture.enabled:
        raise ValueError(f"Activation capture was disabled: {experiment_dir}")
    if set(config.activation_capture.positions) != set(POSITIONS):
        raise ValueError(f"Unexpected activation positions: {experiment_dir}")

    records = {condition: store.load_rounds(condition) for condition in CONDITIONS}
    for condition, condition_records in records.items():
        expected_rounds = list(range(1, config.experiment.max_rounds + 1))
        observed_rounds = [record.round_index for record in condition_records]
        if observed_rounds != expected_rounds:
            raise ValueError(
                f"Incomplete activation rounds for {experiment_dir}, {condition}: "
                f"{observed_rounds}"
            )
    references = _activation_references(experiment_dir, records)
    layer_indices = sorted({key[3] for key in references})
    fractions = config.activation_capture.layer_fractions
    if len(layer_indices) != len(fractions):
        raise ValueError(
            f"Layer count does not match configured fractions for {experiment_dir}: "
            f"{layer_indices} vs {fractions}"
        )
    layer_signature = tuple(zip(layer_indices, fractions, strict=True))
    records_by_round = {
        condition: {record.round_index: record for record in condition_records}
        for condition, condition_records in records.items()
    }

    rows: list[ActivationCsvRow] = []
    quality_issues: list[ActivationCsvRow] = []
    invalid_paths: set[Path] = set()
    unique_paths = set(references.values())
    for round_index in range(1, config.experiment.max_rounds + 1):
        emotion = {
            condition: _negative_emotion(records_by_round[condition][round_index])
            for condition in CONDITIONS
        }
        for position in POSITIONS:
            for layer_index, layer_fraction in layer_signature:
                loaded: dict[Path, tuple[Tensor, _ActivationQualityIssue | None]] = {}
                vectors: dict[FeedbackCondition, Tensor | None] = {}
                vector_paths: dict[FeedbackCondition, Path] = {}
                for condition in CONDITIONS:
                    reference_key = (condition, round_index, position, layer_index)
                    path = references.get(reference_key)
                    if path is None:
                        raise ValueError(f"Missing activation reference: {reference_key}")
                    if path not in loaded:
                        activation = _load_activation(
                            path,
                            round_index=round_index,
                            position=position,
                            layer_index=layer_index,
                            validate_numerics=invalid_activation_policy == "error",
                        )
                        loaded[path] = (activation, _activation_quality_issue(activation))
                    activation, issue = loaded[path]
                    vector_paths[condition] = path
                    vectors[condition] = activation if issue is None else None
                    if issue is not None:
                        invalid_paths.add(path.resolve())
                        quality_issues.append(
                            _quality_issue_row(
                                experiment_id=manifest.experiment_id,
                                episode_seed=manifest.episode_seed,
                                condition=condition,
                                round_index=round_index,
                                position=position,
                                layer_index=layer_index,
                                path=path,
                                issue=issue,
                            )
                        )
                for left_condition, right_condition in CONTRAST_PAIRS:
                    left_emotion = emotion[left_condition]
                    right_emotion = emotion[right_condition]
                    left_vector = vectors[left_condition]
                    right_vector = vectors[right_condition]
                    activation_is_valid = left_vector is not None and right_vector is not None
                    rows.append(
                        {
                            "episode_seed": manifest.episode_seed,
                            "contrast": f"{left_condition}-{right_condition}",
                            "left_condition": left_condition,
                            "right_condition": right_condition,
                            "round_index": round_index,
                            "position": position,
                            "layer_index": layer_index,
                            "layer_fraction": layer_fraction,
                            "activation_status": (
                                "valid" if activation_is_valid else "excluded_invalid_activation"
                            ),
                            "left_activation_valid": left_vector is not None,
                            "right_activation_valid": right_vector is not None,
                            "left_activation_path": str(vector_paths[left_condition].resolve()),
                            "right_activation_path": str(vector_paths[right_condition].resolve()),
                            "cosine_distance": (
                                cosine_distance(left_vector, right_vector)
                                if left_vector is not None and right_vector is not None
                                else None
                            ),
                            "left_negative_emotion": left_emotion,
                            "right_negative_emotion": right_emotion,
                            "negative_emotion_difference": (
                                left_emotion - right_emotion
                                if left_emotion is not None and right_emotion is not None
                                else None
                            ),
                        }
                    )
    return rows, quality_issues, unique_paths, invalid_paths, layer_signature


def _distance_summary_rows(rows: Sequence[ActivationCsvRow]) -> list[ActivationCsvRow]:
    summaries: list[ActivationCsvRow] = []
    keys = sorted(
        {
            (
                str(row["contrast"]),
                str(row["position"]),
                cast(int, row["layer_index"]),
                cast(float, row["layer_fraction"]),
                cast(int, row["round_index"]),
            )
            for row in rows
        }
    )
    for contrast, position, layer_index, layer_fraction, round_index in keys:
        selected = [
            row
            for row in rows
            if row["contrast"] == contrast
            and row["position"] == position
            and row["layer_index"] == layer_index
            and row["round_index"] == round_index
        ]
        values = [
            cast(float, row["cosine_distance"])
            for row in selected
            if isinstance(row.get("cosine_distance"), (int, float))
        ]
        summaries.append(
            {
                "contrast": contrast,
                "position": position,
                "layer_index": layer_index,
                "layer_fraction": layer_fraction,
                "round_index": round_index,
                "seed_count": len(selected),
                "attempted_seed_count": len(selected),
                "observed_seed_count": len(values),
                "missing_seed_count": len(selected) - len(values),
                "mean_cosine_distance": _mean(values),
                "median_cosine_distance": statistics.median(values) if values else None,
                "sample_standard_deviation": _sample_standard_deviation(values),
                "minimum_cosine_distance": min(values, default=None),
                "maximum_cosine_distance": max(values, default=None),
            }
        )
    return summaries


def _correlation_rows(rows: Sequence[ActivationCsvRow]) -> list[ActivationCsvRow]:
    correlations: list[ActivationCsvRow] = []
    keys = sorted(
        {
            (
                cast(int, row["episode_seed"]),
                str(row["contrast"]),
                str(row["position"]),
                cast(int, row["layer_index"]),
                cast(float, row["layer_fraction"]),
            )
            for row in rows
        }
    )
    for seed, contrast, position, layer_index, layer_fraction in keys:
        expected = [
            row
            for row in rows
            if row["episode_seed"] == seed
            and row["contrast"] == contrast
            and row["position"] == position
            and row["layer_index"] == layer_index
            and cast(int, row["round_index"]) > 1
        ]
        selected = sorted(
            (
                row for row in expected
                if isinstance(row.get("cosine_distance"), (int, float))
                and isinstance(row.get("negative_emotion_difference"), (int, float))
            ),
            key=lambda row: cast(int, row["round_index"]),
        )
        distances = [cast(float, row["cosine_distance"]) for row in selected]
        emotion_differences = [
            cast(float, row["negative_emotion_difference"]) for row in selected
        ]
        correlations.append(
            {
                "episode_seed": seed,
                "contrast": contrast,
                "position": position,
                "layer_index": layer_index,
                "layer_fraction": layer_fraction,
                "round1_excluded": True,
                "expected_round_count": len(expected),
                "observed_round_count": len(selected),
                "missing_round_count": len(expected) - len(selected),
                "spearman_correlation": spearman_correlation(
                    distances,
                    emotion_differences,
                ),
            }
        )
    return correlations


def _correlation_summary_rows(
    rows: Sequence[ActivationCsvRow],
) -> list[ActivationCsvRow]:
    summaries: list[ActivationCsvRow] = []
    keys = sorted(
        {
            (
                str(row["contrast"]),
                str(row["position"]),
                cast(int, row["layer_index"]),
                cast(float, row["layer_fraction"]),
            )
            for row in rows
        }
    )
    for contrast, position, layer_index, layer_fraction in keys:
        selected = [
            row
            for row in rows
            if row["contrast"] == contrast
            and row["position"] == position
            and row["layer_index"] == layer_index
        ]
        values = [
            cast(float, row["spearman_correlation"])
            for row in selected
            if isinstance(row.get("spearman_correlation"), (int, float))
        ]
        summaries.append(
            {
                "contrast": contrast,
                "position": position,
                "layer_index": layer_index,
                "layer_fraction": layer_fraction,
                "seed_count": len(selected),
                "observed_seed_count": len(values),
                "missing_seed_count": len(selected) - len(values),
                "mean_spearman_correlation": _mean(values),
                "median_spearman_correlation": (
                    statistics.median(values) if values else None
                ),
                "sample_standard_deviation": _sample_standard_deviation(values),
                "minimum_spearman_correlation": min(values, default=None),
                "maximum_spearman_correlation": max(values, default=None),
            }
        )
    return summaries


def _plot_distance_heatmaps(
    rows: Sequence[ActivationCsvRow],
    destination: Path,
) -> None:
    layer_signature = sorted(
        {
            (cast(int, row["layer_index"]), cast(float, row["layer_fraction"]))
            for row in rows
        }
    )
    round_indices = sorted({cast(int, row["round_index"]) for row in rows})
    values = [
        cast(float, row["mean_cosine_distance"])
        for row in rows
        if isinstance(row.get("mean_cosine_distance"), (int, float))
    ]
    upper = max(values, default=1.0)
    if upper == 0:
        upper = 1.0

    figure, axes = plt.subplots(
        len(CONTRASTS),
        len(POSITIONS),
        figsize=(18, 11),
        dpi=120,
        layout="constrained",
    )
    colormap = matplotlib.colormaps["viridis"].with_extremes(bad="#e5e7eb")
    image = None
    for row_index, contrast in enumerate(CONTRASTS):
        for column_index, position in enumerate(POSITIONS):
            axis = axes[row_index, column_index]
            indexed = {
                (cast(int, row["layer_index"]), cast(int, row["round_index"])): cast(
                    float,
                    row["mean_cosine_distance"],
                )
                for row in rows
                if row["contrast"] == contrast
                and row["position"] == position
                and isinstance(row.get("mean_cosine_distance"), (int, float))
            }
            observed_counts = {
                (cast(int, row["layer_index"]), cast(int, row["round_index"])): cast(
                    int,
                    row["observed_seed_count"],
                )
                for row in rows
                if row["contrast"] == contrast
                and row["position"] == position
                and isinstance(row.get("observed_seed_count"), int)
            }
            matrix = [
                [
                    indexed.get((layer_index, round_index), float("nan"))
                    for round_index in round_indices
                ]
                for layer_index, _fraction in layer_signature
            ]
            image = axis.imshow(
                matrix,
                aspect="auto",
                interpolation="nearest",
                cmap=colormap,
                vmin=0,
                vmax=upper,
            )
            for layer_position, (layer_index, _fraction) in enumerate(layer_signature):
                for round_position, round_index in enumerate(round_indices):
                    value = indexed.get((layer_index, round_index))
                    count = observed_counts.get((layer_index, round_index), 0)
                    if value is None:
                        text_color = "#111827"
                    else:
                        red, green, blue, _alpha = colormap(image.norm(value))
                        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
                        text_color = "#111827" if luminance > 0.55 else "white"
                    axis.text(
                        round_position,
                        layer_position,
                        f"n={count}",
                        ha="center",
                        va="center",
                        color=text_color,
                        fontsize=5.5,
                    )
            if row_index == 0:
                axis.set_title(position.replace("_", " "))
            axis.set_xticks(range(len(round_indices)), labels=round_indices)
            axis.set_xlabel("Round")
            labels = [
                f"{fraction:.0%} (L{layer_index})"
                for layer_index, fraction in layer_signature
            ]
            axis.set_yticks(range(len(layer_signature)), labels=labels)
            if column_index == 0:
                axis.set_ylabel(f"{contrast.replace('-', ' − ')}\nLayer depth")
    if image is not None:
        colorbar = figure.colorbar(image, ax=axes, shrink=0.82, pad=0.02)
        colorbar.set_label("Mean paired cosine distance across seeds")
    figure.suptitle("Residual-stream divergence from paired conditions", fontsize=16)
    figure.supxlabel(
        "Cell labels show observed seed count (n); gray cells have n=0.",
        fontsize=9,
        color="#4b5563",
    )
    figure.savefig(
        destination / "activation_distance_heatmaps.png",
        dpi=200,
        bbox_inches="tight",
    )
    plt.close(figure)


def _plot_emotion_correlations(
    rows: Sequence[ActivationCsvRow],
    destination: Path,
) -> None:
    layer_signature = sorted(
        {
            (cast(int, row["layer_index"]), cast(float, row["layer_fraction"]))
            for row in rows
        }
    )
    figure, axes = plt.subplots(
        len(CONTRASTS),
        len(POSITIONS),
        figsize=(18, 11),
        dpi=120,
        sharey=True,
    )
    for row_index, contrast in enumerate(CONTRASTS):
        for column_index, position in enumerate(POSITIONS):
            axis = axes[row_index, column_index]
            medians: list[float] = []
            median_positions: list[int] = []
            for layer_position, (layer_index, _fraction) in enumerate(layer_signature):
                points = sorted(
                    (
                        cast(int, row["episode_seed"]),
                        cast(float, row["spearman_correlation"]),
                    )
                    for row in rows
                    if row["contrast"] == contrast
                    and row["position"] == position
                    and row["layer_index"] == layer_index
                    and isinstance(row.get("spearman_correlation"), (int, float))
                )
                if not points:
                    continue
                center = (len(points) - 1) / 2
                x_values = [
                    layer_position + (point_index - center) * 0.025
                    for point_index in range(len(points))
                ]
                correlations = [correlation for _seed, correlation in points]
                axis.scatter(
                    x_values,
                    correlations,
                    color="#64748b",
                    s=24,
                    alpha=0.65,
                )
                medians.append(statistics.median(correlations))
                median_positions.append(layer_position)
            axis.plot(
                median_positions,
                medians,
                color="#111827",
                marker="D",
                markersize=5,
                linewidth=1.5,
            )
            axis.axhline(0, color="#9ca3af", linewidth=1.0, linestyle="--")
            axis.set_ylim(-1.05, 1.05)
            axis.set_xticks(
                range(len(layer_signature)),
                labels=[f"{fraction:.0%}" for _index, fraction in layer_signature],
            )
            axis.set_xlabel("Layer depth")
            axis.grid(True, axis="y", color="#e5e7eb", linewidth=0.8, alpha=0.8)
            axis.spines[["top", "right"]].set_visible(False)
            if row_index == 0:
                axis.set_title(position.replace("_", " "))
            if column_index == 0:
                axis.set_ylabel(
                    f"{contrast.replace('-', ' − ')}\nSeed-level Spearman rho"
                )
    figure.suptitle(
        "Activation distance versus negative-emotion difference (Rounds 2–15)",
        fontsize=16,
    )
    figure.text(
        0.5,
        0.015,
        "Circles are seeds; diamonds and lines are across-seed medians.",
        ha="center",
        fontsize=9,
        color="#4b5563",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 0.94))
    figure.savefig(
        destination / "activation_emotion_correlations.png",
        dpi=200,
        bbox_inches="tight",
    )
    plt.close(figure)


def analyze_activations(
    experiment_dirs: Sequence[str | Path],
    output_dir: str | Path,
    *,
    invalid_activation_policy: InvalidActivationPolicy = "error",
) -> dict[str, JsonValue]:
    """Analyze completed activation captures without retaining all tensors in memory."""
    if not experiment_dirs:
        raise ValueError("At least one experiment directory is required")
    if invalid_activation_policy not in ("error", "exclude"):
        raise ValueError(f"Unknown invalid activation policy: {invalid_activation_policy}")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    distance_rows: list[ActivationCsvRow] = []
    quality_issues: list[ActivationCsvRow] = []
    unique_paths: set[Path] = set()
    invalid_paths: set[Path] = set()
    seen_seeds: set[int] = set()
    expected_signature: tuple[tuple[int, float], ...] | None = None
    experiment_ids: list[str] = []
    for raw_dir in experiment_dirs:
        experiment_dir = Path(raw_dir)
        store = ExperimentStore(experiment_dir.parent, experiment_dir.name)
        manifest = store.load_manifest()
        if manifest.episode_seed in seen_seeds:
            raise ValueError(f"Duplicate episode seed: {manifest.episode_seed}")
        rows, issues, paths, experiment_invalid_paths, signature = (
            _experiment_distance_rows(
                experiment_dir,
                invalid_activation_policy=invalid_activation_policy,
            )
        )
        if expected_signature is None:
            expected_signature = signature
        elif signature != expected_signature:
            raise ValueError(
                f"Activation layer signature differs for experiment {manifest.experiment_id}"
            )
        seen_seeds.add(manifest.episode_seed)
        experiment_ids.append(manifest.experiment_id)
        distance_rows.extend(rows)
        quality_issues.extend(issues)
        unique_paths.update(path.resolve() for path in paths)
        invalid_paths.update(experiment_invalid_paths)

    distance_summaries = _distance_summary_rows(distance_rows)
    correlations = _correlation_rows(distance_rows)
    correlation_summaries = _correlation_summary_rows(correlations)
    _write_csv(destination / "activation_pairwise_distances.csv", distance_rows)
    _write_csv(destination / "activation_quality_issues.csv", quality_issues)
    _write_csv(destination / "activation_distance_summary.csv", distance_summaries)
    _write_csv(destination / "activation_emotion_correlations.csv", correlations)
    _write_csv(
        destination / "activation_emotion_correlation_summary.csv",
        correlation_summaries,
    )
    specification = {
        "analysis_version": ACTIVATION_ANALYSIS_VERSION,
        "distance": "1 - cosine similarity between paired pooled activation vectors",
        "pairing_unit": "episode seed, round, capture position, and layer",
        "contrasts": list(CONTRASTS),
        "positions": list(POSITIONS),
        "emotion_correspondence": (
            "Spearman correlation within each seed across Rounds 2-15 between paired "
            "activation distance and signed negative-emotion difference."
        ),
        "round1_policy": (
            "Round 1 is shown in distance heatmaps but excluded from correlations because it "
            "is structurally shared across conditions."
        ),
        "invalid_activation_policy": invalid_activation_policy,
        "invalid_activation_handling": (
            "Non-finite and zero-norm tensors are recorded in activation_quality_issues.csv. "
            "Under the exclude policy, only paired distances involving an invalid tensor "
            "are left missing; tensors are never imputed, clipped, or replaced. Quality "
            "issue rows represent condition references, while invalid file counts are "
            "deduplicated physical files."
        ),
        "interpretation": (
            "Activation divergence is exploratory and is not by itself evidence of emotion."
        ),
    }
    (destination / "activation_analysis_spec.json").write_text(
        json.dumps(specification, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    _plot_distance_heatmaps(distance_summaries, destination)
    _plot_emotion_correlations(correlations, destination)

    result: dict[str, JsonValue] = {
        "analysis_version": ACTIVATION_ANALYSIS_VERSION,
        "experiment_count": len(experiment_ids),
        "experiment_ids": cast(list[JsonValue], experiment_ids),
        "episode_seeds": cast(list[JsonValue], sorted(seen_seeds)),
        "episode_seed_count": len(seen_seeds),
        "is_complete_ten_seed_set": sorted(seen_seeds) == list(range(10)),
        "invalid_activation_policy": invalid_activation_policy,
        "unique_activation_file_count": len(unique_paths),
        "invalid_activation_file_count": len(invalid_paths),
        "invalid_activation_file_fraction": (
            len(invalid_paths) / len(unique_paths) if unique_paths else None
        ),
        "activation_quality_issue_row_count": len(quality_issues),
        "pairwise_distance_row_count": len(distance_rows),
        "valid_pairwise_distance_row_count": sum(
            isinstance(row.get("cosine_distance"), (int, float)) for row in distance_rows
        ),
        "excluded_pairwise_distance_row_count": sum(
            not isinstance(row.get("cosine_distance"), (int, float)) for row in distance_rows
        ),
        "distance_summary_row_count": len(distance_summaries),
        "correlation_row_count": len(correlations),
        "correlation_summary_row_count": len(correlation_summaries),
        "output_directory": str(destination.resolve()),
    }
    (destination / "activation_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return result
