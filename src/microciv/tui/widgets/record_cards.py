"""Record card widgets."""

from __future__ import annotations

from textual.widgets import Button

from microciv.records.models import RecordEntry


class RecordCardButton(Button):
    """Multiline record summary card."""

    def __init__(self, record: RecordEntry, *, id: str | None = None) -> None:
        label = "\n".join(
            [
                f"#{record.record_id:04d}",
                record.timestamp.replace("T", " ")[:16],
                f"score: {record.final_score}",
                f"mode: {record.mode.title()}",
                f"ai: {record.ai_type}",
                f"diff: {record.map_difficulty.title()}",
            ]
        )
        super().__init__(label, id=id)
        self.record = record
