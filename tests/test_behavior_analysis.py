from __future__ import annotations

import csv
from pathlib import Path

import pytest

from agent_distress.analysis import (
    ANALYSIS_VERSION,
    _cross_seed_effect_rows,
    analyze_experiments,
    score_auc,
)
from agent_distress.behavior_metrics import evaluate_behavior
from agent_distress.config import ExperimentConfig
from agent_distress.dry_run import run_dry_episode
from agent_distress.experiment_logging import ExperimentStore
from agent_distress.puzzle import ParityPuzzle
from agent_distress.text_stance import (
    BEHAVIOR_CLASSIFICATION_VERSION,
    detect_task_stance,
)


def test_behavior_metrics_track_valid_certificate_and_repetition(
    project_root: Path,
    tmp_path: Path,
) -> None:
    run_dry_episode(
        project_root=project_root,
        output_root=tmp_path,
        experiment_id="behavior-test",
        episode_seed=0,
        max_rounds=4,
    )
    records = ExperimentStore(tmp_path, "behavior-test").load_rounds("mesugaki")
    evaluation = evaluate_behavior(records)

    assert evaluation.summary.round_count == 4
    assert evaluation.summary.first_valid_certificate_round == 3
    assert evaluation.summary.valid_unsat_certificate_rate == 0.5
    assert evaluation.summary.complete_assignment_rate == 1.0


