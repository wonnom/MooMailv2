from __future__ import annotations

import argparse
import json

from moomail_finance_ai.config import load_opend_config
from moomail_finance_ai.opend import MoomooOpenDClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Check read-only OpenD connectivity.")
    parser.add_argument("--env-file", default=None, help="Optional local env file path.")
    args = parser.parse_args()

    config = load_opend_config(env_file=args.env_file)
    status = MoomooOpenDClient(config).check_connection()
    print(json.dumps(status.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
