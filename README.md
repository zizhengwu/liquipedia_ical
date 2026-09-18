# Liquipedia Tier 1 Dota 2 iCalendar

This repository maintains a schedule and retained history of Liquipedia Tier 1 and allowlisted Tier 2 Dota 2 matches in `dota2-matches.ics`. A scheduled GitHub Actions workflow refreshes it every hour and commits only when the calendar actually changes. Match data comes from the same module used by [Liquipedia:Matches](https://liquipedia.net/dota2/Liquipedia:Matches), with tier filters applied at the API source.

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

- The feed contains up to 50 upcoming Tier 1 matches, plus allowlisted tournaments from the next 50 Tier 2 matches, including TBD participants.
- Edit [the Tier 2 allowlist](src/liquipedia_ical/data/tier2_allowlist.txt) to add tournament names, one per line. It includes **PGL Wallachia Season 9** by default. Blank lines and lines beginning with `#` are ignored. Names are case-insensitive; `Season 9` also matches `S9`, and stage suffixes such as ` - Round 1` or ` - Playoffs` are included. Other seasons do not match.
- Use `--tier2-allowlist path/to/file.txt` to supply another list. An empty file disables Tier 2 fetching. Allowlisted matches outside Liquipedia's next 50 Tier 2 matches appear once they enter that window.
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

The generator uses one gzip-enabled MediaWiki `action=parse` API request per run and asks Liquipedia's match module for separate `filterbuttons-liquipediatier=1` and `filterbuttons-liquipediatier=2` sections, then applies the allowlist to Tier 2. It does not scrape Liquipedia's generated HTML endpoint. The hourly workflow is comfortably within Liquipedia's API rate limits. Calendar descriptions retain each match's tier classification, a source link, and attribution.

Liquipedia-derived data is available under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). Liquipedia's [API Terms of Use](https://liquipedia.net/api-terms-of-use) also apply.
