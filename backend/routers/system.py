from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.auth import (
    create_session_token,
    hash_password_sha256,
    require_auth,
    verify_admin_password,
)
from backend.database.models import LoginRequest, LoginResponse, SettingsUpdateRequest

router = APIRouter(prefix="/api", tags=["system"])


class GlobalPauseRequest(BaseModel):
    paused: bool


@router.post("/auth/login", response_model=LoginResponse)
async def login_admin(req: LoginRequest, request: Request) -> LoginResponse:
    config = request.app.state.config
    if not verify_admin_password(req.password, config.web_admin_password_sha256):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mật khẩu Admin không chính xác.",
        )
    token = create_session_token(config.web_session_secret)
    return LoginResponse(token=token)


@router.get("/auth/verify")
async def verify_session(
    _user: str = Depends(require_auth),
) -> dict[str, Any]:
    return {"authenticated": True, "user": "admin"}


@router.post("/auth/hash-helper")
async def hash_password_helper(
    req: LoginRequest,
    _user: str = Depends(require_auth),
) -> dict[str, str]:
    """Helper endpoint so admin can generate SHA-256 hashes for .env right from Settings."""
    return {"sha256": hash_password_sha256(req.password)}


@router.get("/system/dashboard")
async def get_dashboard(
    request: Request,
    _user: str = Depends(require_auth),
) -> dict[str, Any]:
    store = request.app.state.store
    stats = store.get_dashboard_stats()
    recent_logs = store.list_execution_logs(limit=15)
    recent_backups = store.list_sync_history(limit=10)
    return {
        "stats": stats,
        "recent_logs": recent_logs,
        "recent_backups": recent_backups,
    }


@router.post("/system/global-pause")
async def toggle_global_pause(
    req: GlobalPauseRequest,
    request: Request,
    _user: str = Depends(require_auth),
) -> dict[str, Any]:
    """Feature #17: Global Panic / Kill Switch to immediately pause or resume all background workers."""
    store = request.app.state.store
    paused = store.set_global_paused(req.paused)
    store.add_execution_log(
        category="system",
        level="WARN" if paused else "INFO",
        status="paused" if paused else "resumed",
        message=(
            "ĐÃ KÍCH HOẠT TẠM DỪNG KHẨN CẤP (Global Kill Switch): Mọi tiến trình Auto-Send & Backup đang tạm dừng."
            if paused
            else "ĐÃ TIẾP TỤC HỆ THỐNG: Các tiến trình Auto-Send & Backup hoạt động trở lại."
        ),
    )
    return {"global_paused": paused}


@router.get("/system/logs")
async def list_logs(
    request: Request,
    category: str | None = None,
    fallback_only: bool = False,
    limit: int = 100,
    _user: str = Depends(require_auth),
) -> list[dict[str, Any]]:
    store = request.app.state.store
    return store.list_execution_logs(
        category=category,
        fallback_only=fallback_only,
        limit=min(500, max(1, limit)),
    )


@router.get("/system/settings")
async def get_settings(
    request: Request,
    _user: str = Depends(require_auth),
) -> dict[str, Any]:
    store = request.app.state.store
    config = request.app.state.config
    return {
        "settings": store.get_settings(),
        "global_paused": store.is_global_paused(),
        "env_info": {
            "web_host": config.web_host,
            "web_port": config.web_port,
            "default_tg_api_id_configured": config.default_tg_api_id is not None,
            "db_path": str(config.db_path),
            "sessions_dir": str(config.sessions_dir),
            "backup_reconcile_interval_seconds": config.backup_reconcile_interval_seconds,
            "auto_send_tick_seconds": config.auto_send_tick_seconds,
        },
    }


@router.put("/system/settings")
async def update_settings(
    req: SettingsUpdateRequest,
    request: Request,
    _user: str = Depends(require_auth),
) -> dict[str, Any]:
    store = request.app.state.store
    return {"settings": store.set_settings(req.settings)}


@router.post("/system/checkpoint")
async def checkpoint_database(
    request: Request,
    _user: str = Depends(require_auth),
) -> dict[str, Any]:
    store = request.app.state.store
    store.checkpoint()
    return {"status": "ok", "message": "Đã thực hiện WAL checkpoint SQLite thành công."}


@router.get("/system/export-config")
async def export_config_bundle(
    request: Request,
    _user: str = Depends(require_auth),
) -> dict[str, Any]:
    """Feature #18: One-click export of folders, chat rules, scenarios, library, and settings."""
    store = request.app.state.store
    return store.export_configuration_bundle()


@router.post("/system/import-config")
async def import_config_bundle(
    request: Request,
    bundle: dict[str, Any] = Body(...),
    _user: str = Depends(require_auth),
) -> dict[str, Any]:
    """Feature #18: One-click import of configuration JSON bundle."""
    store = request.app.state.store
    try:
        summary = store.import_configuration_bundle(bundle)
        store.add_execution_log(
            category="system",
            message=f"Đã import gói cấu hình JSON: {summary}",
        )
        return {"status": "ok", "imported": summary}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/system/download-db")
async def download_sqlite_snapshot(
    request: Request,
    _user: str = Depends(require_auth),
) -> FileResponse:
    """Feature #18: Checkpoints SQLite WAL and downloads the `.sqlite` database file."""
    store = request.app.state.store
    config = request.app.state.config
    store.checkpoint()
    if not config.db_path.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy file SQLite.")
    return FileResponse(
        path=str(config.db_path),
        filename="tele_suite_snapshot.sqlite",
        media_type="application/x-sqlite3",
    )
