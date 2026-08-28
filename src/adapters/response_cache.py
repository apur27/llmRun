"""Local disk cache for model responses, keyed by a hash of the exact prompt string.

Exists so re-running the eval against the same prompts does not re-bill the API. Backed by a
directory of small JSON files under `.cache/responses/` — one file per prompt hash, deliberately
a directory rather than one JSON blob, so a crash mid-run never corrupts more than the single
response being written at that moment. Pure I/O, no SDK, no network: callers own the actual API
call, this module only persists and retrieves already-computed responses.
"""

import hashlib
import json
from pathlib import Path

DEFAULT_CACHE_DIR = Path(".cache/responses")


class ResponseCache:
    """Disk-backed cache mapping an exact prompt string to its recorded response."""

    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR) -> None:
        """Use `cache_dir` as the backing directory. Created lazily, on the first write."""
        self._cache_dir = cache_dir

    def get(self, prompt: str) -> str | None:
        """Return the cached response for `prompt`, or `None` on a cache miss."""
        path = self._path_for(prompt)
        if not path.exists():
            return None
        payload: dict[str, str] = json.loads(path.read_text())
        return payload["response"]

    def set(self, prompt: str, response: str) -> None:
        """Persist `response` for `prompt`, overwriting any prior entry for the same prompt."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(prompt)
        path.write_text(json.dumps({"prompt": prompt, "response": response}))

    def _path_for(self, prompt: str) -> Path:
        """The on-disk path for `prompt`'s cache entry, keyed by its sha256 hash."""
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.json"
