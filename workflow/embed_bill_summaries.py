"""Embed the latest available bill summaries with chandar-lab/NeoBERT.

Reads local Congress.gov summary pages; never downloads congressional data.
Model weights are downloaded by Transformers unless already cached.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import importlib.metadata
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL = "chandar-lab/NeoBERT"


class SummaryText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "br", "li", "div"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"p", "li", "div"}:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(html):
    parser = SummaryText()
    parser.feed(html)
    return " ".join("".join(parser.parts).split())


def collect_summaries(directory):
    records, skipped = [], []
    details = sorted((directory / "bills").glob("*/details.json"))
    if not details:
        raise ValueError("No bills/*/details.json found")
    for path in details:
        bill = json.loads(path.read_text())["bill"]
        if bill["congress"] != 119:
            raise ValueError(f"Expected 119th Congress: {path}")
        summary_dir = path.parent / "summaries"
        if not (summary_dir / "completed.json").exists():
            raise ValueError(f"Fetch summaries first with pull_bill_summaries.py: {path.parent.name}")
        summaries = []
        for page in sorted(summary_dir.glob("[0-9]*.json")):
            for summary in json.loads(page.read_text())["summaries"]:
                text = plain_text(summary.get("text") or "")
                if text:
                    summaries.append((summary, text, page))
        if not summaries:
            skipped.append({"bill_id": path.parent.name, "reason": "no_nonempty_summary"})
            continue
        # Select the most recent legislative action, then the latest revision.
        summary, text, page = max(summaries, key=lambda item: (
            item[0].get("actionDate") or "",
            item[0].get("updateDate") or "",
            str(item[0].get("versionCode") or ""),
            item[1],
        ))
        records.append({
            "bill_id": path.parent.name,
            "congress": 119,
            "type": bill["type"],
            "number": bill["number"],
            "action_date": summary.get("actionDate"),
            "update_date": summary.get("updateDate"),
            "version_code": summary.get("versionCode"),
            "source_file": str(page.relative_to(directory)),
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "text": text,
        })
    return records, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Congress download directory with fetched summaries.")
    parser.add_argument("--output", type=Path, help="New output directory; existing paths are refused.")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--revision", default="main", help="Hugging Face model revision; use a commit SHA to pin.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.batch_size < 1 or not 2 <= args.max_length <= 4096:
        parser.error("Use a positive batch size and max length between 2 and 4096")
    records, skipped = collect_summaries(args.input)
    if not records:
        parser.error("No nonempty summaries available to embed")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = args.output or ROOT / "data" / "derived" / "neobert" / timestamp
    if output.exists():
        parser.error(f"Output already exists: {output}")

    # Heavy dependencies are loaded only during an explicit inference run.
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer, set_seed

    if args.device == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA GPU unavailable. Use an HPC GPU allocation, or explicitly choose --device cpu.")
    set_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=args.revision, trust_remote_code=True)
    model = AutoModel.from_pretrained(MODEL, revision=args.revision, trust_remote_code=True)
    model = model.to(args.device).eval()
    output.mkdir(parents=True)
    vectors = []
    with torch.inference_mode():
        for start in range(0, len(records), args.batch_size):
            batch = records[start:start + args.batch_size]
            lengths = [len(tokenizer(record["text"], truncation=False)["input_ids"]) for record in batch]
            inputs = tokenizer(
                [record["text"] for record in batch], padding=True,
                truncation=True, max_length=args.max_length, return_tensors="pt",
            ).to(args.device)
            # The official model card uses the final hidden state of [CLS].
            hidden = model(**inputs).last_hidden_state[:, 0, :]
            vectors.append(hidden.float().cpu().numpy())
            for record, length in zip(batch, lengths):
                record["token_count"] = length
                record["truncated"] = length > args.max_length
            print(f"Embedded {min(start + args.batch_size, len(records))}/{len(records)}", flush=True)
    embeddings = np.concatenate(vectors)
    np.save(output / "embeddings.npy", embeddings)
    with (output / "summaries.jsonl").open("w") as stream:
        for row, record in enumerate(records):
            stream.write(json.dumps({"row": row, **record}) + "\n")
    (output / "skipped.json").write_text(json.dumps(skipped, indent=2) + "\n")
    metadata = {
        "model": MODEL,
        "requested_revision": args.revision,
        "resolved_revision": getattr(model.config, "_commit_hash", None),
        "input": str(args.input.resolve()),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "selection": "latest actionDate, then updateDate, then versionCode and text",
        "pooling": "last_hidden_state CLS; unnormalized",
        "dtype": str(embeddings.dtype),
        "shape": list(embeddings.shape),
        "max_length": args.max_length,
        "truncated_summaries": sum(record["truncated"] for record in records),
        "skipped_bills": len(skipped),
        "device": args.device,
        "batch_size": args.batch_size,
        "seed": args.seed,
        "packages": {name: importlib.metadata.version(name) for name in ["torch", "transformers", "xformers", "numpy"]},
    }
    (output / "completed.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Saved {embeddings.shape} embeddings to {output}")


if __name__ == "__main__":
    main()
