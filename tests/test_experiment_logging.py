from __future__ import annotations

from pathlib import Path
from typing import Literal

import torch
from torch import nn

from fizzbuzz_agent.agent_types import ConversationMessage, EpisodeState, RoundRecord
from fizzbuzz_agent.experiment_logging import (
    ExperimentManifest,
    ExperimentStore,
    create_manifest,
)


def make_manifest(experiment_id: str = "test-run", seed: int = 0) -> ExperimentManifest:
    return create_manifest(
        experiment_id=experiment_id,
        episode_seed=seed,
        experiment_config_snapshot="experiment: snapshot",
        model_catalog_snapshot="catalog: snapshot",
        neutral_template_snapshot="neutral snapshot",
        persona_prompt_snapshots={"mesugaki": "m", "gyaru": "g"},
        feedback_config_snapshots={"mesugaki": "m", "gyaru": "g"},
        emotion_judge_prompt_snapshot="judge snapshot",
    )


def make_round(
    incorrect_count: int = 10,
    status: Literal[
        "pending_feedback",
        "feedback_failed",
        "completed",
        "invalid",
        "training_failed",
    ] = "completed",
) -> RoundRecord:
    return RoundRecord(
        round_index=1,
        condition="neutral",
        round_status=status,
        worker_request={"seed": 5},
        worker_raw_output="worker",
        worker_narrative="worker",
        proposal_raw="{}",
        proposal_parsed={},
        proposal_valid=True,
        violation_codes=[],
        config_hash="a" * 64,
        model_family="mlp",
        parameter_count=100,
        worker_generation_seed=5,
        training_seed=7,
        dataloader_seed=8,
        training_status="completed",
        training_metrics={},
        verification_metrics={},
        public_verdict={
            "status": "failed",
            "incorrect_count": incorrect_count,
            "previous_incorrect_count": None,
            "best_incorrect_count": incorrect_count,
            "improvement": None,
            "regression_from_best": 0,
        },
        timestamps={"started": "now"},
    )


def test_atomic_round_upsert_and_resume_state(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path, "test-run")
    store.initialize(make_manifest())
    store.save_round(make_round(10))
    store.save_round(make_round(8))

    rounds = store.load_rounds("neutral")
    assert len(rounds) == 1
    assert rounds[0].public_verdict["incorrect_count"] == 8

    state = EpisodeState(
        experiment_id="test-run",
        episode_seed=0,
        condition="neutral",
        history=[ConversationMessage(role="worker", content="hello", round_index=1)],
        next_round=2,
        previous_incorrect_count=8,
        best_incorrect_count=8,
    )
    store.save_state(state)
    assert store.load_state("neutral") == state
    conversation = (store.condition_dir("neutral") / "conversation.md").read_text(
        encoding="utf-8"
    )
    assert "Round 001 — worker" in conversation
    assert "hello" in conversation
    assert not list(store.experiment_dir.rglob("*.tmp"))


def test_manifest_snapshots_status_and_trusted_checkpoint(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path, "test-run")
    manifest = store.initialize(make_manifest())
    assert manifest.runtime_versions["python"]
    assert manifest.model_catalog_snapshot == "catalog: snapshot"

    model = nn.Linear(2, 4)
    checkpoint = store.save_checkpoint("neutral", "best", model, {"round": 1})
    payload = torch.load(checkpoint, weights_only=False)
    assert payload["metadata"] == {"round": 1}
    assert set(payload["state_dict"]) == {"weight", "bias"}

    completed = store.update_manifest_status("completed")
    assert completed.status == "completed"
    assert completed.completed_at is not None
