from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from backend.auth import require_auth
from backend.database.models import (
    AccountCreateRequest,
    AccountOtpSendRequest,
    AccountOtpVerifyRequest,
    AccountUpdateRequest,
    BulkJoinRequest,
)

router = APIRouter(prefix="/api/accounts", tags=["accounts"], dependencies=[Depends(require_auth)])


@router.get("")
async def list_accounts(request: Request) -> list[dict[str, Any]]:
    store = request.app.state.store
    return store.list_accounts()


@router.post("")
async def create_account(req: AccountCreateRequest, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    config = request.app.state.config
    try:
        return store.create_account(req, config.sessions_dir)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{account_id}")
async def update_account(
    account_id: int, req: AccountUpdateRequest, request: Request
) -> dict[str, Any]:
    store = request.app.state.store
    updated = store.update_account(account_id, req)
    if not updated:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    return updated


@router.delete("/{account_id}")
async def delete_account(account_id: int, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    pool = request.app.state.pool
    await pool.disconnect_account(account_id)
    deleted = store.delete_account(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    return {"deleted": True, "id": account_id}


@router.get("/{account_id}/groups")
async def list_account_joined_groups(account_id: int, request: Request) -> list[dict[str, Any]]:
    """Returns all groups/channels that this specific account has joined, along with its role and permissions."""
    store = request.app.state.store
    return store.list_chat_groups(account_id=account_id)


@router.post("/{account_id}/connect")
async def connect_account(account_id: int, request: Request) -> dict[str, Any]:
    pool = request.app.state.pool
    try:
        return await pool.connect_account(account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{account_id}/health-check")
async def check_account_health(account_id: int, request: Request) -> dict[str, Any]:
    pool = request.app.state.pool
    try:
        return await pool.check_account_health(account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{account_id}/send-otp")
async def send_account_otp(
    account_id: int, req: AccountOtpSendRequest, request: Request
) -> dict[str, Any]:
    pool = request.app.state.pool
    try:
        return await pool.send_login_code(account_id, phone_override=req.phone)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{account_id}/verify-otp")
async def verify_account_otp(
    account_id: int, req: AccountOtpVerifyRequest, request: Request
) -> dict[str, Any]:
    pool = request.app.state.pool
    try:
        return await pool.verify_login_code(
            account_id, code=req.code, password_2fa=req.password_2fa
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/scan-all-dialogs")
async def scan_all_connected_dialogs(
    request: Request, limit_per_account: int = 250
) -> dict[str, Any]:
    """Scans dialogs across all enabled & connected accounts to reload the group list."""
    pool = request.app.state.pool
    try:
        return await pool.scan_all_connected_accounts_dialogs(
            limit_per_account=limit_per_account
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{account_id}/scan-dialogs")
async def scan_account_dialogs(
    account_id: int, request: Request, limit: int = 250
) -> dict[str, Any]:
    pool = request.app.state.pool
    try:
        groups = await pool.scan_account_dialogs(account_id, limit=limit)
        return {"count": len(groups), "groups": groups}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{account_id}/import-telegram-folders")
async def import_telegram_folders(account_id: int, request: Request) -> dict[str, Any]:
    """
    Clones native Telegram folders (`DialogFilter`) from `account_id` into independent Web Panel folders.
    """
    pool = request.app.state.pool
    try:
        folders = await pool.import_telegram_folders(account_id)
        return {"imported_count": len(folders), "folders": folders}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{account_id}/bulk-join")
async def bulk_join_groups(
    account_id: int, req: BulkJoinRequest, request: Request
) -> dict[str, Any]:
    pool = request.app.state.pool
    try:
        return await pool.bulk_join_chats(
            account_id,
            links_or_usernames=req.links_or_usernames,
            clone_from_account_id=req.clone_from_account_id,
            clone_strategy=req.clone_strategy,
            create_share_folder=req.create_share_folder,
            share_folder_title=req.share_folder_title,
            max_self_joins_per_run=req.max_self_joins_per_run,
            delay_min_sec=req.delay_min_sec,
            delay_max_sec=req.delay_max_sec,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import-session")
async def import_session_file(
    request: Request,
    label: str = Form(...),
    phone: str = Form(...),
    api_id: int | None = Form(None),
    api_hash: str | None = Form(None),
    proxy_url: str | None = Form(None),
    session_file: UploadFile = File(...),
) -> dict[str, Any]:
    store = request.app.state.store
    config = request.app.state.config
    try:
        account = store.create_account(
            AccountCreateRequest(
                label=label,
                phone=phone,
                api_id=api_id,
                api_hash=api_hash,
                proxy_url=proxy_url,
                enabled=True,
            ),
            config.sessions_dir,
        )
        dest_path = Path(account["session_path"])
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with dest_path.open("wb") as f:
            shutil.copyfileobj(session_file.file, f)
        return account
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
