from __future__ import annotations

import asyncio
import base64
import logging
import random
import re
import struct
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from telethon import functions, types
from telethon import utils as tg_utils

from backend.config import AppConfig
from backend.database.db import DatabaseStore
from backend.database.models import AccountMembershipModel
from backend.telegram.client_pool import TelegramClientPool
from backend.telegram.rule_engine import (
    ResolvedSendPlan,
    apply_anti_spam_text_variation,
    classify_telegram_error,
    is_within_active_hours,
    resolve_execution_plan,
)

logger = logging.getLogger(__name__)

_WEB_LOCATION_FLAG = 1 << 24
_FILE_REFERENCE_FLAG = 1 << 25
_CHAT_MSG_REF_RE = re.compile(r"^(me|-?\d+|[a-zA-Z0-9_]{4,}):(\d+)$")


def _rle_decode_telegram(data: bytes) -> bytes:
    """Decodes Telegram Bot API zero-byte run-length encoding (0x00 followed by count)."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b == 0 and i + 1 < n:
            out.extend(b"\x00" * data[i + 1])
            i += 2
        else:
            out.append(b)
            i += 1
    return bytes(out)


def decode_bot_api_file_id(file_id_str: str) -> types.TypeInputMedia | Any | None:
    """
    Decodes both legacy and modern Telegram Bot API v4 file_ids (e.g. 'CAACAgUAAxkBAAEI...')
    into a Telethon InputDocument or InputPhoto.
    Telethon's built-in `resolve_bot_file_id` returns None for modern Bot API v4 file_ids
    that include FILE_REFERENCE_FLAG (0x02000000).
    """
    cleaned = file_id_str.strip()
    if not cleaned:
        return None

    # 1. Try Telethon's built-in resolver first
    try:
        resolved = tg_utils.resolve_bot_file_id(cleaned)
        if resolved is not None:
            return resolved
    except Exception as exc:
        logger.debug("resolve_bot_file_id fallback cho %s: %s", cleaned[:16], exc)

    # 2. Decode modern Bot API v4 file_id with FILE_REFERENCE_FLAG (sub_version >= 30, version == 4)
    try:
        padded = cleaned + "=" * (-len(cleaned) % 4)
        raw = _rle_decode_telegram(base64.urlsafe_b64decode(padded))
        if len(raw) < 24:
            return None

        type_id, _dc_id = struct.unpack("<ii", raw[:8])
        file_type = type_id & ~(_WEB_LOCATION_FLAG | _FILE_REFERENCE_FLAG)
        has_web_location = bool(type_id & _WEB_LOCATION_FLAG)
        has_file_reference = bool(type_id & _FILE_REFERENCE_FLAG)
        if has_web_location:
            return None

        offset = 8
        file_reference = b""
        if has_file_reference:
            first_byte = raw[offset]
            if first_byte < 254:
                ref_len = first_byte
                ref_start = offset + 1
                aligned_len = (1 + ref_len + 3) & ~3
            else:
                ref_len = raw[offset + 1] | (raw[offset + 2] << 8) | (raw[offset + 3] << 16)
                ref_start = offset + 4
                aligned_len = (4 + ref_len + 3) & ~3
            file_reference = raw[ref_start : ref_start + ref_len]
            offset += aligned_len

        if offset + 16 > len(raw):
            return None

        media_id, access_hash = struct.unpack("<qq", raw[offset : offset + 16])
        # file_type 0, 1, 2 = Photo/Thumbnail; 3..13 (including 8 = Sticker) = Document
        if file_type in (0, 1, 2):
            return types.InputPhoto(
                id=media_id,
                access_hash=access_hash,
                file_reference=file_reference,
            )
        return types.InputDocument(
            id=media_id,
            access_hash=access_hash,
            file_reference=file_reference,
        )
    except Exception:
        return None


def compute_next_run_iso(
    scenario: dict[str, Any],
    target: dict[str, Any],
    *,
    extra_delay_seconds: int = 0,
    now: datetime | None = None,
) -> str:
    current = now or datetime.now(UTC)
    base_interval = int(
        target.get("interval_override_seconds")
        or scenario.get("interval_seconds")
        or 1800
    )
    jitter_min = max(0, int(scenario.get("jitter_min_sec") or 0))
    jitter_max = max(jitter_min, int(scenario.get("jitter_max_sec") or 0))
    jitter = random.randint(jitter_min, jitter_max) if jitter_max > 0 else 0

    total_wait = max(5, base_interval + jitter + extra_delay_seconds)
    return (current + timedelta(seconds=total_wait)).replace(microsecond=0).isoformat()


def expand_scenario_destinations(
    store: DatabaseStore, scenario: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    Expands folder targets and individual chat targets for a scenario.
    Web Folders are 100% independent from Telegram native folders, allowing different
    scenarios to run on different Web Folders.
    """
    targets = [t for t in scenario.get("targets", []) if t.get("enabled", True)]
    expanded: list[dict[str, Any]] = []

    for t in targets:
        t_type = t.get("target_type")
        if t_type == "folder":
            folder = store.get_folder(int(t["target_id"]))
            if not folder or not folder.get("enabled", True):
                continue
            for fc in folder.get("chats", []):
                expanded.append(
                    {
                        "target_row_id": int(t["id"]),
                        "target_type": "folder",
                        "folder_id": int(folder["id"]),
                        "folder_name": folder["name"],
                        "chat_id": int(fc["chat_id"]),
                        "topic_id": int(fc.get("topic_id") or t.get("topic_id") or 0),
                        "override_step_order": t.get("override_step_order"),
                        "override_text_content": t.get("override_text_content"),
                        "interval_override_seconds": t.get("interval_override_seconds"),
                        "next_run_at": t.get("next_run_at"),
                    }
                )
        elif t_type == "chat":
            expanded.append(
                {
                    "target_row_id": int(t["id"]),
                    "target_type": "chat",
                    "folder_id": None,
                    "folder_name": None,
                    "chat_id": int(t["target_id"]),
                    "topic_id": int(t.get("topic_id") or 0),
                    "override_step_order": t.get("override_step_order"),
                    "override_text_content": t.get("override_text_content"),
                    "interval_override_seconds": t.get("interval_override_seconds"),
                    "next_run_at": t.get("next_run_at"),
                }
            )
    return expanded


