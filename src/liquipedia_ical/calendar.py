from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Iterable

from liquipedia_ical.matches import MATCHES_PAGE_URL, Match


PRODID = "-//zizhengwu//liquipedia_ical//Dota 2 Tier 1 Matches//EN"
UID_DOMAIN = "liquipedia-ical"


@dataclass(frozen=True, slots=True)
class PreviousEvent:
    content_hash: str
    dtstamp: str
    sequence: int
    start: datetime | None
    end: datetime | None
    raw_block: str


def build_calendar(
    matches: Iterable[Match],
    generated_at: datetime,
    previous_calendar: str | None = None,
) -> str:
    """Build an RFC 5545 calendar while retaining unchanged event metadata."""
    generated_at = generated_at.astimezone(UTC).replace(microsecond=0)
    previous = read_previous_events(previous_calendar or "")
    events: list[tuple[datetime, str]] = []
    seen_uids: set[str] = set()

    for match in sorted(matches, key=lambda item: (item.start, item.team1, item.team2)):
        uid = event_uid(match)
        if uid in seen_uids:
            raise ValueError(
                f"Duplicate calendar UID generated for {match.team1} vs {match.team2}"
            )
        seen_uids.add(uid)

        content_hash = event_content_hash(match)
        old = previous.get(uid)
        if old is not None and old.end is not None and old.end <= generated_at:
            events.append((old.start or match.start, old.raw_block))
            continue

        if old is not None and old.content_hash == content_hash:
            dtstamp = old.dtstamp
            sequence = old.sequence
        else:
            dtstamp = _format_datetime(generated_at)
            sequence = old.sequence + 1 if old is not None else 0

        summary = f"{match.team1} vs {match.team2} ({match.series_format}) — {match.tournament}"
        description = (
            f"Tournament: {match.tournament}\n"
            "Liquipedia tier: 1\n"
            f"Format: {match.series_format}\n"
            f"Start: {_format_datetime(match.start)} (UTC)\n\n"
            "Source: Liquipedia Dota 2 Wiki (CC BY-SA 3.0)\n"
            f"{match.source_url}"
        )
        end = match.start + match.duration
        event_lines = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{dtstamp}",
            f"LAST-MODIFIED:{dtstamp}",
            f"SEQUENCE:{sequence}",
            f"DTSTART:{_format_datetime(match.start)}",
            f"DTEND:{_format_datetime(end)}",
            _text_property("SUMMARY", summary),
            _text_property("DESCRIPTION", description),
            f"URL:{match.source_url}",
            "CATEGORIES:Dota 2,Esports,Liquipedia Tier 1",
            "STATUS:CONFIRMED",
            "TRANSP:TRANSPARENT",
            f"X-LIQUIPEDIA-CONTENT-HASH:{content_hash}",
            "END:VEVENT",
        ]
        events.append(
            (
                match.start,
                "\r\n".join(_fold_line(line) for line in event_lines),
            )
        )

    for uid, old in previous.items():
        if uid in seen_uids or old.start is None or old.start > generated_at:
            continue
        events.append((old.start, old.raw_block))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        _text_property("X-WR-CALNAME", "Dota 2 Tier 1 Matches — Liquipedia"),
        _text_property(
            "X-WR-CALDESC",
            f"Liquipedia Tier 1 Dota 2 match schedule and history from {MATCHES_PAGE_URL}",
        ),
        "X-WR-TIMEZONE:UTC",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    header = "\r\n".join(_fold_line(line) for line in lines)
    event_blocks = "\r\n".join(
        block for _, block in sorted(events, key=lambda item: item[0])
    )
    if event_blocks:
        return f"{header}\r\n{event_blocks}\r\nEND:VCALENDAR\r\n"
    return f"{header}\r\nEND:VCALENDAR\r\n"


def event_uid(match: Match) -> str:
    identity = match.source_id or "|".join(
        (
            _format_datetime(match.start),
            match.team1.casefold(),
            match.team2.casefold(),
            match.tournament.casefold(),
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"{digest}@{UID_DOMAIN}"


def event_content_hash(match: Match) -> str:
    content = {
        "start": _format_datetime(match.start),
        "end": _format_datetime(match.start + match.duration),
        "team1": match.team1,
        "team2": match.team2,
        "tournament": match.tournament,
        "format": match.series_format,
        "liquipedia_tier": 1,
        "url": match.source_url,
    }
    serialized = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def read_previous_events(calendar: str) -> dict[str, PreviousEvent]:
    previous: dict[str, PreviousEvent] = {}
    for raw_block in re.findall(
        r"BEGIN:VEVENT\r?\n.*?\r?\nEND:VEVENT", calendar, re.DOTALL
    ):
        unfolded = re.sub(r"\r?\n[ \t]", "", raw_block)
        properties: dict[str, str] = {}
        for line in unfolded.splitlines():
            name, separator, value = line.partition(":")
            if separator:
                properties[name.split(";", 1)[0]] = value
        uid = properties.get("UID")
        content_hash = properties.get("X-LIQUIPEDIA-CONTENT-HASH")
        dtstamp = properties.get("DTSTAMP")
        if uid and content_hash and dtstamp:
            try:
                sequence = int(properties.get("SEQUENCE", "0"))
            except ValueError:
                sequence = 0
            previous[uid] = PreviousEvent(
                content_hash=content_hash,
                dtstamp=dtstamp,
                sequence=sequence,
                start=_parse_datetime(properties.get("DTSTART")),
                end=_parse_datetime(properties.get("DTEND")),
                raw_block=raw_block,
            )
    return previous


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Calendar datetimes must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _text_property(name: str, value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )
    return f"{name}:{escaped}"


def _fold_line(line: str) -> str:
    """Fold a content line at 75 octets without splitting UTF-8 characters."""
    chunks: list[str] = []
    current = ""
    limit = 75
    for character in line:
        candidate = current + character
        if len(candidate.encode("utf-8")) > limit and current:
            chunks.append(current)
            current = character
            limit = 74
        else:
            current = candidate
    chunks.append(current)
    return "\r\n ".join(chunks)
