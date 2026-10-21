"""Download 119th Congress bill metadata and cosponsors from Congress.gov."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


BASE_URL = "https://api.congress.gov/v3"
CONGRESS = 119
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "congress"


def get_json(url, api_key):
    """Fetch a page, pacing requests and retrying temporary failures."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "api.congress.gov":
        raise ValueError("Unexpected API host in pagination URL")
    params = dict(parse_qsl(parts.query))
    params.pop("api_key", None)
    params.update(format="json", limit="250")
    url = urlunsplit(parts._replace(query=urlencode(params)))
    request = Request(url, headers={
        "X-Api-Key": api_key,
        "User-Agent": "Mozilla/5.0 (compatible; state-dw research downloader)",
        "Accept": "application/json",
    })
    for attempt in range(6):
        time.sleep(0.8)
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code != 429 and not 500 <= error.code < 600:
                raise
            if attempt == 5:
                raise
            delay = error.headers.get("Retry-After", "")
            time.sleep(float(delay) if delay.isdigit() else 2 ** (attempt + 1))
        except (URLError, TimeoutError):
            if attempt == 5:
                raise
            time.sleep(2 ** (attempt + 1))


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as output:
        json.dump(data, output, indent=2)
        output.write("\n")


def pages(url, directory, api_key):
    page = 1
    while url:
        data = get_json(url, api_key)
        save_json(directory / f"{page:05d}.json", data)
        yield data
        url = data.get("pagination", {}).get("next")
        page += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bill-type", choices=["hr", "s", "hjres", "sjres", "hconres", "sconres", "hres", "sres"],
        help="Restrict to one measure type; default includes bills and resolutions.",
    )
    parser.add_argument("--max-bills", type=int, help="Limit downloads for a trial run.")
    parser.add_argument("--sample-size", type=int, help="Random sample without replacement from the full listing.")
    parser.add_argument("--seed", type=int, default=42, help="Random sampling seed (default: 42).")
    args = parser.parse_args()
    if args.max_bills is not None and args.max_bills < 1:
        parser.error("--max-bills must be positive")
    if args.sample_size is not None and args.sample_size < 1:
        parser.error("--sample-size must be positive")
    if args.sample_size is not None and args.max_bills is not None:
        parser.error("Use either --sample-size or --max-bills")
    api_key = os.environ.get("CONGRESS_API_KEY") or os.environ.get("congresskey")
    if not api_key:
        parser.error("Set CONGRESS_API_KEY to your Congress.gov API key")

    started = datetime.now(timezone.utc)
    directory = RAW_DIR / str(CONGRESS) / started.strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    metadata = {
        "congress": CONGRESS,
        "source": BASE_URL,
        "started_at": started.isoformat(),
        "bill_type": args.bill_type,
        "max_bills": args.max_bills,
        "sample_size": args.sample_size,
        "seed": args.seed,
        "status": "in_progress",
    }
    save_json(directory / "run.json", metadata)
    url = f"{BASE_URL}/bill/{CONGRESS}"
    if args.bill_type:
        url += f"/{args.bill_type}"
    listing = pages(url, directory / "bill_pages", api_key)
    if args.sample_size is not None:
        population = {}
        for page in listing:
            for bill in page["bills"]:
                population[(bill["type"].lower(), int(bill["number"]))] = bill
        ordered = [population[key] for key in sorted(population)]
        if len(ordered) < args.sample_size:
            raise ValueError(f"Requested {args.sample_size} bills; only {len(ordered)} available")
        sample = random.Random(args.seed).sample(ordered, args.sample_size)
        save_json(directory / "sample.json", {
            "population_size": len(ordered),
            "seed": args.seed,
            "bills": sample,
        })
        print(f"Sampled {len(sample)} of {len(ordered)} measures", flush=True)
        listing = [{"bills": sample}]
    seen = set()
    for page in listing:
        for bill in page["bills"]:
            bill_type = bill["type"].lower()
            number = bill["number"]
            bill_id = f"{bill_type}{number}"
            if bill_id in seen:
                continue
            bill_url = f"{BASE_URL}/bill/{CONGRESS}/{bill_type}/{number}"
            bill_directory = directory / "bills" / bill_id
            save_json(bill_directory / "details.json", get_json(bill_url, api_key))
            for _ in pages(f"{bill_url}/cosponsors", bill_directory / "cosponsors", api_key):
                pass
            seen.add(bill_id)
            print(f"Downloaded {bill_id} ({len(seen)} bills)", flush=True)
            if args.max_bills and len(seen) >= args.max_bills:
                break
        if args.max_bills and len(seen) >= args.max_bills:
            break
    save_json(directory / "completed.json", {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "bills_downloaded": len(seen),
        "limited_run": args.max_bills is not None or args.sample_size is not None,
    })
    print(f"Saved to {directory}")


if __name__ == "__main__":
    main()
