# Liquipedia Tier 1 Dota 2 iCalendar

This repository maintains a schedule and retained history of Liquipedia Tier 1 Dota 2 matches in `dota2-matches.ics`. A scheduled GitHub Actions workflow refreshes it every hour and commits only when the calendar actually changes. Match data comes from the same module used by [Liquipedia:Matches](https://liquipedia.net/dota2/Liquipedia:Matches), with Liquipedia's Tier 1 filter applied at the API source.

## Subscribe

Subscribe to <https://raw.githubusercontent.com/zizhengwu/liquipedia_ical/refs/heads/master/dota2-matches.ics>.

## Run locally

Create the project-local environment and install from the lockfile:

```powershell
uv sync --locked
$env:LIQUIPEDIA_USER_AGENT = "LiquipediaIcal/1.0 (https://github.com/zizhengwu/liquipedia_ical)"
uv run liquipedia-ical
```

Liquipedia requires a custom User-Agent that identifies the project and includes contact information. The GitHub workflow derives one from the repository URL automatically.

To write somewhere else:

```powershell
uv run liquipedia-ical --output public/dota2-matches.ics
```

Run the tests with:

```powershell
uv run python -m unittest discover -s tests -v
```

## Calendar behavior

- The feed contains up to 50 upcoming matches from tournaments Liquipedia classifies as Tier 1, including TBD participants.
- Times are emitted in UTC, so Google Calendar displays them in each subscriber's local time zone.
- Liquipedia provides start times but not end times. Event lengths are estimates based on the series format: Bo1 is one hour, Bo3 is three hours, Bo5 is five hours, and an unknown format is three hours.
- Events are transparent, so they do not mark subscribers as busy.
- Stable match IDs become stable iCalendar UIDs. If a scheduled time or participant changes, the existing event is updated instead of duplicated.
- Matches remain in the feed unchanged once their scheduled start time passes,
  providing a persistent history even when a series finishes earlier than its
  estimated duration and disappears from Liquipedia's upcoming-match response.
- Existing upcoming matches are updated by stable match ID, and newly discovered matches are appended.
- Missing matches that have not started are removed because Liquipedia may have
  cancelled them.
- The checked-in `dota2-matches.ics` file is the archive; deleting it resets the retained history.

## Liquipedia usage

The generator uses one gzip-enabled MediaWiki `action=parse` API request per run and asks Liquipedia's match module for `filterbuttons-liquipediatier=1`; it does not scrape Liquipedia's generated HTML endpoint. The hourly workflow is comfortably within Liquipedia's API rate limits. Calendar descriptions retain the Tier 1 classification, a source link, and attribution.

Liquipedia-derived data is available under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). Liquipedia's [API Terms of Use](https://liquipedia.net/api-terms-of-use) also apply.
