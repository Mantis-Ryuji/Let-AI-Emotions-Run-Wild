"""Create P2 analysis artifacts from one or more completed episode directories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fizzbuzz_agent.analysis import analyze_experiments


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_dirs", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--analysis-seed", type=int, choices=range(10), default=9)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = analyze_experiments(
        args.experiment_dirs,
        args.output_dir,
        analysis_seed=args.analysis_seed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
