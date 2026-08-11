"""Create paired cross-seed activation analysis artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_distress.activation_analysis import analyze_activations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_dirs", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--invalid-activation-policy",
        choices=("error", "exclude"),
        default="error",
        help=(
            "How to handle non-finite or zero-norm activation tensors. "
            "The default 'error' stops immediately; 'exclude' records and omits only "
            "affected paired distances."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = analyze_activations(
        args.experiment_dirs,
        args.output_dir,
        invalid_activation_policy=args.invalid_activation_policy,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
