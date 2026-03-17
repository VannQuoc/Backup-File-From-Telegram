from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUS_FAILED = 'failed'
STATUS_SKIPPED = 'skipped'
STATUS_SYNCED = 'synced'
VALID_STATUSES = {STATUS_FAILED, STATUS_SKIPPED, STATUS_SYNCED}


@dataclass(frozen=True)
class SourceRecord:
    source_chat_id: int
    dest_chat_id: int
    dest_topic_default: int
    dest_topic_archive: int
    label: str | None = None
    source_invite_link: str | None = None
    enabled: bool = True
    allow_protected_fallback: bool = False
    created_at: str | None = None
    updated_at: str | None = None

    def as_db_params(self) -> dict[str, Any]:
        now = utcnow_iso()
        return {
            'source_chat_id': self.source_chat_id,
            'dest_chat_id': self.dest_chat_id,
            'dest_topic_default': self.dest_topic_default,
            'dest_topic_archive': self.dest_topic_archive,
            'label': self.label,
            'source_invite_link': self.source_invite_link,
            'enabled': int(self.enabled),
            'allow_protected_fallback': int(self.allow_protected_fallback),
            'created_at': self.created_at or now,
            'updated_at': self.updated_at or now,
        }


@dataclass(frozen=True)
class SyncStateRecord:
    source_chat_id: int
    source_msg_id: int
    status: str
    extension: str | None
    document_id: int | None
    filename: str | None
    normalized_filename: str
    size: int | None
    dest_chat_id: int | None = None
    dest_topic_id: int | None = None
    dest_msg_id: int | None = None
    fingerprint: str | None = None
    error_text: str | None = None
    synced_at: str | None = None

    def as_db_params(self) -> dict[str, Any]:
        if self.status not in VALID_STATUSES:
            raise ValueError(f'Trang thai khong hop le: {self.status}')

        return {
            'source_chat_id': self.source_chat_id,
            'source_msg_id': self.source_msg_id,
            'status': self.status,
            'extension': self.extension,
            'document_id': self.document_id,
            'filename': self.filename,
            'normalized_filename': self.normalized_filename,
            'size': self.size,
            'dest_chat_id': self.dest_chat_id,
            'dest_topic_id': self.dest_topic_id,
            'dest_msg_id': self.dest_msg_id,
            'fingerprint': self.fingerprint,
            'error_text': self.error_text,
            'synced_at': self.synced_at or utcnow_iso(),
        }


class SyncStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self.initialize()

    def initialize(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS sources (
                    source_chat_id INTEGER PRIMARY KEY,
                    dest_chat_id INTEGER NOT NULL,
                    dest_topic_default INTEGER NOT NULL,
                    dest_topic_archive INTEGER NOT NULL,
                    label TEXT,
                    source_invite_link TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    allow_protected_fallback INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sources_enabled
                ON sources (enabled, source_chat_id);

                CREATE TABLE IF NOT EXISTS sync_state (
                    source_chat_id INTEGER NOT NULL,
                    source_msg_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    extension TEXT,
                    document_id INTEGER,
                    filename TEXT,
                    normalized_filename TEXT NOT NULL DEFAULT '',
                    size INTEGER,
                    dest_chat_id INTEGER,
                    dest_topic_id INTEGER,
                    dest_msg_id INTEGER,
                    fingerprint TEXT,
                    error_text TEXT,
                    synced_at TEXT NOT NULL,
                    PRIMARY KEY (source_chat_id, source_msg_id)
                );

                CREATE INDEX IF NOT EXISTS idx_sync_state_status
                ON sync_state (source_chat_id, status, source_msg_id);

                CREATE TABLE IF NOT EXISTS txt_fingerprints (
                    fingerprint TEXT PRIMARY KEY,
                    source_chat_id INTEGER NOT NULL,
                    first_source_msg_id INTEGER NOT NULL,
                    dest_chat_id INTEGER,
                    dest_topic_id INTEGER,
                    dest_msg_id INTEGER,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cursor (
                    source_chat_id INTEGER PRIMARY KEY,
                    last_scanned_source_msg_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def close(self) -> None:
        self._conn.close()

    def checkpoint(self) -> None:
        """Flushes the WAL file into the main database file to ensure safe backups."""
        with self._conn:
            self._conn.execute('PRAGMA wal_checkpoint(TRUNCATE);')

    def get_source(self, source_chat_id: int) -> SourceRecord | None:
        row = self._conn.execute(
            'SELECT * FROM sources WHERE source_chat_id = ?',
            (source_chat_id,),
        ).fetchone()
        if row is None:
            return None
        return self._source_from_row(row)

    def list_sources(self, enabled_only: bool | None = None) -> list[SourceRecord]:
        query = 'SELECT * FROM sources'
        params: list[Any] = []
        if enabled_only is True:
            query += ' WHERE enabled = 1'
        elif enabled_only is False:
            pass
        else:
            query += ' WHERE enabled IN (0, 1)'
        query += ' ORDER BY source_chat_id ASC'
        rows = self._conn.execute(query, params).fetchall()
        return [self._source_from_row(row) for row in rows]

    def upsert_source(self, source: SourceRecord) -> None:
        params = source.as_db_params()
        existing = self.get_source(source.source_chat_id)
        if existing is not None and source.created_at is None:
            params['created_at'] = existing.created_at or utcnow_iso()

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO sources (
                    source_chat_id,
                    dest_chat_id,
                    dest_topic_default,
                    dest_topic_archive,
                    label,
                    source_invite_link,
                    enabled,
                    allow_protected_fallback,
                    created_at,
                    updated_at
                )
                VALUES (
                    :source_chat_id,
                    :dest_chat_id,
                    :dest_topic_default,
                    :dest_topic_archive,
                    :label,
                    :source_invite_link,
                    :enabled,
                    :allow_protected_fallback,
                    :created_at,
                    :updated_at
                )
                ON CONFLICT(source_chat_id) DO UPDATE SET
                    dest_chat_id = excluded.dest_chat_id,
                    dest_topic_default = excluded.dest_topic_default,
                    dest_topic_archive = excluded.dest_topic_archive,
                    label = excluded.label,
                    source_invite_link = excluded.source_invite_link,
                    enabled = excluded.enabled,
                    allow_protected_fallback = excluded.allow_protected_fallback,
                    updated_at = excluded.updated_at
                """,
                params,
            )

    def delete_source(self, source_chat_id: int) -> None:
        with self._conn:
            self._conn.execute('DELETE FROM sources WHERE source_chat_id = ?', (source_chat_id,))

    def set_source_enabled(self, source_chat_id: int, enabled: bool) -> None:
        with self._conn:
            self._conn.execute(
                'UPDATE sources SET enabled = ?, updated_at = ? WHERE source_chat_id = ?',
                (int(enabled), utcnow_iso(), source_chat_id),
            )

    def update_source_destination(
        self,
        source_chat_id: int,
        dest_chat_id: int,
        dest_topic_default: int,
        dest_topic_archive: int,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                UPDATE sources
                SET dest_chat_id = ?,
                    dest_topic_default = ?,
                    dest_topic_archive = ?,
                    updated_at = ?
                WHERE source_chat_id = ?
                """,
                (
                    dest_chat_id,
                    dest_topic_default,
                    dest_topic_archive,
                    utcnow_iso(),
                    source_chat_id,
                ),
            )

    def update_source_label(self, source_chat_id: int, label: str | None) -> None:
        with self._conn:
            self._conn.execute(
                'UPDATE sources SET label = ?, updated_at = ? WHERE source_chat_id = ?',
                (label, utcnow_iso(), source_chat_id),
            )

    def update_source_protected_fallback(self, source_chat_id: int, allow: bool) -> None:
        with self._conn:
            self._conn.execute(
                'UPDATE sources SET allow_protected_fallback = ?, updated_at = ? WHERE source_chat_id = ?',
                (int(allow), utcnow_iso(), source_chat_id),
            )

    def count_sources(self, enabled_only: bool | None = None) -> int:
        if enabled_only is True:
            query = 'SELECT COUNT(*) AS total FROM sources WHERE enabled = 1'
            params = ()
        elif enabled_only is False:
            query = 'SELECT COUNT(*) AS total FROM sources WHERE enabled = 0'
            params = ()
        else:
            query = 'SELECT COUNT(*) AS total FROM sources'
            params = ()
        row = self._conn.execute(query, params).fetchone()
        return int(row['total']) if row else 0

    def get_cursor(self, source_chat_id: int) -> int:
        row = self._conn.execute(
            'SELECT last_scanned_source_msg_id FROM cursor WHERE source_chat_id = ?',
            (source_chat_id,),
        ).fetchone()
        if row is None:
            return 0
        return int(row['last_scanned_source_msg_id'])

    def set_cursor(self, source_chat_id: int, last_scanned_source_msg_id: int) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO cursor (source_chat_id, last_scanned_source_msg_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source_chat_id) DO UPDATE SET
                    last_scanned_source_msg_id = excluded.last_scanned_source_msg_id,
                    updated_at = excluded.updated_at
                """,
                (source_chat_id, last_scanned_source_msg_id, utcnow_iso()),
            )

    def get_record(self, source_chat_id: int, source_msg_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT *
            FROM sync_state
            WHERE source_chat_id = ? AND source_msg_id = ?
            """,
            (source_chat_id, source_msg_id),
        ).fetchone()

    def upsert_record(self, record: SyncStateRecord) -> None:
        params = record.as_db_params()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO sync_state (
                    source_chat_id,
                    source_msg_id,
                    status,
                    extension,
                    document_id,
                    filename,
                    normalized_filename,
                    size,
                    dest_chat_id,
                    dest_topic_id,
                    dest_msg_id,
                    fingerprint,
                    error_text,
                    synced_at
                )
                VALUES (
                    :source_chat_id,
                    :source_msg_id,
                    :status,
                    :extension,
                    :document_id,
                    :filename,
                    :normalized_filename,
                    :size,
                    :dest_chat_id,
                    :dest_topic_id,
                    :dest_msg_id,
                    :fingerprint,
                    :error_text,
                    :synced_at
                )
                ON CONFLICT(source_chat_id, source_msg_id) DO UPDATE SET
                    status = excluded.status,
                    extension = excluded.extension,
                    document_id = excluded.document_id,
                    filename = excluded.filename,
                    normalized_filename = excluded.normalized_filename,
                    size = excluded.size,
                    dest_chat_id = excluded.dest_chat_id,
                    dest_topic_id = excluded.dest_topic_id,
                    dest_msg_id = excluded.dest_msg_id,
                    fingerprint = excluded.fingerprint,
                    error_text = excluded.error_text,
                    synced_at = excluded.synced_at
                """,
                params,
            )

    def list_failed(self, source_chat_id: int, limit: int | None = None) -> list[sqlite3.Row]:
        query = """
            SELECT *
            FROM sync_state
            WHERE source_chat_id = ? AND status = ?
            ORDER BY source_msg_id ASC
        """
        params: list[Any] = [source_chat_id, STATUS_FAILED]
        if limit is not None:
            query += ' LIMIT ?'
            params.append(limit)
        return list(self._conn.execute(query, params))

    def has_txt_fingerprint(self, fingerprint: str) -> bool:
        row = self._conn.execute(
            'SELECT 1 FROM txt_fingerprints WHERE fingerprint = ?',
            (fingerprint,),
        ).fetchone()
        return row is not None

    def add_txt_fingerprint(
        self,
        fingerprint: str,
        source_chat_id: int,
        first_source_msg_id: int,
        dest_chat_id: int | None,
        dest_topic_id: int | None,
        dest_msg_id: int | None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO txt_fingerprints (
                    fingerprint,
                    source_chat_id,
                    first_source_msg_id,
                    dest_chat_id,
                    dest_topic_id,
                    dest_msg_id,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fingerprint,
                    source_chat_id,
                    first_source_msg_id,
                    dest_chat_id,
                    dest_topic_id,
                    dest_msg_id,
                    utcnow_iso(),
                ),
            )

    def _source_from_row(self, row: sqlite3.Row) -> SourceRecord:
        return SourceRecord(
            source_chat_id=int(row['source_chat_id']),
            dest_chat_id=int(row['dest_chat_id']),
            dest_topic_default=int(row['dest_topic_default']),
            dest_topic_archive=int(row['dest_topic_archive']),
            label=row['label'],
            source_invite_link=row['source_invite_link'],
            enabled=bool(row['enabled']),
            allow_protected_fallback=bool(row['allow_protected_fallback']),
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
