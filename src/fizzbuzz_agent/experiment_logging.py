"""Atomic manifest, round log, conversation, and resume storage."""

from __future__ import annotations

import io
import json
import os
import platform
import sys
import uuid
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal, cast

import torch
from pydantic import Field
from torch import nn

from fizzbuzz_agent.agent_types import Condition, ConversationMessage, EpisodeState, RoundRecord
from fizzbuzz_agent.config import StrictModel


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ExperimentManifest(StrictModel):
    experiment_id: str
    episode_seed: int
    status: Literal["running", "completed", "failed"]
    started_at: str
    updated_at: str
    completed_at: str | None = None
    git_commit: str
    runtime_versions: dict[str, str]
    experiment_config_snapshot: str
    model_catalog_snapshot: str
    worker_system_prompt_snapshot: str = ""
    neutral_template_snapshot: str
    persona_prompt_snapshots: dict[str, str]
    feedback_config_snapshots: dict[str, str]
    emotion_judge_prompt_snapshot: str
    notes: list[str] = Field(default_factory=list)


class StoreConflictError(RuntimeError):
    pass


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not-installed"


def runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "platform": sys.platform,
        "pytorch": torch.__version__,
        "transformers": _package_version("transformers"),
        "openai": _package_version("openai"),
        "cuda_runtime": str(torch.version.cuda),
        "cuda_available": str(torch.cuda.is_available()),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
    }


def create_manifest(
    *,
    experiment_id: str,
    episode_seed: int,
    experiment_config_snapshot: str,
    model_catalog_snapshot: str,
    neutral_template_snapshot: str,
    persona_prompt_snapshots: dict[str, str],
    feedback_config_snapshots: dict[str, str],
    emotion_judge_prompt_snapshot: str,
    worker_system_prompt_snapshot: str = "",
    git_commit: str = "unknown",
) -> ExperimentManifest:
    timestamp = utc_now()
    return ExperimentManifest(
        experiment_id=experiment_id,
        episode_seed=episode_seed,
        status="running",
        started_at=timestamp,
        updated_at=timestamp,
        git_commit=git_commit,
        runtime_versions=runtime_versions(),
        experiment_config_snapshot=experiment_config_snapshot,
        model_catalog_snapshot=model_catalog_snapshot,
        worker_system_prompt_snapshot=worker_system_prompt_snapshot,
        neutral_template_snapshot=neutral_template_snapshot,
        persona_prompt_snapshots=persona_prompt_snapshots,
        feedback_config_snapshots=feedback_config_snapshots,
        emotion_judge_prompt_snapshot=emotion_judge_prompt_snapshot,
    )


class ExperimentStore:
    """Filesystem store whose mutable records are replaced atomically."""

    def __init__(self, output_root: str | Path, experiment_id: str) -> None:
        self.experiment_dir = Path(output_root) / experiment_id
        self.manifest_path = self.experiment_dir / "manifest.json"

    def initialize(self, manifest: ExperimentManifest) -> ExperimentManifest:
        self.experiment_dir.mkdir(parents=True, exist_ok=True)
        if self.manifest_path.exists():
            existing = self.load_manifest()
            if (
                existing.experiment_id != manifest.experiment_id
                or existing.episode_seed != manifest.episode_seed
            ):
                raise StoreConflictError("Existing manifest belongs to a different experiment")
            return existing
        self._write_model(self.manifest_path, manifest)
        return manifest

    def load_manifest(self) -> ExperimentManifest:
        return ExperimentManifest.model_validate_json(
            self.manifest_path.read_text(encoding="utf-8")
        )

    def update_manifest_status(
        self,
        status: Literal["running", "completed", "failed"],
    ) -> ExperimentManifest:
        current = self.load_manifest()
        timestamp = utc_now()
        updated = current.model_copy(
            update={
                "status": status,
                "updated_at": timestamp,
                "completed_at": timestamp if status != "running" else None,
            }
        )
        self._write_model(self.manifest_path, updated)
        return updated

    def condition_dir(self, condition: Condition) -> Path:
        path = self.experiment_dir / condition
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_round(self, record: RoundRecord) -> None:
        path = self.condition_dir(record.condition) / "rounds.jsonl"
        records = {item.round_index: item for item in self.load_rounds(record.condition)}
        records[record.round_index] = record
        lines = [
            records[index].model_dump_json(exclude_none=False)
            for index in sorted(records)
        ]
        self._atomic_write_text(path, "\n".join(lines) + "\n")

    def load_rounds(self, condition: Condition) -> list[RoundRecord]:
        path = self.condition_dir(condition) / "rounds.jsonl"
        if not path.exists():
            return []
        records: list[RoundRecord] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(RoundRecord.model_validate_json(line))
            except ValueError as exc:
                raise StoreConflictError(f"Invalid round log at {path}:{line_number}") from exc
        if len({record.round_index for record in records}) != len(records):
            raise StoreConflictError(f"Duplicate round index in {path}")
        return sorted(records, key=lambda item: item.round_index)

    def save_state(self, state: EpisodeState) -> None:
        path = self.condition_dir(state.condition) / "state.json"
        self._write_model(path, state)
        self.save_conversation(state.condition, state.history)

    def load_state(self, condition: Condition) -> EpisodeState | None:
        path = self.condition_dir(condition) / "state.json"
        if not path.exists():
            return None
        return EpisodeState.model_validate_json(path.read_text(encoding="utf-8"))

    def save_conversation(
        self,
        condition: Condition,
        history: list[ConversationMessage],
    ) -> None:
        sections = [
            f"## Round {message.round_index:03d} — {message.role}\n\n{message.content.rstrip()}\n"
            for message in history
        ]
        path = self.condition_dir(condition) / "conversation.md"
        self._atomic_write_text(path, "\n".join(sections))

    def save_checkpoint(
        self,
        condition: Condition,
        tag: Literal["best", "final", "success"],
        model: nn.Module,
        metadata: dict[str, object],
    ) -> Path:
        checkpoint_dir = self.condition_dir(condition) / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        torch.save({"state_dict": model.state_dict(), "metadata": metadata}, buffer)
        path = checkpoint_dir / f"{tag}.pt"
        self._atomic_write_bytes(path, buffer.getvalue())
        return path

    def save_runtime_metrics(self, metrics: dict[str, object]) -> None:
        payload = json.dumps(metrics, ensure_ascii=False, sort_keys=True, indent=2)
        self._atomic_write_text(self.experiment_dir / "runtime_metrics.json", payload + "\n")

    def load_runtime_metrics(self) -> dict[str, object] | None:
        path = self.experiment_dir / "runtime_metrics.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise StoreConflictError("runtime_metrics.json must contain a JSON object")
        return cast(dict[str, object], payload)

    def _write_model(self, path: Path, model: StrictModel) -> None:
        payload = json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        self._atomic_write_text(path, payload + "\n")

    def _atomic_write_text(self, path: Path, content: str) -> None:
        self._atomic_write_bytes(path, content.encode("utf-8"))

    def _atomic_write_bytes(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
