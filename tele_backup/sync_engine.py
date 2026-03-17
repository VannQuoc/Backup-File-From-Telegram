from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path

from telethon import errors
from telethon.client import TelegramClient
from telethon.tl.types import Message, MessageMediaDocument

from .config import Settings
from .message_rules import build_txt_fingerprint, decide_file_handling, normalize_filename
from .store import STATUS_FAILED, STATUS_SKIPPED, STATUS_SYNCED, SourceRecord, SyncStateRecord, SyncStore
from .telegram_client import (
    is_authorized,
    is_protected_chat,
    resolve_chat_entity,
    resolve_destination_to_marked_id,
    resolve_source_to_raw_id,
    validate_topic_messages,
)

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    processed: int = 0
    synced: int = 0
    skipped: int = 0
    failed: int = 0

    def merge(self, other: 'SyncStats') -> None:
        self.processed += other.processed
        self.synced += other.synced
        self.skipped += other.skipped
        self.failed += other.failed


@dataclass(frozen=True)
class SourceContext:
    source: SourceRecord
    source_entity: object
    dest_entity: object
    protected: bool
    use_download_fallback: bool


class BackupService:
    def __init__(self, client: TelegramClient, store: SyncStore, settings: Settings) -> None:
        self.client = client
        self.store = store
        self.settings = settings
        self._successful_sends_since_pause = 0
        self._context_cache: dict[int, SourceContext] = {}
        self._warned_protected_sources: set[int] = set()

    async def bootstrap_legacy_source(self) -> None:
        legacy = self.settings.legacy_source
        if legacy is None:
            return
        if self.store.get_source(legacy.source_chat_id) is not None:
            return

        self.store.upsert_source(
            SourceRecord(
                source_chat_id=legacy.source_chat_id,
                dest_chat_id=legacy.dest_chat_id,
                dest_topic_default=legacy.dest_topic_default,
                dest_topic_archive=legacy.dest_topic_archive,
                label=legacy.label,
                allow_protected_fallback=legacy.allow_protected_fallback,
            )
        )
        logger.info('Da bootstrap legacy source %s vao DB.', legacy.source_chat_id)

    def list_sources(self, enabled_only: bool | None = None) -> list[SourceRecord]:
        return self.store.list_sources(enabled_only=enabled_only)

    def get_source(self, source_chat_id: int) -> SourceRecord | None:
        return self.store.get_source(source_chat_id)

    async def add_or_update_source(
        self,
        source_ref: int,
        dest_ref: int,
        topic_default: int,
        topic_archive: int,
        *,
        label: str | None = None,
        enabled: bool | None = None,
        allow_protected_fallback: bool | None = None,
    ) -> SourceRecord:
        source_chat_id = await resolve_source_to_raw_id(self.client, source_ref)
        destination_entity = await resolve_chat_entity(self.client, dest_ref)
        await validate_topic_messages(self.client, destination_entity, [topic_default, topic_archive])
        dest_chat_id = await resolve_destination_to_marked_id(self.client, dest_ref)

        existing = self.store.get_source(source_chat_id)
        record = SourceRecord(
            source_chat_id=source_chat_id,
            dest_chat_id=dest_chat_id,
            dest_topic_default=topic_default,
            dest_topic_archive=topic_archive,
            label=label if label is not None else (existing.label if existing else None),
            source_invite_link=existing.source_invite_link if existing else None,
            enabled=enabled if enabled is not None else (existing.enabled if existing else True),
            allow_protected_fallback=(
                allow_protected_fallback
                if allow_protected_fallback is not None
                else (existing.allow_protected_fallback if existing else False)
            ),
            created_at=existing.created_at if existing else None,
        )
        self.store.upsert_source(record)
        self.invalidate_source(source_chat_id)
        return self.store.get_source(source_chat_id) or record

    def remove_source(self, source_chat_id: int) -> None:
        self.store.delete_source(source_chat_id)
        self.invalidate_source(source_chat_id)

    def set_source_enabled(self, source_chat_id: int, enabled: bool) -> None:
        self.store.set_source_enabled(source_chat_id, enabled)
        self.invalidate_source(source_chat_id)

    def set_source_destination(
        self,
        source_chat_id: int,
        dest_chat_id: int,
        topic_default: int,
        topic_archive: int,
    ) -> None:
        self.store.update_source_destination(source_chat_id, dest_chat_id, topic_default, topic_archive)
        self.invalidate_source(source_chat_id)

    def set_source_label(self, source_chat_id: int, label: str | None) -> None:
        self.store.update_source_label(source_chat_id, label)
        self.invalidate_source(source_chat_id)

    def set_source_protected_fallback(self, source_chat_id: int, allow: bool) -> None:
        self.store.update_source_protected_fallback(source_chat_id, allow)
        self.invalidate_source(source_chat_id)

    def invalidate_source(self, source_chat_id: int) -> None:
        self._context_cache.pop(source_chat_id, None)
        self._warned_protected_sources.discard(source_chat_id)

    async def build_status_text(self, queue_size: int = 0) -> str:
        authorized = await is_authorized(self.client)
        enabled = self.store.count_sources(enabled_only=True)
        total = self.store.count_sources(enabled_only=None)
        return (
            f'Session authorized: {authorized}\n'
            f'Sources enabled/total: {enabled}/{total}\n'
            f'Pending queue: {queue_size}'
        )

    async def run_sync_once(
        self,
        *,
        source_chat_id: int | None = None,
        limit: int | None = None,
    ) -> SyncStats:
        await self.bootstrap_legacy_source()
        if not await is_authorized(self.client):
            raise RuntimeError('Session user chua login. Dung login truoc khi sync.')

        if source_chat_id is not None:
            source = self.store.get_source(source_chat_id)
            if source is None:
                raise RuntimeError(f'Khong tim thay source {source_chat_id} trong DB.')
            sources = [source]
        else:
            sources = self.store.list_sources(enabled_only=True)

        stats = SyncStats()
        for source in sources:
            stats.merge(await self._sync_source_once(source, limit=limit))
        return stats

    async def process_message_by_id(self, source_chat_id: int, message_id: int) -> SyncStats:
        source = self.store.get_source(source_chat_id)
        if source is None or not source.enabled:
            return SyncStats()

        context = await self._prepare_source_context(source)
        if context is None:
            return SyncStats()

        message = await self.client.get_messages(context.source_entity, ids=message_id)
        if message is None:
            self.store.upsert_record(
                SyncStateRecord(
                    source_chat_id=source_chat_id,
                    source_msg_id=message_id,
                    status=STATUS_FAILED,
                    extension=None,
                    document_id=None,
                    filename=None,
                    normalized_filename='',
                    size=None,
                    error_text='Khong lay duoc source message khi xu ly realtime/daemon.',
                )
            )
            return SyncStats(processed=1, failed=1)

        return await self._process_message(context, message)

    async def enqueueable_backlog_ids(self, source: SourceRecord, limit: int | None = None) -> list[int]:
        context = await self._prepare_source_context(source)
        if context is None:
            return []

        cursor = self.store.get_cursor(source.source_chat_id)
        message_ids: list[int] = []
        async for message in self.client.iter_messages(context.source_entity, min_id=cursor, reverse=True):
            message_ids.append(message.id)
            if limit is not None and len(message_ids) >= limit:
                break
        return message_ids

    def failed_message_ids(self, source_chat_id: int, limit: int | None = None) -> list[int]:
        return [int(row['source_msg_id']) for row in self.store.list_failed(source_chat_id, limit=limit)]

    async def _sync_source_once(self, source: SourceRecord, limit: int | None = None) -> SyncStats:
        context = await self._prepare_source_context(source)
        if context is None:
            return SyncStats()

        effective_limit = self._resolve_limit(limit)
        stats = SyncStats()
        retry_remaining = effective_limit
        stats.merge(await self._retry_failed(context, retry_remaining))

        if effective_limit is not None:
            retry_remaining = max(effective_limit - stats.processed, 0)
            if retry_remaining == 0:
                return stats

        cursor = self.store.get_cursor(source.source_chat_id)
        logger.info('Cursor source %s hien tai: %s', source.source_chat_id, cursor)
        
        chunk_size = 500
        while True:
            fetch_limit = chunk_size
            if retry_remaining is not None:
                fetch_limit = min(fetch_limit, retry_remaining)
                
            messages_chunk = await self.client.get_messages(context.source_entity, min_id=cursor, limit=fetch_limit, reverse=True)
            if not messages_chunk:
                break
                
            for message in messages_chunk:
                if retry_remaining is not None and retry_remaining <= 0:
                    break

                outcome = await self._process_message(context, message)
                stats.merge(outcome)
                self.store.set_cursor(source.source_chat_id, message.id)
                cursor = message.id

                if retry_remaining is not None:
                    retry_remaining -= 1

            # Xả bộ nhớ để tránh ngốn RAM
            del messages_chunk
            
            if retry_remaining is not None and retry_remaining <= 0:
                break
                
            # Tự động tạm dừng nhỏ nếu quét nhiều
            await asyncio.sleep(0.5)

        return stats

    def _resolve_limit(self, requested_limit: int | None) -> int | None:
        if requested_limit is None:
            return self.settings.sync_limit
        if requested_limit <= 0:
            return None
        return requested_limit

    async def _prepare_source_context(self, source: SourceRecord) -> SourceContext | None:
        cached = self._context_cache.get(source.source_chat_id)
        if cached is not None:
            return cached

        source_entity = await resolve_chat_entity(self.client, source.source_chat_id)
        dest_entity = await resolve_chat_entity(self.client, source.dest_chat_id)
        await validate_topic_messages(
            self.client,
            dest_entity,
            [source.dest_topic_default, source.dest_topic_archive],
        )

        protected = is_protected_chat(source_entity)
        if protected and not source.allow_protected_fallback:
            if source.source_chat_id not in self._warned_protected_sources:
                logger.warning(
                    'Source %s dang protected/no-forwards va chua bat fallback download. Dang bo qua source nay.',
                    source.source_chat_id,
                )
                self._warned_protected_sources.add(source.source_chat_id)
            return None

        context = SourceContext(
            source=source,
            source_entity=source_entity,
            dest_entity=dest_entity,
            protected=protected,
            use_download_fallback=protected and source.allow_protected_fallback,
        )
        self._context_cache[source.source_chat_id] = context
        return context

    async def _retry_failed(self, context: SourceContext, limit: int | None) -> SyncStats:
        rows = self.store.list_failed(context.source.source_chat_id, limit=limit)
        if not rows:
            return SyncStats()

        logger.info('Dang retry %s message loi cua source %s.', len(rows), context.source.source_chat_id)
        stats = SyncStats()
        for row in rows:
            source_msg_id = int(row['source_msg_id'])
            message = await self.client.get_messages(context.source_entity, ids=source_msg_id)
            if message is None:
                self.store.upsert_record(
                    SyncStateRecord(
                        source_chat_id=context.source.source_chat_id,
                        source_msg_id=source_msg_id,
                        status=STATUS_FAILED,
                        extension=row['extension'],
                        document_id=row['document_id'],
                        filename=row['filename'],
                        normalized_filename=row['normalized_filename'] or '',
                        size=row['size'],
                        fingerprint=row['fingerprint'],
                        error_text='Khong con truy cap duoc source message de retry.',
                    )
                )
                stats.processed += 1
                stats.failed += 1
                continue

            stats.merge(await self._process_message(context, message))
        return stats

    async def _process_message(self, context: SourceContext, message: Message) -> SyncStats:
        stats = SyncStats(processed=1)
        existing = self.store.get_record(context.source.source_chat_id, message.id)
        if existing is not None and existing['status'] in {STATUS_SYNCED, STATUS_SKIPPED}:
            stats.skipped += 1
            return stats

        if not self._is_supported_document_message(message):
            self.store.upsert_record(
                SyncStateRecord(
                    source_chat_id=context.source.source_chat_id,
                    source_msg_id=message.id,
                    status=STATUS_SKIPPED,
                    extension=None,
                    document_id=None,
                    filename=None,
                    normalized_filename='',
                    size=None,
                    error_text='Khong phai document/file duoc ho tro.',
                )
            )
            stats.skipped += 1
            return stats

        file_name = getattr(message.file, 'name', None)
        normalized_name = normalize_filename(file_name)
        document = message.document
        document_id = getattr(document, 'id', None)
        file_size = getattr(document, 'size', None)
        decision = decide_file_handling(
            filename=file_name,
            default_topic_id=context.source.dest_topic_default,
            archive_topic_id=context.source.dest_topic_archive,
        )
        fingerprint = (
            build_txt_fingerprint(document_id, file_size, normalized_name)
            if decision.dedupe_txt
            else None
        )

        if fingerprint and self.store.has_txt_fingerprint(fingerprint):
            self.store.upsert_record(
                SyncStateRecord(
                    source_chat_id=context.source.source_chat_id,
                    source_msg_id=message.id,
                    status=STATUS_SKIPPED,
                    extension=decision.extension,
                    document_id=document_id,
                    filename=file_name,
                    normalized_filename=normalized_name,
                    size=file_size,
                    fingerprint=fingerprint,
                    error_text='TXT fingerprint da ton tai, bo qua de tranh trung.',
                )
            )
            stats.skipped += 1
            return stats

        caption = message.message if decision.preserve_caption else None
        formatting_entities = message.entities if decision.preserve_caption and message.message else None

        try:
            sent = await self._send_document_copy(
                context=context,
                message=message,
                topic_id=decision.topic_id,
                caption=caption,
                formatting_entities=formatting_entities,
            )
        except Exception as exc:
            logger.exception('Khong the sync source %s message %s', context.source.source_chat_id, message.id)
            self.store.upsert_record(
                SyncStateRecord(
                    source_chat_id=context.source.source_chat_id,
                    source_msg_id=message.id,
                    status=STATUS_FAILED,
                    extension=decision.extension,
                    document_id=document_id,
                    filename=file_name,
                    normalized_filename=normalized_name,
                    size=file_size,
                    fingerprint=fingerprint,
                    error_text=str(exc),
                )
            )
            stats.failed += 1
            return stats

        self.store.upsert_record(
            SyncStateRecord(
                source_chat_id=context.source.source_chat_id,
                source_msg_id=message.id,
                status=STATUS_SYNCED,
                extension=decision.extension,
                document_id=document_id,
                filename=file_name,
                normalized_filename=normalized_name,
                size=file_size,
                dest_chat_id=context.source.dest_chat_id,
                dest_topic_id=decision.topic_id,
                dest_msg_id=sent.id,
                fingerprint=fingerprint,
            )
        )

        if fingerprint:
            self.store.add_txt_fingerprint(
                fingerprint=fingerprint,
                source_chat_id=context.source.source_chat_id,
                first_source_msg_id=message.id,
                dest_chat_id=context.source.dest_chat_id,
                dest_topic_id=decision.topic_id,
                dest_msg_id=sent.id,
            )

        logger.info(
            'Synced source %s message %s -> destination %s (topic %s)',
            context.source.source_chat_id,
            message.id,
            sent.id,
            decision.topic_id,
        )
        stats.synced += 1
        return stats

    def _is_supported_document_message(self, message: Message) -> bool:
        if not (isinstance(message.media, MessageMediaDocument) and message.document is not None):
            return False
            
        if any((
            getattr(message, 'video', None) is not None,
            getattr(message, 'voice', None) is not None,
            getattr(message, 'audio', None) is not None,
            getattr(message, 'sticker', None) is not None,
            getattr(message, 'gif', None) is not None,
            getattr(message, 'video_note', None) is not None,
        )):
            return False
            
        return True

    async def _send_document_copy(
        self,
        *,
        context: SourceContext,
        message: Message,
        topic_id: int,
        caption: str | None,
        formatting_entities,
    ):
        while True:
            try:
                if context.use_download_fallback:
                    sent_message = await self._download_and_reupload(
                        context=context,
                        message=message,
                        topic_id=topic_id,
                        caption=caption,
                        formatting_entities=formatting_entities,
                    )
                else:
                    sent_message = await self.client.send_file(
                        entity=context.dest_entity,
                        file=message.media,
                        caption=caption,
                        formatting_entities=formatting_entities,
                        reply_to=topic_id,
                        force_document=True,
                    )
                await self._apply_send_pacing()
                return sent_message
            except errors.FloodWaitError as exc:
                wait_seconds = int(exc.seconds) + random.uniform(5.0, 15.0)
                logger.warning('Gap FloodWait %ss, dang ngu %.1fs', exc.seconds, wait_seconds)
                await asyncio.sleep(wait_seconds)

    async def _download_and_reupload(
        self,
        *,
        context: SourceContext,
        message: Message,
        topic_id: int,
        caption: str | None,
        formatting_entities,
    ):
        safe_name = _safe_temp_name(getattr(message.file, 'name', None), message.id)
        temp_path = self.settings.temp_dir / f'{context.source.source_chat_id}_{safe_name}'
        try:
            await self.client.download_media(message, file=str(temp_path))
            
            # Thêm delay sau khi download trước khi upload
            await asyncio.sleep(random.uniform(self.settings.download_delay_min, self.settings.download_delay_max))
            
            return await self.client.send_file(
                entity=context.dest_entity,
                file=str(temp_path),
                caption=caption,
                formatting_entities=formatting_entities,
                reply_to=topic_id,
                force_document=True,
            )
        finally:
            if temp_path.exists():
                temp_path.unlink()

    async def _apply_send_pacing(self) -> None:
        delay_ms = random.randint(self.settings.send_delay_min_ms, self.settings.send_delay_max_ms)
        await asyncio.sleep(delay_ms / 1000)

        self._successful_sends_since_pause += 1
        if self._successful_sends_since_pause % 10 == 0:
            batch_pause = random.uniform(self.settings.batch_pause_min, self.settings.batch_pause_max)
            logger.info('Tam nghi %.1fs sau 10 message thanh cong de tranh ban account.', batch_pause)
            await asyncio.sleep(batch_pause)
            
        if self._successful_sends_since_pause % 50 == 0:
            long_pause = random.uniform(self.settings.long_pause_min, self.settings.long_pause_max)
            logger.info('Nghi dai %.1fs sau 50 message thanh cong.', long_pause)
            await asyncio.sleep(long_pause)


def _safe_temp_name(filename: str | None, message_id: int) -> str:
    if not filename:
        return f'message_{message_id}.bin'
    sanitized = re.sub(r'[^A-Za-z0-9._-]+', '_', Path(filename).name)
    return sanitized or f'message_{message_id}.bin'

