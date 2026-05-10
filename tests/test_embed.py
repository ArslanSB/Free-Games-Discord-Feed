from datetime import UTC, datetime

from bot import DESCRIPTION_LIMIT, EMBED_COLOR_GREEN, Entry, build_embed_payload


def _entry(**kwargs) -> Entry:
    base = dict(
        id="id-1",
        title="Epic Games (Game) - Hollow Knight",
        store="Epic Games",
        kind="Game",
        game_name="Hollow Knight",
        link="https://store.epicgames.com/p/hollow-knight",
        image_url="https://example.com/hk.jpg",
        description="A challenging 2D action-adventure.",
        published_at=datetime(2026, 5, 10, 10, 0, 0, tzinfo=UTC),
    )
    base.update(kwargs)
    return Entry(**base)


def test_payload_has_one_embed_with_core_fields():
    payload = build_embed_payload(_entry())
    assert payload["username"] == "Free Games"
    assert len(payload["embeds"]) == 1
    embed = payload["embeds"][0]
    assert embed["title"] == "Hollow Knight"
    assert embed["url"] == "https://store.epicgames.com/p/hollow-knight"
    assert embed["description"] == "A challenging 2D action-adventure."
    assert embed["image"] == {"url": "https://example.com/hk.jpg"}
    assert embed["footer"]["text"].startswith("Epic Games")
    assert embed["timestamp"] == "2026-05-10T10:00:00+00:00"
    assert embed["color"] == EMBED_COLOR_GREEN


def test_omits_image_when_none():
    embed = build_embed_payload(_entry(image_url=None))["embeds"][0]
    assert "image" not in embed


def test_truncates_long_description():
    long_desc = "x" * 1000
    embed = build_embed_payload(_entry(description=long_desc))["embeds"][0]
    assert len(embed["description"]) == DESCRIPTION_LIMIT
    assert embed["description"].endswith("…")


def test_short_description_not_truncated():
    embed = build_embed_payload(_entry(description="short"))["embeds"][0]
    assert embed["description"] == "short"


def test_empty_description_omitted():
    embed = build_embed_payload(_entry(description=""))["embeds"][0]
    assert "description" not in embed
