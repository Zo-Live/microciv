"""Persistent storage for match records."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from microciv.constants import MAX_RECORDS, PROJECT_VERSION
from microciv.game.models import GameState
from microciv.records.models import RECORDS_SCHEMA_VERSION, RecordDatabase, RecordEntry


class RecordStore:
    """Load, append, and save the local records file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> RecordDatabase:
        if not self.path.exists():
            return self._empty_database()

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        try:
            database = RecordDatabase.from_dict(payload)
        except (KeyError, TypeError, ValueError):
            return self._reset_incompatible_file()

        if database.schema_version != RECORDS_SCHEMA_VERSION:
            return self._reset_incompatible_file()
        return database

    def save(self, database: RecordDatabase) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(database.to_dict(), ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
        )
        temp_path.replace(self.path)

    def append_completed_game(
        self,
        state: GameState,
        *,
        timestamp: str | None = None,
        game_version: str = PROJECT_VERSION,
    ) -> RecordEntry:
        if not state.is_game_over:
            raise ValueError("Only completed games may be written to Records.")

        database = self.load()
        entry = RecordEntry.from_game_state(
            record_id=database.next_record_id,
            timestamp=timestamp or datetime.now().astimezone().isoformat(timespec="seconds"),
            state=state,
            game_version=game_version,
        )
        database.next_record_id += 1
        database.records.append(entry)
        if len(database.records) > MAX_RECORDS:
            database.records = database.records[-MAX_RECORDS:]
        self.save(database)
        return entry

    def delete_record(self, record_id: int) -> bool:
        database = self.load()
        remaining = [record for record in database.records if record.record_id != record_id]
        if len(remaining) == len(database.records):
            return False
        database.records = remaining
        self.save(database)
        return True

    def clear(self) -> None:
        database = self.load()
        database.records = []
        database.next_record_id = 1
        self.save(database)

    def _empty_database(self) -> RecordDatabase:
        return RecordDatabase(schema_version=RECORDS_SCHEMA_VERSION, next_record_id=1, records=[])

    def _reset_incompatible_file(self) -> RecordDatabase:
        backup_path = self.path.with_suffix(f"{self.path.suffix}.incompatible")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if backup_path.exists():
            backup_path.unlink()
        self.path.replace(backup_path)
        return self._empty_database()
