from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import gzip
import json
import re
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, Tag


API_URL = "https://liquipedia.net/dota2/api.php"
MATCHES_PAGE_URL = "https://liquipedia.net/dota2/Liquipedia:Matches"
TIER_ONE_MATCHES_WIKITEXT = (
    '<div id="liquipedia-tier-one-matches">'
    "{{#invoke:Lua|invoke|module=MatchTicker/Custom|fn=mainPage|dev=false|"
    "type=upcoming|limit=50|filterbuttons-liquipediatier=1}}"
    "</div>"
)


class LiquipediaError(RuntimeError):
    """Raised when the Liquipedia response cannot safely produce a calendar."""


@dataclass(frozen=True, slots=True)
class Match:
    start: datetime
    team1: str
    team2: str
    tournament: str
    series_format: str
    source_url: str
    source_id: str | None = None

    @property
    def duration(self) -> timedelta:
        """Return a conservative estimate because Liquipedia has no end time."""
        best_of = re.fullmatch(r"Bo(\d+)", self.series_format, re.IGNORECASE)
        hours = int(best_of.group(1)) if best_of else 3
        return timedelta(hours=max(1, min(hours, 8)))


def fetch_matches_html(user_agent: str, timeout: float = 30) -> str:
    """Render upcoming Tier 1 matches through Liquipedia's MediaWiki API."""
    parameters = urlencode(
        {
            "action": "parse",
            "title": "Liquipedia:Matches",
            "text": TIER_ONE_MATCHES_WIKITEXT,
            "prop": "text",
            "format": "json",
            "formatversion": "2",
        }
    )
    request = Request(
        f"{API_URL}?{parameters}",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": user_agent,
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS URL
            payload = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                payload = gzip.decompress(payload)
            data = json.loads(payload.decode("utf-8"))
    except Exception as error:
        raise LiquipediaError(f"Liquipedia API request failed: {error}") from error

    if "error" in data:
        message = data["error"].get("info", "unknown API error")
        raise LiquipediaError(f"Liquipedia API returned an error: {message}")

    try:
        return data["parse"]["text"]
    except (KeyError, TypeError) as error:
        raise LiquipediaError(
            "Liquipedia API response did not contain parsed HTML"
        ) from error


def parse_upcoming_matches(html: str) -> list[Match]:
    """Parse the Tier 1 upcoming match cards rendered by Liquipedia."""
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#liquipedia-tier-one-matches")
    trusted_tier_one_response = container is not None
    if container is None:
        container = soup.select_one('[data-toggle-area-content="1"]')
    if container is None:
        expansion = soup.select_one('[data-filter-expansion-template*="type=upcoming"]')
        container = expansion
    if container is None:
        container = soup

    cards = container.select(".match-info")
    matches: list[Match] = []
    for card in cards:
        match = _parse_match_card(card)
        if match is not None:
            matches.append(match)

    if not matches and not trusted_tier_one_response:
        raise LiquipediaError(
            "Liquipedia returned no parseable upcoming matches; refusing to replace the calendar"
        )
    if len(matches) != len(cards):
        raise LiquipediaError(
            f"Parsed only {len(matches)} of {len(cards)} upcoming matches; "
            "refusing to replace the calendar with partial data"
        )

    return sorted(matches, key=lambda match: (match.start, match.team1, match.team2))


def _parse_match_card(card: Tag) -> Match | None:
    timestamp = card.select_one(".timer-object[data-timestamp]")
    opponent_slots = card.select(".match-info-header-opponent")
    if timestamp is None or len(opponent_slots) != 2:
        return None

    try:
        start = datetime.fromtimestamp(int(timestamp["data-timestamp"]), UTC)
    except (KeyError, TypeError, ValueError, OSError):
        return None

    team1 = _opponent_label(opponent_slots[0])
    team2 = _opponent_label(opponent_slots[1])
    tournament = _text(card.select_one(".match-info-tournament-name")) or "Dota 2"
    format_text = _text(card.select_one(".match-info-header-scoreholder-lower"))
    series_format = format_text.strip("() ") or "TBD"

    source_id, match_url = _match_identity_and_url(card)
    tournament_link = card.select_one(".match-info-tournament-name a[href]")
    source_url = match_url or _absolute_href(tournament_link) or MATCHES_PAGE_URL

    return Match(
        start=start,
        team1=team1,
        team2=team2,
        tournament=tournament,
        series_format=series_format,
        source_url=source_url,
        source_id=source_id,
    )


def _opponent_label(opponent: Tag) -> str:
    """Read team names as well as bracket seeds such as "A3" and "B4"."""
    for selector in (".name", ".brkts-opponent-block-literal"):
        label = _text(opponent.select_one(selector))
        if label:
            return label
    return _text(opponent) or "TBD"


def _match_identity_and_url(card: Tag) -> tuple[str | None, str | None]:
    for link in card.select(".match-info-links a[href]"):
        href = str(link.get("href", ""))
        parsed = urlparse(unquote(href))
        query_title = parse_qs(parsed.query).get("title", [None])[0]
        path_title = unquote(parsed.path.rsplit("/", 1)[-1]).replace("_", " ")
        title = query_title or path_title
        if title and title.startswith("Match:"):
            normalized = title.replace(" ", "_")
            path = quote(normalized, safe=":_-.")
            return normalized, f"https://liquipedia.net/dota2/{path}"
    return None, None


def _absolute_href(link: Tag | None) -> str | None:
    if link is None or not link.get("href"):
        return None
    return urljoin(MATCHES_PAGE_URL, str(link["href"]))


def _text(element: Tag | None) -> str:
    return element.get_text(" ", strip=True) if element is not None else ""
