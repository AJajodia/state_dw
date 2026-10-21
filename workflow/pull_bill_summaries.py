"""Fetch summary pages for bills in an existing 119th Congress download."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from pull_congress import BASE_URL, pages, save_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Congress download directory containing bills/.")
    args = parser.parse_args()
    details = sorted((args.input / "bills").glob("*/details.json"))
    if not details:
        parser.error("No bills/*/details.json found")
    api_key = os.environ.get("CONGRESS_API_KEY") or os.environ.get("congresskey")
    if not api_key:
        parser.error("Set CONGRESS_API_KEY or load .env containing congresskey")
    for index, path in enumerate(details, 1):
        bill = json.loads(path.read_text())["bill"]
        if bill["congress"] != 119:
            raise ValueError(f"Expected 119th Congress: {path}")
        destination = path.parent / "summaries"
        if destination.exists():
            print(f"Already saved: {path.parent.name}", flush=True)
            continue
        # Rename only after all pages arrive, so retries cannot mistake a partial
        # collection for a completed one. Original responses remain unchanged.
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        temporary = path.parent / f"summaries.partial-{timestamp}"
        url = f"{BASE_URL}/bill/119/{bill['type'].lower()}/{bill['number']}/summaries"
        count = 0
        for page in pages(url, temporary, api_key):
            count += len(page["summaries"])
        save_json(temporary / "completed.json", {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "summary_count": count,
            "source": url,
        })
        temporary.rename(destination)
        print(f"{path.parent.name}: {count} summaries ({index}/{len(details)})", flush=True)


if __name__ == "__main__":
    main()
