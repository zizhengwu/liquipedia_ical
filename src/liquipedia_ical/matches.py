from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import gzip
import json
import re
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, Tag


API_URL = "https://liquipedia.net/dota2/api.php"
MATCHES_PAGE_URL = "https://liquipedia.net/dota2/Liquipedia:Matches"
DEFAULT_ALLOWLIST = Path(__file__).parent / "data" / "tier2_allowlist.txt"


def load_allowlist(path: Path = DEFAULT_ALLOWLIST) -> set[str]:
    """Read one tournament name per line, ignoring blank lines and comments."""
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _tournament_key(name: str) -> str:
    name = " ".join(name.casefold().split())
    return re.sub(r"\bseason\s+(\d+)\b", r"s\1", name)


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
    liquipedia_tier: int = 1

    @property
    def duration(self) -> timedelta:
        """Return a conservative estimate because Liquipedia has no end time."""
        best_of = re.fullmatch(r"Bo(\d+)", self.series_format, re.IGNORECASE)
        hours = int(best_of.group(1)) if best_of else 3
        return timedelta(hours=max(1, min(hours, 8)))


def _matches_wikitext(tier: int) -> str:
    return (
        f'<div id="liquipedia-tier-{tier}-matches">'
        "{{#invoke:Lua|invoke|module=MatchTicker/Custom|fn=mainPage|dev=false|"
        f"type=upcoming|limit=50|filterbuttons-liquipediatier={tier}"
        "}}</div>"
    )


def fetch_matches_html(
    user_agent: str, timeout: float = 30, *, include_tier_two: bool = False
) -> str:
    """Render separate, source-filtered tiers in one MediaWiki API request."""
    parameters = urlencode(
        {
            "action": "parse",
            "title": "Liquipedia:Matches",
            "text": _matches_wikitext(1)
            + (_matches_wikitext(2) if include_tier_two else ""),
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


def parse_upcoming_matches(
    html: str, *, tier_two_allowlist: set[str] | None = None
) -> list[Match]:
    """Parse Tier 1 matches and explicitly allowed Tier 2 tournaments."""
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#liquipedia-tier-1-matches")
    if container is None:
        raise LiquipediaError("Liquipedia response is missing the Tier 1 section")
    matches = [_parse_match_card(card) for card in container.select(".match-info")]

    if tier_two_allowlist:
        tier_two = soup.select_one("#liquipedia-tier-2-matches")
        if tier_two is None:
            raise LiquipediaError("Liquipedia response is missing the Tier 2 section")
        allowed = {_tournament_key(name) for name in tier_two_allowlist}
        source_ids = {match.source_id for match in matches if match.source_id}
        for card in tier_two.select(".match-info"):
            name = _text(card.select_one(".match-info-tournament-name"))
            name = _tournament_key(name)
            if not any(
                name == entry or name.startswith(entry + " - ")
                for entry in allowed
            ):
                continue
            match = _parse_match_card(card, liquipedia_tier=2)
            if match.source_id and match.source_id in source_ids:
                continue
            matches.append(match)
            if match.source_id:
                source_ids.add(match.source_id)

    return sorted(matches, key=lambda match: (match.start, match.team1, match.team2))


def _parse_match_card(card: Tag, liquipedia_tier: int = 1) -> Match:
    timestamp = card.select_one(".timer-object[data-timestamp]")
    opponent_slots = card.select(".match-info-header-opponent")
    if timestamp is None or len(opponent_slots) != 2:
        raise LiquipediaError("Match card requires a timestamp and two opponent slots")

    try:
        start = datetime.fromtimestamp(int(timestamp["data-timestamp"]), UTC)
    except (TypeError, ValueError, OSError, OverflowError) as error:
        raise LiquipediaError("Match card has an invalid timestamp") from error

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
        liquipedia_tier=liquipedia_tier,
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
