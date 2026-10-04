from datetime import UTC, datetime
from dataclasses import replace
import re
import unittest

from liquipedia_ical.calendar import build_calendar, event_uid, read_previous_events
from liquipedia_ical.matches import Match


class BuildCalendarTest(unittest.TestCase):
    def test_postponement_keeps_uid_after_old_start_and_end(self) -> None:
        first = build_calendar([self.match], self.first_run)
        postponed = replace(self.match, start=datetime(2026, 7, 18, 18, tzinfo=UTC))
        uid = event_uid(self.match)
        for hour in (11, 12, 14, 15):
            with self.subTest(hour=hour):
                now = datetime(2026, 7, 17, hour, tzinfo=UTC)
                # The match can disappear from the response before reappearing.
                archived = build_calendar([], now, first)
                updated = build_calendar([postponed], now, archived)
                events = read_previous_events(updated)
                self.assertEqual(list(events), [uid])
                self.assertEqual(events[uid].start, postponed.start)
                self.assertEqual(events[uid].sequence, 1)
                self.assertEqual(events[uid].dtstamp, now.strftime("%Y%m%dT%H%M%SZ"))
                self.assertEqual(build_calendar([postponed], now, updated), updated)

    def test_missing_match_at_its_start_is_retained(self) -> None:
        first = build_calendar([self.match], self.first_run)
        self.assertEqual(build_calendar([], self.match.start, first), first)

    def test_missing_source_id_is_rejected_instead_of_guessing_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing Liquipedia match ID"):
            build_calendar([replace(self.match, source_id=None)], self.first_run)

    def test_rematch_has_its_own_identity_and_preserves_previous_match(self) -> None:
        first = build_calendar([self.match], self.first_run)
        rematch = replace(
            self.match, source_id="Match:ID_rematch",
            start=datetime(2026, 7, 18, 11, tzinfo=UTC),
        )
        result = build_calendar([rematch], datetime(2026, 7, 17, 15, tzinfo=UTC), first)
        self.assertEqual(set(read_previous_events(result)), {event_uid(self.match), event_uid(rematch)})

    def test_duplicate_ids_keep_first_occurrence_within_either_tier(self) -> None:
        for tier in (1, 2):
            with self.subTest(tier=tier):
                first = replace(self.match, liquipedia_tier=tier)
                duplicate = replace(first, team1="Conflicting team")
                calendar = build_calendar([first, duplicate], self.first_run)
                self.assertEqual(len(read_previous_events(calendar)), 1)
                self.assertNotIn("Conflicting team", calendar)

    def test_duplicate_ids_prefer_tier_one_regardless_of_input_order(self) -> None:
        tier_two = replace(self.match, liquipedia_tier=2, team1="Tier two copy")
        expected = build_calendar([self.match], self.first_run)
        for matches in ([tier_two, self.match], [self.match, tier_two]):
            self.assertEqual(build_calendar(matches, self.first_run), expected)

    def test_output_order_is_stable_for_ties_and_retained_history(self) -> None:
        other = replace(self.match, source_id="Match:ID_other")
        future = replace(self.match, source_id="Match:ID_future", start=datetime(2026, 7, 18, 11, tzinfo=UTC))
        expected = build_calendar([self.match, other, future], self.first_run)
        self.assertEqual(build_calendar([future, other, self.match], self.first_run), expected)
        self.assertEqual(
            build_calendar([future], datetime(2026, 7, 17, 15, tzinfo=UTC), expected),
            expected,
        )

    def test_excludes_new_qualifier_events(self) -> None:
        qualifier = replace(self.match, tournament="Test League - Closed Qualifier")
        self.assertNotIn("BEGIN:VEVENT", build_calendar([qualifier], self.first_run))

    def test_removes_qualifiers_from_existing_calendar_including_history(self) -> None:
        first = build_calendar([self.match], self.first_run)
        for label in ("Closed Qualifier", "EU Qual."):
            previous = first.replace("Tournament: ", f"Tournament: {label} - ")
            for hour in (3, 12, 15):
                with self.subTest(label=label, hour=hour):
                    calendar = build_calendar(
                        [], datetime(2026, 7, 17, hour, tzinfo=UTC), previous
                    )
                    self.assertNotIn("BEGIN:VEVENT", calendar)

    def test_tier_change_updates_metadata_without_changing_uid(self) -> None:
        first = build_calendar([self.match], self.first_run)
        tier_two = replace(self.match, liquipedia_tier=2)
        calendar = build_calendar([tier_two], self.first_run, first)
        unfolded = re.sub(r"\r\n ", "", calendar)
        self.assertEqual(event_uid(self.match), event_uid(tier_two))
        self.assertIn("Liquipedia tier: 2", unfolded)
        self.assertIn("CATEGORIES:Dota 2,Esports,Liquipedia Tier 2", unfolded)
        self.assertIn("SEQUENCE:1", unfolded)

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

    def test_updates_a_returned_match_after_its_old_estimated_end(self) -> None:
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

        self.assertIn("Changed Team", later)
        self.assertIn("DTSTART:20260717T120000Z", later)
        self.assertIn("SEQUENCE:1", later)

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
