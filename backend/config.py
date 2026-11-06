from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    web_admin_password_sha256: str
    web_session_secret: str
    web_host: str
    web_port: int
    default_tg_api_id: int | None
    default_tg_api_hash: str | None
    data_dir: Path
    db_path: Path
    sessions_dir: Path
    uploads_dir: Path
    temp_dir: Path
    log_path: Path
    backup_reconcile_interval_seconds: int
    auto_send_tick_seconds: int

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)


def load_config(env_file: Path | str | None = None) -> AppConfig:
    if env_file:
        load_dotenv(dotenv_path=env_file, override=False)
    else:
        load_dotenv(override=False)

    # Default SHA-256 is hash of "admin123" if not configured yet
    default_hash = hashlib.sha256(b"admin123").hexdigest()
    raw_hash = os.getenv("WEB_ADMIN_PASSWORD_SHA256", "").strip().lower()
    password_sha256 = raw_hash if len(raw_hash) == 64 else default_hash

    session_secret = os.getenv(
        "WEB_SESSION_SECRET",
        "tele-suite-default-hmac-secret-key-2026",
    ).strip()

    raw_api_id = os.getenv("DEFAULT_TG_API_ID", os.getenv("TG_API_ID", "")).strip()
    default_api_id = int(raw_api_id) if raw_api_id.isdigit() else None
    default_api_hash = (
        os.getenv("DEFAULT_TG_API_HASH", os.getenv("TG_API_HASH", "")).strip() or None
    )

    data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    db_path = Path(os.getenv("DB_PATH", str(data_dir / "state.sqlite"))).resolve()
    sessions_dir = Path(os.getenv("SESSIONS_DIR", str(data_dir / "sessions"))).resolve()
    uploads_dir = Path(os.getenv("UPLOADS_DIR", str(data_dir / "uploads"))).resolve()
    temp_dir = Path(os.getenv("TEMP_DIR", str(data_dir / "temp"))).resolve()
    log_path = Path(os.getenv("LOG_PATH", str(data_dir / "logs" / "app.log"))).resolve()

    cfg = AppConfig(
        web_admin_password_sha256=password_sha256,
        web_session_secret=session_secret,
        web_host=os.getenv("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1",
        web_port=int(os.getenv("WEB_PORT", "8000")),
        default_tg_api_id=default_api_id,
        default_tg_api_hash=default_api_hash,
        data_dir=data_dir,
        db_path=db_path,
        sessions_dir=sessions_dir,
        uploads_dir=uploads_dir,
        temp_dir=temp_dir,
        log_path=log_path,
        backup_reconcile_interval_seconds=max(
            15, int(os.getenv("BACKUP_RECONCILE_INTERVAL_SECONDS", "120"))
        ),
        auto_send_tick_seconds=max(2, int(os.getenv("AUTO_SEND_TICK_SECONDS", "5"))),
    )
    cfg.ensure_dirs()
    return cfg

