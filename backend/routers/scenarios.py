from __future__ import annotations

import shutil
import time
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from backend.auth import require_auth
from backend.database.models import (
    ChatRuleModel,
    MediaLibraryCreateRequest,
    ScenarioCreateRequest,
    ScenarioStepInput,
    ScenarioUpdateRequest,
)
from backend.telegram.auto_sender import expand_scenario_destinations
from backend.telegram.rule_engine import is_within_active_hours, resolve_execution_plan

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"], dependencies=[Depends(require_auth)])


class SimulateFallbackRequest(BaseModel):
    step: ScenarioStepInput
    chat_id: int | None = None
    custom_rule: ChatRuleModel | None = None
    override_text_content: str | None = None


@router.get("")
async def list_scenarios(request: Request) -> list[dict[str, Any]]:
    store = request.app.state.store
    auto_sender = request.app.state.auto_sender
    raw_list = store.list_scenarios()
    enriched: list[dict[str, Any]] = []
    for sc in raw_list:
        sid = int(sc["id"])
        enabled_targets = [t for t in sc.get("targets", []) if t.get("enabled", True)]
        next_runs = [
            str(t["next_run_at"])
            for t in enabled_targets
            if t.get("next_run_at")
        ]
        enriched.append(
            {
                **sc,
                "within_active_hours": is_within_active_hours(
                    sc.get("active_hours_start"),
                    sc.get("active_hours_end"),
                ),
                "next_run_at": min(next_runs) if next_runs else None,
                "live_run": auto_sender.get_scenario_run_status(sid),
            }
        )
    return enriched


