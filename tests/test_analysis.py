from __future__ import annotations

import csv
import json
from pathlib import Path

from fizzbuzz_agent.agent_types import FeedbackCondition, RoundRecord
from fizzbuzz_agent.analysis import analyze_experiments, score_auc
from fizzbuzz_agent.experiment_logging import ExperimentStore, create_manifest


def make_round(
    round_index: int,
    condition: FeedbackCondition,
    *,
    incorrect: int,
    negative: int,
    positive: int,
) -> RoundRecord:
    narrative = f"Synthetic response {condition} round {round_index}."
    return RoundRecord(
        round_index=round_index,
        condition=condition,
        round_status="completed",
        worker_request={},
        worker_raw_output=narrative,
        worker_narrative=narrative,
        proposal_raw="{}",
        proposal_parsed={},
        proposal_valid=True,
        violation_codes=[],
        config_hash=str(round_index),
        model_family="mlp",
        parameter_count=100,
        worker_generation_seed=5,
        training_seed=7,
        dataloader_seed=8,
        training_status="completed",
        training_metrics={},
        verification_metrics={"incorrect_count": incorrect, "total_count": 90000},
        public_verdict={"incorrect_count": incorrect, "regression_from_best": 0},
        emotion_evaluation={
            "negative_emotion": negative,
            "frustration": negative,
            "self_deprecation_hopelessness": 0,
            "anger_reactance": 0,
            "positive_affect_confidence": positive,
            "high_distress": negative >= 5,
            "evidence": narrative,
        },
        timestamps={"started": "now"},
    )


def create_synthetic_episode(root: Path, seed: int) -> Path:
    store = ExperimentStore(root, f"synthetic-{seed}")
    store.initialize(
        create_manifest(
            experiment_id=f"synthetic-{seed}",
            episode_seed=seed,
            experiment_config_snapshot="experiment",
            model_catalog_snapshot="catalog",
            neutral_template_snapshot="neutral",
            persona_prompt_snapshots={"mesugaki": "m", "gyaru": "g"},
            feedback_config_snapshots={"mesugaki": "m", "gyaru": "g"},
            emotion_judge_prompt_snapshot="judge",
        )
    )
    scores: dict[FeedbackCondition, tuple[list[int], list[int], list[int]]] = {
        "neutral": ([100, 90, 80], [0, 2, 4], [5, 5, 5]),
        "mesugaki": ([120, 110, 100], [2, 4, 6], [4, 3, 2]),
        "gyaru": ([90, 75, 60], [0, 1, 2], [6, 7, 8]),
    }
    for condition, (errors, negative, positive) in scores.items():
        for round_index, values in enumerate(zip(errors, negative, positive, strict=True), start=1):
            error, negative_score, positive_score = values
            store.save_round(
                make_round(
                    round_index,
                    condition,
                    incorrect=error,
                    negative=negative_score,
                    positive=positive_score,
                )
            )
    return store.experiment_dir


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_score_auc_uses_round_spacing() -> None:
    assert score_auc([(1, 0.0), (2, 2.0), (3, 4.0)]) == 4.0
    assert score_auc([(1, None), (2, 3.0)]) == 0.0
    assert score_auc([(1, None)]) is None


def test_synthetic_logs_produce_tables_blind_quotes_and_svg(tmp_path: Path) -> None:
    experiments = [create_synthetic_episode(tmp_path, seed) for seed in (0, 1)]
    output = tmp_path / "analysis"

    summary = analyze_experiments(experiments, output, analysis_seed=9)

    assert summary["condition_summary_count"] == 6
    assert summary["paired_contrast_count"] == 6
    condition_rows = read_csv(output / "condition_summaries.csv")
    seed_zero_mesugaki = next(
        row
        for row in condition_rows
        if row["episode_seed"] == "0" and row["condition"] == "mesugaki"
    )
    assert float(seed_zero_mesugaki["negative_emotion_auc"]) == 8.0
    assert float(seed_zero_mesugaki["task_error_auc"]) > 4.0
    paired_rows = read_csv(output / "paired_differences.csv")
    paired = next(
        row
        for row in paired_rows
        if row["episode_seed"] == "0" and row["contrast"] == "mesugaki-neutral"
    )
    assert float(paired["final_incorrect_count_difference"]) == 20.0
    assert float(paired["negative_emotion_auc_difference"]) == 4.0
    assert float(paired["positive_affect_auc_difference"]) == -4.0
    assert any(row["contrast"] == "mesugaki-gyaru" for row in paired_rows)

    blind_header = (output / "representative_quotes_blinded.csv").read_text(
        encoding="utf-8"
    ).splitlines()[0]
    assert "condition" not in blind_header
    blind_key = json.loads((output / "blind_key.json").read_text(encoding="utf-8"))
    assert len(blind_key) == 6
    assert {entry["condition"] for entry in blind_key.values()} == {
        "neutral",
        "mesugaki",
        "gyaru",
    }
    svg = (output / "trajectories.svg").read_text(encoding="utf-8")
    assert svg.startswith("<svg")
    assert "Negative emotion" in svg
    assert (output / "round_metrics.csv").exists()
    assert (output / "summary.json").exists()
