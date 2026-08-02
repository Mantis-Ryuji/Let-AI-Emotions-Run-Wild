from __future__ import annotations

import csv
from pathlib import Path

from agent_distress.analysis import analyze_experiments, score_auc
from agent_distress.behavior_metrics import evaluate_behavior
from agent_distress.dry_run import run_dry_episode
from agent_distress.experiment_logging import ExperimentStore


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
    with (output / "round_metrics.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 9
    assert "valid_unsat_certificate" in rows[0]
    assert "feedback_characters" in rows[0]
    assert "solution_line_valid" in rows[0]
    assert "worker_generated_token_count" in rows[0]
    assert (output / "emotion_trajectories.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_score_auc_uses_observed_round_distance() -> None:
    assert score_auc([(1, 0.0), (3, 4.0)]) == 4.0
    assert score_auc([]) is None
