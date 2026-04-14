"""JSON export helpers for records."""

from __future__ import annotations

import json
from pathlib import Path

from microciv.records.models import RecordDatabase


def export_records_json(database: RecordDatabase, output_dir: Path) -> Path:
    """Export the current records database to a stable JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "records_export.json"
    output_path.write_text(
        json.dumps(database.to_dict(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path
