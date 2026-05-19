"""Filesystem helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile


@contextmanager
def atomic_output_path(path: Path) -> Iterator[Path]:
    """Yield a temporary sibling path and atomically replace the target on success."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = NamedTemporaryFile(
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary.name)
    temporary.close()
    try:
        yield temporary_path
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write bytes through a temporary sibling file, then atomically replace."""
    with atomic_output_path(path) as temporary_path:
        temporary_path.write_bytes(data)
