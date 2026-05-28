from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from moomail_finance_ai.research import LocalSentimentAgent  # noqa: E402
from moomail_finance_ai.research_fixtures import build_sample_research_store  # noqa: E402
from moomail_finance_ai.schemas import SentimentScopeItem  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local research Sentiment Agent demo.")
    parser.add_argument("tickers", nargs="*", default=["AAPL"], help="Tickers to analyze.")
    parser.add_argument("--output", default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    scope = [
        SentimentScopeItem(ticker=ticker.upper(), reason="Manual research demo scope.")
        for ticker in args.tickers
    ]
    packet = LocalSentimentAgent(build_sample_research_store()).run(scope)
    payload = json.dumps(packet.model_dump(mode="json"), indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()

