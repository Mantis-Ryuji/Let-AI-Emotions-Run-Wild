"""One-generation real-Gemma probe for P3-4 activation capture wiring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

import torch
from dotenv import load_dotenv

from fizzbuzz_agent.config import load_experiment_config
from fizzbuzz_agent.worker import TransformersGemmaRuntime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/experiment/fizzbuzz_agent.yaml"),
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
                    "Write two short reflective sentences, then an "
                    "<experiment_proposal> JSON block."
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
        artifacts.append(
            {
                "key": key,
                "shape": metadata["shape"],
                "dtype": metadata["dtype"],
                "device": metadata["device"],
                "token_start": metadata["token_start"],
                "token_end": metadata["token_end"],
                "path": raw_path,
            }
        )
    print(
        json.dumps(
            {
                "model_id": experiment.worker.model_id,
                "generated_characters": len(generation.text),
                "activation_count": len(artifacts),
                "artifacts": artifacts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
