from datetime import UTC, datetime, timedelta
import gzip
import json
from pathlib import Path
import tempfile
from urllib.parse import parse_qs, urlparse
import unittest
from unittest.mock import patch

from liquipedia_ical.matches import (
    LiquipediaError,
    fetch_matches_html,
    load_allowlist,
    parse_upcoming_matches,
)


def match_card(
    tournament: str = "Test League - Playoffs",
    match_id: str = "abc_R01-M001",
    timestamp: str = "1784286000",
) -> str:
    return f"""
<div class="match-info">
  <span class="timer-object" data-timestamp="{timestamp}">date</span>
  <div class="match-info-header">
    <div class="match-info-header-opponent"><span class="name">Team &amp; One</span></div>
    <span class="match-info-header-scoreholder-lower">(Bo3)</span>
    <div class="match-info-header-opponent"><span class="name">Team Two</span></div>
  </div>
  <div class="match-info-tournament-name">
    <a href="/dota2/Test_League">{tournament}</a>
  </div>
  <div class="match-info-links">
    <a href="/dota2/index.php?title=Match:ID_{match_id}&amp;action=edit">details</a>
  </div>
</div>
"""


def tier_section(tier: int, *cards: str) -> str:
    return f'<div id="liquipedia-tier-{tier}-matches">{"".join(cards)}</div>'


HTML = tier_section(1, match_card())

BRACKET_SEED_HTML = """
<div id="liquipedia-tier-1-matches">
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
    def test_loads_allowlist_with_comments_and_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "allowlist.txt"
            path.write_text("# comment\n\n PGL Wallachia Season 9 \n", encoding="utf-8")
            self.assertEqual(load_allowlist(path), {"PGL Wallachia Season 9"})

    def test_includes_only_allowlisted_tier_two_tournaments_and_stages(self) -> None:
        html = tier_section(1, match_card()) + tier_section(
            2,
            match_card("PGL Wallachia S9 - Round 1", "allowed"),
            match_card("PGL Wallachia S90 - Round 1", "other"),
        )
        matches = parse_upcoming_matches(
            html, tier_two_allowlist={"PGL Wallachia Season 9"}
        )
        self.assertEqual([match.liquipedia_tier for match in matches], [1, 2])
        self.assertEqual(matches[1].tournament, "PGL Wallachia S9 - Round 1")

    def test_empty_tier_two_section_is_valid(self) -> None:
        matches = parse_upcoming_matches(
            tier_section(1) + tier_section(2),
            tier_two_allowlist={"PGL Wallachia Season 9"},
        )
        self.assertEqual(matches, [])

    def test_missing_tier_section_is_rejected(self) -> None:
        for tier in (1, 2):
            with self.subTest(tier=tier), self.assertRaises(LiquipediaError):
                parse_upcoming_matches(
                    tier_section(tier),
                    tier_two_allowlist={"PGL Wallachia Season 9"},
                )

    def test_malformed_allowed_match_is_rejected(self) -> None:
        html = tier_section(1) + tier_section(
            2, match_card("PGL Wallachia S9", timestamp="invalid")
        )
        with self.assertRaisesRegex(LiquipediaError, "invalid timestamp"):
            parse_upcoming_matches(
                html, tier_two_allowlist={"PGL Wallachia Season 9"}
            )

    @patch("liquipedia_ical.matches.urlopen")
    def test_fetch_requests_both_tiers_in_one_call(self, mock_urlopen) -> None:
        mock_urlopen.return_value = _Response(
            gzip.compress(json.dumps({"parse": {"text": HTML}}).encode("utf-8"))
        )
        fetch_matches_html("Test/1.0 (test@example.com)", include_tier_two=True)
        mock_urlopen.assert_called_once()
        query = parse_qs(urlparse(mock_urlopen.call_args.args[0].full_url).query)
        self.assertIn("filterbuttons-liquipediatier=1", query["text"][0])
        self.assertIn("filterbuttons-liquipediatier=2", query["text"][0])

    def test_parses_only_upcoming_match_cards(self) -> None:
        matches = parse_upcoming_matches(
            HTML + '<div data-toggle-area-content="2">'
            + match_card("Completed tournament", "old") + "</div>"
        )

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

    def test_rejects_html_without_the_requested_section(self) -> None:
        for html in ("", match_card(), '<div data-toggle-area-content="1"></div>'):
            with self.subTest(html=html), self.assertRaisesRegex(
                LiquipediaError, "missing the Tier 1 section"
            ):
                parse_upcoming_matches(html)

    def test_accepts_an_empty_tier_one_section(self) -> None:
        matches = parse_upcoming_matches('<div id="liquipedia-tier-1-matches"></div>')

        self.assertEqual(matches, [])

    def test_refuses_to_return_partial_data(self) -> None:
        malformed = tier_section(
            1, match_card(), '<div class="match-info">missing required fields</div>'
        )
        with self.assertRaisesRegex(LiquipediaError, "timestamp and two opponent slots"):
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
        self.assertIn('id="liquipedia-tier-1-matches"', query["text"][0])
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
