from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from telethon import TelegramClient, utils
from telethon.sessions import SQLiteSession, StringSession
from telethon.tl import types
from telethon.tl.types import Message
from telethon.errors import AuthKeyUnregisteredError

from .config import Settings

logger = logging.getLogger(__name__)

_SQLITE_HEADER = b'SQLite format 3\x00'
_SESSION_PATH_ATTR = '_local_session_path'


def build_user_client(settings: Settings) -> TelegramClient:
    return _build_client(
        session_path=settings.session_path,
        api_id=settings.api_id,
        api_hash=settings.api_hash,
        device_model='Tele Backup ULP',
        system_version='Windows',
        app_version='0.2.2',
    )


def build_manager_bot_client(settings: Settings) -> TelegramClient | None:
    if not settings.manager_bot_token:
        return None
    return _build_client(
        session_path=settings.manager_bot_session_path,
        api_id=settings.api_id,
        api_hash=settings.api_hash,
        device_model='Tele Backup ULP Manager',
        system_version='Windows',
        app_version='0.2.2',
    )


async def connect_client(client: TelegramClient) -> None:
    await client.connect()
    persist_session(client)


async def login_interactive(client: TelegramClient, phone: str) -> None:
    await connect_client(client)
    if await client.is_user_authorized():
        logger.info('Session da duoc dang nhap truoc do.')
        return

    await client.start(phone=phone)
    persist_session(client)
    me = await client.get_me()
    logger.info('Dang nhap thanh cong voi account %s', getattr(me, 'username', None) or me.id)


async def start_bot_client(client: TelegramClient, bot_token: str) -> None:
    await client.start(bot_token=bot_token)
    persist_session(client)


async def is_authorized(client: TelegramClient) -> bool:
    await connect_client(client)
    try:
        return await client.is_user_authorized()
    except AuthKeyUnregisteredError:
        logger.warning('Session token da bi thu hoi (AuthKeyUnregisteredError). Dang xoa session cu.')
        clear_persisted_session(client)
        return False


async def ensure_authorized(client: TelegramClient) -> None:
    await connect_client(client)
    try:
        authorized = await client.is_user_authorized()
    except AuthKeyUnregisteredError:
        logger.warning('Session token da bi thu hoi (AuthKeyUnregisteredError). Dang xoa session cu.')
        clear_persisted_session(client)
        authorized = False
        
    if not authorized:
        raise RuntimeError('Session chua dang nhap hoac token sai. Hay chay `python -m tele_backup login` truoc.')


def persist_session(client: TelegramClient) -> None:
    session_path = _get_session_path(client)
    session_string = StringSession.save(client.session)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(session_string, encoding='utf-8')


def clear_persisted_session(client: TelegramClient) -> None:
    session_path = _get_session_path(client)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text('', encoding='utf-8')


async def resolve_chat_entity(client: TelegramClient, configured_id: int):
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        candidate_ids = collect_candidate_ids(entity, dialog.id)
        if configured_id in candidate_ids:
            return entity
    return await client.get_entity(configured_id)


def collect_candidate_ids(entity, dialog_id: int | None = None) -> set[int]:
    candidates: set[int] = set()
    if dialog_id is not None:
        candidates.add(dialog_id)

    raw_id = getattr(entity, 'id', None)
    if isinstance(raw_id, int):
        candidates.add(raw_id)

    try:
        candidates.add(utils.get_peer_id(entity))
    except Exception:
        pass

    return candidates


async def validate_topic_messages(
    client: TelegramClient,
    destination_entity,
    topic_ids: Iterable[int],
) -> None:
    topic_ids = list(topic_ids)
    messages = await client.get_messages(destination_entity, ids=topic_ids)
    if not isinstance(messages, list):
        messages = [messages]

    missing = [
        topic_id
        for topic_id, topic_message in zip(topic_ids, messages, strict=True)
        if topic_message is None
    ]
    if missing:
        raise RuntimeError(f"Khong tim thay topic root message: {', '.join(map(str, missing))}.")


async def resolve_source_to_raw_id(client: TelegramClient, source_ref: int) -> int:
    entity = await resolve_chat_entity(client, source_ref)
    raw_id = getattr(entity, 'id', None)
    if not isinstance(raw_id, int):
        raise RuntimeError('Khong resolve duoc raw source chat id.')
    return raw_id


async def resolve_destination_to_marked_id(client: TelegramClient, destination_ref: int) -> int:
    entity = await resolve_chat_entity(client, destination_ref)
    return utils.get_peer_id(entity)


def is_protected_chat(entity) -> bool:
    return bool(getattr(entity, 'noforwards', False))


def extract_raw_source_chat_id(message: Message) -> int | None:
    peer = message.peer_id
    if isinstance(peer, types.PeerChannel):
        return peer.channel_id
    if isinstance(peer, types.PeerChat):
        return peer.chat_id
    if isinstance(peer, types.PeerUser):
        return peer.user_id
    return None


def _build_client(
    *,
    session_path: Path,
    api_id: int,
    api_hash: str,
    device_model: str,
    system_version: str,
    app_version: str,
) -> TelegramClient:
    session = _load_session_backend(session_path)
    client = TelegramClient(
        session=session,
        api_id=api_id,
        api_hash=api_hash,
        device_model=device_model,
        system_version=system_version,
        app_version=app_version,
    )
    setattr(client, _SESSION_PATH_ATTR, session_path)
    return client


def _load_session_backend(session_path: Path):
    session_path.parent.mkdir(parents=True, exist_ok=True)
    if not session_path.exists():
        return StringSession()

    raw = session_path.read_bytes()
    if not raw:
        return StringSession()

    if raw.startswith(_SQLITE_HEADER):
        try:
            sqlite_session = SQLiteSession(str(session_path))
            try:
                session_string = StringSession.save(sqlite_session)
            finally:
                sqlite_session.close()
        except Exception as exc:
            return _reset_broken_session(
                session_path,
                raw,
                reason=f'SQLite session loi ({exc}). Da reset de login lai.',
                backup_suffix='sqlite.corrupt.bak',
            )

        backup_path = session_path.with_name(f'{session_path.name}.sqlite.bak')
        if not backup_path.exists():
            backup_path.write_bytes(raw)
        session_path.write_text(session_string, encoding='utf-8')
        logger.info('Da migrate Telethon sqlite session -> string session: %s', session_path)
        return StringSession(session_string)

    try:
        session_string = raw.decode('utf-8').strip()
        return StringSession(session_string) if session_string else StringSession()
    except Exception as exc:
        return _reset_broken_session(
            session_path,
            raw,
            reason=f'String session loi ({exc}). Da reset de login lai.',
            backup_suffix='string.corrupt.bak',
        )


def _reset_broken_session(session_path: Path, raw: bytes, *, reason: str, backup_suffix: str):
    backup_path = session_path.with_name(f'{session_path.name}.{backup_suffix}')
    if not backup_path.exists():
        backup_path.write_bytes(raw)
    session_path.write_text('', encoding='utf-8')
    logger.warning('%s Backup tai %s', reason, backup_path)
    return StringSession()


def _get_session_path(client: TelegramClient) -> Path:
    path = getattr(client, _SESSION_PATH_ATTR, None)
    if not isinstance(path, Path):
        raise RuntimeError('Khong xac dinh duoc local session path de persist.')
    return path
