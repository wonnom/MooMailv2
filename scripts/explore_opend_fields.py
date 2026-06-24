from __future__ import annotations

import argparse
import json
from pathlib import Path

from moomail_finance_ai.config import load_opend_config
from moomail_finance_ai.opend import MoomooOpenDClient


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
