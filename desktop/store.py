"""SQLite history. Metadata and result bodies are separated for cheap polling."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path


def encode(value):
    return json.dumps(value, ensure_ascii=False)


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(directory / "history.sqlite3", check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA journal_mode=WAL")
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            self._db.close()
            raise RuntimeError("任务历史由更新版本创建，请使用更新版本打开。")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                position INTEGER NOT NULL, data TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS items_job ON items(job_id, position);
            PRAGMA user_version=1;
        """)

    def settings(self):
        with self._lock:
            row = self._db.execute("SELECT data FROM settings WHERE key='desktop'").fetchone()
            return json.loads(row[0]) if row else None

    def save_settings(self, value):
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO settings VALUES ('desktop', ?)", (encode(value),))

    def add_source(self, source):
        with self._lock, self._db:
            self._db.execute("INSERT INTO sources VALUES (?,?)", (source["id"], encode(source)))

    def source(self, source_id):
        with self._lock:
            row = self._db.execute("SELECT data FROM sources WHERE id=?", (source_id,)).fetchone()
            if not row:
                raise ValueError("原文件记录不存在，请重新导入。")
            return json.loads(row[0])

    def create_job(self, job, items):
        with self._lock, self._db:
            self._db.execute("INSERT INTO jobs VALUES (?,?,?)", (job["id"], job["created_at"], encode(job)))
            for position, item in enumerate(items):
                self._db.execute(
                    "INSERT INTO items(id,job_id,position,data) VALUES (?,?,?,?)",
                    (item["id"], job["id"], position, encode(item)),
                )

    def job(self, job_id):
        with self._lock:
            row = self._db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("任务记录不存在。")
            job = json.loads(row[0])
            job["items"] = [
                json.loads(row[0])
                for row in self._db.execute("SELECT data FROM items WHERE job_id=? ORDER BY position", (job_id,))
            ]
            return job

    def jobs(self):
        with self._lock:
            ids = [row[0] for row in self._db.execute("SELECT id FROM jobs ORDER BY created_at DESC, rowid DESC")]
            return [self.job(job_id) for job_id in ids]

    def update_job(self, job_id, **changes):
        with self._lock, self._db:
            job = self.job(job_id)
            job.pop("items")
            job.update(changes)
            self._db.execute("UPDATE jobs SET data=? WHERE id=?", (encode(job), job_id))

    def item(self, item_id):
        with self._lock:
            row = self._db.execute("SELECT data,result FROM items WHERE id=?", (item_id,)).fetchone()
            if not row:
                raise ValueError("结果记录不存在。")
            return json.loads(row[0]), json.loads(row[1])

    def update_item(self, item_id, result=None, **changes):
        with self._lock, self._db:
            item, previous = self.item(item_id)
            item.update(changes)
            self._db.execute(
                "UPDATE items SET data=?,result=? WHERE id=?",
                (encode(item), encode(previous if result is None else result), item_id),
            )

    def delete_job(self, job_id):
        with self._lock, self._db:
            self._db.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    def recover(self):
        """A dead process cannot resume an in-flight engine call."""
        for job in self.jobs():
            if job["state"] in ("queued", "running"):
                for item in job["items"]:
                    if item["state"] in ("queued", "running"):
                        self.update_item(item["id"], state="interrupted", error="上次运行意外结束，请重新导入重试。")
                self.update_job(job["id"], state="interrupted", stop_requested=False)

    def close(self):
        with self._lock:
            self._db.close()
