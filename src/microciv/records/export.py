"""CSV export helpers for records."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Sequence

from microciv.records.models import CSV_FIELD_ORDER, RecordEntry


def export_records_csv(
    records: Sequence[RecordEntry],
    output_dir: Path,
    *,
    now: datetime | None = None,
) -> Path:
    """Export records to a timestamped CSV file with the frozen field order."""
    output_dir.mkdir(parents=True, exist_ok=True)
    export_time = now or datetime.now().astimezone()
    output_path = output_dir / f"records-{export_time.strftime('%Y%m%d-%H%M%S')}.csv"

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_FIELD_ORDER))
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())

    return output_path
