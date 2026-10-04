# Dota 2 Calendar

A calendar of major Dota 2 matches from [Liquipedia](https://liquipedia.net/dota2/Liquipedia:Matches), updated hourly. Qualifiers are excluded, and past matches are kept.

## Subscribe

Add this URL to your calendar app:

```text
https://raw.githubusercontent.com/zizhengwu/liquipedia_ical/refs/heads/master/dota2-matches.ics
```

Match times display in your local time zone. End times are estimates.

## Run locally

```powershell
uv sync --locked
$env:LIQUIPEDIA_USER_AGENT = "LiquipediaIcal/1.0 (https://github.com/zizhengwu/liquipedia_ical)"
uv run liquipedia-ical
```

Writes to `dota2-matches.ics`. Use a User-Agent with your own contact information.

Data from Liquipedia under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). [API terms](https://liquipedia.net/api-terms-of-use) apply.
