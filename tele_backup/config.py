from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class LegacySourceBootstrap:
    source_chat_id: int
    dest_chat_id: int
    dest_topic_default: int
    dest_topic_archive: int
    label: str | None
    allow_protected_fallback: bool


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    phone: str
    db_path: Path
    session_path: Path
    manager_bot_session_path: Path
    log_path: Path
    temp_dir: Path
    send_delay_min_ms: int
    send_delay_max_ms: int
    sync_limit: int | None
    live_reconcile_seconds: int
    manager_bot_token: str | None
    admin_user_ids: tuple[int, ...]
    legacy_source: LegacySourceBootstrap | None
    batch_pause_min: int
    batch_pause_max: int
    long_pause_min: int
    long_pause_max: int
    download_delay_min: int
    download_delay_max: int


def load_settings(env_path: Path | None = None) -> Settings:
    load_dotenv(dotenv_path=env_path or Path('.env'), override=False)

    send_delay_min_ms = _read_int('SEND_DELAY_MIN_MS', default=3000)
    send_delay_max_ms = _read_int('SEND_DELAY_MAX_MS', default=6000)
    if send_delay_min_ms <= 0 or send_delay_max_ms <= 0:
        raise ConfigError('SEND_DELAY_MIN_MS va SEND_DELAY_MAX_MS phai lon hon 0.')
    if send_delay_min_ms > send_delay_max_ms:
        raise ConfigError('SEND_DELAY_MIN_MS khong duoc lon hon SEND_DELAY_MAX_MS.')

    sync_limit = _read_optional_int('SYNC_LIMIT', default=None)
    if sync_limit is not None and sync_limit <= 0:
        sync_limit = None

    live_reconcile_seconds = _read_int('LIVE_RECONCILE_SECONDS', default=120)
    if live_reconcile_seconds <= 0:
        raise ConfigError('LIVE_RECONCILE_SECONDS phai lon hon 0.')

    return Settings(
        api_id=_read_int('TG_API_ID'),
        api_hash=_read_str('TG_API_HASH'),
        phone=_read_str('TG_PHONE'),
        db_path=_read_path('DB_PATH', default='./data/state.sqlite'),
        session_path=_read_path('SESSION_PATH', default='./data/user.session'),
        manager_bot_session_path=_read_path(
            'MANAGER_BOT_SESSION_PATH',
            default='./data/manager_bot.session',
        ),
        log_path=_read_path('LOG_PATH', default='./data/logs/sync.log'),
        temp_dir=_read_path('TEMP_DIR', default='./data/temp'),
        send_delay_min_ms=send_delay_min_ms,
        send_delay_max_ms=send_delay_max_ms,
        sync_limit=sync_limit,
        live_reconcile_seconds=live_reconcile_seconds,
        manager_bot_token=_read_optional_str('MANAGER_BOT_TOKEN'),
        admin_user_ids=_read_int_list('ADMIN_USER_IDS'),
        legacy_source=_read_legacy_source(),
        batch_pause_min=_read_int('BATCH_PAUSE_MIN', default=30),
        batch_pause_max=_read_int('BATCH_PAUSE_MAX', default=60),
        long_pause_min=_read_int('LONG_PAUSE_MIN', default=300),
        long_pause_max=_read_int('LONG_PAUSE_MAX', default=600),
        download_delay_min=_read_int('DOWNLOAD_DELAY_MIN', default=1),
        download_delay_max=_read_int('DOWNLOAD_DELAY_MAX', default=3),
    )


def ensure_runtime_dirs(settings: Settings) -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.session_path.parent.mkdir(parents=True, exist_ok=True)
    settings.manager_bot_session_path.parent.mkdir(parents=True, exist_ok=True)
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    settings.temp_dir.mkdir(parents=True, exist_ok=True)


def _read_str(name: str) -> str:
    value = os.getenv(name, '').strip()
    if not value:
        raise ConfigError(f'Thieu bien moi truong {name}.')
    return value


def _read_optional_str(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _read_int(name: str, default: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        if default is None:
            raise ConfigError(f'Thieu bien moi truong {name}.')
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f'{name} phai la so nguyen.') from exc


def _read_optional_int(name: str, default: int | None = None) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f'{name} phai la so nguyen neu co gia tri.') from exc


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default

    value = raw.strip().lower()
    if value in {'1', 'true', 'yes', 'y', 'on'}:
        return True
    if value in {'0', 'false', 'no', 'n', 'off'}:
        return False
    raise ConfigError(f'{name} phai la boolean (true/false, 1/0).')


def _read_int_list(name: str) -> tuple[int, ...]:
    raw = os.getenv(name, '').strip()
    if not raw:
        return ()

    values = []
    for part in raw.split(','):
        item = part.strip()
        if not item:
            continue
        try:
            values.append(int(item))
        except ValueError as exc:
            raise ConfigError(f'{name} phai la danh sach so nguyen cach nhau boi dau phay.') from exc
    return tuple(values)


def _read_legacy_source() -> LegacySourceBootstrap | None:
    source_chat_id = _read_optional_int('SOURCE_CHAT_ID')
    dest_chat_id = _read_optional_int('DEST_CHAT_ID')
    dest_topic_default = _read_optional_int('DEST_TOPIC_DEFAULT')
    dest_topic_archive = _read_optional_int('DEST_TOPIC_ARCHIVE')

    values = [source_chat_id, dest_chat_id, dest_topic_default, dest_topic_archive]
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ConfigError(
            'Neu dung legacy SOURCE_/DEST_ env vars thi phai cung cap day du '
            'SOURCE_CHAT_ID, DEST_CHAT_ID, DEST_TOPIC_DEFAULT, DEST_TOPIC_ARCHIVE.'
        )

    return LegacySourceBootstrap(
        source_chat_id=source_chat_id,
        dest_chat_id=dest_chat_id,
        dest_topic_default=dest_topic_default,
        dest_topic_archive=dest_topic_archive,
        label=_read_optional_str('SOURCE_LABEL'),
        allow_protected_fallback=_read_bool('ALLOW_PROTECTED_FALLBACK', default=False),
    )


def _read_path(name: str, default: str) -> Path:
    raw = os.getenv(name, default).strip()
    if not raw:
        raw = default
    return Path(raw).expanduser().resolve()
