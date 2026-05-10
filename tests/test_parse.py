from datetime import UTC, datetime

from bot import Entry, parse_entries

EXPECTED_ENTRIES = 3


def test_parses_well_formed_entries(sample_feed_xml: str):
    entries = parse_entries(sample_feed_xml)
    # Malformed-title entry is skipped during parsing.
    assert len(entries) == EXPECTED_ENTRIES


def test_parses_first_entry_fields(sample_feed_xml: str):
    entries = parse_entries(sample_feed_xml)
    e = entries[0]
    assert isinstance(e, Entry)
    assert e.id == "https://feed.eikowagenknecht.com/lootscraper/10001"
    assert e.title == "Epic Games (Game) - Hollow Knight"
    assert e.store == "Epic Games"
    assert e.kind == "Game"
    assert e.game_name == "Hollow Knight"
    assert e.link == "https://store.epicgames.com/p/hollow-knight"
    assert e.image_url == "https://example.com/hk.jpg"
    assert "challenging 2D action-adventure" in e.description
    assert e.published_at == datetime(2026, 5, 10, 10, 0, 0, tzinfo=UTC)


def test_entry_without_image_has_none(sample_feed_xml: str):
    entries = parse_entries(sample_feed_xml)
    gog_entry = next(e for e in entries if e.store == "GOG")
    assert gog_entry.image_url is None


def test_loot_entry_is_returned_during_parse(sample_feed_xml: str):
    # parse_entries doesn't filter — that's filter_games' job.
    entries = parse_entries(sample_feed_xml)
    kinds = [e.kind for e in entries]
    assert "Loot" in kinds


def test_empty_feed_returns_empty_list():
    minimal = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><id>x</id><title>t</title><updated>2026-01-01T00:00:00Z</updated></feed>"""
    assert parse_entries(minimal) == []