@router.post("")
async def create_scenario(req: ScenarioCreateRequest, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    try:
        return store.create_scenario(req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{scenario_id}")
async def update_scenario(
    scenario_id: int, req: ScenarioUpdateRequest, request: Request
) -> dict[str, Any]:
    store = request.app.state.store
    updated = store.update_scenario(scenario_id, req)
    if not updated:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản")
    return updated


@router.delete("/{scenario_id}")
async def delete_scenario(scenario_id: int, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    deleted = store.delete_scenario(scenario_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản")
    return {"deleted": True, "id": scenario_id}


@router.post("/{scenario_id}/run")
async def run_scenario_now(
    scenario_id: int,
    request: Request,
    wait: bool = False,
) -> dict[str, Any]:
    auto_sender = request.app.state.auto_sender
    try:
        if wait:
            logs = await auto_sender.run_scenario_now(scenario_id)
            return {
                "scenario_id": scenario_id,
                "status": "completed",
                "background": False,
                "executed_count": len(logs),
                "logs": logs,
            }
        return await auto_sender.trigger_scenario_background(scenario_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{scenario_id}/run-status")
async def get_scenario_run_status(scenario_id: int, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    auto_sender = request.app.state.auto_sender
    scenario = store.get_scenario(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản")
    live = auto_sender.get_scenario_run_status(scenario_id)
    return live or {
        "scenario_id": scenario_id,
        "scenario_name": scenario["name"],
        "running": False,
        "total_destinations": len(expand_scenario_destinations(store, scenario)),
        "processed": 0,
        "sent_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "started_at": None,
        "finished_at": None,
        "last_message": None,
    }


@router.post("/{scenario_id}/clone")
async def clone_scenario(
    scenario_id: int,
    request: Request,
    new_name: str | None = None,
) -> dict[str, Any]:
    store = request.app.state.store
    cloned = store.clone_scenario(scenario_id, new_name=new_name)
    if not cloned:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản để nhân bản")
    return cloned


@router.get("/{scenario_id}/preflight-check")
async def preflight_check_scenario(scenario_id: int, request: Request) -> dict[str, Any]:
    """
    Simulates how all steps in `scenario_id` will execute across all target groups/folders,
    reporting Native sends vs Auto-Fallbacks vs Skips and member account availability.
    """
    store = request.app.state.store
    scenario = store.get_scenario(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản")

    destinations = expand_scenario_destinations(store, scenario)
    steps = scenario.get("steps", [])
    matrix: list[dict[str, Any]] = []
    native_count = 0
    fallback_count = 0
    skip_count = 0

    for dest in destinations:
        cid = int(dest["chat_id"])
        tid = int(dest.get("topic_id") or 0)
        chat_info = store.get_chat_group(cid) or {}
        chat_title = chat_info.get("title") or f"Chat {cid}"
        rule = store.get_chat_rule(cid)
        members = store.get_member_accounts_for_chat(cid, require_send_permission=True)
        prev_sent = store.get_last_sent_message_for_scenario(scenario_id, cid, tid)

        step_outcomes: list[dict[str, Any]] = []
        for s in steps:
            plan = resolve_execution_plan(
                s,
                rule,
                override_text_content=dest.get("override_text_content"),
                render_context={
                    "chat_id": cid,
                    "chat_title": chat_title,
                    "account_name": members[0]["account_label"] if members else "Auto Nick",
                },
            )
            if plan.action_to_execute == "skip":
                skip_count += 1
            elif plan.fallback_applied:
                fallback_count += 1
            else:
                native_count += 1

            step_outcomes.append(
                {
                    "step_order": s.get("step_order"),
                    "step_name": s.get("name"),
                    "original_action": str(s.get("action_type") or "send_text"),
                    "action_to_execute": plan.action_to_execute,
                    "fallback_applied": plan.fallback_applied,
                    "fallback_reasons": plan.fallback_reasons,
                    "preview_text": (plan.text_content or "")[:120],
                }
            )

        matrix.append(
            {
                "chat_id": cid,
                "chat_title": chat_title,
                "topic_id": tid,
                "folder_name": dest.get("folder_name"),
                "eligible_member_accounts": [m["account_label"] for m in members],
                "last_sent_msg_id": (prev_sent or {}).get("last_msg_id"),
                "steps": step_outcomes,
            }
        )

    return {
        "scenario_id": scenario_id,
        "scenario_name": scenario["name"],
        "total_destinations": len(destinations),
        "summary": {
            "native_count": native_count,
            "fallback_count": fallback_count,
            "skip_count": skip_count,
        },
        "destinations": matrix,
    }


@router.post("/simulate-fallback")
async def simulate_fallback_plan(
    req: SimulateFallbackRequest, request: Request
) -> dict[str, Any]:
    """Allows testing how a ScenarioStep will transform or fallback (including Spintax/Variables) for a specific chat's rules."""
    store = request.app.state.store
    chat_title = "Nhóm Mô Phỏng"
    if req.custom_rule is not None:
        rule = req.custom_rule
    elif req.chat_id is not None:
        rule = store.get_chat_rule(req.chat_id)
        chat_info = store.get_chat_group(req.chat_id)
        if chat_info:
            chat_title = chat_info.get("title") or chat_title
    else:
        rule = ChatRuleModel(chat_id=0)

    plan = resolve_execution_plan(
        req.step.model_dump(),
        rule,
        override_text_content=req.override_text_content,
        render_context={
            "chat_id": req.chat_id or -100123456789,
            "chat_title": chat_title,
            "account_name": "Nick Demo",
        },
    )
    return {
        "chat_rule_applied": rule.model_dump(),
        "resolved_plan": asdict(plan),
    }


@router.post("/upload-media")
async def upload_scenario_media(
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    config = request.app.state.config
    safe_name = "".join(
        ch for ch in (file.filename or "upload.bin") if ch.isalnum() or ch in "._-"
    )
    dest = config.uploads_dir / f"{int(time.time())}_{safe_name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"filename": file.filename, "media_path": str(dest.resolve())}


# -------------------------------------------------------------------------
# MEDIA, STICKER & SPINTAX TEMPLATE LIBRARY (FEATURE #12)
# -------------------------------------------------------------------------
@router.get("/library/items")
async def list_media_library(
    request: Request,
    item_type: str | None = None,
) -> list[dict[str, Any]]:
    store = request.app.state.store
    return store.list_media_library(item_type=item_type)


@router.post("/library/items")
async def create_media_library_item(
    req: MediaLibraryCreateRequest,
    request: Request,
) -> dict[str, Any]:
    store = request.app.state.store
    return store.create_media_library_item(req)


@router.delete("/library/items/{item_id}")
async def delete_media_library_item(
    item_id: int,
    request: Request,
) -> dict[str, Any]:
    store = request.app.state.store
    deleted = store.delete_media_library_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Không tìm thấy mẫu trong Thư viện")
    return {"deleted": True, "id": item_id}
