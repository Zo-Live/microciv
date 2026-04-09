"""Record card widgets."""

from __future__ import annotations

from textual.widgets import Button

from microciv.records.models import RecordEntry


class RecordCardButton(Button):
    """Multiline record summary card."""

    def __init__(self, record: RecordEntry, *, id: str | None = None) -> None:
        label = "\n".join(
            [
                f"#{record.record_id}",
                record.timestamp.replace("T", " ")[:16],
                f"score: {record.final_score}",
                f"mode: {record.mode}",
                f"ai: {record.ai_type}",
                f"diff: {record.map_difficulty}",
            ]
        )
        super().__init__(label, id=id)
        self.record = record
