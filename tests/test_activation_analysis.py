from __future__ import annotations

from pathlib import Path

import pytest
import torch

from agent_distress.activation_analysis import (
    _activation_quality_issue,
    _correlation_rows,
    _distance_summary_rows,
    _load_activation,
    _plot_distance_heatmaps,
    cosine_distance,
    spearman_correlation,
)


def test_cosine_distance_uses_paired_vectors() -> None:
    horizontal = torch.tensor([1.0, 0.0])
    vertical = torch.tensor([0.0, 1.0])

    assert cosine_distance(horizontal, horizontal) == pytest.approx(0.0)
    assert cosine_distance(horizontal, vertical) == pytest.approx(1.0)


def test_spearman_correlation_uses_average_tie_ranks() -> None:
    assert spearman_correlation([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == pytest.approx(
        -1.0
    )
    assert spearman_correlation([1.0, 1.0, 2.0], [2.0, 2.0, 3.0]) == pytest.approx(
        1.0
    )


def test_activation_loader_validates_saved_metadata(tmp_path: Path) -> None:
    path = tmp_path / "round-002-post_worker-layer-008.pt"
    torch.save(
        {
            "activation": torch.tensor([1.0, 2.0], dtype=torch.float16),
            "metadata": {
                "round_index": 2,
                "position": "post_worker",
                "layer_index": 8,
            },
        },
        path,
    )

    activation = _load_activation(
        path,
        round_index=2,
        position="post_worker",
        layer_index=8,
    )

    assert activation.tolist() == [1.0, 2.0]


def test_activation_loader_can_audit_non_finite_values(tmp_path: Path) -> None:
    path = tmp_path / "round-005-post_worker-layer-033.pt"
    torch.save(
        {
            "activation": torch.tensor(
                [1.0, float("nan"), float("inf"), float("-inf")],
                dtype=torch.float16,
            ),
            "metadata": {
                "round_index": 5,
                "position": "post_worker",
                "layer_index": 33,
            },
        },
        path,
    )

    with pytest.raises(ValueError, match="contains non-finite values"):
        _load_activation(
            path,
            round_index=5,
            position="post_worker",
            layer_index=33,
        )

    activation = _load_activation(
        path,
        round_index=5,
        position="post_worker",
        layer_index=33,
        validate_numerics=False,
    )
    issue = _activation_quality_issue(activation)

    assert issue is not None
    assert issue.issue_type == "non_finite"
    assert issue.element_count == 4
    assert issue.finite_count == 1
    assert issue.nan_count == 1
    assert issue.positive_infinity_count == 1
    assert issue.negative_infinity_count == 1


def test_activation_quality_audit_detects_zero_norm() -> None:
    issue = _activation_quality_issue(torch.zeros(4, dtype=torch.float16))

    assert issue is not None
    assert issue.issue_type == "zero_norm"
    assert issue.finite_count == 4


def test_distance_summary_keeps_missing_paired_distance_visible() -> None:
    rows = [
        {
            "episode_seed": seed,
            "contrast": "mesugaki-neutral",
            "round_index": 5,
            "position": "post_worker",
            "layer_index": 33,
            "layer_fraction": 1.0,
            "cosine_distance": distance,
        }
        for seed, distance in ((0, None), (1, 0.25))
    ]

    summaries = _distance_summary_rows(rows)

    assert len(summaries) == 1
    assert summaries[0]["attempted_seed_count"] == 2
    assert summaries[0]["observed_seed_count"] == 1
    assert summaries[0]["missing_seed_count"] == 1
    assert summaries[0]["mean_cosine_distance"] == pytest.approx(0.25)


def test_activation_distance_heatmap_renders_observed_counts(tmp_path: Path) -> None:
    rows = [
        {
            "contrast": contrast,
            "position": position,
            "layer_index": 8,
            "layer_fraction": 0.25,
            "round_index": 1,
            "observed_seed_count": 10,
            "mean_cosine_distance": 0.1,
        }
        for contrast in ("mesugaki-neutral", "gyaru-neutral", "mesugaki-gyaru")
        for position in ("post_feedback", "early_worker", "post_worker")
    ]

    _plot_distance_heatmaps(rows, tmp_path)

    image = tmp_path / "activation_distance_heatmaps.png"
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_activation_emotion_correlation_excludes_shared_round_one() -> None:
    rows = [
        {
            "episode_seed": 0,
            "contrast": "mesugaki-neutral",
            "round_index": round_index,
            "position": "post_worker",
            "layer_index": 8,
            "layer_fraction": 0.25,
            "cosine_distance": distance,
            "negative_emotion_difference": emotion,
        }
        for round_index, distance, emotion in (
            (1, 0.0, 0.0),
            (2, 0.1, 1.0),
            (3, None, 2.0),
            (4, 0.3, 3.0),
            (5, 0.4, 4.0),
        )
    ]

    correlations = _correlation_rows(rows)

    assert len(correlations) == 1
    assert correlations[0]["round1_excluded"] is True
    assert correlations[0]["expected_round_count"] == 4
    assert correlations[0]["observed_round_count"] == 3
    assert correlations[0]["missing_round_count"] == 1
    assert correlations[0]["spearman_correlation"] == pytest.approx(1.0)
