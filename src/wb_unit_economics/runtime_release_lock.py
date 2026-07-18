"""Shared fail-closed lock for runtime build, promotion, and retention."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

DEFAULT_RUNTIME_RELEASE_LOCK = Path("/run/lock/shumeiko-runtime-release.lock")


@contextmanager
def exclusive_runtime_release_lock(
    path: Path = DEFAULT_RUNTIME_RELEASE_LOCK,
) -> Iterator[IO[str]]:
    """Acquire the shared runtime release lock without waiting."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                f"runtime release operation is already active: {path}"
            ) from exc
        yield lock
