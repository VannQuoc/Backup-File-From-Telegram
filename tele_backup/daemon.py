from __future__ import annotations

import asyncio
import logging

from telethon import events
from telethon.client import TelegramClient

from .config import Settings
from .store import SyncStore
from .sync_engine import BackupService, SyncStats
from .telegram_client import connect_client, extract_raw_source_chat_id, is_authorized

logger = logging.getLogger(__name__)


class BackupDaemon:
    def __init__(
        self,
        *,
        settings: Settings,
        store: SyncStore,
        user_client: TelegramClient,
        service: BackupService,
        manager_bot=None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.user_client = user_client
        self.service = service
        self.manager_bot = manager_bot
        self._process_lock = asyncio.Lock()
        self._reconcile_task: asyncio.Task | None = None
        self._active_sync_task: asyncio.Task | None = None
        self._started = False
        self._stop_requested = False

    async def start(self) -> None:
        if self._started:
            return

        await self.service.bootstrap_legacy_source()
        await connect_client(self.user_client)
        self.user_client.add_event_handler(self._on_new_message, events.NewMessage())

        if self.manager_bot is not None:
            await self.manager_bot.start()

        if await is_authorized(self.user_client):
            await self.schedule_sync(wait=True)
        elif self.manager_bot is None:
            raise RuntimeError('Session user chua login va khong co manager bot de dieu khien login tu xa.')

        self._reconcile_task = asyncio.create_task(self._reconcile_loop(), name='backup-reconcile')
        self._started = True

    async def run(self) -> None:
        await self.start()
        waiters = [asyncio.create_task(self.user_client.run_until_disconnected(), name='user-client')]
        if self.manager_bot is not None:
            waiters.append(asyncio.create_task(self.manager_bot.run_until_disconnected(), name='manager-bot'))
        if self._reconcile_task is not None:
            waiters.append(self._reconcile_task)

        done, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        try:
            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc
        finally:
            await self.stop()
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def stop(self) -> None:
        if self._stop_requested:
            return
        self._stop_requested = True

        tasks = []
        if self._active_sync_task is not None and not self._active_sync_task.done():
            self._active_sync_task.cancel()
            tasks.append(self._active_sync_task)
        if self._reconcile_task is not None and not self._reconcile_task.done():
            self._reconcile_task.cancel()
            tasks.append(self._reconcile_task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        if self.manager_bot is not None:
            await self.manager_bot.stop()
        await self.user_client.disconnect()

    async def on_user_authorized(self) -> None:
        self.service._context_cache.clear()
        self.service._warned_protected_sources.clear()
        await self.schedule_sync(wait=False)

    async def schedule_sync(
        self,
        *,
        source_chat_id: int | None = None,
        limit: int | None = None,
        wait: bool = False,
    ) -> asyncio.Task | SyncStats:
        if self._active_sync_task is not None and not self._active_sync_task.done():
            if wait:
                return await self._active_sync_task
            return self._active_sync_task

        self._active_sync_task = asyncio.create_task(
            self._run_sync(source_chat_id=source_chat_id, limit=limit),
            name='backup-manual-sync',
        )
        if wait:
            return await self._active_sync_task
        return self._active_sync_task

    def is_busy(self) -> bool:
        return self._process_lock.locked() or (
            self._active_sync_task is not None and not self._active_sync_task.done()
        )

    async def status_text(self) -> str:
        base = await self.service.build_status_text(queue_size=0)
        return f'{base}\nBusy: {self.is_busy()}'

    async def _run_sync(self, *, source_chat_id: int | None, limit: int | None) -> SyncStats:
        async with self._process_lock:
            return await self.service.run_sync_once(source_chat_id=source_chat_id, limit=limit)

    async def _reconcile_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.settings.live_reconcile_seconds)
                if not await is_authorized(self.user_client):
                    continue
                if self.is_busy():
                    continue
                try:
                    await self.schedule_sync(wait=True)
                except Exception:
                    logger.exception('Reconcile loop bi loi.')
        except asyncio.CancelledError:
            raise

    async def _on_new_message(self, event) -> None:
        source_chat_id = extract_raw_source_chat_id(event.message)
        if source_chat_id is None:
            return

        source = self.service.get_source(source_chat_id)
        if source is None or not source.enabled:
            return
        if not await is_authorized(self.user_client):
            return

        async with self._process_lock:
            stats = await self.service.process_message_by_id(source_chat_id, event.message.id)
            if stats.processed > 0:
                current_cursor = self.store.get_cursor(source_chat_id)
                if event.message.id > current_cursor:
                    self.store.set_cursor(source_chat_id, event.message.id)
