import pytest

from bot import parse_title


def test_parses_game_title():
    assert parse_title("Epic Games (Game) - Hollow Knight") == (
        "Epic Games",
        "Game",
        "Hollow Knight",
    )


def test_parses_loot_title():
    assert parse_title("Amazon Prime (Loot) - Fortnite Skin Pack") == (
        "Amazon Prime",
        "Loot",
        "Fortnite Skin Pack",
    )


def test_handles_store_with_spaces_and_punctuation():
    assert parse_title("Humble Bundle (Game) - Foo: The Bar") == (
        "Humble Bundle",
        "Game",
        "Foo: The Bar",
    )


def test_handles_game_name_with_hyphen():
    assert parse_title("Steam (Game) - Half-Life 2") == ("Steam", "Game", "Half-Life 2")


def test_returns_none_for_malformed():
    assert parse_title("Random title without pattern") is None


def test_returns_none_for_unknown_kind():
    assert parse_title("Steam (Bundle) - Some Bundle") is None


@pytest.mark.parametrize("bad", ["", "() - ", "Store - Game", "(Game) - Foo"])
def test_returns_none_for_garbage(bad: str):
    assert parse_title(bad) is None