class AutoSenderEngine:
    """
    Executes scheduled messaging scenarios across independent Web Folders and groups,
    applying the Hybrid Rule & Fallback Engine (Hướng 3), Spintax/Variables, Active Hours,
    Auto-Delete Previous Message, and Smart Membership-Aware Account Rotation.
    """

    def __init__(
        self,
        store: DatabaseStore,
        pool: TelegramClientPool,
        config: AppConfig,
        event_broadcaster: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self._store = store
        self._pool = pool
        self._config = config
        self._broadcaster = event_broadcaster
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _scheduler_loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("AutoSender tick error: %s", exc)
            await asyncio.sleep(self._config.auto_send_tick_seconds)

    async def tick(self) -> list[dict[str, Any]]:
        # Feature #17: Respect Global Panic / Kill Switch
        if self._store.is_global_paused():
            return []

        now_iso = datetime.now(UTC).replace(microsecond=0).isoformat()
        results: list[dict[str, Any]] = []
        scenarios = self._store.list_scenarios(enabled_only=True)

        for scenario in scenarios:
            # Feature #8: Check Active Hours / Quiet Hours window
            if not is_within_active_hours(
                scenario.get("active_hours_start"),
                scenario.get("active_hours_end"),
            ):
                continue

            targets = [t for t in scenario.get("targets", []) if t.get("enabled", True)]
            for target in targets:
                next_run = target.get("next_run_at")
                if next_run and next_run > now_iso:
                    continue
                res = await self.execute_scenario_target(scenario, target)
                results.extend(res)
        return results

    async def run_scenario_now(self, scenario_id: int) -> list[dict[str, Any]]:
        scenario = self._store.get_scenario(scenario_id)
        if not scenario:
            raise ValueError(f"Không tìm thấy kịch bản #{scenario_id}")
        results: list[dict[str, Any]] = []
        for target in scenario.get("targets", []):
            res = await self.execute_scenario_target(scenario, target, force=True)
            results.extend(res)
        return results

    def _select_steps_for_target(
        self, scenario: dict[str, Any], target: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], int]:
        steps = scenario.get("steps") or []
        if not steps:
            return [], 0

        override_order = target.get("override_step_order")
        if override_order is not None:
            matched = [s for s in steps if int(s.get("step_order", 0)) == int(override_order)]
            if matched:
                return matched, int(scenario.get("step_cursor") or 0)

        mode = scenario.get("selection_mode") or "sequential"
        cursor = int(scenario.get("step_cursor") or 0)
        if mode == "all_steps":
            return steps, cursor
        if mode == "random":
            return [random.choice(steps)], cursor

        selected = steps[cursor % len(steps)]
        next_cursor = (cursor + 1) % len(steps)
        return [selected], next_cursor

    async def execute_scenario_target(
        self,
        scenario: dict[str, Any],
        target: dict[str, Any],
        *,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        if not force and not is_within_active_hours(
            scenario.get("active_hours_start"),
            scenario.get("active_hours_end"),
        ):
            return []

        scenario_id = int(scenario["id"])
        target_row_id = int(target["id"])
        selected_steps, next_cursor = self._select_steps_for_target(scenario, target)
        if not selected_steps:
            return []

        temp_scenario = {**scenario, "targets": [target]}
        destinations = expand_scenario_destinations(self._store, temp_scenario)
        if not destinations:
            return []

        # Smart Anti-Spam: Shuffle destination order when sending to multiple groups
        # so accounts never hit groups in a robotic, deterministic timestamp sequence.
        is_multi_dest = len(destinations) > 1
        if is_multi_dest:
            random.shuffle(destinations)

        preferred_acc_id = scenario.get("sender_account_id")
        execution_records: list[dict[str, Any]] = []
        sent_counter = 0

        for dest_idx, dest in enumerate(destinations):
            chat_id = int(dest["chat_id"])
            topic_id = int(dest.get("topic_id") or 0)
            override_text = dest.get("override_text_content")

            # Feature #9 & #11: Pick a connected account within quota that is a member of `chat_id`
            try:
                picked = await self._pool.pick_any_authorized_client(
                    preferred_account_id=preferred_acc_id,
                    target_chat_id=chat_id,
                )
            except TypeError:
                picked = await self._pool.pick_any_authorized_client(preferred_acc_id)
            if not picked:
                log = self._store.add_execution_log(
                    category="auto_send",
                    level="WARN",
                    scenario_id=scenario_id,
                    chat_id=chat_id,
                    topic_id=topic_id,
                    status="failed",
                    message=(
                        f"Kịch bản '{scenario['name']}' tạm hoãn gửi tới nhóm {chat_id}: "
                        "Không có tài khoản nào kết nối hoặc tất cả đang tạm nghỉ chống Spam / chạm hạn mức Quota."
                    ),
                )
                execution_records.append(log)
                continue

            account_id, client = picked
            for step in selected_steps:
                rec = await self._send_step_to_chat(
                    client=client,
                    account_id=account_id,
                    scenario=scenario,
                    step=step,
                    chat_id=chat_id,
                    topic_id=topic_id,
                    override_text_content=override_text,
                    apply_hash_variation=is_multi_dest,
                )
                execution_records.append(rec)
                if rec.get("status") == "success":
                    sent_counter += 1

                if is_multi_dest and dest_idx < len(destinations) - 1:
                    is_real_tg = type(client).__name__ == "TelegramClient"
                    if is_real_tg:
                        # Adaptive Anti-Spam Pacing: 3.5s - 7.5s between groups, plus a 12-20s micro-break every 5 groups
                        delay_s = random.uniform(3.5, 7.5)
                        if (dest_idx + 1) % 5 == 0:
                            delay_s += random.uniform(12.0, 20.0)
                        await asyncio.sleep(delay_s)
                    else:
                        await asyncio.sleep(random.uniform(0.05, 0.15))

        next_run_iso = compute_next_run_iso(scenario, target)
        self._store.advance_scenario_target_schedule(
            scenario_id=scenario_id,
            target_row_id=target_row_id,
            next_run_iso=next_run_iso,
            step_cursor=next_cursor,
            sent_count_increment=sent_counter,
        )

        if self._broadcaster and execution_records:
            await self._broadcaster(
                {
                    "type": "auto_send_executed",
                    "data": {
                        "scenario_id": scenario_id,
                        "scenario_name": scenario["name"],
                        "sent_count": sent_counter,
                        "next_run_at": next_run_iso,
                    },
                }
            )
        return execution_records

    async def _count_messages_since_last_sent(
        self,
        *,
        client: Any,
        chat_id: int,
        topic_id: int,
        last_msg_id: int,
        max_limit: int = 200,
    ) -> int | None:
        """
        Counts how many messages have been posted in `chat_id` (and `topic_id` if > 0)
        since `last_msg_id`.
        """
        try:
            if hasattr(client, "iter_messages"):
                count = 0
                kwargs: dict[str, Any] = {"min_id": last_msg_id, "limit": max_limit + 5}
                if topic_id > 0:
                    kwargs["reply_to"] = topic_id
                try:
                    async for m in client.iter_messages(chat_id, **kwargs):
                        if int(getattr(m, "id", 0) or 0) > last_msg_id:
                            count += 1
                    return count
                except TypeError:
                    kwargs.pop("reply_to", None)
                    async for m in client.iter_messages(chat_id, **kwargs):
                        if int(getattr(m, "id", 0) or 0) > last_msg_id:
                            count += 1
                    return count

            if hasattr(client, "get_messages"):
                msgs = await client.get_messages(chat_id, min_id=last_msg_id, limit=max_limit + 5)
                if isinstance(msgs, (list, tuple)):
                    return sum(1 for m in msgs if int(getattr(m, "id", 0) or 0) > last_msg_id)
                if msgs is not None and hasattr(msgs, "id"):
                    return max(0, int(msgs.id) - last_msg_id)

            if hasattr(client, "latest_chat_msg_id"):
                return max(0, int(client.latest_chat_msg_id) - last_msg_id)

            if hasattr(client, "msg_counter"):
                return max(0, int(client.msg_counter) - last_msg_id)
        except Exception as exc:
            logger.debug("Không thể đo khoảng cách tin nhắn từ #%s tại nhóm %s: %s", last_msg_id, chat_id, exc)
        return None

    async def _maybe_delete_previous_message(
        self,
        *,
        client: Any,
        scenario: dict[str, Any],
        chat_id: int,
        topic_id: int,
        precomputed_distance: int | None = None,
    ) -> bool:
        scenario_id = int(scenario["id"])
        delete_always = bool(scenario.get("delete_previous_sent_message"))
        delete_within_x = int(scenario.get("delete_if_within_x_messages") or 0)
        if not delete_always and delete_within_x <= 0:
            return False

        prev = self._store.get_last_sent_message_for_scenario(scenario_id, chat_id, topic_id)
        if not prev or not prev.get("last_msg_id"):
            return False
        last_msg_id = int(prev["last_msg_id"])

        # If `delete_if_within_x_messages > 0`, only delete when distance <= X
        if delete_within_x > 0:
            dist = (
                precomputed_distance
                if precomputed_distance is not None
                else await self._count_messages_since_last_sent(
                    client=client,
                    chat_id=chat_id,
                    topic_id=topic_id,
                    last_msg_id=last_msg_id,
                    max_limit=delete_within_x + 10,
                )
            )
            if dist is not None and dist > delete_within_x:
                logger.info(
                    "Giữ lại tin cũ #%s tại nhóm %s vì đã cách %s tin nhắn (> ngưỡng %s tin)",
                    last_msg_id,
                    chat_id,
                    dist,
                    delete_within_x,
                )
                return False

        try:
            if hasattr(client, "delete_messages"):
                await client.delete_messages(chat_id, [last_msg_id])
                return True
        except Exception as exc:
            logger.debug("Không thể xóa tin nhắn cũ #%s trong nhóm %s: %s", last_msg_id, chat_id, exc)
        return False

    async def _simulate_human_typing(self, client: Any, chat_id: int, text: str | None) -> None:
        """
        Sends a realistic `SetTypingRequest` before dispatching a message on real Telethon
        clients so Telegram's behavioral anti-spam filter sees human-like typing activity.
        """
        if type(client).__name__ != "TelegramClient" or not callable(client):
            return
        try:
            await client(
                functions.messages.SetTypingRequest(
                    peer=chat_id,
                    action=types.SendMessageTypingAction(),
                )
            )
            char_len = len(text or "")
            typing_sec = min(2.4, max(0.8, char_len / 65.0))
            await asyncio.sleep(random.uniform(0.7, typing_sec))
        except Exception as exc:
            logger.debug("SetTypingRequest fallback: %s", exc)

    async def _send_step_to_chat(
        self,
        *,
        client: Any,
        account_id: int,
        scenario: dict[str, Any],
        step: dict[str, Any],
        chat_id: int,
        topic_id: int,
        override_text_content: str | None = None,
        apply_hash_variation: bool = False,
    ) -> dict[str, Any]:
        scenario_id = int(scenario["id"])
        attempted_action = str(step.get("action_type") or "send_text")
        chat_rule = self._store.get_chat_rule(chat_id)
        chat_info = self._store.get_chat_group(chat_id)
        account_info = self._store.get_account(account_id)

        render_ctx = {
            "chat_id": chat_id,
            "chat_title": (chat_info or {}).get("title") or f"Chat {chat_id}",
            "account_name": (account_info or {}).get("label") or f"Acc #{account_id}",
        }

        plan = resolve_execution_plan(
            step,
            chat_rule,
            override_text_content=override_text_content,
            render_context=render_ctx,
        )

        if plan.action_to_execute == "skip":
            return self._store.add_execution_log(
                category="auto_send",
                level="INFO",
                account_id=account_id,
                chat_id=chat_id,
                topic_id=topic_id,
                scenario_id=scenario_id,
                action_attempted=attempted_action,
                action_executed="skip",
                fallback_applied=True,
                fallback_reason=plan.fallback_reason_summary,
                status="skipped",
                message=f"Bỏ qua gửi tới nhóm {chat_id}: {plan.fallback_reason_summary}",
            )

        # Apply subtle anti-hash perturbation when sending across multiple groups
        if apply_hash_variation and plan.text_content:
            plan.text_content = apply_anti_spam_text_variation(plan.text_content, chat_id)

        # Smart Anti-Spam Distance Check (`skip_if_within_x_messages` & `delete_if_within_x_messages`)
        skip_within_x = int(scenario.get("skip_if_within_x_messages") or 0)
        delete_within_x = int(scenario.get("delete_if_within_x_messages") or 0)
        delete_always = bool(scenario.get("delete_previous_sent_message"))
        precomputed_dist: int | None = None

        if skip_within_x > 0 or delete_within_x > 0:
            prev_rec = self._store.get_last_sent_message_for_scenario(scenario_id, chat_id, topic_id)
            if prev_rec and prev_rec.get("last_msg_id"):
                prev_msg_id = int(prev_rec["last_msg_id"])
                precomputed_dist = await self._count_messages_since_last_sent(
                    client=client,
                    chat_id=chat_id,
                    topic_id=topic_id,
                    last_msg_id=prev_msg_id,
                    max_limit=max(skip_within_x, delete_within_x) + 10,
                )
                if skip_within_x > 0 and precomputed_dist is not None and precomputed_dist <= skip_within_x:
                    return self._store.add_execution_log(
                        category="auto_send",
                        level="INFO",
                        account_id=account_id,
                        chat_id=chat_id,
                        topic_id=topic_id,
                        scenario_id=scenario_id,
                        action_attempted=attempted_action,
                        action_executed="skip",
                        fallback_applied=True,
                        fallback_reason=f"Chưa trôi quá {skip_within_x} tin nhắn (hiện cách {precomputed_dist} tin)",
                        status="skipped",
                        message=(
                            f"Tạm bỏ qua gửi tới nhóm {chat_id}: Tin cũ #{prev_msg_id} mới cách hiện tại "
                            f"{precomputed_dist} tin nhắn (chưa vượt ngưỡng {skip_within_x} tin)."
                        ),
                    )

        # Feature #10 + Smart X-Message Distance Delete: Auto-Delete Previous Sent Message
        if delete_always or delete_within_x > 0:
            await self._maybe_delete_previous_message(
                client=client,
                scenario=scenario,
                chat_id=chat_id,
                topic_id=topic_id,
                precomputed_distance=precomputed_dist,
            )

        try:
            await self._simulate_human_typing(client, chat_id, plan.text_content)
            sent_msg_id = await self._dispatch_plan_via_telethon(
                client, chat_id, topic_id, plan, chat_rule.no_media
            )
            if sent_msg_id:
                self._store.record_last_sent_message_for_scenario(
                    scenario_id=scenario_id,
                    chat_id=chat_id,
                    topic_id=topic_id,
                    account_id=account_id,
                    last_msg_id=sent_msg_id,
                )
            return self._store.add_execution_log(
                category="auto_send",
                level="INFO",
                account_id=account_id,
                chat_id=chat_id,
                topic_id=topic_id,
                scenario_id=scenario_id,
                action_attempted=attempted_action,
                action_executed=plan.action_to_execute,
                fallback_applied=plan.fallback_applied,
                fallback_reason=plan.fallback_reason_summary,
                status="success",
                message=(
                    f"Đã gửi ({plan.action_to_execute}) tới nhóm {chat_id}"
                    + (f" [Fallback: {plan.fallback_reason_summary}]" if plan.fallback_applied else "")
                ),
            )
        except Exception as first_exc:
            learned = classify_telegram_error(first_exc)

            # 1) Account Session Expired -> Switch status to `need_login` immediately!
            if learned.session_expired:
                self._store.update_account_status(
                    account_id,
                    "need_login",
                    last_error=learned.reason_note or str(first_exc),
                )

            # 2) PeerFlood / FloodWait -> Quarantine account to protect from permanent Telegram ban!
            if learned.is_peer_flood or learned.flood_wait_seconds:
                wait_sec = int(learned.flood_wait_seconds or (10800 if learned.is_peer_flood else 60))
                self._store.quarantine_account_flood(
                    account_id,
                    wait_sec,
                    learned.reason_note or f"FloodWait/PeerFlood ({wait_sec}s)",
                    status="flood_wait",
                )

            # 3) Account muted/banned in this specific group -> Mark `can_send_messages=False`
            if learned.account_banned_in_chat:
                self._store.upsert_account_membership(
                    AccountMembershipModel(
                        account_id=account_id,
                        chat_id=chat_id,
                        role="restricted",
                        can_send_messages=False,
                        can_send_media=False,
                        can_send_stickers=False,
                        can_embed_links=False,
                    )
                )

            # 4) Instant Multi-Account Failover if current account had session/flood/ban issue
            if (
                learned.session_expired
                or learned.is_peer_flood
                or learned.flood_wait_seconds
                or learned.account_banned_in_chat
            ):
                try:
                    failover = await self._pool.pick_any_authorized_client(
                        preferred_account_id=None,
                        target_chat_id=chat_id,
                        exclude_account_ids={account_id},
                    )
                except TypeError:
                    failover = None

                if failover:
                    alt_acc_id, alt_client = failover
                    try:
                        await self._simulate_human_typing(alt_client, chat_id, plan.text_content)
                        sent_msg_id = await self._dispatch_plan_via_telethon(
                            alt_client, chat_id, topic_id, plan, chat_rule.no_media
                        )
                        if sent_msg_id:
                            self._store.record_last_sent_message_for_scenario(
                                scenario_id=scenario_id,
                                chat_id=chat_id,
                                topic_id=topic_id,
                                account_id=alt_acc_id,
                                last_msg_id=sent_msg_id,
                            )
                        failover_note = (
                            f"Tự động đảo sang Nick #{alt_acc_id} do Nick #{account_id} gặp sự cố "
                            f"({learned.reason_note or first_exc})"
                        )
                        return self._store.add_execution_log(
                            category="auto_send",
                            level="INFO",
                            account_id=alt_acc_id,
                            chat_id=chat_id,
                            topic_id=topic_id,
                            scenario_id=scenario_id,
                            action_attempted=attempted_action,
                            action_executed=plan.action_to_execute,
                            fallback_applied=True,
                            fallback_reason=failover_note,
                            status="success",
                            message=f"Đã gửi thành công tới {chat_id} nhờ Failover sang Nick #{alt_acc_id}",
                        )
                    except Exception as failover_exc:
                        first_exc = failover_exc

            # LAYER 2: Runtime Error Auto-Learn & Instant Fallback Retry
            if learned.learned_any_rule:
                updated_rule = self._store.auto_learn_chat_restriction(
                    chat_id,
                    no_links=learned.no_links,
                    no_stickers=learned.no_stickers,
                    no_forwards=learned.no_forwards,
                    no_media=learned.no_media,
                    no_bot_mentions=learned.no_bot_mentions,
                    slow_mode_seconds=learned.slow_mode_seconds,
                    reason_note=learned.reason_note,
                )
                retry_plan = resolve_execution_plan(
                    step,
                    updated_rule,
                    override_text_content=override_text_content,
                    render_context=render_ctx,
                )
                if retry_plan.action_to_execute != "skip":
                    try:
                        sent_msg_id = await self._dispatch_plan_via_telethon(
                            client, chat_id, topic_id, retry_plan, updated_rule.no_media
                        )
                        if sent_msg_id:
                            self._store.record_last_sent_message_for_scenario(
                                scenario_id=scenario_id,
                                chat_id=chat_id,
                                topic_id=topic_id,
                                account_id=account_id,
                                last_msg_id=sent_msg_id,
                            )
                        combined_reason = "; ".join(
                            filter(None, [learned.reason_note, retry_plan.fallback_reason_summary])
                        )
                        return self._store.add_execution_log(
                            category="auto_send",
                            level="INFO",
                            account_id=account_id,
                            chat_id=chat_id,
                            topic_id=topic_id,
                            scenario_id=scenario_id,
                            action_attempted=attempted_action,
                            action_executed=retry_plan.action_to_execute,
                            fallback_applied=True,
                            fallback_reason=combined_reason,
                            status="success",
                            message=f"Tự động học Rule & gửi lại thành công ({retry_plan.action_to_execute}) tới {chat_id}: {combined_reason}",
                        )
                    except Exception as second_exc:
                        first_exc = second_exc

            return self._store.add_execution_log(
                category="auto_send",
                level="ERROR",
                account_id=account_id,
                chat_id=chat_id,
                topic_id=topic_id,
                scenario_id=scenario_id,
                action_attempted=attempted_action,
                action_executed=plan.action_to_execute,
                fallback_applied=plan.fallback_applied,
                fallback_reason=learned.reason_note or plan.fallback_reason_summary,
                status="failed",
                message=f"Gửi thất bại tới nhóm {chat_id}: {learned.reason_note or first_exc}",
            )

    async def _dispatch_plan_via_telethon(
        self,
        client: Any,
        chat_id: int,
        topic_id: int,
        plan: ResolvedSendPlan,
        no_media: bool = False,
    ) -> int | None:
        reply_to = topic_id if topic_id > 0 else None
        action = plan.action_to_execute

        if action == "forward_message":
            if not plan.forward_from_chat_id or not plan.forward_from_msg_id:
                raise ValueError("Thiếu forward_from_chat_id hoặc forward_from_msg_id")
            sent = await client.forward_messages(
                entity=chat_id,
                messages=int(plan.forward_from_msg_id),
                from_peer=int(plan.forward_from_chat_id),
            )
            if isinstance(sent, list) and sent:
                return int(getattr(sent[0], "id", 0) or 0)
            return int(getattr(sent, "id", 0) or 0)

        if action == "copy_source_message":
            if not plan.forward_from_chat_id or not plan.forward_from_msg_id:
                raise ValueError("Thiếu nguồn để copy tin nhắn")
            src_msg = await client.get_messages(
                int(plan.forward_from_chat_id), ids=int(plan.forward_from_msg_id)
            )
            if not src_msg:
                raise ValueError("Không tìm thấy tin nhắn mẫu để copy")
            msg_text = plan.text_content or getattr(src_msg, "message", "") or ""
            if getattr(src_msg, "media", None) and not no_media:
                sent = await client.send_file(
                    entity=chat_id,
                    file=src_msg.media,
                    caption=msg_text or None,
                    reply_to=reply_to,
                )
            else:
                sent = await client.send_message(
                    entity=chat_id,
                    message=msg_text or "(Tin nhắn sao chép)",
                    reply_to=reply_to,
                    link_preview=plan.link_preview,
                )
            return int(getattr(sent, "id", 0) or 0)

        if action == "send_sticker":
            if not plan.sticker_id_or_path:
                raise ValueError("Thiếu sticker_id_or_path")
            return await self._resolve_and_send_file_or_sticker(
                client=client,
                chat_id=chat_id,
                raw_input=plan.sticker_id_or_path,
                caption=None,
                reply_to=reply_to,
            )

        if action == "send_media":
            if not plan.media_path:
                raise ValueError("Thiếu media_path")
            return await self._resolve_and_send_file_or_sticker(
                client=client,
                chat_id=chat_id,
                raw_input=plan.media_path,
                caption=plan.text_content or None,
                reply_to=reply_to,
            )

        # Default: send_text
        sent = await client.send_message(
            entity=chat_id,
            message=plan.text_content or "",
            reply_to=reply_to,
            link_preview=plan.link_preview,
        )
        return int(getattr(sent, "id", 0) or 0)

    async def _resolve_and_send_file_or_sticker(
        self,
        *,
        client: Any,
        chat_id: int,
        raw_input: str,
        caption: str | None,
        reply_to: int | None,
    ) -> int | None:
        cleaned = raw_input.strip()
        local_path = Path(cleaned)

        # 1. If `chat_id:msg_id` or `me:msg_id` reference (e.g. "me:42" or "-100123456:88")
        ref_match = _CHAT_MSG_REF_RE.match(cleaned)
        if ref_match and not local_path.exists():
            peer_raw, msg_id_raw = ref_match.group(1), int(ref_match.group(2))
            peer: int | str = int(peer_raw) if peer_raw.lstrip("-").isdigit() else peer_raw
            src_msg = await client.get_messages(peer, ids=msg_id_raw)
            if not src_msg or not getattr(src_msg, "media", None):
                raise ValueError(f"Không tìm thấy Sticker/Media tại tin nhắn nguồn {cleaned}")
            sent = await client.send_file(
                entity=chat_id,
                file=src_msg.media,
                caption=caption,
                reply_to=reply_to,
            )
            return int(getattr(sent, "id", 0) or 0)

        # 2. If not an existing local file, check if it's a Bot API v4 file_id (e.g. "CAACAgUAA...")
        file_target: Any = cleaned
        if not local_path.exists():
            decoded = decode_bot_api_file_id(cleaned)
            if decoded is not None:
                file_target = decoded

        try:
            sent = await client.send_file(
                entity=chat_id,
                file=file_target,
                caption=caption,
                reply_to=reply_to,
            )
            return int(getattr(sent, "id", 0) or 0)
        except Exception as exc:
            err_str = f"{type(exc).__name__}: {exc}".upper()
            # If file_reference in Bot API file_id expired, retry once with empty file_reference
            if isinstance(file_target, (types.InputDocument, types.InputPhoto)) and (
                "FILE_REFERENCE" in err_str or "MEDIA_EMPTY" in err_str
            ):
                try:
                    fallback_target = (
                        types.InputDocument(
                            id=file_target.id,
                            access_hash=file_target.access_hash,
                            file_reference=b"",
                        )
                        if isinstance(file_target, types.InputDocument)
                        else types.InputPhoto(
                            id=file_target.id,
                            access_hash=file_target.access_hash,
                            file_reference=b"",
                        )
                    )
                    sent = await client.send_file(
                        entity=chat_id,
                        file=fallback_target,
                        caption=caption,
                        reply_to=reply_to,
                    )
                    return int(getattr(sent, "id", 0) or 0)
                except Exception as retry_exc:
                    raise ValueError(
                        f"Telegram từ chối mã file_id '{cleaned[:24]}...' ({retry_exc}). "
                        "Lưu ý: Mã CAACAg... lấy từ Bot bên thứ 3 (@ShowJsonBot...) có access_hash riêng của Bot đó nên Userbot có thể bị chặn MEDIA_EMPTY. "
                        "Cách khắc phục 100%: Hãy gửi Sticker đó vào Saved Messages (hoặc 1 nhóm) rồi nhập 'me:ID_tin_nhắn' (VD: me:125), hoặc dùng đường dẫn file .webp/.tgs trên máy."
                    ) from retry_exc
            raise
