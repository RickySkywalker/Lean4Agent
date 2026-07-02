"""Sample a fixed-size subset of ELAIPBench and save as parquet.

Mirrors the layout used for SWE-bench subsets:
    <out_dir>/test.parquet

Usage:
    python experiments/elaipbench/sample_subset.py \
        --size 100 \
        --seed 42 \
        --out-dir data/test_dataset/ELAIPBench_100problems_subset
"""

import argparse
import random
from pathlib import Path

import pandas as pd
from datasets import load_dataset


def main():
    parser = argparse.ArgumentParser(description="Sample a subset of ELAIPBench")
    parser.add_argument("--size", type=int, default=100, help="Number of questions to sample")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--stratify",
        action="store_true",
        help="Stratify the sample by question_type to preserve SA-MCQ/MA-MCQ ratio",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        required=True,
        help="Output directory; test.parquet will be written here",
    )
    args = parser.parse_args()

    print("Loading ELAIPBench from HuggingFace...")
    ds = load_dataset(
        "KangKang625/ELAIPBench", data_files="elabench.jsonl", split="train"
    )
    rows = [dict(r) for r in ds]
    print(f"Full dataset: {len(rows)} rows")

    if args.size > len(rows):
        raise ValueError(
            f"Requested size ({args.size}) exceeds dataset size ({len(rows)})."
        )

    rng = random.Random(args.seed)

    if args.stratify:
        by_type: dict = {}
        for r in rows:
            by_type.setdefault(r["question_type"], []).append(r)
        # Floor allocation per stratum, distribute remainder by descending fractional part.
        total = sum(len(v) for v in by_type.values())
        raw_alloc = {t: args.size * len(v) / total for t, v in by_type.items()}
        floor_alloc = {t: int(v) for t, v in raw_alloc.items()}
        remainder = args.size - sum(floor_alloc.values())
        leftovers = sorted(
            ((raw_alloc[t] - floor_alloc[t], t) for t in raw_alloc),
            reverse=True,
        )
        for _, t in leftovers[:remainder]:
            floor_alloc[t] += 1
        sampled = []
        for t, n in floor_alloc.items():
            sampled.extend(rng.sample(by_type[t], n))
        rng.shuffle(sampled)
    else:
        sampled = rng.sample(rows, args.size)

    print(f"Sampled {len(sampled)} rows")
    print(
        "Per-type:",
        {t: sum(1 for r in sampled if r["question_type"] == t) for t in
         sorted({r["question_type"] for r in sampled})},
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "test.parquet"

    df = pd.DataFrame(sampled)
    df.to_parquet(out_path, index=False)
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"Wrote {out_path} ({size_mb:.2f} MB, {len(df)} rows, columns={list(df.columns)})")


if __name__ == "__main__":
    main()
