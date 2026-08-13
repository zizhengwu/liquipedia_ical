from datetime import UTC, datetime
import re
import unittest

from liquipedia_ical.calendar import build_calendar, event_uid
from liquipedia_ical.matches import Match


class BuildCalendarTest(unittest.TestCase):
    def setUp(self) -> None:
        self.match = Match(
            start=datetime(2026, 7, 17, 11, 0, tzinfo=UTC),
            team1="A, B & Friends",
            team2="Semicolon; Squad",
            tournament="A very long tournament name with 世界 competitors and finals",
            series_format="Bo3",
            source_url="https://liquipedia.net/dota2/Match:ID_test",
            source_id="Match:ID_test",
        )
        self.first_run = datetime(2026, 7, 17, 2, 0, tzinfo=UTC)

    def test_emits_validly_folded_and_escaped_content_lines(self) -> None:
        calendar = build_calendar([self.match], self.first_run)

        self.assertTrue(calendar.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(calendar.endswith("END:VCALENDAR\r\n"))
        self.assertIn("DTSTART:20260717T110000Z", calendar)
        self.assertIn("DTEND:20260717T140000Z", calendar)
        unfolded = re.sub(r"\r\n ", "", calendar)
        self.assertIn("X-WR-CALNAME:Dota 2 Tier 1 Matches", unfolded)
        self.assertIn("Liquipedia tier: 1", unfolded)
        self.assertIn("A\\, B & Friends", unfolded)
        self.assertIn("Semicolon\\; Squad", unfolded)
        for line in calendar.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75, line)

    def test_unchanged_matches_produce_an_identical_calendar(self) -> None:
        first = build_calendar([self.match], self.first_run)
        later = build_calendar(
            [self.match],
            datetime(2026, 7, 17, 3, 0, tzinfo=UTC),
            previous_calendar=first,
        )

        self.assertEqual(first, later)

    def test_changed_match_increments_sequence_and_modification_time(self) -> None:
        first = build_calendar([self.match], self.first_run)
        changed = Match(
            start=datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
            team1=self.match.team1,
            team2=self.match.team2,
            tournament=self.match.tournament,
            series_format=self.match.series_format,
            source_url=self.match.source_url,
            source_id=self.match.source_id,
        )
        second = build_calendar(
            [changed],
            datetime(2026, 7, 17, 3, 0, tzinfo=UTC),
            previous_calendar=first,
        )

        self.assertEqual(event_uid(self.match), event_uid(changed))
        self.assertIn("SEQUENCE:1", second)
        self.assertIn("DTSTAMP:20260717T030000Z", second)
        self.assertIn("DTSTART:20260717T120000Z", second)

    def test_retains_an_expired_match_unchanged_when_it_disappears(self) -> None:
        first = build_calendar([self.match], self.first_run)
        original_event = _event_block(first)

        later = build_calendar(
            [],
            datetime(2026, 7, 17, 15, 0, tzinfo=UTC),
            previous_calendar=first,
        )

        self.assertEqual(_event_block(later), original_event)

    def test_retains_a_started_match_when_it_disappears_before_estimated_end(
        self,
    ) -> None:
        first = build_calendar([self.match], self.first_run)
        original_event = _event_block(first)

        later = build_calendar(
            [],
            datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
            previous_calendar=first,
        )

        self.assertEqual(_event_block(later), original_event)

    def test_does_not_update_an_expired_match(self) -> None:
        first = build_calendar([self.match], self.first_run)
        changed = Match(
            start=datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
            team1="Changed Team",
            team2=self.match.team2,
            tournament=self.match.tournament,
            series_format=self.match.series_format,
            source_url=self.match.source_url,
            source_id=self.match.source_id,
        )

        later = build_calendar(
            [changed],
            datetime(2026, 7, 17, 15, 0, tzinfo=UTC),
            previous_calendar=first,
        )

        self.assertEqual(_event_block(later), _event_block(first))
        self.assertNotIn("Changed Team", later)

    def test_removes_a_missing_future_match(self) -> None:
        first = build_calendar([self.match], self.first_run)

        later = build_calendar(
            [],
            datetime(2026, 7, 17, 3, 0, tzinfo=UTC),
            previous_calendar=first,
        )

        self.assertNotIn("BEGIN:VEVENT", later)


def _event_block(calendar: str) -> str:
    match = re.search(r"BEGIN:VEVENT\r\n.*?\r\nEND:VEVENT", calendar, re.DOTALL)
    if match is None:
        raise AssertionError("Calendar does not contain an event")
    return match.group(0)


if __name__ == "__main__":
    unittest.main()
