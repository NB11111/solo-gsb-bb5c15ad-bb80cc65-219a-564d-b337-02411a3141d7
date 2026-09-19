"""Runtime configuration read from environment variables."""

import os


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"environment variable {name} must be an integer") from exc


# default reviews required per manuscript when the request does not state one
DEFAULT_REVIEWS_PER_MANUSCRIPT = _int_env(
    "DEFAULT_REVIEWS_PER_MANUSCRIPT", 2
)
# guard rails against arbitrarily large requests
MAX_MANUSCRIPTS = _int_env("MAX_MANUSCRIPTS", 10_000)
MAX_REVIEWERS = _int_env("MAX_REVIEWERS", 10_000)

SERVICE_NAME = "anonymous-review-assignment"
