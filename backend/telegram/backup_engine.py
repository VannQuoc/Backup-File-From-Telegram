from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from telethon import events
from telethon.tl.types import (
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
)

from backend.config import AppConfig
from backend.database.db import DatabaseStore
from backend.database.models import BackupFilterConfig
from backend.telegram.client_pool import TelegramClientPool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageEvaluation:
    should_sync: bool
    skip_reason: str | None = None
    content_type: str = "document"  # "document" | "photo" | "video" | "sticker" | "voice" | "text"
    filename: str | None = None
    renamed_filename: str | None = None
    normalized_filename: str = ""
    extension: str = ""
    file_size: int | None = None
    document_id: int | None = None
    target_topic_id: int = 0
    caption_to_send: str = ""
    fingerprint: str | None = None
    content_hash_dedupe: bool = False


def normalize_filename(filename: str | None) -> str:
    if not filename:
        return ""
    return Path(filename).name.lower().strip()


def apply_filename_rename(
    filename: str | None,
    prefix: str = "",
    suffix: str = "",
) -> str | None:
    if not filename:
        return None
    p = prefix.strip()
    s = suffix.strip()
    if not p and not s:
        return filename
    path_obj = Path(filename)
    return f"{p}{path_obj.stem}{s}{path_obj.suffix}"


