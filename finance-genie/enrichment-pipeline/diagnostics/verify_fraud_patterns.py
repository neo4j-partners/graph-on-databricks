"""Regression diagnostic for the structural fraud patterns in the generated dataset.

Measures the whale-PageRank separation, ten-ring density ratio, anchor-merchant
Jaccard, and column-signal sanity, and exits non-zero on any threshold miss.

Usage:
    uv run diagnostics/verify_fraud_patterns.py
    uv run diagnostics/verify_fraud_patterns.py --input ./data/
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

_AUTOMATED = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AUTOMATED))
sys.path.insert(0, str(_AUTOMATED / "setup"))

from config import SEED  # noqa: E402
from generate_data import build_ground_truth  # noqa: E402

from checks_genie_csv import check_gds_output, check_genie_output, run_genie_csv_check  # noqa: E402
from checks_structural import (  # noqa: E402
    check_anchor_jaccard,
    check_column_signals,
    check_kyc_background_uniqueness,
    check_kyc_story_ring,
    check_ring_density,
    check_whale_pagerank,
    load_data,
    verify_ground_truth_matches,
)
from report import (  # noqa: E402
    build_snapshot,
    compare_snapshots,
    render_comparison_report_rich,
    render_report_rich,
    write_snapshot,
)


def main():
    parser = argparse.ArgumentParser(
        description="Verify the structural fraud patterns in the generated dataset."
    )
    parser.add_argument(
        "--input",
        default="./data",
        help="Directory containing accounts.csv, account_labels.csv, merchants.csv, "
             "transactions.csv, account_links.csv (default: ./data)",
    )
    parser.add_argument(
        "--output-json", metavar="PATH",
        help="Write structural check results as a JSON snapshot to PATH.",
    )
    parser.add_argument(
        "--compare-json", metavar="PATH",
        help="Compare current structural results against a prior JSON snapshot at PATH.",
    )
    parser.add_argument(
        "--tolerance-pct", type=float, default=5.0,
        help="Relative tolerance in percent for float comparisons (default: 5.0).",
    )
    parser.add_argument(
        "--gds-csv", metavar="PATH",
        help="Path to enriched accounts CSV (account_id, is_fraud, risk_score, "
             "community_id, similarity_score). Runs GDS distribution checks.",
    )
    parser.add_argument(
        "--genie-json", metavar="PATH",
        help="Path to a recorded Genie output JSON snapshot. "
             "Validates whale/fraud account split.",
    )
    parser.add_argument(
        "--genie-csv", metavar="PATH", action="append", dest="genie_csvs",
        help=(
            "Path to a Genie output CSV. The check type is auto-detected from "
            "column names: account_id (centrality, before-GDS), "
            "account_id_a+account_id_b (community_pairs, before-GDS), "
            "account_id_a+account_id_b+shared_merchant_count (merchant_overlap, before-GDS), "
            "account_id+risk_score (pagerank, after-GDS), "
            "account_id+community_id (louvain, after-GDS), "
            "account_id_a+account_id_b+similarity_score (similarity, after-GDS). "
            "Repeat the flag to validate multiple CSVs in one run. "
            "Lines starting with # are treated as comments and ignored."
        ),
    )
    args = parser.parse_args()

    input_dir = Path(args.input)
    if not input_dir.exists():
        raise SystemExit(f"Input directory not found: {input_dir.resolve()}")

    print(f"Loading data from {input_dir.resolve()}", file=sys.stderr)
    data = load_data(input_dir)

    random.seed(SEED)
    rings, fraud_ids, whale_ids = build_ground_truth()
    verify_ground_truth_matches(data["account_labels"], fraud_ids)

    print(
        f"Reconstructed: {len(rings)} rings, {len(fraud_ids)} fraud accounts, "
        f"{len(whale_ids)} whales",
        file=sys.stderr,
    )

    gt_path = input_dir / "ground_truth.json"
    ground_truth = json.loads(gt_path.read_text()) if gt_path.exists() else {}
    kyc_gt = ground_truth.get("kyc_story_ring")
    if kyc_gt is None:
        raise SystemExit(
            f"{gt_path} is missing or has no kyc_story_ring entry. "
            "Re-run setup/generate_data.py before verifying."
        )

    checks = [
        check_whale_pagerank(data["account_links"], fraud_ids, whale_ids),
        check_ring_density(data["account_links"], rings),
        check_anchor_jaccard(data["transactions"], rings, fraud_ids),
        check_column_signals(
            data["accounts"], data["transactions"], fraud_ids
        ),
        check_kyc_story_ring(data["customers"], kyc_gt),
        check_kyc_background_uniqueness(data["customers"], kyc_gt),
    ]

    render_report_rich(checks)

    structural_failed = not all(c["passed"] for c in checks)

    snapshot = build_snapshot(checks, SEED)

    if args.output_json:
        write_snapshot(snapshot, Path(args.output_json))

    if args.compare_json:
        baseline = json.loads(Path(args.compare_json).read_text())
        comparison = compare_snapshots(baseline, snapshot, args.tolerance_pct)
        render_comparison_report_rich(comparison)
        if not comparison["passed"]:
            sys.exit(1)

    if args.gds_csv:
        gds_checks = check_gds_output(Path(args.gds_csv), fraud_ids)
        render_report_rich(gds_checks)
        if args.output_json:
            gds_path = Path(args.output_json)
            gds_out = gds_path.with_stem(gds_path.stem + "_gds")
            write_snapshot(build_snapshot(gds_checks, SEED, kind="gds_output"), gds_out)
        if not all(c["passed"] for c in gds_checks):
            sys.exit(1)

    if args.genie_json:
        genie_data = json.loads(Path(args.genie_json).read_text())
        genie_checks = check_genie_output(genie_data, whale_ids, fraud_ids)
        render_report_rich(genie_checks)
        if not all(c["passed"] for c in genie_checks):
            sys.exit(1)

    if args.genie_csvs:
        csv_checks = [
            run_genie_csv_check(Path(p), rings, fraud_ids, whale_ids)
            for p in args.genie_csvs
        ]
        render_report_rich(csv_checks)
        if not all(c["passed"] for c in csv_checks):
            sys.exit(1)

    if structural_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
