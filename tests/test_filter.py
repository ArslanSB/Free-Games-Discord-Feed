from datetime import UTC, datetime

from bot import Entry, filter_games


def _entry(store: str, kind: str, game_name: str = "X") -> Entry:
    return Entry(
        id=f"id-{store}-{kind}-{game_name}",
        title=f"{store} ({kind}) - {game_name}",
        store=store,
        kind=kind,
        game_name=game_name,
        link="https://example.com",
        image_url=None,
        description="",
        published_at=datetime(2026, 5, 10, tzinfo=UTC),
    )


def test_drops_loot_entries():
    entries = [_entry("Epic Games", "Game"), _entry("Amazon Prime", "Loot")]
    out = filter_games(entries)
    assert [e.kind for e in out] == ["Game"]


def test_keeps_all_games_when_no_exclusions():
    entries = [_entry("Epic Games", "Game"), _entry("Steam", "Game")]
    out = filter_games(entries, exclude_stores=[])
    expected_count = 2
    assert len(out) == expected_count


def test_excludes_listed_stores_case_insensitive():
    entries = [_entry("Epic Games", "Game"), _entry("Steam", "Game")]
    out = filter_games(entries, exclude_stores=["epic games"])
    assert [e.store for e in out] == ["Steam"]


def test_empty_input_returns_empty():
    assert filter_games([]) == []