def compute_file_sha256(file_path: str | Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def extract_message_metadata(message: Any) -> dict[str, Any]:
    """Extracts content type, filename, extension, size, and IDs from a Telethon message."""
    raw_text = str(getattr(message, "message", "") or getattr(message, "text", "") or "")
    media = getattr(message, "media", None)

    if media is None:
        return {
            "content_type": "text" if raw_text.strip() else "service",
            "filename": None,
            "extension": "",
            "size": len(raw_text.encode("utf-8")) if raw_text else 0,
            "document_id": None,
            "raw_text": raw_text,
        }

    if isinstance(media, MessageMediaPhoto) or getattr(message, "photo", None) is not None:
        photo = getattr(media, "photo", None) or getattr(message, "photo", None)
        photo_id = getattr(photo, "id", None)
        return {
            "content_type": "photo",
            "filename": f"photo_{photo_id or message.id}.jpg",
            "extension": ".jpg",
            "size": getattr(getattr(message, "file", None), "size", None),
            "document_id": photo_id,
            "raw_text": raw_text,
        }

    doc = getattr(media, "document", None) or getattr(message, "document", None)
    if isinstance(media, MessageMediaDocument) or doc is not None:
        doc_id = getattr(doc, "id", None)
        doc_size = getattr(doc, "size", None)
        attrs = getattr(doc, "attributes", []) or []
        filename: str | None = None
        is_sticker = False
        is_video = False
        is_voice = False

        for attr in attrs:
            if isinstance(attr, DocumentAttributeFilename):
                filename = attr.file_name
            elif isinstance(attr, DocumentAttributeSticker):
                is_sticker = True
            elif isinstance(attr, DocumentAttributeVideo):
                is_video = True
            elif isinstance(attr, DocumentAttributeAudio) and getattr(attr, "voice", False):
                is_voice = True

        # Fallback for mock objects in tests
        if filename is None and hasattr(message, "file") and getattr(message.file, "name", None):
            filename = str(message.file.name)

        norm_name = normalize_filename(filename)
        ext = Path(norm_name).suffix if norm_name else ""

        if is_sticker or getattr(message, "sticker", None) is not None:
            content_type = "sticker"
        elif is_voice or getattr(message, "voice", None) is not None:
            content_type = "voice"
        elif is_video or getattr(message, "video", None) is not None or ext in {".mp4", ".mkv", ".mov", ".webm"}:
            content_type = "video"
        else:
            content_type = "document"

        return {
            "content_type": content_type,
            "filename": filename,
            "extension": ext,
            "size": doc_size,
            "document_id": doc_id,
            "raw_text": raw_text,
        }

    return {
        "content_type": "other",
        "filename": None,
        "extension": "",
        "size": None,
        "document_id": None,
        "raw_text": raw_text,
    }


def evaluate_message_for_backup(
    message: Any,
    job: dict[str, Any],
) -> MessageEvaluation:
    """Pure decision function: evaluates whether and how a message should be backed up."""
    meta = extract_message_metadata(message)
    ctype = meta["content_type"]
    raw_text = meta["raw_text"] or ""
    filename = meta["filename"]
    norm_filename = normalize_filename(filename)
    ext = meta["extension"]
    size = meta["size"]
    doc_id = meta["document_id"]
    msg_id = int(getattr(message, "id", 0) or 0)
    msg_date = getattr(message, "date", None)

    cfg_raw = job.get("filter_config") or {}
    cfg = (
        cfg_raw
        if isinstance(cfg_raw, BackupFilterConfig)
        else BackupFilterConfig.model_validate(cfg_raw)
    )

    # 0. Check Message ID Range & Date Range filters (Feature #15)
    if cfg.min_msg_id is not None and msg_id > 0 and msg_id < int(cfg.min_msg_id):
        return MessageEvaluation(
            should_sync=False,
            skip_reason=f"Message ID ({msg_id}) nhỏ hơn min_msg_id ({cfg.min_msg_id})",
            content_type=ctype,
        )
    if cfg.max_msg_id is not None and msg_id > 0 and msg_id > int(cfg.max_msg_id):
        return MessageEvaluation(
            should_sync=False,
            skip_reason=f"Message ID ({msg_id}) vượt quá max_msg_id ({cfg.max_msg_id})",
            content_type=ctype,
        )

    if msg_date is not None:
        msg_iso = msg_date.isoformat() if hasattr(msg_date, "isoformat") else str(msg_date)
        if cfg.min_date_iso and msg_iso[:10] < cfg.min_date_iso.strip()[:10]:
            return MessageEvaluation(
                should_sync=False,
                skip_reason=f"Ngày tin nhắn ({msg_iso[:10]}) trước ngày bắt đầu ({cfg.min_date_iso})",
                content_type=ctype,
            )
        if cfg.max_date_iso and msg_iso[:10] > cfg.max_date_iso.strip()[:10]:
            return MessageEvaluation(
                should_sync=False,
                skip_reason=f"Ngày tin nhắn ({msg_iso[:10]}) sau ngày kết thúc ({cfg.max_date_iso})",
                content_type=ctype,
            )

    # 1. Check content type switches
    if ctype == "service" or ctype == "other":
        return MessageEvaluation(should_sync=False, skip_reason="Tin nhắn hệ thống / không hỗ trợ")
    if ctype == "document" and not cfg.sync_documents:
        return MessageEvaluation(should_sync=False, skip_reason="Job tắt đồng bộ Document", content_type=ctype)
    if ctype == "photo" and not cfg.sync_photos:
        return MessageEvaluation(should_sync=False, skip_reason="Job tắt đồng bộ Photo", content_type=ctype)
    if ctype == "video" and not cfg.sync_videos:
        return MessageEvaluation(should_sync=False, skip_reason="Job tắt đồng bộ Video", content_type=ctype)
    if ctype == "text" and not cfg.sync_text:
        return MessageEvaluation(should_sync=False, skip_reason="Job tắt đồng bộ Text thuần", content_type=ctype)
    if ctype == "sticker" and not cfg.sync_stickers:
        return MessageEvaluation(should_sync=False, skip_reason="Job tắt đồng bộ Sticker", content_type=ctype)
    if ctype == "voice" and not cfg.sync_voice:
        return MessageEvaluation(should_sync=False, skip_reason="Job tắt đồng bộ Voice", content_type=ctype)

    # 2. Check allowed document extensions (if configured)
    if ctype == "document" and cfg.allowed_extensions:
        normalized_allowed = {
            (e.lower().strip() if e.strip().startswith(".") else f".{e.lower().strip()}")
            for e in cfg.allowed_extensions
            if e.strip()
        }
        if normalized_allowed and ext not in normalized_allowed:
            return MessageEvaluation(
                should_sync=False,
                skip_reason=f"Đuôi file '{ext or 'none'}' không nằm trong danh sách cho phép",
                content_type=ctype,
                filename=filename,
                normalized_filename=norm_filename,
                extension=ext,
            )

    # 3. Check file size limits
    if size is not None:
        if cfg.min_file_size_bytes and size < cfg.min_file_size_bytes:
            return MessageEvaluation(
                should_sync=False,
                skip_reason=f"Dung lượng ({size} B) nhỏ hơn mức tối thiểu",
                content_type=ctype,
            )
        if cfg.max_file_size_bytes and size > cfg.max_file_size_bytes:
            return MessageEvaluation(
                should_sync=False,
                skip_reason=f"Dung lượng ({size} B) vượt mức tối đa",
                content_type=ctype,
            )

    # 4. Keyword filtering (checks both caption/text and filename)
    searchable = f"{raw_text} {filename or ''}".lower()
    if cfg.include_keywords and not any(
        kw.lower().strip() in searchable for kw in cfg.include_keywords if kw.strip()
    ):
        return MessageEvaluation(
            should_sync=False,
            skip_reason="Không khớp từ khóa bắt buộc (include_keywords)",
            content_type=ctype,
        )
    if cfg.exclude_keywords and any(
        kw.lower().strip() in searchable for kw in cfg.exclude_keywords if kw.strip()
    ):
        return MessageEvaluation(
            should_sync=False,
            skip_reason="Chứa từ khóa bị loại trừ (exclude_keywords)",
            content_type=ctype,
        )

    # 5. Route destination topic (archive vs default)
    archive_exts = {
        (e.lower().strip() if e.strip().startswith(".") else f".{e.lower().strip()}")
        for e in cfg.archive_extensions
        if e.strip()
    }
    default_topic = int(job.get("dest_topic_default") or 0)
    archive_topic = int(job.get("dest_topic_archive") or default_topic)
    target_topic_id = archive_topic if (ext and ext in archive_exts) else default_topic

    # 6. Resolve filename rename (Feature #16)
    renamed_filename = apply_filename_rename(filename, cfg.rename_prefix, cfg.rename_suffix)

    # 7. Resolve caption mode & watermark (Feature #16)
    caption_mode = job.get("caption_mode") or "strip_for_txt"
    if ctype == "text":
        caption_to_send = raw_text
    elif caption_mode == "strip":
        caption_to_send = ""
    elif caption_mode == "strip_for_txt":
        caption_to_send = "" if ext == ".txt" else raw_text
    elif caption_mode == "custom_template":
        tpl = str(job.get("custom_caption_template") or "{caption}")
        caption_to_send = (
            tpl.replace("{caption}", raw_text)
            .replace("{filename}", renamed_filename or filename or "")
            .replace("{source_id}", str(job.get("source_chat_id", "")))
            .strip()
        )
    else:
        caption_to_send = raw_text

    if cfg.caption_watermark and cfg.caption_watermark.strip():
        wm = cfg.caption_watermark.strip()
        caption_to_send = f"{caption_to_send}\n\n{wm}".strip() if caption_to_send else wm

    # 8. Build deduplication fingerprint
    fingerprint: str | None = None
    if job.get("dedupe_enabled", True):
        if ctype in ("document", "video", "voice", "sticker") and doc_id is not None:
            fingerprint = f"doc:{doc_id}:{size or 0}:{norm_filename}"
        elif ctype == "photo" and doc_id is not None:
            fingerprint = f"photo:{doc_id}"
        elif ctype == "text" and raw_text.strip():
            text_hash = hashlib.sha256(raw_text.strip().encode("utf-8")).hexdigest()[:24]
            fingerprint = f"text:{job.get('id', 0)}:{text_hash}"

    return MessageEvaluation(
        should_sync=True,
        content_type=ctype,
        filename=filename,
        renamed_filename=renamed_filename,
        normalized_filename=norm_filename,
        extension=ext,
        file_size=size,
        document_id=doc_id,
        target_topic_id=target_topic_id,
        caption_to_send=caption_to_send,
        fingerprint=fingerprint,
        content_hash_dedupe=bool(cfg.content_hash_dedupe),
    )


class BackupEngine:
    """Handles live listening, catch-up backlog syncing, and protected content fallback across accounts."""

    def __init__(
        self,
        store: DatabaseStore,
        pool: TelegramClientPool,
        config: AppConfig,
        event_broadcaster: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self._store = store
        self._pool = pool
        self._config = config
        self._broadcaster = event_broadcaster
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._job_locks: dict[int, asyncio.Lock] = {}
        self._registered_client_ids: set[int] = set()

    def _get_job_lock(self, job_id: int) -> asyncio.Lock:
        if job_id not in self._job_locks:
            self._job_locks[job_id] = asyncio.Lock()
        return self._job_locks[job_id]

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._reconcile_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _reconcile_loop(self) -> None:
        while self._running:
            try:
                if not self._store.is_global_paused():
                    await self._attach_live_listeners()
                    await self.sync_all_enabled_jobs(limit_per_job=100)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Backup reconcile loop error: %s", exc)
            await asyncio.sleep(self._config.backup_reconcile_interval_seconds)

    async def _attach_live_listeners(self) -> None:
        jobs = self._store.list_backup_jobs(enabled_only=True)
        for job in jobs:
            reader_id = int(job["reader_account_id"])
            client = await self._pool.get_authorized_client(reader_id)
            if not client or id(client) in self._registered_client_ids:
                continue

            self._registered_client_ids.add(id(client))

            @client.on(events.NewMessage())
            async def _on_new_message(event: Any) -> None:
                if self._store.is_global_paused():
                    return
                chat_id = int(getattr(event, "chat_id", 0) or 0)
                if not chat_id:
                    return
                matching_jobs = [
                    j
                    for j in self._store.list_backup_jobs(enabled_only=True)
                    if int(j["source_chat_id"]) == chat_id
                ]
                for matched_job in matching_jobs:
                    try:
                        await self.process_single_message(matched_job, event.message)
                    except Exception as exc:
                        logger.warning(
                            "Lỗi xử lý live message %s cho job #%s: %s",
                            getattr(event.message, "id", "?"),
                            matched_job["id"],
                            exc,
                        )

    async def sync_all_enabled_jobs(self, limit_per_job: int | None = None) -> list[dict[str, Any]]:
        if self._store.is_global_paused():
            return []
        results = []
        for job in self._store.list_backup_jobs(enabled_only=True):
            res = await self.run_backup_job(int(job["id"]), limit=limit_per_job)
            results.append(res)
        return results

    async def run_backup_job(
        self, job_id: int, *, limit: int | None = None
    ) -> dict[str, Any]:
        job = self._store.get_backup_job(job_id)
        if not job:
            raise ValueError(f"Không tìm thấy luồng Backup #{job_id}")

        lock = self._get_job_lock(job_id)
        if lock.locked():
            return {"job_id": job_id, "status": "already_running", "synced": 0, "skipped": 0, "failed": 0}

        async with lock:
            reader_id = int(job["reader_account_id"])
            reader_client = await self._pool.get_authorized_client(reader_id)
            if not reader_client:
                msg = f"Tài khoản đọc nguồn #{reader_id} chưa kết nối Telegram."
                self._store.add_execution_log(
                    category="backup",
                    level="WARN",
                    backup_job_id=job_id,
                    account_id=reader_id,
                    status="failed",
                    message=msg,
                )
                return {"job_id": job_id, "status": "error", "error": msg, "synced": 0, "skipped": 0, "failed": 0}

            source_chat_id = int(job["source_chat_id"])
            last_cursor = int(job.get("last_scanned_msg_id") or 0)
            cfg = BackupFilterConfig.model_validate(job.get("filter_config") or {})

            effective_min_id = max(last_cursor, int(cfg.min_msg_id) - 1) if cfg.min_msg_id else last_cursor

            synced_count = 0
            skipped_count = 0
            failed_count = 0
            highest_msg_id = last_cursor

            iter_kwargs: dict[str, Any] = {
                "entity": source_chat_id,
                "min_id": effective_min_id,
                "reverse": True,
            }
            if cfg.max_msg_id:
                iter_kwargs["max_id"] = int(cfg.max_msg_id) + 1
            if limit is not None and limit > 0:
                iter_kwargs["limit"] = limit
            if job.get("source_topic_id"):
                iter_kwargs["reply_to"] = int(job["source_topic_id"])

            async for message in reader_client.iter_messages(**iter_kwargs):
                msg_id = int(message.id)
                highest_msg_id = max(highest_msg_id, msg_id)

                outcome = await self.process_single_message(job, message)
                if outcome == "synced":
                    synced_count += 1
                elif outcome == "skipped":
                    skipped_count += 1
                elif outcome == "failed":
                    failed_count += 1

                if outcome == "synced":
                    delay_min = max(100, int(job.get("send_delay_min_ms", 800)))
                    delay_max = max(delay_min, int(job.get("send_delay_max_ms", 1500)))
                    await asyncio.sleep(random.uniform(delay_min / 1000.0, delay_max / 1000.0))

            if highest_msg_id > last_cursor:
                self._store.update_backup_cursor(job_id, highest_msg_id, synced_increment=synced_count)

            summary = {
                "job_id": job_id,
                "status": "completed",
                "synced": synced_count,
                "skipped": skipped_count,
                "failed": failed_count,
                "cursor": highest_msg_id,
            }
            if self._broadcaster and (synced_count > 0 or failed_count > 0):
                await self._broadcaster({"type": "backup_progress", "data": summary})
            return summary

    async def process_single_message(self, job: dict[str, Any], message: Any) -> str:
        job_id = int(job["id"])
        source_chat_id = int(job["source_chat_id"])
        msg_id = int(message.id)

        existing = self._store.get_sync_state(job_id, msg_id)
        if existing and existing["status"] == "synced":
            return "skipped"

        evaluation = evaluate_message_for_backup(message, job)
        if not evaluation.should_sync:
            self._store.record_sync_state(
                backup_job_id=job_id,
                source_chat_id=source_chat_id,
                source_msg_id=msg_id,
                status="skipped",
                content_type=evaluation.content_type,
                extension=evaluation.extension,
                document_id=evaluation.document_id,
                filename=evaluation.filename,
                normalized_filename=evaluation.normalized_filename,
                size=evaluation.file_size,
                error_text=evaluation.skip_reason,
            )
            return "skipped"

        # Check metadata fingerprint deduplication
        if evaluation.fingerprint and self._store.has_fingerprint(evaluation.fingerprint):
            self._store.record_sync_state(
                backup_job_id=job_id,
                source_chat_id=source_chat_id,
                source_msg_id=msg_id,
                status="skipped",
                content_type=evaluation.content_type,
                extension=evaluation.extension,
                document_id=evaluation.document_id,
                filename=evaluation.filename,
                normalized_filename=evaluation.normalized_filename,
                size=evaluation.file_size,
                fingerprint=evaluation.fingerprint,
                error_text="Trùng lặp Fingerprint (File đã từng được backup)",
            )
            return "skipped"

        reader_id = int(job["reader_account_id"])
        sender_id = int(job.get("sender_account_id") or reader_id)
        dest_chat_id = int(job["dest_chat_id"])
        reply_to_topic = evaluation.target_topic_id if evaluation.target_topic_id > 0 else None

        sender_client = await self._pool.get_authorized_client(sender_id)
        reader_client = await self._pool.get_authorized_client(reader_id)
        if not sender_client or not reader_client:
            err = "Tài khoản đọc hoặc gửi chưa kết nối"
            self._store.record_sync_state(
                backup_job_id=job_id,
                source_chat_id=source_chat_id,
                source_msg_id=msg_id,
                status="failed",
                content_type=evaluation.content_type,
                extension=evaluation.extension,
                document_id=evaluation.document_id,
                filename=evaluation.filename,
                normalized_filename=evaluation.normalized_filename,
                size=evaluation.file_size,
                error_text=err,
            )
            return "failed"

        used_protected_fallback = False
        dest_msg_id: int | None = None
        content_sha_fingerprint: str | None = None
        final_filename = evaluation.renamed_filename or evaluation.filename

        try:
            if evaluation.content_type == "text":
                sent_msg = await sender_client.send_message(
                    entity=dest_chat_id,
                    message=evaluation.caption_to_send,
                    reply_to=reply_to_topic,
                )
                dest_msg_id = int(getattr(sent_msg, "id", 0) or 0)
            else:
                msg_noforwards = bool(getattr(message, "noforwards", False))
                chat_noforwards = bool(getattr(getattr(message, "chat", None), "noforwards", False))
                has_rename = bool(
                    evaluation.renamed_filename
                    and evaluation.renamed_filename != evaluation.filename
                )
                needs_download = (
                    (reader_id != sender_id)
                    or msg_noforwards
                    or chat_noforwards
                    or has_rename
                    or evaluation.content_hash_dedupe
                )

                if not needs_download:
                    try:
                        sent_msg = await sender_client.send_file(
                            entity=dest_chat_id,
                            file=message.media,
                            caption=evaluation.caption_to_send or None,
                            reply_to=reply_to_topic,
                        )
                        dest_msg_id = int(getattr(sent_msg, "id", 0) or 0)
                    except Exception:
                        if not job.get("allow_protected_fallback", True):
                            raise
                        needs_download = True

                if needs_download:
                    if not job.get("allow_protected_fallback", True) and (msg_noforwards or chat_noforwards):
                        raise PermissionError(
                            "Nguồn bật Protected Content nhưng luồng Backup đang tắt allow_protected_fallback."
                        )
                    used_protected_fallback = True
                    temp_subdir = self._config.temp_dir / f"job_{job_id}_{msg_id}"
                    temp_subdir.mkdir(parents=True, exist_ok=True)
                    downloaded_path: str | None = None
                    upload_path: Path | None = None
                    try:
                        downloaded_path = await reader_client.download_media(
                            message, file=str(temp_subdir)
                        )
                        if not downloaded_path:
                            raise RuntimeError("Không thể tải media từ tin nhắn nguồn.")

                        upload_path = Path(downloaded_path)

                        # Feature #14: Content-Hash SHA-256 Deduplication
                        if job.get("dedupe_enabled", True) and upload_path.is_file():
                            sha_hex = compute_file_sha256(upload_path)
                            content_sha_fingerprint = f"sha256:{sha_hex}"
                            if self._store.has_fingerprint(content_sha_fingerprint):
                                self._store.record_sync_state(
                                    backup_job_id=job_id,
                                    source_chat_id=source_chat_id,
                                    source_msg_id=msg_id,
                                    status="skipped",
                                    content_type=evaluation.content_type,
                                    extension=evaluation.extension,
                                    document_id=evaluation.document_id,
                                    filename=final_filename,
                                    normalized_filename=evaluation.normalized_filename,
                                    size=evaluation.file_size,
                                    fingerprint=content_sha_fingerprint,
                                    error_text="Trùng lặp SHA-256 Content Hash (Nội dung file giống hệt file đã backup)",
                                )
                                return "skipped"

                        # Feature #16: Rename file with prefix/suffix before re-uploading
                        if final_filename and upload_path.is_file() and upload_path.name != final_filename:
                            target_renamed_path = upload_path.parent / final_filename
                            upload_path.rename(target_renamed_path)
                            upload_path = target_renamed_path

                        sent_msg = await sender_client.send_file(
                            entity=dest_chat_id,
                            file=str(upload_path),
                            caption=evaluation.caption_to_send or None,
                            reply_to=reply_to_topic,
                        )
                        dest_msg_id = int(getattr(sent_msg, "id", 0) or 0)
                    finally:
                        for p in (upload_path, Path(downloaded_path) if downloaded_path else None):
                            if p and p.exists():
                                try:
                                    p.unlink()
                                except OSError:
                                    pass
                        try:
                            temp_subdir.rmdir()
                        except OSError:
                            pass

            primary_fp = content_sha_fingerprint or evaluation.fingerprint
            self._store.record_sync_state(
                backup_job_id=job_id,
                source_chat_id=source_chat_id,
                source_msg_id=msg_id,
                status="synced",
                content_type=evaluation.content_type,
                extension=evaluation.extension,
                document_id=evaluation.document_id,
                filename=final_filename,
                normalized_filename=evaluation.normalized_filename,
                size=evaluation.file_size,
                dest_chat_id=dest_chat_id,
                dest_topic_id=evaluation.target_topic_id,
                dest_msg_id=dest_msg_id,
                fingerprint=primary_fp,
                used_protected_fallback=used_protected_fallback,
            )
            for fp in filter(None, {evaluation.fingerprint, content_sha_fingerprint}):
                self._store.add_fingerprint(
                    fingerprint=fp,
                    backup_job_id=job_id,
                    source_chat_id=source_chat_id,
                    first_source_msg_id=msg_id,
                    filename=final_filename,
                    dest_chat_id=dest_chat_id,
                    dest_topic_id=evaluation.target_topic_id,
                    dest_msg_id=dest_msg_id,
                )
            self._store.add_execution_log(
                category="backup",
                account_id=sender_id,
                chat_id=dest_chat_id,
                topic_id=evaluation.target_topic_id,
                backup_job_id=job_id,
                action_attempted=f"backup_{evaluation.content_type}",
                action_executed="download_reupload" if used_protected_fallback else "direct_resend",
                fallback_applied=used_protected_fallback,
                fallback_reason="Protected Content / Cross-account / Rename Re-upload" if used_protected_fallback else None,
                status="success",
                message=f"Đã backup {final_filename or evaluation.content_type} (msg #{msg_id} -> #{dest_msg_id})",
            )
            return "synced"

        except Exception as exc:
            err_msg = str(exc)
            self._store.record_sync_state(
                backup_job_id=job_id,
                source_chat_id=source_chat_id,
                source_msg_id=msg_id,
                status="failed",
                content_type=evaluation.content_type,
                extension=evaluation.extension,
                document_id=evaluation.document_id,
                filename=final_filename,
                normalized_filename=evaluation.normalized_filename,
                size=evaluation.file_size,
                error_text=err_msg,
            )
            self._store.add_execution_log(
                category="backup",
                level="ERROR",
                account_id=sender_id,
                chat_id=dest_chat_id,
                backup_job_id=job_id,
                status="failed",
                message=f"Lỗi backup msg #{msg_id}: {err_msg}",
            )
            return "failed"
