from contextlib import redirect_stdout
from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from liquipedia_ical.cli import main
from liquipedia_ical.calendar import build_calendar, event_uid, read_previous_events
from liquipedia_ical.matches import Match


class MainTest(unittest.TestCase):
    def test_missing_match_id_does_not_block_other_updates(self) -> None:
        match = Match(
            start=datetime(2026, 7, 17, 11, tzinfo=UTC),
            team1="A", team2="B", tournament="League", series_format="Bo3",
            source_url="https://liquipedia.net/dota2/League",
        )
        identified = replace(match, source_id="Match:ID_test")
        updated = replace(identified, start=datetime(2026, 7, 18, 11, tzinfo=UTC))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "matches.ics"
            original = build_calendar([identified], datetime(2026, 7, 17, 2, tzinfo=UTC))
            output.write_bytes(original.encode("utf-8"))
            with (
                patch("liquipedia_ical.cli.load_allowlist", return_value=set()),
                patch("liquipedia_ical.cli.fetch_matches_html", return_value=""),
                patch("liquipedia_ical.cli.parse_upcoming_matches", return_value=[match, updated]),
                self.assertLogs("liquipedia_ical.calendar", level="WARNING") as logs,
                redirect_stdout(StringIO()),
            ):
                result = main(["--output", str(output), "--user-agent", "Test/1.0"])
            self.assertEqual(result, 0)
            events = read_previous_events(output.read_text(encoding="utf-8"))
            self.assertEqual(set(events), {event_uid(identified)})
            self.assertEqual(events[event_uid(identified)].start, updated.start)
            self.assertEqual(events[event_uid(identified)].sequence, 1)
            self.assertIn("missing Liquipedia match ID", logs.output[0])


if __name__ == "__main__":
    unittest.main()
