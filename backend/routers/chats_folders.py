from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.auth import require_auth
from backend.database.models import (
    AnalyzeChatHistoryBatchRequest,
    AnalyzeChatHistoryRequest,
    ChatGroupUpsertRequest,
    ChatRuleUpdateRequest,
    CreateTopicRequest,
    FolderCreateRequest,
    FolderUpdateRequest,
)

router = APIRouter(prefix="/api", tags=["chats_folders"], dependencies=[Depends(require_auth)])


@router.get("/chats")
async def list_chat_groups(
    request: Request,
    account_id: int | None = None,
) -> list[dict[str, Any]]:
    store = request.app.state.store
    return store.list_chat_groups(account_id=account_id)


@router.post("/chats")
async def upsert_chat_group(req: ChatGroupUpsertRequest, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    return store.upsert_chat_group(req)


@router.put("/chats/{chat_id}/rules")
async def update_chat_rules(
    chat_id: int, req: ChatRuleUpdateRequest, request: Request
) -> dict[str, Any]:
    store = request.app.state.store
    return store.update_chat_rule(chat_id, req)


@router.delete("/chats/{chat_id}")
async def delete_chat_group(chat_id: int, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    deleted = store.delete_chat_group(chat_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhóm")
    return {"deleted": True, "chat_id": chat_id}


@router.get("/chats/{chat_id}/topics")
async def list_chat_topics(chat_id: int, request: Request) -> list[dict[str, Any]]:
    store = request.app.state.store
    return store.list_chat_topics(chat_id)


@router.post("/chats/{chat_id}/scan-topics")
async def scan_chat_topics(
    chat_id: int,
    request: Request,
    account_id: int | None = None,
) -> dict[str, Any]:
    pool = request.app.state.pool
    try:
        topics = await pool.scan_chat_topics(account_id or 0, chat_id)
        return {"chat_id": chat_id, "count": len(topics), "topics": topics}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/chats/{chat_id}/create-topic")
async def create_forum_topic(
    chat_id: int,
    req: CreateTopicRequest,
    request: Request,
) -> dict[str, Any]:
    pool = request.app.state.pool
    try:
        topic = await pool.create_forum_topic(
            req.account_id,
            chat_id,
            req.title,
            req.icon_color,
        )
        return topic
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/chats/{chat_id}/recent-messages")
async def get_recent_chat_messages(
    chat_id: int,
    request: Request,
    account_id: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    pool = request.app.state.pool
    try:
        messages = await pool.get_recent_chat_messages(
            chat_id=chat_id,
            account_id=account_id,
            limit=limit,
        )
        return {"chat_id": chat_id, "count": len(messages), "messages": messages}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/chats/{chat_id}/analyze-history")
async def analyze_chat_history_permissions(
    chat_id: int,
    req: AnalyzeChatHistoryRequest,
    request: Request,
) -> dict[str, Any]:
    """
    Scans up to `req.limit` (default 1000) recent messages in `chat_id` to see whether
    normal members (excluding Admins/Bots) send links, forwards, stickers, media, or bot mentions.
    If normal users can send them, automatically unlocks those rules (`auto_apply_unlock=True`).
    """
    pool = request.app.state.pool
    try:
        return await pool.analyze_chat_member_permissions_from_history(
            chat_id=chat_id,
            account_id=req.account_id,
            limit=req.limit,
            auto_apply_unlock=req.auto_apply_unlock,
            strict_infer_blocks=req.strict_infer_blocks,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/chats/analyze-history-batch")
async def analyze_chat_history_batch(
    req: AnalyzeChatHistoryBatchRequest,
    request: Request,
) -> dict[str, Any]:
    """Batch-scans recent 1,000 messages across multiple groups (or a Folder) to auto-detect normal user permissions."""
    store = request.app.state.store
    pool = request.app.state.pool

    target_ids: list[int] = [int(cid) for cid in req.chat_ids]
    if not target_ids and req.folder_id is not None:
        folder = store.get_folder(req.folder_id)
        if folder:
            target_ids = [int(fc["chat_id"]) for fc in folder.get("chats", [])]
    if not target_ids:
        target_ids = [int(c["chat_id"]) for c in store.list_chat_groups()]

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for cid in target_ids:
        try:
            res = await pool.analyze_chat_member_permissions_from_history(
                chat_id=cid,
                account_id=req.account_id,
                limit=req.limit_per_chat,
                auto_apply_unlock=req.auto_apply_unlock,
                strict_infer_blocks=req.strict_infer_blocks,
            )
            results.append(res)
        except Exception as exc:
            errors.append({"chat_id": cid, "error": str(exc)})

    return {
        "scanned_count": len(results),
        "failed_count": len(errors),
        "results": results,
        "errors": errors,
    }


@router.get("/folders")
async def list_folders(request: Request) -> list[dict[str, Any]]:
    store = request.app.state.store
    return store.list_folders()


@router.post("/folders")
async def create_folder(req: FolderCreateRequest, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    try:
        return store.create_folder(req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/folders/{folder_id}")
async def update_folder(
    folder_id: int, req: FolderUpdateRequest, request: Request
) -> dict[str, Any]:
    store = request.app.state.store
    updated = store.update_folder(folder_id, req)
    if not updated:
        raise HTTPException(status_code=404, detail="Không tìm thấy Folder")
    return updated


@router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: int, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    deleted = store.delete_folder(folder_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Không tìm thấy Folder")
    return {"deleted": True, "id": folder_id}
