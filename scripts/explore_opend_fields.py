from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from moomail_finance_ai.config import load_opend_config  # noqa: E402
from moomail_finance_ai.opend import MoomooOpenDClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Explore read-only OpenD fields.")
    parser.add_argument("--env-file", default=None, help="Optional local env file path.")
    parser.add_argument("--output", default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    config = load_opend_config(env_file=args.env_file)
    report = MoomooOpenDClient(config).explore_fields()
    payload = json.dumps(report.model_dump(mode="json"), indent=2)
    print(payload)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

