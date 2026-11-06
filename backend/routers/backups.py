from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.auth import require_auth
from backend.database.models import BackupJobCreateRequest, BackupJobUpdateRequest

router = APIRouter(prefix="/api/backups", tags=["backups"], dependencies=[Depends(require_auth)])


@router.get("")
async def list_backup_jobs(request: Request) -> list[dict[str, Any]]:
    store = request.app.state.store
    return store.list_backup_jobs()


@router.post("")
async def create_backup_job(req: BackupJobCreateRequest, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    try:
        return store.create_backup_job(req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{job_id}")
async def update_backup_job(
    job_id: int, req: BackupJobUpdateRequest, request: Request
) -> dict[str, Any]:
    store = request.app.state.store
    updated = store.update_backup_job(job_id, req)
    if not updated:
        raise HTTPException(status_code=404, detail="Không tìm thấy luồng Backup")
    return updated


@router.delete("/{job_id}")
async def delete_backup_job(job_id: int, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    deleted = store.delete_backup_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Không tìm thấy luồng Backup")
    return {"deleted": True, "id": job_id}


@router.post("/{job_id}/run")
async def run_backup_job_now(
    job_id: int, request: Request, limit: int | None = 100
) -> dict[str, Any]:
    backup_engine = request.app.state.backup_engine
    try:
        return await backup_engine.run_backup_job(job_id, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/run-all")
async def run_all_backup_jobs(
    request: Request, limit_per_job: int | None = 100
) -> list[dict[str, Any]]:
    backup_engine = request.app.state.backup_engine
    return await backup_engine.sync_all_enabled_jobs(limit_per_job=limit_per_job)


@router.get("/history")
async def list_backup_history(
    request: Request,
    backup_job_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    store = request.app.state.store
    return store.list_sync_history(
        backup_job_id=backup_job_id,
        status=status,
        limit=min(500, max(1, limit)),
    )

