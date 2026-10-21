"""Offline checks of summary selection and download completion semantics."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workflow"))
from embed_bill_summaries import collect_summaries, plain_text
import pull_bill_summaries


class SummaryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bill = self.root / "bills" / "hr1"
        self.bill.mkdir(parents=True)
        (self.bill / "details.json").write_text(json.dumps({
            "bill": {"congress": 119, "type": "HR", "number": "1"},
        }))

    def summaries(self, records):
        directory = self.bill / "summaries"
        directory.mkdir()
        (directory / "00001.json").write_text(json.dumps({"summaries": records}))
        (directory / "completed.json").write_text("{}")

    def test_html_preserves_words_and_entities(self):
        self.assertEqual(plain_text("<p>A <b>bill</b> &amp; act</p><p>Next</p>"), "A bill & act Next")

    def test_latest_action_then_revision(self):
        self.summaries([
            {"actionDate": "2025-01-01", "updateDate": "2026-01-01", "text": "Old action"},
            {"actionDate": "2025-02-01", "updateDate": "2025-03-01", "text": "First revision"},
            {"actionDate": "2025-02-01", "updateDate": "2025-04-01", "text": "<p>Latest revision</p>"},
        ])
        records, skipped = collect_summaries(self.root)
        self.assertEqual(records[0]["text"], "Latest revision")
        self.assertEqual(records[0]["bill_id"], "hr1")
        self.assertEqual(skipped, [])

    def test_missing_summary_is_recorded(self):
        self.summaries([])
        records, skipped = collect_summaries(self.root)
        self.assertEqual(records, [])
        self.assertEqual(skipped[0]["reason"], "no_nonempty_summary")

    def test_unfetched_summaries_fail_before_inference(self):
        with self.assertRaisesRegex(ValueError, "Fetch summaries first"):
            collect_summaries(self.root)

    def test_failed_download_cannot_be_mistaken_for_complete(self):
        def interrupted(url, directory, api_key):
            directory.mkdir()
            (directory / "00001.json").write_text('{"summaries": []}')
            raise RuntimeError("interrupted")
            yield

        with patch("sys.argv", ["pull", str(self.root)]), patch.dict("os.environ", {"CONGRESS_API_KEY": "test"}), patch.object(pull_bill_summaries, "pages", interrupted):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                pull_bill_summaries.main()
        self.assertFalse((self.bill / "summaries").exists())
        self.assertEqual(len(list(self.bill.glob("summaries.partial-*"))), 1)


if __name__ == "__main__":
    unittest.main()
