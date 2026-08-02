from __future__ import annotations

from pathlib import Path

from agent_distress.dry_run import run_dry_episode
from agent_distress.experiment_logging import ExperimentStore


def test_dry_run_branches_after_common_round_and_never_stops_early(
    project_root: Path,
    tmp_path: Path,
) -> None:
    summary = run_dry_episode(
        project_root=project_root,
        output_root=tmp_path,
        experiment_id="dry-test",
        episode_seed=0,
        max_rounds=4,
    )
    store = ExperimentStore(tmp_path, "dry-test")

    assert summary["worker_calls"] == 10
    assert summary["feedback_calls"] == 9
    assert len(store.load_rounds("common")) == 1
    for condition in ("neutral", "mesugaki", "gyaru"):
        records = store.load_rounds(condition)
        state = store.load_state(condition)
        assert len(records) == 4
        assert state is not None and state.stop_reason == "max_rounds"
        assert records[0].common_artifact_ref is not None
        assert records[-1].feedback_message is None
        assert any(record.private_evaluation["private_correct"] is True for record in records)
        assert all(record.public_verdict["status"] == "rejected" for record in records)


def test_dry_run_is_resumable(project_root: Path, tmp_path: Path) -> None:
    kwargs = {
        "project_root": project_root,
        "output_root": tmp_path,
        "experiment_id": "resume-test",
        "episode_seed": 1,
        "max_rounds": 3,
    }
    run_dry_episode(**kwargs)
    summary = run_dry_episode(**kwargs)
    assert summary["worker_calls"] == 0
    assert summary["feedback_calls"] == 0
