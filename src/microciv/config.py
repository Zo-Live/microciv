"""Shared configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    """Filesystem locations used by the application."""

    root: Path
    data_dir: Path
    exports_dir: Path
    records_file: Path


def build_app_paths(root: Path | None = None) -> AppPaths:
    """Build application paths relative to the repository root."""
    resolved_root = root.resolve() if root is not None else Path(__file__).resolve().parents[2]
    data_dir = resolved_root / "data"
    exports_dir = resolved_root / "exports"
    return AppPaths(
        root=resolved_root,
        data_dir=data_dir,
        exports_dir=exports_dir,
        records_file=data_dir / "records.json",
    )
