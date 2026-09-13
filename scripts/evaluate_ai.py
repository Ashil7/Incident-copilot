"""Run synthetic offline evaluation; live provider use requires two explicit flags."""

import argparse
import json
from pathlib import Path

from app.config import PROJECT_ROOT, Settings
from app.evaluation import evaluate, load_dataset
from app.services.llm_service import get_provider

DEFAULT_DATASET = PROJECT_ROOT / "evaluations" / "incident_analysis.json"
DEFAULT_REPORT = PROJECT_ROOT / "reports" / "offline-evaluation.json"


def write_report(report, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-cost", action="store_true")
    args = parser.parse_args()
    if args.live != args.confirm_cost:
        parser.error("live evaluation requires both --live and --confirm-cost")
    try:
        provider = get_provider(Settings()) if args.live else None
        report = evaluate(load_dataset(args.dataset), provider)
        write_report(report, args.output)
        metrics = report["metrics"]
        print(
            f"PASS: {report['mode']} evaluation completed for {report['case_count']} synthetic cases."
        )
        print(
            "Scores: parser={parser_success_rate:.4f}, fields={field_accuracy:.4f}, "
            "redaction={redaction_recall:.4f}, statistics={statistics_accuracy:.4f}, "
            "evidence={evidence_reference_validity:.4f}, type={incident_type_agreement:.4f}, "
            "unsupported={unsupported_claim_rate:.4f}, gaps={information_gap_recall:.4f}".format(
                **metrics
            )
        )
        print("Report:", args.output)
    except Exception:
        print(
            "Evaluation failed. Check the synthetic dataset/provider configuration; no payloads printed."
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
