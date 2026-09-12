"""Preview redacted synthetic events without database or provider calls."""

import argparse
from pathlib import Path

from app.services.log_parser import parse_lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--redact-ipv4", action="store_true")
    args = parser.parse_args()
    with args.path.open(encoding="utf-8") as source:
        result = parse_lines(source, mask_ipv4=args.redact_ipv4)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
