from contextlib import redirect_stderr
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from liquipedia_ical.cli import main
from liquipedia_ical.matches import Match


class MainTest(unittest.TestCase):
    def test_missing_match_id_preserves_existing_file(self) -> None:
        match = Match(
            start=datetime(2026, 7, 17, 11, tzinfo=UTC),
            team1="A", team2="B", tournament="League", series_format="Bo3",
            source_url="https://liquipedia.net/dota2/League",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "matches.ics"
            original = b"existing calendar\r\n"
            output.write_bytes(original)
            errors = StringIO()
            with (
                patch("liquipedia_ical.cli.load_allowlist", return_value=set()),
                patch("liquipedia_ical.cli.fetch_matches_html", return_value=""),
                patch("liquipedia_ical.cli.parse_upcoming_matches", return_value=[match]),
                redirect_stderr(errors),
            ):
                result = main(["--output", str(output), "--user-agent", "Test/1.0"])
            self.assertEqual(result, 1)
            self.assertEqual(output.read_bytes(), original)
            self.assertIn("Missing Liquipedia match ID", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
