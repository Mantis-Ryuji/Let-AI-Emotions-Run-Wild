"""One-generation real-Gemma probe for activation capture wiring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

import torch
from dotenv import load_dotenv

from agent_distress.config import load_experiment_config
from agent_distress.worker import TransformersGemmaRuntime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiment/reasoning_distress.yaml"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("outputs/smoke/p3-4-activation-probe"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    config_path = args.config if args.config.is_absolute() else project_root / args.config
    output_root = (
        args.output_root if args.output_root.is_absolute() else project_root / args.output_root
    )
    experiment = load_experiment_config(config_path)
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    runtime = TransformersGemmaRuntime(
        experiment.worker,
        activation_config=experiment.activation_capture,
        activation_root=output_root,
    )
    generation = runtime.generate(
        [
            {"role": "system", "content": "You are a concise test Worker."},
            {
                "role": "user",
                "content": (
                    "Reason briefly about whether a claimed mathematical result should be "
                    "checked again, then give a one-sentence conclusion."
                ),
            },
        ],
        {
            "do_sample": False,
            "max_new_tokens": 128,
        },
        seed=0,
        condition="common",
        round_index=1,
    )
    artifacts: list[dict[str, Any]] = []
    for key, raw_path in sorted(generation.activation_files.items()):
        payload = cast(dict[str, Any], torch.load(raw_path, weights_only=True))
        metadata = cast(dict[str, Any], payload["metadata"])
        activation = cast(torch.Tensor, payload["activation"])
        artifacts.append(
            {
                "key": key,
                "shape": list(activation.shape),
                "dtype": str(activation.dtype),
                "device": str(activation.device),
                "all_finite": bool(torch.isfinite(activation).all().item()),
                "l2_norm": float(torch.linalg.vector_norm(activation.float()).item()),
                "metadata_consistent": (
                    list(activation.shape) == metadata["shape"]
                    and str(activation.dtype) == metadata["dtype"]
                    and str(activation.device) == metadata["device"]
                ),
                "token_start": metadata["token_start"],
                "token_end": metadata["token_end"],
                "file_bytes": Path(raw_path).stat().st_size,
                "path": raw_path,
            }
        )
    gpu_memory: dict[str, Any] = {"available": torch.cuda.is_available()}
    if torch.cuda.is_available():
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        gib = 1024**3
        gpu_memory.update(
            {
                "device": torch.cuda.get_device_name(torch.cuda.current_device()),
                "peak_allocated_gib": round(torch.cuda.max_memory_allocated() / gib, 3),
                "peak_reserved_gib": round(torch.cuda.max_memory_reserved() / gib, 3),
                "free_gib": round(free_bytes / gib, 3),
                "total_gib": round(total_bytes / gib, 3),
            }
        )
    result = {
        "model_id": experiment.worker.model_id,
        "generated_characters": len(generation.text),
        "generated_tokens": generation.generated_token_count,
        "hit_max_new_tokens": generation.hit_max_new_tokens,
        "activation_count": len(artifacts),
        "all_finite": all(artifact["all_finite"] for artifact in artifacts),
        "all_metadata_consistent": all(
            artifact["metadata_consistent"] for artifact in artifacts
        ),
        "total_file_bytes": sum(artifact["file_bytes"] for artifact in artifacts),
        "gpu_memory": gpu_memory,
        "artifacts": artifacts,
    }
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "audit.json").write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
