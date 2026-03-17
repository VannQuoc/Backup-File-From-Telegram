from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Sequence

from .config import ConfigError, ensure_runtime_dirs, load_settings
from .daemon import BackupDaemon
from .logging_utils import configure_logging
from .manager_bot import ManagerBotController
from .store import SyncStore
from .sync_engine import BackupService
from .telegram_client import (
    build_manager_bot_client,
    build_user_client,
    ensure_authorized,
    login_interactive,
)

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='tele_backup',
        description='Backup file/document tu private Telegram channel sang forum group.',
    )
    parser.add_argument('--verbose', action='store_true', help='Bat log debug.')

    subparsers = parser.add_subparsers(dest='command', required=True)

    login_parser = subparsers.add_parser('login', help='Dang nhap session Telegram.')
    login_parser.set_defaults(command='login')

    sync_parser = subparsers.add_parser('sync', help='Chay backup one-shot cho tat ca source enabled.')
    sync_parser.add_argument('--source-chat-id', type=int, help='Chi sync mot source cu the.')
    sync_parser.add_argument(
        '--limit',
        type=int,
        help='Gioi han so message moi moi source trong mot lan chay. <=0 nghia la khong gioi han.',
    )
    sync_parser.set_defaults(command='sync')

    daemon_parser = subparsers.add_parser('daemon', help='Chay daemon 24/7 va manager bot neu co config.')
    daemon_parser.set_defaults(command='daemon')

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        parser.error(str(exc))
        return 2

    ensure_runtime_dirs(settings)
    configure_logging(settings.log_path, verbose=args.verbose)

    try:
        return asyncio.run(_run(args, settings))
    except KeyboardInterrupt:
        logger.warning('Da dung theo yeu cau nguoi dung.')
        return 130


async def _run(args, settings) -> int:
    if args.command == 'login':
        client = build_user_client(settings)
        async with client:
            await login_interactive(client, settings.phone)
        logger.info('Session da san sang tai %s', settings.session_path)
        return 0

    if args.command == 'sync':
        client = build_user_client(settings)
        store = SyncStore(settings.db_path)
        try:
            async with client:
                await ensure_authorized(client)
                service = BackupService(client=client, store=store, settings=settings)
                stats = await service.run_sync_once(
                    source_chat_id=args.source_chat_id,
                    limit=args.limit,
                )
        finally:
            store.close()

        logger.info(
            'Hoan tat: processed=%s synced=%s skipped=%s failed=%s',
            stats.processed,
            stats.synced,
            stats.skipped,
            stats.failed,
        )
        return 0 if stats.failed == 0 else 1

    if args.command == 'daemon':
        user_client = build_user_client(settings)
        bot_client = build_manager_bot_client(settings)
        store = SyncStore(settings.db_path)
        service = BackupService(client=user_client, store=store, settings=settings)
        manager_bot = None
        if bot_client is not None:
            manager_bot = ManagerBotController(
                settings=settings,
                bot_client=bot_client,
                user_client=user_client,
                service=service,
                daemon=None,
            )

        daemon = BackupDaemon(
            settings=settings,
            store=store,
            user_client=user_client,
            service=service,
            manager_bot=manager_bot,
        )
        if manager_bot is not None:
            manager_bot.daemon = daemon

        try:
            await daemon.run()
        finally:
            store.close()
        return 0

    raise RuntimeError(f'Lenh khong duoc ho tro: {args.command}')
