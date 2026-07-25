from datetime import UTC, datetime, timedelta
import gzip
import json
from urllib.parse import parse_qs, urlparse
import unittest
from unittest.mock import patch

from liquipedia_ical.matches import (
    LiquipediaError,
    fetch_matches_html,
    parse_upcoming_matches,
)


HTML = """
<div data-toggle-area-content="1">
  <div class="match-info">
    <span class="timer-object" data-timestamp="1784286000">date</span>
    <div class="match-info-header">
      <div class="match-info-header-opponent"><span class="name">Team &amp; One</span></div>
      <div class="match-info-header-scoreholder">
        <span class="match-info-header-scoreholder-lower">(Bo3)</span>
      </div>
      <div class="match-info-header-opponent"><span class="name">Team Two</span></div>
    </div>
    <div class="match-info-tournament-name">
      <a href="/dota2/Test_League">Test League - Playoffs</a>
    </div>
    <div class="match-info-links">
      <a href="/dota2/index.php?title=Match:ID_abc_R01-M001&amp;action=edit&amp;redlink=1">details</a>
    </div>
  </div>
</div>
<div data-toggle-area-content="2">
  <div class="match-info">
    <span class="timer-object" data-timestamp="1">completed</span>
    <div class="match-info-header-opponent"><span class="name">Old One</span></div>
    <div class="match-info-header-opponent"><span class="name">Old Two</span></div>
  </div>
</div>
"""

BRACKET_SEED_HTML = """
<div id="liquipedia-tier-one-matches">
  <div class="match-info">
    <span class="timer-object" data-timestamp="1785747600">date</span>
    <div class="match-info-header">
      <div class="match-info-header-opponent">
        <div class="brkts-opponent-block-literal flipped">A3</div>
      </div>
      <div class="match-info-header-scoreholder">
        <span class="match-info-header-scoreholder-lower">(Bo3)</span>
      </div>
      <div class="match-info-header-opponent">
        <div class="brkts-opponent-block-literal">B4</div>
      </div>
    </div>
    <div class="match-info-tournament-name">
      <a href="/dota2/1win_Essence/2#Playoffs">1win Essence II - Playoffs</a>
    </div>
    <div class="match-info-links">
      <a href="/dota2/index.php?title=Match:ID_PrdW9jwDqV_R01-M001&amp;action=edit">
        details
      </a>
    </div>
  </div>
</div>
"""


class ParseUpcomingMatchesTest(unittest.TestCase):
    def test_parses_only_upcoming_match_cards(self) -> None:
        matches = parse_upcoming_matches(HTML)

        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match.start, datetime(2026, 7, 17, 11, 0, tzinfo=UTC))
        self.assertEqual(match.team1, "Team & One")
        self.assertEqual(match.team2, "Team Two")
        self.assertEqual(match.tournament, "Test League - Playoffs")
        self.assertEqual(match.series_format, "Bo3")
        self.assertEqual(match.duration, timedelta(hours=3))
        self.assertEqual(match.source_id, "Match:ID_abc_R01-M001")
        self.assertEqual(
            match.source_url,
            "https://liquipedia.net/dota2/Match:ID_abc_R01-M001",
        )

    def test_parses_bracket_seed_opponents_without_name_elements(self) -> None:
        matches = parse_upcoming_matches(BRACKET_SEED_HTML)

        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match.team1, "A3")
        self.assertEqual(match.team2, "B4")
        self.assertEqual(match.series_format, "Bo3")
        self.assertEqual(match.source_id, "Match:ID_PrdW9jwDqV_R01-M001")

    def test_refuses_to_return_an_empty_calendar(self) -> None:
        with self.assertRaises(LiquipediaError):
            parse_upcoming_matches('<div data-toggle-area-content="1"></div>')

    def test_accepts_a_trusted_empty_tier_one_response(self) -> None:
        matches = parse_upcoming_matches('<div id="liquipedia-tier-one-matches"></div>')

        self.assertEqual(matches, [])

    def test_refuses_to_return_partial_data(self) -> None:
        malformed = HTML.replace(
            '</div>\n</div>\n<div data-toggle-area-content="2">',
            '<div class="match-info">missing required fields</div></div>\n'
            '<div data-toggle-area-content="2">',
            1,
        )

        with self.assertRaises(LiquipediaError):
            parse_upcoming_matches(malformed)

    @patch("liquipedia_ical.matches.urlopen")
    def test_fetch_filters_to_tier_one_at_the_source(self, mock_urlopen) -> None:
        response = _Response(
            gzip.compress(json.dumps({"parse": {"text": HTML}}).encode("utf-8"))
        )
        mock_urlopen.return_value = response

        self.assertEqual(fetch_matches_html("Test/1.0 (test@example.com)"), HTML)
        request = mock_urlopen.call_args.args[0]
        query = parse_qs(urlparse(request.full_url).query)
        self.assertNotIn("page", query)
        self.assertEqual(query["title"], ["Liquipedia:Matches"])
        self.assertIn('id="liquipedia-tier-one-matches"', query["text"][0])
        self.assertIn("filterbuttons-liquipediatier=1", query["text"][0])
        self.assertIn("type=upcoming", query["text"][0])


class _Response:
    headers = {"Content-Encoding": "gzip"}

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


if __name__ == "__main__":
    unittest.main()
