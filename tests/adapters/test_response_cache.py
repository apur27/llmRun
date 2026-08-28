"""Unit tests for `src.adapters.response_cache.ResponseCache`.

No network: every test is write-then-read against a `tmp_path`-backed cache directory.
"""

from pathlib import Path

from src.adapters.response_cache import ResponseCache


def test_get_on_empty_cache_is_a_miss(tmp_path: Path) -> None:
    """A prompt never written to the cache returns `None`, not an error."""
    cache = ResponseCache(cache_dir=tmp_path / "responses")

    assert cache.get("what is the revenue?") is None


def test_set_then_get_returns_the_same_response(tmp_path: Path) -> None:
    """A response written for a prompt is returned unchanged by a later `get` of that prompt."""
    cache = ResponseCache(cache_dir=tmp_path / "responses")

    cache.set("what is the revenue?", "ANSWER: 42.0")

    assert cache.get("what is the revenue?") == "ANSWER: 42.0"


def test_different_prompts_do_not_collide(tmp_path: Path) -> None:
    """Two distinct prompt strings hash to distinct cache entries."""
    cache = ResponseCache(cache_dir=tmp_path / "responses")

    cache.set("prompt a", "response a")
    cache.set("prompt b", "response b")

    assert cache.get("prompt a") == "response a"
    assert cache.get("prompt b") == "response b"
