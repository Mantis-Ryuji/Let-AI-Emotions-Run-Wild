from __future__ import annotations

from pathlib import Path

from fizzbuzz_agent.dry_run import run_dry_episode


def test_runnable_dry_run_creates_complete_three_condition_logs(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    summary = run_dry_episode(
        project_root=project_root,
        output_root=tmp_path,
        experiment_id="runnable-dry-run",
        episode_seed=0,
        max_rounds=3,
    )

    assert summary["worker_calls"] == 7
    assert summary["training_calls"] == 7
    assert summary["feedback_calls"] == 9
    experiment_dir = tmp_path / "runnable-dry-run"
    assert (experiment_dir / "manifest.json").exists()
    assert len((experiment_dir / "common/rounds.jsonl").read_text().splitlines()) == 1
    for condition in ("neutral", "mesugaki", "gyaru"):
        assert len((experiment_dir / condition / "rounds.jsonl").read_text().splitlines()) == 3
        assert (experiment_dir / condition / "conversation.md").exists()

