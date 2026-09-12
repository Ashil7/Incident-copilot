"""Preview deterministic statistics and evidence from synthetic log files."""

import argparse
import json
from pathlib import Path

from app.config import Settings
from app.services.error_signatures import with_error_signatures
from app.services.evidence_selector import select_evidence
from app.services.log_parser import parse_lines
from app.services.statistics import calculate_statistics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-evidence", type=int)
    args = parser.parse_args()
    limit = args.max_evidence if args.max_evidence is not None else Settings().max_evidence_items
    with args.path.open(encoding="utf-8") as source:
        parsed = parse_lines(source, mask_ipv4=True)
    events = with_error_signatures(parsed.events)
    result = {
        "statistics": calculate_statistics(parsed),
        "evidence": [
            item.model_dump(mode="json") for item in select_evidence(events, max_items=limit)
        ],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
