from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.database.models import (
    AccountCreateRequest,
    AccountMembershipModel,
    AccountUpdateRequest,
    BackupFilterConfig,
    BackupJobCreateRequest,
    BackupJobUpdateRequest,
    ChatGroupUpsertRequest,
    ChatRuleModel,
    ChatRuleUpdateRequest,
    ChatTopicModel,
    FallbackPolicyConfig,
    FolderChatEntry,
    FolderCreateRequest,
    FolderUpdateRequest,
    MediaLibraryCreateRequest,
    ScenarioCreateRequest,
    ScenarioStepInput,
    ScenarioTargetInput,
    ScenarioUpdateRequest,
)


def utcnow_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class DatabaseStore:
    """Thread-safe SQLite store (WAL mode) for Telegram Backup & Auto-Messaging Suite."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.initialize()

    def initialize(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    phone TEXT NOT NULL UNIQUE,
                    api_id INTEGER,
                    api_hash TEXT,
                    session_path TEXT NOT NULL,
                    proxy_url TEXT,
                    status TEXT NOT NULL DEFAULT 'need_login',
                    tg_user_id INTEGER,
                    tg_username TEXT,
                    flood_wait_until TEXT,
                    max_messages_per_hour INTEGER NOT NULL DEFAULT 60,
                    max_messages_per_day INTEGER NOT NULL DEFAULT 500,
                    health_check_at TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_groups (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    username TEXT,
                    chat_type TEXT NOT NULL DEFAULT 'supergroup',
                    is_forum INTEGER NOT NULL DEFAULT 0,
                    participants_count INTEGER,
                    default_topic_id INTEGER,
                    discovered_by_account_id INTEGER,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS account_memberships (
                    account_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT 'member',
                    can_send_messages INTEGER NOT NULL DEFAULT 1,
                    can_send_media INTEGER NOT NULL DEFAULT 1,
                    can_send_stickers INTEGER NOT NULL DEFAULT 1,
                    can_embed_links INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, chat_id),
                    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                    FOREIGN KEY (chat_id) REFERENCES chat_groups(chat_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_memberships_chat
                ON account_memberships (chat_id, account_id);

                CREATE TABLE IF NOT EXISTS chat_topics (
                    chat_id INTEGER NOT NULL,
                    topic_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    icon_color INTEGER,
                    is_closed INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, topic_id),
                    FOREIGN KEY (chat_id) REFERENCES chat_groups(chat_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS chat_rules (
                    chat_id INTEGER PRIMARY KEY,
                    no_links INTEGER NOT NULL DEFAULT 0,
                    no_stickers INTEGER NOT NULL DEFAULT 0,
                    no_forwards INTEGER NOT NULL DEFAULT 0,
                    no_media INTEGER NOT NULL DEFAULT 0,
                    no_bot_mentions INTEGER NOT NULL DEFAULT 0,
                    slow_mode_seconds INTEGER NOT NULL DEFAULT 0,
                    banned_words_json TEXT NOT NULL DEFAULT '[]',
                    auto_learned INTEGER NOT NULL DEFAULT 0,
                    notes TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (chat_id) REFERENCES chat_groups(chat_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    color TEXT NOT NULL DEFAULT '#10b981',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS folder_chats (
                    folder_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    topic_id INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (folder_id, chat_id, topic_id),
                    FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE,
                    FOREIGN KEY (chat_id) REFERENCES chat_groups(chat_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS backup_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    reader_account_id INTEGER NOT NULL,
                    sender_account_id INTEGER NOT NULL,
                    source_chat_id INTEGER NOT NULL,
                    source_topic_id INTEGER,
                    dest_chat_id INTEGER NOT NULL,
                    dest_topic_default INTEGER NOT NULL DEFAULT 0,
                    dest_topic_archive INTEGER NOT NULL DEFAULT 0,
                    filter_config_json TEXT NOT NULL,
                    caption_mode TEXT NOT NULL DEFAULT 'strip_for_txt',
                    custom_caption_template TEXT,
                    dedupe_enabled INTEGER NOT NULL DEFAULT 1,
                    allow_protected_fallback INTEGER NOT NULL DEFAULT 1,
                    send_delay_min_ms INTEGER NOT NULL DEFAULT 800,
                    send_delay_max_ms INTEGER NOT NULL DEFAULT 1500,
                    last_scanned_msg_id INTEGER NOT NULL DEFAULT 0,
                    total_synced_count INTEGER NOT NULL DEFAULT 0,
                    last_sync_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_backup_jobs_enabled
                ON backup_jobs (enabled, source_chat_id);

                CREATE TABLE IF NOT EXISTS sync_state (
                    backup_job_id INTEGER NOT NULL,
                    source_chat_id INTEGER NOT NULL,
                    source_msg_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    content_type TEXT NOT NULL DEFAULT 'document',
                    extension TEXT,
                    document_id INTEGER,
                    filename TEXT,
                    normalized_filename TEXT NOT NULL DEFAULT '',
                    size INTEGER,
                    dest_chat_id INTEGER,
                    dest_topic_id INTEGER,
                    dest_msg_id INTEGER,
                    fingerprint TEXT,
                    used_protected_fallback INTEGER NOT NULL DEFAULT 0,
                    error_text TEXT,
                    synced_at TEXT NOT NULL,
                    PRIMARY KEY (backup_job_id, source_msg_id),
                    FOREIGN KEY (backup_job_id) REFERENCES backup_jobs(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sync_state_job_status
                ON sync_state (backup_job_id, status, source_msg_id DESC);

                CREATE TABLE IF NOT EXISTS file_fingerprints (
                    fingerprint TEXT PRIMARY KEY,
                    backup_job_id INTEGER NOT NULL,
                    source_chat_id INTEGER NOT NULL,
                    first_source_msg_id INTEGER NOT NULL,
                    filename TEXT,
                    dest_chat_id INTEGER,
                    dest_topic_id INTEGER,
                    dest_msg_id INTEGER,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scenarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    sender_account_id INTEGER,
                    schedule_type TEXT NOT NULL DEFAULT 'interval',
                    interval_seconds INTEGER NOT NULL DEFAULT 1800,
                    jitter_min_sec INTEGER NOT NULL DEFAULT 5,
                    jitter_max_sec INTEGER NOT NULL DEFAULT 30,
                    daily_times_json TEXT NOT NULL DEFAULT '[]',
                    active_hours_start TEXT,
                    active_hours_end TEXT,
                    delete_previous_sent_message INTEGER NOT NULL DEFAULT 0,
                    delete_if_within_x_messages INTEGER NOT NULL DEFAULT 0,
                    skip_if_within_x_messages INTEGER NOT NULL DEFAULT 0,
                    selection_mode TEXT NOT NULL DEFAULT 'sequential',
                    step_cursor INTEGER NOT NULL DEFAULT 0,
                    total_sent_count INTEGER NOT NULL DEFAULT 0,
                    last_run_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scenario_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scenario_id INTEGER NOT NULL,
                    step_order INTEGER NOT NULL DEFAULT 1,
                    name TEXT NOT NULL DEFAULT 'Bước 1',
                    action_type TEXT NOT NULL DEFAULT 'send_text',
                    text_content TEXT,
                    media_path TEXT,
                    sticker_id_or_path TEXT,
                    forward_from_chat_id INTEGER,
                    forward_from_msg_id INTEGER,
                    via_bot_username TEXT,
                    fallback_policy_json TEXT NOT NULL,
                    FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_scenario_steps_scenario
                ON scenario_steps (scenario_id, step_order ASC);

                CREATE TABLE IF NOT EXISTS scenario_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scenario_id INTEGER NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id INTEGER NOT NULL,
                    topic_id INTEGER NOT NULL DEFAULT 0,
                    override_step_order INTEGER,
                    override_text_content TEXT,
                    interval_override_seconds INTEGER,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_sent_at TEXT,
                    next_run_at TEXT,
                    FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_scenario_targets_due
                ON scenario_targets (enabled, next_run_at);

                CREATE TABLE IF NOT EXISTS scenario_sent_history (
                    scenario_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    topic_id INTEGER NOT NULL DEFAULT 0,
                    account_id INTEGER NOT NULL,
                    last_sent_msg_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scenario_id, chat_id, topic_id),
                    FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS media_library (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    item_type TEXT NOT NULL DEFAULT 'text_template',
                    content_or_path TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS execution_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    level TEXT NOT NULL DEFAULT 'INFO',
                    account_id INTEGER,
                    chat_id INTEGER,
                    topic_id INTEGER,
                    scenario_id INTEGER,
                    backup_job_id INTEGER,
                    action_attempted TEXT,
                    action_executed TEXT,
                    fallback_applied INTEGER NOT NULL DEFAULT 0,
                    fallback_reason TEXT,
                    status TEXT NOT NULL DEFAULT 'success',
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_execution_logs_created
                ON execution_logs (id DESC);

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            # Safe schema migrations if upgrading from v2.0 initial tables
            self._ensure_column("accounts", "max_messages_per_hour", "INTEGER NOT NULL DEFAULT 60")
            self._ensure_column("accounts", "max_messages_per_day", "INTEGER NOT NULL DEFAULT 500")
            self._ensure_column("accounts", "health_check_at", "TEXT")
            self._ensure_column("chat_groups", "participants_count", "INTEGER")
            self._ensure_column("scenarios", "active_hours_start", "TEXT")
            self._ensure_column("scenarios", "active_hours_end", "TEXT")
            self._ensure_column(
                "scenarios", "delete_previous_sent_message", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                "scenarios", "delete_if_within_x_messages", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                "scenarios", "skip_if_within_x_messages", "INTEGER NOT NULL DEFAULT 0"
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self._conn:
            yield self._conn

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        cols = [
            r["name"]
            for r in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        ]
        if column not in cols:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def checkpoint(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    # -------------------------------------------------------------------------
    # GLOBAL PANIC / KILL SWITCH
    # -------------------------------------------------------------------------
    def is_global_paused(self) -> bool:
        settings = self.get_settings()
        return bool(settings.get("global_pause", False))

    def set_global_paused(self, paused: bool) -> bool:
        self.set_settings({"global_pause": bool(paused)})
        return self.is_global_paused()

    # -------------------------------------------------------------------------
    # ACCOUNTS & QUOTA CRUD
    # -------------------------------------------------------------------------
    def create_account(self, req: AccountCreateRequest, sessions_dir: Path) -> dict[str, Any]:
        now = utcnow_iso()
        safe_phone = "".join(ch for ch in req.phone if ch.isalnum() or ch == "+")
        session_file = str((sessions_dir / f"acc_{safe_phone.lstrip('+')}.session").resolve())
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO accounts (
                    label, phone, api_id, api_hash, session_path, proxy_url,
                    max_messages_per_hour, max_messages_per_day,
                    status, enabled, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'need_login', ?, ?, ?)
                """,
                (
                    req.label.strip(),
                    req.phone.strip(),
                    req.api_id,
                    req.api_hash,
                    session_file,
                    req.proxy_url,
                    req.max_messages_per_hour,
                    req.max_messages_per_day,
                    int(req.enabled),
                    now,
                    now,
                ),
            )
            account_id = int(cur.lastrowid)
        return self.get_account(account_id)  # type: ignore[return-value]

    def get_account_send_counts(self, account_id: int) -> dict[str, int]:
        now = datetime.now(UTC)
        five_min_ago = (now - timedelta(minutes=5)).replace(microsecond=0).isoformat()
        one_hour_ago = (now - timedelta(hours=1)).replace(microsecond=0).isoformat()
        one_day_ago = (now - timedelta(hours=24)).replace(microsecond=0).isoformat()
        with self._lock:
            sent_5m = self._conn.execute(
                """
                SELECT COUNT(*) AS c FROM execution_logs
                WHERE account_id = ? AND category = 'auto_send' AND status = 'success'
                  AND created_at >= ?
                """,
                (account_id, five_min_ago),
            ).fetchone()["c"]
            sent_1h = self._conn.execute(
                """
                SELECT COUNT(*) AS c FROM execution_logs
                WHERE account_id = ? AND category = 'auto_send' AND status = 'success'
                  AND created_at >= ?
                """,
                (account_id, one_hour_ago),
            ).fetchone()["c"]
            sent_24h = self._conn.execute(
                """
                SELECT COUNT(*) AS c FROM execution_logs
                WHERE account_id = ? AND category = 'auto_send' AND status = 'success'
                  AND created_at >= ?
                """,
                (account_id, one_day_ago),
            ).fetchone()["c"]
            joined_groups = self._conn.execute(
                "SELECT COUNT(*) AS c FROM account_memberships WHERE account_id = ?",
                (account_id,),
            ).fetchone()["c"]
        return {
            "sent_last_5m": int(sent_5m),
            "sent_last_hour": int(sent_1h),
            "sent_last_24h": int(sent_24h),
            "joined_groups_count": int(joined_groups),
        }

    def is_account_within_quota(self, account_id: int) -> tuple[bool, str | None]:
        acc = self.get_account(account_id)
        if not acc:
            return False, f"Không tìm thấy tài khoản #{account_id}"
        if not acc.get("enabled"):
            return False, "Tài khoản đang bị tắt (disabled)"

        now_iso = utcnow_iso()
        fw_until = acc.get("flood_wait_until")
        if fw_until:
            if str(fw_until) > now_iso:
                return (
                    False,
                    f"Đang tạm nghỉ chống Spam/FloodWait đến {fw_until}",
                )
            # Expired cooldown -> auto restore if status was flood_wait
            if acc.get("status") in ("flood_wait", "spam_limited"):
                self.update_account_status(
                    account_id,
                    "connected",
                    flood_wait_until=None,
                    last_error=None,
                )

        counts = acc.get("usage") or self.get_account_send_counts(account_id)
        max_1h = int(acc.get("max_messages_per_hour") or 60)
        max_24h = int(acc.get("max_messages_per_day") or 500)
        if counts["sent_last_hour"] >= max_1h:
            return False, f"Đã chạm hạn mức giờ ({counts['sent_last_hour']}/{max_1h} tin/1h)"
        if counts["sent_last_24h"] >= max_24h:
            return False, f"Đã chạm hạn mức ngày ({counts['sent_last_24h']}/{max_24h} tin/24h)"
        return True, None

    def quarantine_account_flood(
        self,
        account_id: int,
        wait_seconds: int,
        reason: str,
        *,
        status: str = "flood_wait",
    ) -> str:
        until_iso = (
            datetime.now(UTC) + timedelta(seconds=max(10, int(wait_seconds)))
        ).replace(microsecond=0).isoformat()
        self.update_account_status(
            account_id,
            status,
            flood_wait_until=until_iso,
            last_error=f"{reason} (Tạm nghỉ đến {until_iso})",
        )
        return until_iso

    def get_known_account_tg_user_ids(self) -> set[int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT tg_user_id FROM accounts WHERE tg_user_id IS NOT NULL"
            ).fetchall()
        return {int(r["tg_user_id"]) for r in rows if r["tg_user_id"] is not None}

    def get_account(self, account_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
        return self._row_to_account(row) if row else None

    def list_accounts(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM accounts"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY id ASC"
        with self._lock:
            rows = self._conn.execute(query).fetchall()
        return [self._row_to_account(r) for r in rows]

    def update_account(self, account_id: int, req: AccountUpdateRequest) -> dict[str, Any] | None:
        existing = self.get_account(account_id)
        if not existing:
            return None
        now = utcnow_iso()
        label = req.label.strip() if req.label is not None else existing["label"]
        phone = req.phone.strip() if req.phone is not None else existing["phone"]
        api_id = req.api_id if req.api_id is not None else existing["api_id"]
        api_hash = req.api_hash if req.api_hash is not None else existing["api_hash"]
        proxy_url = req.proxy_url if req.proxy_url is not None else existing["proxy_url"]
        max_1h = (
            req.max_messages_per_hour
            if req.max_messages_per_hour is not None
            else existing["max_messages_per_hour"]
        )
        max_24h = (
            req.max_messages_per_day
            if req.max_messages_per_day is not None
            else existing["max_messages_per_day"]
        )
        enabled = int(req.enabled) if req.enabled is not None else int(existing["enabled"])

        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE accounts
                SET label = ?, phone = ?, api_id = ?, api_hash = ?, proxy_url = ?,
                    max_messages_per_hour = ?, max_messages_per_day = ?,
                    enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (label, phone, api_id, api_hash, proxy_url, max_1h, max_24h, enabled, now, account_id),
            )
        return self.get_account(account_id)

    def update_account_status(
        self,
        account_id: int,
        status: str,
        *,
        tg_user_id: int | None = None,
        tg_username: str | None = None,
        flood_wait_until: str | None = None,
        last_error: str | None = None,
    ) -> None:
        now = utcnow_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE accounts
                SET status = ?,
                    tg_user_id = COALESCE(?, tg_user_id),
                    tg_username = COALESCE(?, tg_username),
                    flood_wait_until = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    tg_user_id,
                    tg_username,
                    flood_wait_until,
                    last_error,
                    now,
                    account_id,
                ),
            )

    def delete_account(self, account_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            return cur.rowcount > 0

    def _row_to_account(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        usage = self.get_account_send_counts(int(d["id"]))
        d["usage"] = usage
        d["sent_last_hour"] = usage["sent_last_hour"]
        d["sent_last_24h"] = usage["sent_last_24h"]
        d["joined_groups_count"] = usage["joined_groups_count"]
        return d

    # -------------------------------------------------------------------------
    # ACCOUNT MEMBERSHIPS & FORUM TOPICS CRUD
    # -------------------------------------------------------------------------
    def upsert_account_membership(self, mem: AccountMembershipModel) -> None:
        now = utcnow_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO account_memberships (
                    account_id, chat_id, role, can_send_messages,
                    can_send_media, can_send_stickers, can_embed_links, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, chat_id) DO UPDATE SET
                    role = excluded.role,
                    can_send_messages = excluded.can_send_messages,
                    can_send_media = excluded.can_send_media,
                    can_send_stickers = excluded.can_send_stickers,
                    can_embed_links = excluded.can_embed_links,
                    updated_at = excluded.updated_at
                """,
                (
                    mem.account_id,
                    mem.chat_id,
                    mem.role,
                    int(mem.can_send_messages),
                    int(mem.can_send_media),
                    int(mem.can_send_stickers),
                    int(mem.can_embed_links),
                    now,
                ),
            )

    def get_chat_memberships(self, chat_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT m.*, a.label AS account_label, a.phone AS account_phone, a.status AS account_status
                FROM account_memberships m
                JOIN accounts a ON m.account_id = a.id
                WHERE m.chat_id = ?
                ORDER BY m.account_id ASC
                """,
                (chat_id,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["can_send_messages"] = bool(d["can_send_messages"])
            d["can_send_media"] = bool(d["can_send_media"])
            d["can_send_stickers"] = bool(d["can_send_stickers"])
            d["can_embed_links"] = bool(d["can_embed_links"])
            result.append(d)
        return result

    def get_member_accounts_for_chat(
        self, chat_id: int, require_send_permission: bool = False
    ) -> list[dict[str, Any]]:
        memberships = self.get_chat_memberships(chat_id)
        if require_send_permission:
            return [m for m in memberships if m.get("can_send_messages", True)]
        return memberships

    def upsert_chat_topic(self, topic: ChatTopicModel) -> dict[str, Any]:
        now = utcnow_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO chat_topics (chat_id, topic_id, title, icon_color, is_closed, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, topic_id) DO UPDATE SET
                    title = excluded.title,
                    icon_color = excluded.icon_color,
                    is_closed = excluded.is_closed,
                    updated_at = excluded.updated_at
                """,
                (
                    topic.chat_id,
                    topic.topic_id,
                    topic.title.strip(),
                    topic.icon_color,
                    int(topic.is_closed),
                    now,
                ),
            )
        return {
            "chat_id": topic.chat_id,
            "topic_id": topic.topic_id,
            "title": topic.title.strip(),
            "icon_color": topic.icon_color,
            "is_closed": topic.is_closed,
            "updated_at": now,
        }

    def upsert_chat_topics(
        self, chat_id: int, topics: list[ChatTopicModel]
    ) -> list[dict[str, Any]]:
        for t in topics:
            self.upsert_chat_topic(
                ChatTopicModel(
                    chat_id=chat_id,
                    topic_id=t.topic_id,
                    title=t.title,
                    icon_color=t.icon_color,
                    is_closed=t.is_closed,
                    is_pinned=getattr(t, "is_pinned", False),
                )
            )
        return self.list_chat_topics(chat_id)

    def list_chat_topics(self, chat_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM chat_topics WHERE chat_id = ? ORDER BY topic_id ASC",
                (chat_id,),
            ).fetchall()
        return [
            {
                "chat_id": int(r["chat_id"]),
                "topic_id": int(r["topic_id"]),
                "title": r["title"],
                "icon_color": r["icon_color"],
                "is_closed": bool(r["is_closed"]),
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    # -------------------------------------------------------------------------
    # CHAT GROUPS & RULES CRUD
    # -------------------------------------------------------------------------
    def upsert_chat_group(self, req: ChatGroupUpsertRequest) -> dict[str, Any]:
        now = utcnow_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO chat_groups (
                    chat_id, title, username, chat_type, is_forum,
                    participants_count, default_topic_id, discovered_by_account_id, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title = excluded.title,
                    username = COALESCE(excluded.username, chat_groups.username),
                    chat_type = excluded.chat_type,
                    is_forum = excluded.is_forum,
                    participants_count = COALESCE(excluded.participants_count, chat_groups.participants_count),
                    default_topic_id = COALESCE(excluded.default_topic_id, chat_groups.default_topic_id),
                    discovered_by_account_id = COALESCE(excluded.discovered_by_account_id, chat_groups.discovered_by_account_id),
                    updated_at = excluded.updated_at
                """,
                (
                    req.chat_id,
                    req.title.strip(),
                    req.username,
                    req.chat_type,
                    int(req.is_forum),
                    req.participants_count,
                    req.default_topic_id,
                    req.discovered_by_account_id,
                    now,
                ),
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO chat_rules (
                    chat_id, no_links, no_stickers, no_forwards, no_media,
                    no_bot_mentions, slow_mode_seconds, banned_words_json,
                    auto_learned, updated_at
                )
                VALUES (?, 0, 0, 0, 0, 0, 0, '[]', 0, ?)
                """,
                (req.chat_id, now),
            )
            if req.rules is not None:
                self._conn.execute(
                    """
                    UPDATE chat_rules
                    SET no_links = ?,
                        no_stickers = ?,
                        no_forwards = ?,
                        no_media = ?,
                        no_bot_mentions = ?,
                        slow_mode_seconds = ?,
                        banned_words_json = ?,
                        auto_learned = ?,
                        notes = COALESCE(?, notes),
                        updated_at = ?
                    WHERE chat_id = ?
                    """,
                    (
                        int(req.rules.no_links),
                        int(req.rules.no_stickers),
                        int(req.rules.no_forwards),
                        int(req.rules.no_media),
                        int(req.rules.no_bot_mentions),
                        req.rules.slow_mode_seconds,
                        json.dumps(req.rules.banned_words, ensure_ascii=False),
                        int(req.rules.auto_learned),
                        req.rules.notes,
                        now,
                        req.chat_id,
                    ),
                )
            if req.discovered_by_account_id is not None:
                self.upsert_account_membership(
                    AccountMembershipModel(
                        account_id=req.discovered_by_account_id,
                        chat_id=req.chat_id,
                    )
                )
        return self.get_chat_group(req.chat_id)  # type: ignore[return-value]

    def get_chat_group(self, chat_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT g.*,
                       r.no_links, r.no_stickers, r.no_forwards, r.no_media,
                       r.no_bot_mentions, r.slow_mode_seconds, r.banned_words_json,
                       r.auto_learned, r.notes, r.updated_at AS rule_updated_at
                FROM chat_groups g
                LEFT JOIN chat_rules r ON g.chat_id = r.chat_id
                WHERE g.chat_id = ?
                """,
                (chat_id,),
            ).fetchone()
        return self._row_to_chat_group(row) if row else None

    def list_chat_groups(self, account_id: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if account_id is not None:
                rows = self._conn.execute(
                    """
                    SELECT g.*,
                           r.no_links, r.no_stickers, r.no_forwards, r.no_media,
                           r.no_bot_mentions, r.slow_mode_seconds, r.banned_words_json,
                           r.auto_learned, r.notes, r.updated_at AS rule_updated_at
                    FROM chat_groups g
                    INNER JOIN account_memberships m ON g.chat_id = m.chat_id AND m.account_id = ?
                    LEFT JOIN chat_rules r ON g.chat_id = r.chat_id
                    ORDER BY g.title COLLATE NOCASE ASC
                    """,
                    (account_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT g.*,
                           r.no_links, r.no_stickers, r.no_forwards, r.no_media,
                           r.no_bot_mentions, r.slow_mode_seconds, r.banned_words_json,
                           r.auto_learned, r.notes, r.updated_at AS rule_updated_at
                    FROM chat_groups g
                    LEFT JOIN chat_rules r ON g.chat_id = r.chat_id
                    ORDER BY g.title COLLATE NOCASE ASC
                    """
                ).fetchall()
        return [self._row_to_chat_group(r) for r in rows]

    def get_chat_rule(self, chat_id: int) -> ChatRuleModel:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM chat_rules WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        if not row:
            return ChatRuleModel(chat_id=chat_id)
        return ChatRuleModel(
            chat_id=int(row["chat_id"]),
            no_links=bool(row["no_links"]),
            no_stickers=bool(row["no_stickers"]),
            no_forwards=bool(row["no_forwards"]),
            no_media=bool(row["no_media"]),
            no_bot_mentions=bool(row["no_bot_mentions"]),
            slow_mode_seconds=int(row["slow_mode_seconds"]),
            banned_words=json.loads(row["banned_words_json"] or "[]"),
            auto_learned=bool(row["auto_learned"]),
            notes=row["notes"],
            updated_at=row["updated_at"],
        )

    def update_chat_rule(self, chat_id: int, req: ChatRuleUpdateRequest) -> dict[str, Any]:
        now = utcnow_iso()
        existing = self.get_chat_group(chat_id)
        if not existing:
            self.upsert_chat_group(ChatGroupUpsertRequest(chat_id=chat_id, title=f"Chat {chat_id}"))

        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE chat_rules
                SET no_links = ?,
                    no_stickers = ?,
                    no_forwards = ?,
                    no_media = ?,
                    no_bot_mentions = ?,
                    slow_mode_seconds = ?,
                    banned_words_json = ?,
                    notes = ?,
                    updated_at = ?
                WHERE chat_id = ?
                """,
                (
                    int(req.no_links),
                    int(req.no_stickers),
                    int(req.no_forwards),
                    int(req.no_media),
                    int(req.no_bot_mentions),
                    req.slow_mode_seconds,
                    json.dumps(req.banned_words, ensure_ascii=False),
                    req.notes,
                    now,
                    chat_id,
                ),
            )
        return self.get_chat_group(chat_id)  # type: ignore[return-value]

    def auto_learn_chat_restriction(
        self,
        chat_id: int,
        *,
        no_links: bool | None = None,
        no_stickers: bool | None = None,
        no_forwards: bool | None = None,
        no_media: bool | None = None,
        no_bot_mentions: bool | None = None,
        slow_mode_seconds: int | None = None,
        reason_note: str | None = None,
    ) -> ChatRuleModel:
        existing = self.get_chat_group(chat_id)
        if not existing:
            self.upsert_chat_group(ChatGroupUpsertRequest(chat_id=chat_id, title=f"Chat {chat_id}"))

        rule = self.get_chat_rule(chat_id)
        now = utcnow_iso()
        new_notes = rule.notes or ""
        if reason_note and reason_note not in new_notes:
            new_notes = f"{new_notes}; {reason_note}".strip("; ")

        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE chat_rules
                SET no_links = ?,
                    no_stickers = ?,
                    no_forwards = ?,
                    no_media = ?,
                    no_bot_mentions = ?,
                    slow_mode_seconds = ?,
                    auto_learned = 1,
                    notes = ?,
                    updated_at = ?
                WHERE chat_id = ?
                """,
                (
                    int(no_links if no_links is not None else rule.no_links),
                    int(no_stickers if no_stickers is not None else rule.no_stickers),
                    int(no_forwards if no_forwards is not None else rule.no_forwards),
                    int(no_media if no_media is not None else rule.no_media),
                    int(no_bot_mentions if no_bot_mentions is not None else rule.no_bot_mentions),
                    slow_mode_seconds if slow_mode_seconds is not None else rule.slow_mode_seconds,
                    new_notes or None,
                    now,
                    chat_id,
                ),
            )
        return self.get_chat_rule(chat_id)

    def delete_chat_group(self, chat_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM chat_groups WHERE chat_id = ?", (chat_id,))
            return cur.rowcount > 0

    def _row_to_chat_group(self, row: sqlite3.Row) -> dict[str, Any]:
        cid = int(row["chat_id"])
        return {
            "chat_id": cid,
            "title": row["title"],
            "username": row["username"],
            "chat_type": row["chat_type"],
            "is_forum": bool(row["is_forum"]),
            "participants_count": row["participants_count"],
            "default_topic_id": row["default_topic_id"],
            "discovered_by_account_id": row["discovered_by_account_id"],
            "updated_at": row["updated_at"],
            "member_accounts": self.get_chat_memberships(cid),
            "topics": self.list_chat_topics(cid),
            "rules": {
                "chat_id": cid,
                "no_links": bool(row["no_links"]),
                "no_stickers": bool(row["no_stickers"]),
                "no_forwards": bool(row["no_forwards"]),
                "no_media": bool(row["no_media"]),
                "no_bot_mentions": bool(row["no_bot_mentions"]),
                "slow_mode_seconds": int(row["slow_mode_seconds"] or 0),
                "banned_words": json.loads(row["banned_words_json"] or "[]"),
                "auto_learned": bool(row["auto_learned"]),
                "notes": row["notes"],
                "updated_at": row["rule_updated_at"],
            },
        }

    # -------------------------------------------------------------------------
    # FOLDERS CRUD (Independent Web Folders + Optional Telegram Clone)
    # -------------------------------------------------------------------------
    def create_folder(self, req: FolderCreateRequest) -> dict[str, Any]:
        now = utcnow_iso()
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO folders (name, description, color, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    req.name.strip(),
                    req.description,
                    req.color,
                    int(req.enabled),
                    now,
                    now,
                ),
            )
            folder_id = int(cur.lastrowid)
            self._replace_folder_chats(folder_id, req.chats)
        return self.get_folder(folder_id)  # type: ignore[return-value]

    def _replace_folder_chats(self, folder_id: int, chats: list[Any]) -> None:
        self._conn.execute("DELETE FROM folder_chats WHERE folder_id = ?", (folder_id,))
        for entry in chats:
            chat_id = int(entry.chat_id if hasattr(entry, "chat_id") else entry["chat_id"])
            topic_id = int(
                (entry.topic_id if hasattr(entry, "topic_id") else entry.get("topic_id", 0)) or 0
            )
            exists = self._conn.execute(
                "SELECT 1 FROM chat_groups WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            if not exists:
                self.upsert_chat_group(
                    ChatGroupUpsertRequest(chat_id=chat_id, title=f"Group {chat_id}")
                )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO folder_chats (folder_id, chat_id, topic_id)
                VALUES (?, ?, ?)
                """,
                (folder_id, chat_id, topic_id),
            )

    def get_folder(self, folder_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM folders WHERE id = ?", (folder_id,)
            ).fetchone()
            if not row:
                return None
            chat_rows = self._conn.execute(
                """
                SELECT fc.chat_id, fc.topic_id, g.title, g.username
                FROM folder_chats fc
                LEFT JOIN chat_groups g ON fc.chat_id = g.chat_id
                WHERE fc.folder_id = ?
                ORDER BY g.title COLLATE NOCASE ASC
                """,
                (folder_id,),
            ).fetchall()
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        d["chats"] = [dict(r) for r in chat_rows]
        return d

    def list_folders(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM folders ORDER BY name COLLATE NOCASE ASC"
            ).fetchall()
        return [self.get_folder(int(r["id"])) for r in rows if r]  # type: ignore[misc]

    def update_folder(self, folder_id: int, req: FolderUpdateRequest) -> dict[str, Any] | None:
        existing = self.get_folder(folder_id)
        if not existing:
            return None
        now = utcnow_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE folders
                SET name = ?, description = ?, color = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    req.name.strip() if req.name is not None else existing["name"],
                    req.description if req.description is not None else existing["description"],
                    req.color if req.color is not None else existing["color"],
                    int(req.enabled) if req.enabled is not None else int(existing["enabled"]),
                    now,
                    folder_id,
                ),
            )
            if req.chats is not None:
                self._replace_folder_chats(folder_id, req.chats)
        return self.get_folder(folder_id)

    def delete_folder(self, folder_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # BACKUP JOBS & SYNC STATE CRUD
    # -------------------------------------------------------------------------
    def create_backup_job(self, req: BackupJobCreateRequest) -> dict[str, Any]:
        now = utcnow_iso()
        sender_id = req.sender_account_id or req.reader_account_id
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO backup_jobs (
                    label, enabled, reader_account_id, sender_account_id,
                    source_chat_id, source_topic_id, dest_chat_id,
                    dest_topic_default, dest_topic_archive, filter_config_json,
                    caption_mode, custom_caption_template, dedupe_enabled,
                    allow_protected_fallback, send_delay_min_ms, send_delay_max_ms,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.label.strip(),
                    int(req.enabled),
                    req.reader_account_id,
                    sender_id,
                    req.source_chat_id,
                    req.source_topic_id,
                    req.dest_chat_id,
                    req.dest_topic_default,
                    req.dest_topic_archive,
                    req.filter_config.model_dump_json(),
                    req.caption_mode,
                    req.custom_caption_template,
                    int(req.dedupe_enabled),
                    int(req.allow_protected_fallback),
                    req.send_delay_min_ms,
                    req.send_delay_max_ms,
                    now,
                    now,
                ),
            )
            job_id = int(cur.lastrowid)
        return self.get_backup_job(job_id)  # type: ignore[return-value]

    def get_backup_job(self, job_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM backup_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_backup_job(row) if row else None

    def list_backup_jobs(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM backup_jobs"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY id ASC"
        with self._lock:
            rows = self._conn.execute(query).fetchall()
        return [self._row_to_backup_job(r) for r in rows]

    def update_backup_job(
        self, job_id: int, req: BackupJobUpdateRequest
    ) -> dict[str, Any] | None:
        existing = self.get_backup_job(job_id)
        if not existing:
            return None
        now = utcnow_iso()
        filter_json = (
            req.filter_config.model_dump_json()
            if req.filter_config is not None
            else json.dumps(existing["filter_config"], ensure_ascii=False)
        )
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE backup_jobs
                SET label = ?,
                    enabled = ?,
                    reader_account_id = ?,
                    sender_account_id = ?,
                    source_chat_id = ?,
                    source_topic_id = ?,
                    dest_chat_id = ?,
                    dest_topic_default = ?,
                    dest_topic_archive = ?,
                    filter_config_json = ?,
                    caption_mode = ?,
                    custom_caption_template = ?,
                    dedupe_enabled = ?,
                    allow_protected_fallback = ?,
                    send_delay_min_ms = ?,
                    send_delay_max_ms = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    req.label.strip() if req.label is not None else existing["label"],
                    int(req.enabled) if req.enabled is not None else int(existing["enabled"]),
                    req.reader_account_id
                    if req.reader_account_id is not None
                    else existing["reader_account_id"],
                    req.sender_account_id
                    if req.sender_account_id is not None
                    else existing["sender_account_id"],
                    req.source_chat_id
                    if req.source_chat_id is not None
                    else existing["source_chat_id"],
                    req.source_topic_id
                    if req.source_topic_id is not None
                    else existing["source_topic_id"],
                    req.dest_chat_id
                    if req.dest_chat_id is not None
                    else existing["dest_chat_id"],
                    req.dest_topic_default
                    if req.dest_topic_default is not None
                    else existing["dest_topic_default"],
                    req.dest_topic_archive
                    if req.dest_topic_archive is not None
                    else existing["dest_topic_archive"],
                    filter_json,
                    req.caption_mode
                    if req.caption_mode is not None
                    else existing["caption_mode"],
                    req.custom_caption_template
                    if req.custom_caption_template is not None
                    else existing["custom_caption_template"],
                    int(req.dedupe_enabled)
                    if req.dedupe_enabled is not None
                    else int(existing["dedupe_enabled"]),
                    int(req.allow_protected_fallback)
                    if req.allow_protected_fallback is not None
                    else int(existing["allow_protected_fallback"]),
                    req.send_delay_min_ms
                    if req.send_delay_min_ms is not None
                    else existing["send_delay_min_ms"],
                    req.send_delay_max_ms
                    if req.send_delay_max_ms is not None
                    else existing["send_delay_max_ms"],
                    now,
                    job_id,
                ),
            )
        return self.get_backup_job(job_id)

    def update_backup_cursor(
        self, job_id: int, last_scanned_msg_id: int, synced_increment: int = 0
    ) -> None:
        now = utcnow_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE backup_jobs
                SET last_scanned_msg_id = MAX(last_scanned_msg_id, ?),
                    total_synced_count = total_synced_count + ?,
                    last_sync_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (last_scanned_msg_id, synced_increment, now, now, job_id),
            )

    def delete_backup_job(self, job_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM backup_jobs WHERE id = ?", (job_id,))
            return cur.rowcount > 0

    def record_sync_state(
        self,
        *,
        backup_job_id: int,
        source_chat_id: int,
        source_msg_id: int,
        status: str,
        content_type: str = "document",
        extension: str | None = None,
        document_id: int | None = None,
        filename: str | None = None,
        normalized_filename: str = "",
        size: int | None = None,
        dest_chat_id: int | None = None,
        dest_topic_id: int | None = None,
        dest_msg_id: int | None = None,
        fingerprint: str | None = None,
        used_protected_fallback: bool = False,
        error_text: str | None = None,
    ) -> None:
        now = utcnow_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO sync_state (
                    backup_job_id, source_chat_id, source_msg_id, status,
                    content_type, extension, document_id, filename,
                    normalized_filename, size, dest_chat_id, dest_topic_id,
                    dest_msg_id, fingerprint, used_protected_fallback,
                    error_text, synced_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(backup_job_id, source_msg_id) DO UPDATE SET
                    status = excluded.status,
                    content_type = excluded.content_type,
                    extension = excluded.extension,
                    document_id = excluded.document_id,
                    filename = excluded.filename,
                    normalized_filename = excluded.normalized_filename,
                    size = excluded.size,
                    dest_chat_id = excluded.dest_chat_id,
                    dest_topic_id = excluded.dest_topic_id,
                    dest_msg_id = excluded.dest_msg_id,
                    fingerprint = excluded.fingerprint,
                    used_protected_fallback = excluded.used_protected_fallback,
                    error_text = excluded.error_text,
                    synced_at = excluded.synced_at
                """,
                (
                    backup_job_id,
                    source_chat_id,
                    source_msg_id,
                    status,
                    content_type,
                    extension,
                    document_id,
                    filename,
                    normalized_filename,
                    size,
                    dest_chat_id,
                    dest_topic_id,
                    dest_msg_id,
                    fingerprint,
                    int(used_protected_fallback),
                    error_text,
                    now,
                ),
            )

    def get_sync_state(self, backup_job_id: int, source_msg_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sync_state WHERE backup_job_id = ? AND source_msg_id = ?",
                (backup_job_id, source_msg_id),
            ).fetchone()
        return dict(row) if row else None

    def list_sync_history(
        self,
        *,
        backup_job_id: int | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM sync_state WHERE 1=1"
        params: list[Any] = []
        if backup_job_id is not None:
            query += " AND backup_job_id = ?"
            params.append(backup_job_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY synced_at DESC, source_msg_id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def has_fingerprint(self, fingerprint: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM file_fingerprints WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        return row is not None

    def add_fingerprint(
        self,
        *,
        fingerprint: str,
        backup_job_id: int,
        source_chat_id: int,
        first_source_msg_id: int,
        filename: str | None,
        dest_chat_id: int | None,
        dest_topic_id: int | None,
        dest_msg_id: int | None,
    ) -> None:
        now = utcnow_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO file_fingerprints (
                    fingerprint, backup_job_id, source_chat_id, first_source_msg_id,
                    filename, dest_chat_id, dest_topic_id, dest_msg_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fingerprint,
                    backup_job_id,
                    source_chat_id,
                    first_source_msg_id,
                    filename,
                    dest_chat_id,
                    dest_topic_id,
                    dest_msg_id,
                    now,
                ),
            )

    def _row_to_backup_job(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        d["dedupe_enabled"] = bool(d["dedupe_enabled"])
        d["allow_protected_fallback"] = bool(d["allow_protected_fallback"])
        d["filter_config"] = BackupFilterConfig.model_validate_json(
            d.pop("filter_config_json") or "{}"
        ).model_dump()
        return d

    # -------------------------------------------------------------------------
    # SCENARIOS, STEPS, TARGETS & PREVIOUS SENT MSG TRACKING
    # -------------------------------------------------------------------------
    def create_scenario(self, req: ScenarioCreateRequest) -> dict[str, Any]:
        now = utcnow_iso()
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO scenarios (
                    name, description, enabled, sender_account_id,
                    schedule_type, interval_seconds, jitter_min_sec, jitter_max_sec,
                    daily_times_json, active_hours_start, active_hours_end,
                    delete_previous_sent_message, delete_if_within_x_messages,
                    skip_if_within_x_messages, selection_mode, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.name.strip(),
                    req.description,
                    int(req.enabled),
                    req.sender_account_id,
                    req.schedule_type,
                    req.interval_seconds,
                    req.jitter_min_sec,
                    req.jitter_max_sec,
                    json.dumps(req.daily_times),
                    req.active_hours_start,
                    req.active_hours_end,
                    int(req.delete_previous_sent_message),
                    int(req.delete_if_within_x_messages),
                    int(req.skip_if_within_x_messages),
                    req.selection_mode,
                    now,
                    now,
                ),
            )
            scenario_id = int(cur.lastrowid)
            self._replace_scenario_steps(scenario_id, req.steps)
            self._replace_scenario_targets(scenario_id, req.targets)
        return self.get_scenario(scenario_id)  # type: ignore[return-value]

    def _replace_scenario_steps(
        self, scenario_id: int, steps: list[ScenarioStepInput]
    ) -> None:
        self._conn.execute("DELETE FROM scenario_steps WHERE scenario_id = ?", (scenario_id,))
        for idx, step in enumerate(steps, start=1):
            order = step.step_order or idx
            self._conn.execute(
                """
                INSERT INTO scenario_steps (
                    scenario_id, step_order, name, action_type,
                    text_content, media_path, sticker_id_or_path,
                    forward_from_chat_id, forward_from_msg_id,
                    via_bot_username, fallback_policy_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scenario_id,
                    order,
                    step.name,
                    step.action_type,
                    step.text_content,
                    step.media_path,
                    step.sticker_id_or_path,
                    step.forward_from_chat_id,
                    step.forward_from_msg_id,
                    step.via_bot_username,
                    step.fallback_policy.model_dump_json(),
                ),
            )

    def _replace_scenario_targets(
        self, scenario_id: int, targets: list[ScenarioTargetInput]
    ) -> None:
        self._conn.execute("DELETE FROM scenario_targets WHERE scenario_id = ?", (scenario_id,))
        now = utcnow_iso()
        for t in targets:
            self._conn.execute(
                """
                INSERT INTO scenario_targets (
                    scenario_id, target_type, target_id, topic_id,
                    override_step_order, override_text_content,
                    interval_override_seconds, enabled, next_run_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scenario_id,
                    t.target_type,
                    t.target_id,
                    t.topic_id,
                    t.override_step_order,
                    t.override_text_content,
                    t.interval_override_seconds,
                    int(t.enabled),
                    now,
                ),
            )

    def get_scenario(self, scenario_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM scenarios WHERE id = ?", (scenario_id,)
            ).fetchone()
            if not row:
                return None
            step_rows = self._conn.execute(
                "SELECT * FROM scenario_steps WHERE scenario_id = ? ORDER BY step_order ASC, id ASC",
                (scenario_id,),
            ).fetchall()
            target_rows = self._conn.execute(
                "SELECT * FROM scenario_targets WHERE scenario_id = ? ORDER BY id ASC",
                (scenario_id,),
            ).fetchall()

        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        d["delete_previous_sent_message"] = bool(d.get("delete_previous_sent_message", 0))
        d["delete_if_within_x_messages"] = int(d.get("delete_if_within_x_messages") or 0)
        d["skip_if_within_x_messages"] = int(d.get("skip_if_within_x_messages") or 0)
        d["daily_times"] = json.loads(d.pop("daily_times_json") or "[]")
        steps = []
        for s in step_rows:
            sd = dict(s)
            sd["fallback_policy"] = FallbackPolicyConfig.model_validate_json(
                sd.pop("fallback_policy_json") or "{}"
            ).model_dump()
            steps.append(sd)
        d["steps"] = steps

        targets = []
        for t in target_rows:
            td = dict(t)
            td["enabled"] = bool(td["enabled"])
            targets.append(td)
        d["targets"] = targets
        return d

    def list_scenarios(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT id FROM scenarios"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY id ASC"
        with self._lock:
            rows = self._conn.execute(query).fetchall()
        return [self.get_scenario(int(r["id"])) for r in rows if r]  # type: ignore[misc]

    def update_scenario(
        self, scenario_id: int, req: ScenarioUpdateRequest
    ) -> dict[str, Any] | None:
        existing = self.get_scenario(scenario_id)
        if not existing:
            return None
        now = utcnow_iso()
        fields_set = req.model_fields_set
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE scenarios
                SET name = ?,
                    description = ?,
                    enabled = ?,
                    sender_account_id = ?,
                    schedule_type = ?,
                    interval_seconds = ?,
                    jitter_min_sec = ?,
                    jitter_max_sec = ?,
                    daily_times_json = ?,
                    active_hours_start = ?,
                    active_hours_end = ?,
                    delete_previous_sent_message = ?,
                    delete_if_within_x_messages = ?,
                    skip_if_within_x_messages = ?,
                    selection_mode = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    req.name.strip() if req.name is not None else existing["name"],
                    req.description if "description" in fields_set else existing["description"],
                    int(req.enabled) if req.enabled is not None else int(existing["enabled"]),
                    req.sender_account_id
                    if "sender_account_id" in fields_set
                    else existing["sender_account_id"],
                    req.schedule_type
                    if req.schedule_type is not None
                    else existing["schedule_type"],
                    req.interval_seconds
                    if req.interval_seconds is not None
                    else existing["interval_seconds"],
                    req.jitter_min_sec
                    if req.jitter_min_sec is not None
                    else existing["jitter_min_sec"],
                    req.jitter_max_sec
                    if req.jitter_max_sec is not None
                    else existing["jitter_max_sec"],
                    json.dumps(req.daily_times)
                    if req.daily_times is not None
                    else json.dumps(existing["daily_times"]),
                    req.active_hours_start
                    if "active_hours_start" in fields_set
                    else existing.get("active_hours_start"),
                    req.active_hours_end
                    if "active_hours_end" in fields_set
                    else existing.get("active_hours_end"),
                    int(req.delete_previous_sent_message)
                    if req.delete_previous_sent_message is not None
                    else int(existing.get("delete_previous_sent_message", False)),
                    int(req.delete_if_within_x_messages)
                    if req.delete_if_within_x_messages is not None
                    else int(existing.get("delete_if_within_x_messages") or 0),
                    int(req.skip_if_within_x_messages)
                    if req.skip_if_within_x_messages is not None
                    else int(existing.get("skip_if_within_x_messages") or 0),
                    req.selection_mode
                    if req.selection_mode is not None
                    else existing["selection_mode"],
                    now,
                    scenario_id,
                ),
            )
            if req.steps is not None:
                self._replace_scenario_steps(scenario_id, req.steps)
            if req.targets is not None:
                self._replace_scenario_targets(scenario_id, req.targets)
        return self.get_scenario(scenario_id)

    def clone_scenario(
        self, scenario_id: int, new_name: str | None = None
    ) -> dict[str, Any] | None:
        existing = self.get_scenario(scenario_id)
        if not existing:
            return None
        cloned_steps = [
            ScenarioStepInput(
                step_order=int(s.get("step_order") or idx),
                name=str(s.get("name") or f"Bước {idx}"),
                action_type=s.get("action_type") or "send_text",
                text_content=s.get("text_content"),
                media_path=s.get("media_path"),
                sticker_id_or_path=s.get("sticker_id_or_path"),
                forward_from_chat_id=s.get("forward_from_chat_id"),
                forward_from_msg_id=s.get("forward_from_msg_id"),
                via_bot_username=s.get("via_bot_username"),
                fallback_policy=FallbackPolicyConfig.model_validate(
                    s.get("fallback_policy") or {}
                ),
            )
            for idx, s in enumerate(existing.get("steps", []), start=1)
        ]
        cloned_targets = [
            ScenarioTargetInput(
                target_type=t.get("target_type") or "folder",
                target_id=int(t["target_id"]),
                topic_id=int(t.get("topic_id") or 0),
                override_step_order=t.get("override_step_order"),
                override_text_content=t.get("override_text_content"),
                interval_override_seconds=t.get("interval_override_seconds"),
                enabled=bool(t.get("enabled", True)),
            )
            for t in existing.get("targets", [])
        ]
        create_req = ScenarioCreateRequest(
            name=(new_name or f"{existing['name']} (Bản sao)").strip()[:120],
            description=existing.get("description"),
            enabled=False,
            sender_account_id=existing.get("sender_account_id"),
            schedule_type=existing.get("schedule_type") or "interval",
            interval_seconds=int(existing.get("interval_seconds") or 1800),
            jitter_min_sec=int(existing.get("jitter_min_sec") or 5),
            jitter_max_sec=int(existing.get("jitter_max_sec") or 30),
            daily_times=existing.get("daily_times") or [],
            active_hours_start=existing.get("active_hours_start"),
            active_hours_end=existing.get("active_hours_end"),
            delete_previous_sent_message=bool(existing.get("delete_previous_sent_message", False)),
            delete_if_within_x_messages=int(existing.get("delete_if_within_x_messages") or 0),
            skip_if_within_x_messages=int(existing.get("skip_if_within_x_messages") or 0),
            selection_mode=existing.get("selection_mode") or "sequential",
            steps=cloned_steps,
            targets=cloned_targets,
        )
        return self.create_scenario(create_req)

    def get_last_sent_message_for_scenario(
        self, scenario_id: int, chat_id: int, topic_id: int = 0
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM scenario_sent_history
                WHERE scenario_id = ? AND chat_id = ? AND topic_id = ?
                """,
                (scenario_id, chat_id, topic_id),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["last_msg_id"] = d.get("last_sent_msg_id")
        return d

    def record_last_sent_message_for_scenario(
        self,
        *,
        scenario_id: int,
        chat_id: int,
        topic_id: int = 0,
        account_id: int,
        last_sent_msg_id: int | None = None,
        last_msg_id: int | None = None,
    ) -> None:
        msg_id_val = int(last_sent_msg_id or last_msg_id or 0)
        now = utcnow_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO scenario_sent_history (
                    scenario_id, chat_id, topic_id, account_id, last_sent_msg_id, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scenario_id, chat_id, topic_id) DO UPDATE SET
                    account_id = excluded.account_id,
                    last_sent_msg_id = excluded.last_sent_msg_id,
                    updated_at = excluded.updated_at
                """,
                (scenario_id, chat_id, topic_id, account_id, msg_id_val, now),
            )

    def advance_scenario_target_schedule(
        self,
        *,
        scenario_id: int,
        target_row_id: int,
        next_run_iso: str,
        step_cursor: int,
        sent_count_increment: int = 1,
    ) -> None:
        now = utcnow_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE scenario_targets
                SET last_sent_at = ?, next_run_at = ?
                WHERE id = ?
                """,
                (now, next_run_iso, target_row_id),
            )
            self._conn.execute(
                """
                UPDATE scenarios
                SET step_cursor = ?,
                    total_sent_count = total_sent_count + ?,
                    last_run_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (step_cursor, sent_count_increment, now, now, scenario_id),
            )

    def delete_scenario(self, scenario_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # MEDIA & STICKER TEMPLATE LIBRARY (Feature #12)
    # -------------------------------------------------------------------------
    def create_media_library_item(self, req: MediaLibraryCreateRequest) -> dict[str, Any]:
        now = utcnow_iso()
        val = (req.content_or_path or req.content or "").strip()
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO media_library (name, item_type, content_or_path, tags_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    req.name.strip(),
                    req.item_type,
                    val,
                    json.dumps(req.tags, ensure_ascii=False),
                    now,
                ),
            )
            item_id = int(cur.lastrowid)
            row = self._conn.execute(
                "SELECT * FROM media_library WHERE id = ?", (item_id,)
            ).fetchone()
        return self._row_to_media_item(row)

    def list_media_library(self, item_type: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM media_library"
        params: list[Any] = []
        if item_type:
            query += " WHERE item_type = ?"
            params.append(item_type)
        query += " ORDER BY id DESC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_media_item(r) for r in rows]

    def delete_media_library_item(self, item_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM media_library WHERE id = ?", (item_id,))
            return cur.rowcount > 0

    def _row_to_media_item(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["content"] = d.get("content_or_path") or ""
        d["tags"] = json.loads(d.pop("tags_json") or "[]")
        return d

    # -------------------------------------------------------------------------
    # CONFIG EXPORT / IMPORT SNAPSHOT (Feature #18)
    # -------------------------------------------------------------------------
    def export_configuration_bundle(self) -> dict[str, Any]:
        return {
            "exported_at": utcnow_iso(),
            "version": "2.1.0",
            "chats": self.list_chat_groups(),
            "folders": self.list_folders(),
            "backups": self.list_backup_jobs(),
            "scenarios": self.list_scenarios(),
            "media_library": self.list_media_library(),
            "settings": self.get_settings(),
        }

    def import_configuration_bundle(self, bundle: dict[str, Any]) -> dict[str, int]:
        imported_chats = 0
        imported_folders = 0
        imported_library = 0

        for c in bundle.get("chats", []):
            rules_raw = c.get("rules")
            rule_model = ChatRuleModel.model_validate(rules_raw) if rules_raw else None
            self.upsert_chat_group(
                ChatGroupUpsertRequest(
                    chat_id=int(c["chat_id"]),
                    title=str(c["title"]),
                    username=c.get("username"),
                    chat_type=str(c.get("chat_type", "supergroup")),
                    is_forum=bool(c.get("is_forum", False)),
                    participants_count=c.get("participants_count"),
                    rules=rule_model,
                )
            )
            for t in c.get("topics", []):
                self.upsert_chat_topic(ChatTopicModel.model_validate(t))
            imported_chats += 1

        existing_folder_names = {f["name"] for f in self.list_folders()}
        for f in bundle.get("folders", []):
            fname = str(f["name"])
            if fname in existing_folder_names:
                continue
            self.create_folder(
                FolderCreateRequest(
                    name=fname,
                    description=f.get("description"),
                    color=f.get("color", "#10b981"),
                    enabled=bool(f.get("enabled", True)),
                    chats=[
                        FolderChatEntry(
                            chat_id=int(fc["chat_id"]),
                            topic_id=int(fc.get("topic_id", 0)),
                        )
                        for fc in f.get("chats", [])
                    ],
                )
            )
            imported_folders += 1

        for item in bundle.get("media_library", []):
            self.create_media_library_item(
                MediaLibraryCreateRequest(
                    name=str(item["name"]),
                    item_type=item.get("item_type", "text_template"),
                    content_or_path=str(item["content_or_path"]),
                    tags=item.get("tags", []),
                )
            )
            imported_library += 1

        if isinstance(bundle.get("settings"), dict):
            self.set_settings(bundle["settings"])

        return {
            "imported_chats": imported_chats,
            "imported_folders": imported_folders,
            "imported_library": imported_library,
        }

    # -------------------------------------------------------------------------
    # LOGS & SETTINGS
    # -------------------------------------------------------------------------
    def add_execution_log(
        self,
        *,
        category: str,
        message: str,
        level: str = "INFO",
        account_id: int | None = None,
        chat_id: int | None = None,
        topic_id: int | None = None,
        scenario_id: int | None = None,
        backup_job_id: int | None = None,
        action_attempted: str | None = None,
        action_executed: str | None = None,
        fallback_applied: bool = False,
        fallback_reason: str | None = None,
        status: str = "success",
    ) -> dict[str, Any]:
        now = utcnow_iso()
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO execution_logs (
                    category, level, account_id, chat_id, topic_id,
                    scenario_id, backup_job_id, action_attempted, action_executed,
                    fallback_applied, fallback_reason, status, message, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    category,
                    level,
                    account_id,
                    chat_id,
                    topic_id,
                    scenario_id,
                    backup_job_id,
                    action_attempted,
                    action_executed,
                    int(fallback_applied),
                    fallback_reason,
                    status,
                    message,
                    now,
                ),
            )
            log_id = int(cur.lastrowid)
            row = self._conn.execute(
                "SELECT * FROM execution_logs WHERE id = ?", (log_id,)
            ).fetchone()
        d = dict(row)
        d["fallback_applied"] = bool(d["fallback_applied"])
        return d

    def list_execution_logs(
        self,
        *,
        category: str | None = None,
        fallback_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM execution_logs WHERE 1=1"
        params: list[Any] = []
        if category:
            query += " AND category = ?"
            params.append(category)
        if fallback_only:
            query += " AND fallback_applied = 1"
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["fallback_applied"] = bool(d["fallback_applied"])
            result.append(d)
        return result

    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value_json FROM app_settings").fetchall()
        return {r["key"]: json.loads(r["value_json"]) for r in rows}

    def set_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        with self._lock, self._conn:
            for k, v in settings.items():
                self._conn.execute(
                    """
                    INSERT INTO app_settings (key, value_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = excluded.updated_at
                    """,
                    (str(k), json.dumps(v, ensure_ascii=False), now),
                )
        return self.get_settings()

    def get_dashboard_stats(self) -> dict[str, Any]:
        with self._lock:
            total_accounts = self._conn.execute(
                "SELECT COUNT(*) AS c FROM accounts"
            ).fetchone()["c"]
            connected_accounts = self._conn.execute(
                "SELECT COUNT(*) AS c FROM accounts WHERE status = 'connected'"
            ).fetchone()["c"]
            total_groups = self._conn.execute(
                "SELECT COUNT(*) AS c FROM chat_groups"
            ).fetchone()["c"]
            restricted_groups = self._conn.execute(
                """
                SELECT COUNT(*) AS c FROM chat_rules
                WHERE no_links = 1 OR no_stickers = 1 OR no_forwards = 1
                   OR no_media = 1 OR no_bot_mentions = 1
                """
            ).fetchone()["c"]
            total_topics = self._conn.execute(
                "SELECT COUNT(*) AS c FROM chat_topics"
            ).fetchone()["c"]
            total_folders = self._conn.execute(
                "SELECT COUNT(*) AS c FROM folders"
            ).fetchone()["c"]
            total_backup_jobs = self._conn.execute(
                "SELECT COUNT(*) AS c FROM backup_jobs"
            ).fetchone()["c"]
            active_backup_jobs = self._conn.execute(
                "SELECT COUNT(*) AS c FROM backup_jobs WHERE enabled = 1"
            ).fetchone()["c"]
            total_synced_files = self._conn.execute(
                "SELECT COUNT(*) AS c FROM sync_state WHERE status = 'synced'"
            ).fetchone()["c"]
            total_scenarios = self._conn.execute(
                "SELECT COUNT(*) AS c FROM scenarios"
            ).fetchone()["c"]
            active_scenarios = self._conn.execute(
                "SELECT COUNT(*) AS c FROM scenarios WHERE enabled = 1"
            ).fetchone()["c"]
            total_auto_sent = self._conn.execute(
                "SELECT COALESCE(SUM(total_sent_count), 0) AS c FROM scenarios"
            ).fetchone()["c"]
            total_fallbacks = self._conn.execute(
                "SELECT COUNT(*) AS c FROM execution_logs WHERE fallback_applied = 1"
            ).fetchone()["c"]

        return {
            "global_pause": self.is_global_paused(),
            "global_paused": self.is_global_paused(),
            "accounts": {"total": int(total_accounts), "connected": int(connected_accounts)},
            "groups": {
                "total": int(total_groups),
                "with_rules": int(restricted_groups),
                "topics_discovered": int(total_topics),
            },
            "folders": {"total": int(total_folders)},
            "backups": {
                "total_jobs": int(total_backup_jobs),
                "active_jobs": int(active_backup_jobs),
                "synced_items": int(total_synced_files),
            },
            "scenarios": {
                "total": int(total_scenarios),
                "active": int(active_scenarios),
                "messages_sent": int(total_auto_sent),
                "fallbacks_triggered": int(total_fallbacks),
            },
        }
