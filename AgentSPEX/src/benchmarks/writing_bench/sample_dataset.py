"""Sample a balanced subset from WritingBench by primary domain.

Randomly selects N questions per primary domain (domain1) and writes a new
JSONL file. Also prints the selected indices for direct use with run.py's
``--query-indices`` flag.

Usage:
    python src/benchmarks/writing_bench/sample_dataset.py                # defaults: 20 per domain, seed=42
    python src/benchmarks/writing_bench/sample_dataset.py --per-domain 10 --seed 123
"""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"
_BENCHMARK_PATH = _DATA_DIR / "benchmark_all.jsonl"
_DEFAULT_PER_DOMAIN = 20
_DEFAULT_SEED = 42


def load_queries(path: Path) -> list[dict]:
    queries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                queries.append(json.loads(line))
    return queries


def sample_by_domain(queries: list[dict], per_domain: int, seed: int) -> list[dict]:
    rng = random.Random(seed)

    by_domain: dict[str, list[dict]] = defaultdict(list)
    for q in queries:
        by_domain[q["domain1"]].append(q)

    sampled: list[dict] = []
    for domain in sorted(by_domain):
        pool = by_domain[domain]
        n = min(per_domain, len(pool))
        sampled.extend(rng.sample(pool, n))

    # Sort by original index for deterministic ordering
    sampled.sort(key=lambda q: q["index"])
    return sampled


def main():
    parser = argparse.ArgumentParser(
        description="Sample a balanced subset from WritingBench by primary domain."
    )
    parser.add_argument(
        "--per-domain",
        type=int,
        default=_DEFAULT_PER_DOMAIN,
        help=f"Number of questions to sample per domain (default: {_DEFAULT_PER_DOMAIN})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=_DEFAULT_SEED,
        help=f"Random seed for reproducibility (default: {_DEFAULT_SEED})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSONL path (default: data/benchmark_sampled_{per_domain}x{num_domains}.jsonl)",
    )
    args = parser.parse_args()

    queries = load_queries(_BENCHMARK_PATH)
    sampled = sample_by_domain(queries, args.per_domain, args.seed)

    # Determine output path
    domains = sorted(set(q["domain1"] for q in sampled))
    num_domains = len(domains)
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = (
            _DATA_DIR / f"benchmark_sampled_{args.per_domain}x{num_domains}.jsonl"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for q in sampled:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    # Print summary
    print(f"Seed: {args.seed}")
    print(f"Sampled {len(sampled)} questions ({args.per_domain} per domain):\n")
    from collections import Counter

    counts = Counter(q["domain1"] for q in sampled)
    for domain in sorted(counts):
        print(f"  {domain}: {counts[domain]}")

    print(f"\nSaved to: {out_path}")

    # Print indices for use with run.py --query-indices
    indices = [q["index"] for q in sampled]
    print(f"\n--query-indices for run.py:\n{' '.join(map(str, indices))}")


if __name__ == "__main__":
    main()
