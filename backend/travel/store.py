from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock

from travel.schemas import Draft, Event, Itinerary, ItineraryList, ItineraryQuery, Task, now


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
          CREATE TABLE IF NOT EXISTS task_requests (task_id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS submission_keys (key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, task_id TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS resource_owners (kind TEXT, resource_id TEXT, owner_id TEXT NOT NULL,
            PRIMARY KEY(kind, resource_id));
          CREATE INDEX IF NOT EXISTS owner_lookup ON resource_owners(owner_id,kind);
          CREATE TABLE IF NOT EXISTS user_submissions (owner_id TEXT, key TEXT, fingerprint TEXT NOT NULL, task_id TEXT NOT NULL,
            PRIMARY KEY(owner_id,key));
          INSERT OR IGNORE INTO resource_owners SELECT 'task',id,'local' FROM tasks;
          INSERT OR IGNORE INTO resource_owners SELECT 'draft',id,'local' FROM drafts;
          INSERT OR IGNORE INTO resource_owners SELECT 'itinerary',id,'local' FROM itineraries;
          INSERT OR IGNORE INTO user_submissions
            SELECT o.owner_id,s.key,s.fingerprint,s.task_id FROM submission_keys s
            JOIN resource_owners o ON o.kind='task' AND o.resource_id=s.task_id;
        """)
        self.db.commit()

    def put_task(self, task: Task):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO tasks VALUES (?, ?)", (task.id, task.model_dump_json()))
            self.db.execute("INSERT OR IGNORE INTO resource_owners VALUES ('task',?,'local')",(task.id,))

    def owns(self,kind: str,resource_id: str,owner_id: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM resource_owners WHERE kind=? AND resource_id=? AND owner_id=?",
                                   (kind,resource_id,owner_id)).fetchone() is not None

    def owner(self,kind: str,resource_id: str) -> str:
        with self.lock:
            row=self.db.execute("SELECT owner_id FROM resource_owners WHERE kind=? AND resource_id=?",(kind,resource_id)).fetchone()
            return row[0] if row else 'local'

    def submission(self, key: str, fingerprint: str | None = None, *, owner_id: str = 'local') -> Task | None:
        from travel.provider import TravelFailure
        with self.lock:
            row = self.db.execute("SELECT fingerprint, task_id FROM user_submissions WHERE owner_id=? AND key=?", (owner_id,key)).fetchone()
            if row and fingerprint is not None and row[0] != fingerprint:
                raise TravelFailure("idempotency_conflict", "同一提交标识不能用于不同条件，请重新提交", status=409)
            return self.task(row[1],owner_id=owner_id) if row else None

    def register_task(self, task: Task, payload: dict, key: str | None, fingerprint: str, *, owner_id: str = 'local', admit=None) -> tuple[Task, bool]:
        import json
        with self.lock, self.db:
            existing = self.submission(key, fingerprint,owner_id=owner_id) if key else None
            if existing:
                return existing, False
            if admit is not None:
                admit(owner_id)
            self.db.execute("INSERT INTO tasks VALUES (?, ?)", (task.id, task.model_dump_json()))
            self.db.execute("INSERT INTO resource_owners VALUES ('task',?,?)",(task.id,owner_id))
            self.db.execute("INSERT INTO task_requests VALUES (?, ?)", (task.id, json.dumps(payload, ensure_ascii=False)))
            if key:
                self.db.execute("INSERT INTO user_submissions VALUES (?, ?, ?, ?)", (owner_id,key,fingerprint,task.id))
            return task, True

    def task_request(self, task_id: str) -> dict | None:
        import json
        with self.lock:
            row = self.db.execute("SELECT data FROM task_requests WHERE task_id=?", (task_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def task(self, task_id: str, *, owner_id: str | None = None) -> Task | None:
        with self.lock:
            if owner_id is not None and not self.owns('task',task_id,owner_id): return None
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

    def itinerary(self, itinerary_id: str, *, owner_id: str | None = None) -> Itinerary | None:
        with self.lock:
            if owner_id is not None and not self.owns('itinerary',itinerary_id,owner_id): return None
            row = self.db.execute("SELECT data FROM itineraries WHERE id=?", (itinerary_id,)).fetchone()
        return Itinerary.from_saved_json(row[0]) if row else None

    def itineraries(self, limit: int = 50, *, owner_id: str = 'local') -> list[Itinerary]:
        with self.lock:
            rows = self.db.execute("SELECT i.data FROM itineraries i JOIN resource_owners o ON o.kind='itinerary' AND o.resource_id=i.id WHERE o.owner_id=? ORDER BY i.rowid DESC LIMIT ?", (owner_id,limit)).fetchall()
        return [Itinerary.from_saved_json(row[0]) for row in rows]

    def itinerary_page(self, query: ItineraryQuery, *, owner_id: str = 'local') -> ItineraryList:
        from travel.itinerary_listing import itinerary_page
        with self.lock:
            return itinerary_page(self.db, query, owner_id)

    def succeed(self, task: Task, itinerary: Itinerary):
        task.status, task.itinerary_id, task.updated_at = "succeeded", itinerary.id, now()
        with self.lock, self.db:
            self.db.execute("INSERT INTO itineraries VALUES (?,?)", (itinerary.id, itinerary.model_dump_json()))
            self.db.execute("INSERT INTO resource_owners VALUES ('itinerary',?,?)",(itinerary.id,self.owner('task',task.id)))
            self.db.execute("INSERT OR REPLACE INTO tasks VALUES (?,?)", (task.id, task.model_dump_json()))
            self.db.execute("INSERT OR IGNORE INTO resource_owners VALUES ('task',?,'local')",(task.id,))

    def draft(self, draft_id: str, *, owner_id: str | None = None) -> Draft | None:
        with self.lock:
            if owner_id is not None and not self.owns('draft',draft_id,owner_id): return None
            row = self.db.execute("SELECT data FROM drafts WHERE id=?", (draft_id,)).fetchone()
        return Draft.model_validate_json(row[0]) if row else None

    def succeed_draft(self, task: Task, draft: Draft):
        task.status, task.draft_id, task.updated_at = "succeeded", draft.id, now()
        with self.lock, self.db:
            self.db.execute("INSERT INTO drafts VALUES (?,?)", (draft.id, draft.model_dump_json()))
            self.db.execute("INSERT INTO resource_owners VALUES ('draft',?,?)",(draft.id,self.owner('task',task.id)))
            self.db.execute("INSERT OR REPLACE INTO tasks VALUES (?,?)", (task.id, task.model_dump_json()))
            self.db.execute("INSERT OR IGNORE INTO resource_owners VALUES ('task',?,'local')",(task.id,))

    def update_draft(self, draft: Draft, expected_revision: int, *, owner_id: str | None = None):
        from travel.provider import TravelFailure
        with self.lock, self.db:
            if owner_id is not None and not self.owns('draft',draft.id,owner_id):
                raise TravelFailure('draft_not_found','需求草案不存在',status=404)
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
