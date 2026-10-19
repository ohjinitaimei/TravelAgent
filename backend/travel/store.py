from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock

from travel.schemas import Draft, Event, Itinerary, Task, now


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events (task_id TEXT, seq INTEGER, data TEXT NOT NULL, PRIMARY KEY(task_id, seq));
          CREATE TABLE IF NOT EXISTS itineraries (id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        """)
        self.db.commit()

    def put_task(self, task: Task):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO tasks VALUES (?, ?)", (task.id, task.model_dump_json()))

    def task(self, task_id: str) -> Task | None:
        with self.lock:
            row = self.db.execute("SELECT data FROM tasks WHERE id=?", (task_id,)).fetchone()
        return Task.model_validate_json(row[0]) if row else None

    def tasks(self) -> list[Task]:
        with self.lock:
            rows = self.db.execute("SELECT data FROM tasks").fetchall()
        return [Task.model_validate_json(row[0]) for row in rows]

    def event(self, task_id: str, stage: str, message: str):
        with self.lock, self.db:
            seq = self.db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE task_id=?", (task_id,)).fetchone()[0]
            event = Event(id=seq, stage=stage, message=message)
            self.db.execute("INSERT INTO events VALUES (?, ?, ?)", (task_id, seq, event.model_dump_json()))

    def events(self, task_id: str, after: int = 0) -> list[Event]:
        with self.lock:
            rows = self.db.execute("SELECT data FROM events WHERE task_id=? AND seq>? ORDER BY seq", (task_id, after)).fetchall()
        return [Event.model_validate_json(row[0]) for row in rows]

    def itinerary(self, itinerary_id: str) -> Itinerary | None:
        with self.lock:
            row = self.db.execute("SELECT data FROM itineraries WHERE id=?", (itinerary_id,)).fetchone()
        return Itinerary.model_validate_json(row[0]) if row else None

    def itineraries(self, limit: int = 50) -> list[Itinerary]:
        with self.lock:
            rows = self.db.execute("SELECT data FROM itineraries ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        return [Itinerary.model_validate_json(row[0]) for row in rows]

    def succeed(self, task: Task, itinerary: Itinerary):
        task.status, task.itinerary_id, task.updated_at = "succeeded", itinerary.id, now()
        with self.lock, self.db:
            self.db.execute("INSERT INTO itineraries VALUES (?,?)", (itinerary.id, itinerary.model_dump_json()))
            self.db.execute("INSERT OR REPLACE INTO tasks VALUES (?,?)", (task.id, task.model_dump_json()))

    def draft(self, draft_id: str) -> Draft | None:
        with self.lock:
            row = self.db.execute("SELECT data FROM drafts WHERE id=?", (draft_id,)).fetchone()
        return Draft.model_validate_json(row[0]) if row else None

    def succeed_draft(self, task: Task, draft: Draft):
        task.status, task.draft_id, task.updated_at = "succeeded", draft.id, now()
        with self.lock, self.db:
            self.db.execute("INSERT INTO drafts VALUES (?,?)", (draft.id, draft.model_dump_json()))
            self.db.execute("INSERT OR REPLACE INTO tasks VALUES (?,?)", (task.id, task.model_dump_json()))

    def update_draft(self, draft: Draft, expected_revision: int):
        from travel.provider import TravelFailure
        with self.lock, self.db:
            row = self.db.execute("SELECT data FROM drafts WHERE id=?", (draft.id,)).fetchone()
            if not row:
                raise TravelFailure("draft_not_found", "需求草案不存在", status=404)
            if Draft.model_validate_json(row[0]).revision != expected_revision:
                raise TravelFailure("draft_revision_conflict", "草案已在其他页面更新，请先加载最新版本后核对补充内容", status=409)
            cursor = self.db.execute("UPDATE drafts SET data=? WHERE id=? AND data=?",
                                     (draft.model_dump_json(), draft.id, row[0]))
            if cursor.rowcount != 1:
                raise TravelFailure("draft_revision_conflict", "草案已更新，请重新加载并核对", status=409)

    def close(self):
        self.db.close()
