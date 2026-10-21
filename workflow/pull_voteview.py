"""Save an unchanged snapshot of Voteview's 119th Congress member ideology CSV.

Run with: uv run python workflow/pull_voteview.py
Field definitions: https://voteview.com/articles/data_help_members
NOMINATE estimates describe career ideology; Nokken-Poole estimates are specific
to a Congress. Both are retained, along with missing and conditional estimates.
"""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen


CONGRESS = 119
SOURCE = "https://voteview.com/static/data/out/members/HS119_members.csv"
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "voteview" / "119"


def validate_csv(content):
    """Reject unexpected exports without dropping rows with unavailable scores."""
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    required = {
        "congress", "chamber", "icpsr", "bioguide_id", "bioname",
        "nominate_dim1", "nominate_dim2", "conditional",
        "nokken_poole_dim1", "nokken_poole_dim2",
    }
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"Voteview CSV is missing columns: {sorted(missing)}")
    rows = list(reader)
    if not rows:
        raise ValueError("Voteview CSV contains no members")
    if any(row["congress"] != str(CONGRESS) for row in rows):
        raise ValueError("Voteview CSV contains a Congress other than 119")
    chambers = {row["chamber"] for row in rows}
    if not {"House", "Senate"}.issubset(chambers):
        raise ValueError("Voteview CSV must include both House and Senate")
    if chambers - {"House", "Senate", "President"}:
        raise ValueError(f"Unexpected chambers: {sorted(chambers)}")
    return {
        "rows": len(rows),
        "columns": reader.fieldnames,
        "rows_by_chamber": {
            chamber: sum(row["chamber"] == chamber for row in rows)
            for chamber in sorted(chambers)
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=RAW_DIR,
                        help="Parent directory for timestamped raw snapshots.")
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    request = Request(SOURCE, headers={"User-Agent": "state-dw research downloader"})
    with urlopen(request, timeout=120) as response:
        content = response.read()
        http_metadata = {
            "resolved_url": response.geturl(),
            "last_modified": response.headers.get("Last-Modified"),
            "etag": response.headers.get("ETag"),
        }
    summary = validate_csv(content)
    directory = args.output_dir / started.strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    with (directory / "HS119_members.csv").open("xb") as output:
        output.write(content)
    metadata = {
        "congress": CONGRESS,
        "source_url": SOURCE,
        "documentation_url": "https://voteview.com/articles/data_help_members",
        "retrieval_started_at": started.isoformat(),
        "retrieval_finished_at": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(content).hexdigest(),
        **http_metadata,
        **summary,
        "notes": "Unchanged source CSV; missing scores and all source rows retained. "
                 "Conditional estimates may change as Voteview updates its data.",
    }
    with (directory / "metadata.json").open("x") as output:
        json.dump(metadata, output, indent=2)
        output.write("\n")
    print(f"Saved {summary['rows']} member rows to {directory}")


if __name__ == "__main__":
    main()