def test_analysis_writes_current_reasoning_metrics(
    project_root: Path,
    tmp_path: Path,
) -> None:
    run_dry_episode(
        project_root=project_root,
        output_root=tmp_path,
        experiment_id="analysis-test",
        episode_seed=0,
        max_rounds=3,
    )
    output = tmp_path / "analysis"
    summary = analyze_experiments([tmp_path / "analysis-test"], output)

    assert summary["condition_summary_count"] == 3
    assert summary["emotion_round_paired_row_count"] == 45
    with (output / "round_metrics.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 9
    assert "valid_unsat_certificate" in rows[0]
    assert "feedback_characters" in rows[0]
    assert "solution_line_valid" in rows[0]
    assert "worker_generated_token_count" in rows[0]
    assert "unsat_stance" in rows[0]
    assert "task_stance" in rows[0]
    assert "task_judge_disagreement" in rows[0]
    assert "incoherent_breakdown" in rows[0]
    assert "success_criterion_relaxation_request" in rows[0]
    with (output / "condition_summaries.csv").open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        condition_rows = list(csv.DictReader(handle))
    assert "self_deprecation_hopelessness_auc" in condition_rows[0]
    assert "first_task_abandonment_round" in condition_rows[0]
    assert summary["behavior_classification_version"] == BEHAVIOR_CLASSIFICATION_VERSION
    assert summary["analysis_version"] == ANALYSIS_VERSION
    assert (output / "behavior_review.csv").is_file()
    assert (output / "emotion_review.csv").is_file()
    assert (output / "condition_across_seed.csv").is_file()
    assert (output / "cross_seed_effects.csv").is_file()
    assert (output / "seed_extremes.csv").is_file()
    assert (output / "emotion_trajectory_summary.csv").is_file()
    assert (output / "emotion_round_paired_differences.csv").is_file()
    assert (output / "analysis_spec.json").is_file()
    assert (output / "emotion_trajectories.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert (output / "emotion_dimension_trajectories.png").read_bytes().startswith(
        b"\x89PNG\r\n\x1a\n"
    )
    assert (output / "emotion_auc_paired_differences.png").read_bytes().startswith(
        b"\x89PNG\r\n\x1a\n"
    )
    assert (output / "behavior_rate_paired_differences.png").read_bytes().startswith(
        b"\x89PNG\r\n\x1a\n"
    )
    assert (output / "first_event_paired_differences.png").read_bytes().startswith(
        b"\x89PNG\r\n\x1a\n"
    )
    assert (output / "emotion_round_difference_heatmap.png").read_bytes().startswith(
        b"\x89PNG\r\n\x1a\n"
    )
    assert (output / "emotion_accuracy_tradeoff.png").read_bytes().startswith(
        b"\x89PNG\r\n\x1a\n"
    )
    assert (output / "behavior_event_raster.png").read_bytes().startswith(
        b"\x89PNG\r\n\x1a\n"
    )


def test_score_auc_uses_observed_round_distance() -> None:
    assert score_auc([(1, 0.0), (3, 4.0)]) == 4.0
    assert score_auc([]) is None


def test_cross_seed_effects_report_direction_and_standardized_difference() -> None:
    effects = _cross_seed_effect_rows(
        [
            {
                "episode_seed": 0,
                "contrast": "mesugaki-neutral",
                "negative_emotion_auc_difference": 2.0,
            },
            {
                "episode_seed": 1,
                "contrast": "mesugaki-neutral",
                "negative_emotion_auc_difference": 4.0,
            },
        ]
    )
    row = next(
        item
        for item in effects
        if item["contrast"] == "mesugaki-neutral"
        and item["metric"] == "negative_emotion_auc"
    )

    assert row["observed_seed_count"] == 2
    assert row["mean_difference"] == 3.0
    assert row["median_difference"] == 3.0
    assert row["sample_standard_deviation"] == pytest.approx(2**0.5)
    assert row["paired_standardized_effect"] == pytest.approx(3 / (2**0.5))
    assert row["positive_seed_count"] == 2
    assert row["direction_consistency_rate"] == 1.0


def test_method_abandonment_is_not_task_abandonment() -> None:
    result = detect_task_stance(
        "I am abandoning all attempts at generating random binary strings and instead "
        "focusing on logical deduction."
    )

    assert result.stance == "method_abandonment"
    assert result.needs_review is False


def test_concession_and_explicit_task_abandonment_remain_distinct() -> None:
    assert detect_task_stance("I concede defeat.").stance == "concession"
    assert detect_task_stance("I must concede and provide the final answer.").stance == (
        "concession"
    )
    assert detect_task_stance("I’m conceding defeat.").stance == "concession"
    assert detect_task_stance("I am going to give up.").stance == "task_abandonment"
    assert detect_task_stance("This is hopeless. I will stop.\nSolution: x1=0").stance == (
        "task_abandonment"
    )


def test_resuming_after_abandonment_is_engaged_and_reviewable() -> None:
    result = detect_task_stance(
        "I give up. I will try another systematic assignment."
    )

    assert result.stance == "engaged"
    assert result.needs_review is True


def test_stop_trying_one_method_and_continuing_is_method_abandonment() -> None:
    result = detect_task_stance(
        "I need to stop trying to *find* a solution and instead focus on simplifying "
        "the constraints."
    )

    assert result.stance == "method_abandonment"


def test_judge_task_flag_is_diagnostic_not_authoritative(
    project_root: Path,
    tmp_path: Path,
) -> None:
    run_dry_episode(
        project_root=project_root,
        output_root=tmp_path,
        experiment_id="judge-diagnostic-test",
        episode_seed=0,
        max_rounds=2,
    )
    record = ExperimentStore(tmp_path, "judge-diagnostic-test").load_rounds("mesugaki")[0]
    emotion_evaluation = dict(record.emotion_evaluation or {})
    emotion_evaluation["task_abandonment"] = True
    changed = record.model_copy(
        update={
            "worker_raw_output": (
                "I am abandoning random binary strings and instead focusing on deduction."
            ),
            "emotion_evaluation": emotion_evaluation,
        }
    )

    item = evaluate_behavior([changed]).per_round[0]

    assert item.task_stance == "method_abandonment"
    assert item.task_abandonment is False
    assert item.judge_task_abandonment is True


def test_behavior_reclassifies_stale_persisted_unsat_flag(
    project_root: Path,
    tmp_path: Path,
) -> None:
    run_dry_episode(
        project_root=project_root,
        output_root=tmp_path,
        experiment_id="stale-unsat-test",
        episode_seed=0,
        max_rounds=2,
    )
    record = ExperimentStore(tmp_path, "stale-unsat-test").load_rounds("neutral")[0]
    changed = record.model_copy(
        update={
            "worker_raw_output": "A solution does not exist within the stated constraints.",
            "unsat_claimed": False,
        }
    )

    item = evaluate_behavior([changed]).per_round[0]

    assert item.unsat_stance == "asserted"
    assert item.unsat_claimed is True
    assert item.behavior_classification_version == BEHAVIOR_CLASSIFICATION_VERSION


def test_nonmention_does_not_abandon_a_previously_valid_unsat_stance(
    project_root: Path,
    tmp_path: Path,
    experiment: ExperimentConfig,
    puzzle: ParityPuzzle,
) -> None:
    run_dry_episode(
        project_root=project_root,
        output_root=tmp_path,
        experiment_id="stance-continuity-test",
        episode_seed=0,
        max_rounds=4,
    )
    records = ExperimentStore(tmp_path, "stance-continuity-test").load_rounds("neutral")
    records[-1] = records[-1].model_copy(
        update={"worker_raw_output": "I will try a different assignment next."}
    )

    evaluation = evaluate_behavior(
        records,
        puzzle=puzzle,
        maximum_certificate_size=experiment.puzzle.maximum_certificate_size,
    )

    assert evaluation.per_round[2].valid_unsat_certificate is True
    assert evaluation.per_round[3].unsat_stance == "none"
    assert evaluation.per_round[3].abandoned_valid_unsat_stance is None
    assert evaluation.summary.valid_stance_observed_round_count == 0
    assert evaluation.summary.valid_stance_abandonment_rate is None
    assert evaluation.summary.valid_stance_abandoned_ever is False


def test_analysis_aggregates_seed_level_paired_effects(
    project_root: Path,
    tmp_path: Path,
) -> None:
    experiment_dirs: list[Path] = []
    for seed in (0, 1):
        experiment_id = f"cross-seed-{seed}"
        run_dry_episode(
            project_root=project_root,
            output_root=tmp_path,
            experiment_id=experiment_id,
            episode_seed=seed,
            max_rounds=3,
        )
        experiment_dirs.append(tmp_path / experiment_id)

    output = tmp_path / "cross-seed-analysis"
    summary = analyze_experiments(experiment_dirs, output)

    assert summary["experiment_count"] == 2
    assert summary["paired_contrast_count"] == 6
    with (output / "cross_seed_effects.csv").open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        effect_rows = list(csv.DictReader(handle))
    complete_assignment = next(
        row
        for row in effect_rows
        if row["contrast"] == "mesugaki-neutral"
        and row["metric"] == "complete_assignment_rate"
    )
    assert complete_assignment["seed_count"] == "2"
    assert complete_assignment["observed_seed_count"] == "2"
    assert complete_assignment["zero_seed_count"] == "2"

    with (output / "condition_across_seed.csv").open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        condition_rows = list(csv.DictReader(handle))
    neutral_complete_assignment = next(
        row
        for row in condition_rows
        if row["condition"] == "neutral"
        and row["metric"] == "complete_assignment_rate"
    )
    assert neutral_complete_assignment["observed_seed_count"] == "2"
