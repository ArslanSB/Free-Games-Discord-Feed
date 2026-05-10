import httpx
import respx

from bot import post_to_discord

WEBHOOK = "https://discord.com/api/webhooks/test/abc"


@respx.mock
def test_post_succeeds_on_204():
    route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    with httpx.Client() as client:
        ok = post_to_discord(client, WEBHOOK, {"content": "hi"})
    assert ok is True
    assert route.called


@respx.mock
def test_post_returns_false_on_4xx_other_than_429():
    respx.post(WEBHOOK).mock(return_value=httpx.Response(400, json={"message": "bad"}))
    with httpx.Client() as client:
        ok = post_to_discord(client, WEBHOOK, {"content": "hi"})
    assert ok is False


@respx.mock
def test_post_retries_once_on_429_then_succeeds():
    route = respx.post(WEBHOOK).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}, json={"retry_after": 0}),
            httpx.Response(204),
        ]
    )
    with httpx.Client() as client:
        ok = post_to_discord(client, WEBHOOK, {"content": "hi"})
    assert ok is True
    assert route.call_count == 2  # noqa: PLR2004


@respx.mock
def test_post_returns_false_when_429_persists():
    respx.post(WEBHOOK).mock(return_value=httpx.Response(429, headers={"Retry-After": "0"}))
    with httpx.Client() as client:
        ok = post_to_discord(client, WEBHOOK, {"content": "hi"})
    assert ok is False


@respx.mock
def test_post_handles_non_numeric_retry_after():
    """Retry-After can be HTTP-date per RFC; we should not crash."""
    route = respx.post(WEBHOOK).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "Fri, 31 Dec 1999 23:59:59 GMT"}),
            httpx.Response(204),
        ]
    )
    with httpx.Client() as client:
        ok = post_to_discord(client, WEBHOOK, {"content": "hi"})
    assert ok is True
    assert route.call_count == 2  # noqa: PLR2004
