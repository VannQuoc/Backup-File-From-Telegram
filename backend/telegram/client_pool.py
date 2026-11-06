from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from telethon import TelegramClient, functions, types, utils
from telethon.errors import SessionPasswordNeededError

from backend.config import AppConfig
from backend.database.db import DatabaseStore
from backend.database.models import (
    AccountMembershipModel,
    ChatGroupUpsertRequest,
    ChatRuleModel,
    ChatRuleUpdateRequest,
    ChatTopicModel,
    FolderChatEntry,
    FolderCreateRequest,
)

logger = logging.getLogger(__name__)

INVITE_LINK_REGEX = re.compile(
    r"(?:t\.me/\+|t\.me/joinchat/|telegram\.me/\+|telegram\.me/joinchat/)([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)
USERNAME_LINK_REGEX = re.compile(
    r"(?:https?://)?(?:t\.me/|telegram\.me/)([a-zA-Z0-9_]{4,})",
    re.IGNORECASE,
)


def parse_proxy_url(proxy_url: str | None) -> dict[str, Any] | None:
    if not proxy_url or not proxy_url.strip():
        return None
    parsed = urlparse(proxy_url.strip())
    if not parsed.scheme or not parsed.hostname or not parsed.port:
        return None
    scheme = parsed.scheme.lower()
    proxy_type = "socks5"
    if "http" in scheme:
        proxy_type = "http"
    elif "socks4" in scheme:
        proxy_type = "socks4"
    return {
        "proxy_type": proxy_type,
        "addr": parsed.hostname,
        "port": int(parsed.port),
        "username": parsed.username,
        "password": parsed.password,
        "rdns": True,
    }


def _extract_dialog_filter_title(raw_title: Any) -> str:
    if raw_title is None:
        return "Telegram Folder"
    if isinstance(raw_title, str):
        return raw_title.strip() or "Telegram Folder"
    text_attr = getattr(raw_title, "text", None)
    if isinstance(text_attr, str) and text_attr.strip():
        return text_attr.strip()
    return str(raw_title).strip() or "Telegram Folder"


class TelegramClientPool:
    """Manages multiple Telethon client sessions, web OTP/2FA login flows, dialog/topic discovery, and smart rotation."""

    def __init__(self, store: DatabaseStore, config: AppConfig) -> None:
        self._store = store
        self._config = config
        self._clients: dict[int, TelegramClient] = {}
        self._pending_phone_hashes: dict[int, tuple[str, str]] = {}
        self._lock = asyncio.Lock()

    def _resolve_credentials(self, account: dict[str, Any]) -> tuple[int, str]:
        api_id = account.get("api_id") or self._config.default_tg_api_id
        api_hash = account.get("api_hash") or self._config.default_tg_api_hash
        if not api_id or not api_hash:
            raise ValueError(
                f"Tài khoản #{account['id']} ({account['label']}) thiếu API ID / API Hash. "
                "Vui lòng nhập trong phần cấu hình tài khoản hoặc đặt DEFAULT_TG_API_ID/HASH trong .env."
            )
        return int(api_id), str(api_hash)

    def _build_client(self, account: dict[str, Any]) -> TelegramClient:
        api_id, api_hash = self._resolve_credentials(account)
        session_path = Path(account["session_path"])
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_str = str(session_path.with_suffix(""))
        proxy = parse_proxy_url(account.get("proxy_url"))
        return TelegramClient(session_str, api_id, api_hash, proxy=proxy)

    async def connect_all_enabled(self) -> None:
        accounts = self._store.list_accounts(enabled_only=True)
        for acc in accounts:
            try:
                await self.connect_account(int(acc["id"]))
            except Exception as exc:
                logger.warning("Không thể kết nối account #%s: %s", acc["id"], exc)

    async def connect_account(self, account_id: int) -> dict[str, Any]:
        account = self._store.get_account(account_id)
        if not account:
            raise ValueError(f"Không tìm thấy tài khoản #{account_id}")

        async with self._lock:
            client = self._clients.get(account_id)
            if client is None:
                client = self._build_client(account)
                self._clients[account_id] = client

            if not client.is_connected():
                await client.connect()

            if await client.is_user_authorized():
                me = await client.get_me()
                self._store.update_account_status(
                    account_id,
                    "connected",
                    tg_user_id=getattr(me, "id", None),
                    tg_username=getattr(me, "username", None),
                    last_error=None,
                )
            else:
                self._store.update_account_status(
                    account_id,
                    "need_login",
                    last_error="Chưa đăng nhập phiên Telethon",
                )

        return self._store.get_account(account_id)  # type: ignore[return-value]

    async def disconnect_account(self, account_id: int) -> None:
        async with self._lock:
            client = self._clients.pop(account_id, None)
            self._pending_phone_hashes.pop(account_id, None)
            if client and client.is_connected():
                await client.disconnect()

    async def disconnect_all(self) -> None:
        account_ids = list(self._clients.keys())
        for acc_id in account_ids:
            await self.disconnect_account(acc_id)

    async def get_authorized_client(self, account_id: int) -> TelegramClient | None:
        account = self._store.get_account(account_id)
        if not account or not account.get("enabled"):
            return None
        client = self._clients.get(account_id)
        if client is None:
            try:
                await self.connect_account(account_id)
                client = self._clients.get(account_id)
            except Exception as exc:
                logger.warning("Lỗi kết nối account #%s: %s", account_id, exc)
                return None

        if client and client.is_connected() and await client.is_user_authorized():
            return client
        return None

    async def pick_any_authorized_client(
        self,
        preferred_account_id: int | None = None,
        target_chat_id: int | None = None,
    ) -> tuple[int, TelegramClient] | None:
        """
        Smart Account Rotation & Membership-Aware Failover:
        1. If `preferred_account_id` is specified, within quota, and connected -> use it.
        2. If `target_chat_id` is specified -> prioritize accounts known to be members (`can_send_messages=True`)
           and within quota, sorted by least messages sent in the last hour.
        3. Otherwise -> pick any connected account within quota.
        """
        if preferred_account_id is not None:
            within_quota, _ = self._store.is_account_within_quota(preferred_account_id)
            if within_quota:
                client = await self.get_authorized_client(preferred_account_id)
                if client:
                    return preferred_account_id, client

        if target_chat_id is not None:
            member_rows = self._store.get_member_accounts_for_chat(
                target_chat_id, require_send_permission=True
            )
            # Sort by least sent in last hour for balanced load rotation
            candidates: list[tuple[int, int]] = []
            for m in member_rows:
                acc_id = int(m["account_id"])
                within_quota, _ = self._store.is_account_within_quota(acc_id)
                if within_quota:
                    counts = self._store.get_account_send_counts(acc_id)
                    candidates.append((counts["sent_last_hour"], acc_id))
            candidates.sort(key=lambda x: x[0])
            for _, acc_id in candidates:
                client = await self.get_authorized_client(acc_id)
                if client:
                    return acc_id, client

        # Fallback: any enabled & connected account within quota
        all_enabled = self._store.list_accounts(enabled_only=True)
        for acc in all_enabled:
            acc_id = int(acc["id"])
            within_quota, _ = self._store.is_account_within_quota(acc_id)
            if not within_quota:
                continue
            client = await self.get_authorized_client(acc_id)
            if client:
                return acc_id, client
        return None

    # -------------------------------------------------------------------------
    # WEB OTP / 2FA LOGIN FLOW
    # -------------------------------------------------------------------------
    async def send_login_code(self, account_id: int, phone_override: str | None = None) -> dict[str, Any]:
        account = self._store.get_account(account_id)
        if not account:
            raise ValueError(f"Không tìm thấy tài khoản #{account_id}")

        phone = (phone_override or account["phone"]).strip()
        async with self._lock:
            client = self._clients.get(account_id)
            if client is None:
                client = self._build_client(account)
                self._clients[account_id] = client
            if not client.is_connected():
                await client.connect()

            if await client.is_user_authorized():
                me = await client.get_me()
                self._store.update_account_status(
                    account_id,
                    "connected",
                    tg_user_id=getattr(me, "id", None),
                    tg_username=getattr(me, "username", None),
                )
                return {
                    "status": "already_connected",
                    "message": "Tài khoản này đã được đăng nhập sẵn.",
                    "account": self._store.get_account(account_id),
                }

            sent = await client.send_code_request(phone)
            self._pending_phone_hashes[account_id] = (phone, sent.phone_code_hash)
            self._store.update_account_status(account_id, "otp_sent", last_error=None)
            return {
                "status": "otp_sent",
                "message": f"Đã gửi mã OTP tới số {phone}. Vui lòng nhập mã xác thực.",
                "account": self._store.get_account(account_id),
            }

    async def verify_login_code(
        self, account_id: int, code: str, password_2fa: str | None = None
    ) -> dict[str, Any]:
        account = self._store.get_account(account_id)
        if not account:
            raise ValueError(f"Không tìm thấy tài khoản #{account_id}")

        async with self._lock:
            client = self._clients.get(account_id)
            pending = self._pending_phone_hashes.get(account_id)
            if not client:
                raise ValueError("Chưa khởi tạo phiên đăng nhập. Hãy bấm 'Gửi mã OTP' trước.")

            if not client.is_connected():
                await client.connect()

            try:
                if pending:
                    phone, phone_code_hash = pending
                    await client.sign_in(
                        phone=phone,
                        code=code.strip(),
                        phone_code_hash=phone_code_hash,
                    )
                elif password_2fa:
                    await client.sign_in(password=password_2fa)
                else:
                    raise ValueError("Phiên OTP đã hết hạn. Vui lòng gửi lại mã OTP.")
            except SessionPasswordNeededError:
                if not password_2fa:
                    self._store.update_account_status(
                        account_id,
                        "need_2fa",
                        last_error="Tài khoản bật xác thực 2 lớp (2FA). Vui lòng nhập mật khẩu 2FA.",
                    )
                    return {
                        "status": "need_2fa",
                        "message": "Tài khoản yêu cầu mật khẩu 2FA (Two-Step Verification).",
                        "account": self._store.get_account(account_id),
                    }
                await client.sign_in(password=password_2fa)

            me = await client.get_me()
            self._pending_phone_hashes.pop(account_id, None)
            self._store.update_account_status(
                account_id,
                "connected",
                tg_user_id=getattr(me, "id", None),
                tg_username=getattr(me, "username", None),
                last_error=None,
            )
            self._store.add_execution_log(
                category="account",
                account_id=account_id,
                message=f"Đăng nhập thành công tài khoản {account['label']} (@{getattr(me, 'username', 'N/A')})",
            )
            return {
                "status": "connected",
                "message": "Đăng nhập thành công!",
                "account": self._store.get_account(account_id),
            }

    # -------------------------------------------------------------------------
    # DIALOG SCANNER, MEMBERSHIP EXPLORER & FORUM TOPIC INSPECTOR
    # -------------------------------------------------------------------------
    async def scan_account_dialogs(self, account_id: int, limit: int = 250) -> list[dict[str, Any]]:
        client = await self.get_authorized_client(account_id)
        if not client:
            raise ValueError(
                f"Tài khoản #{account_id} chưa kết nối hoặc chưa đăng nhập. Không thể quét nhóm."
            )

        discovered: list[dict[str, Any]] = []
        async for dialog in client.iter_dialogs(limit=limit):
            if not (dialog.is_group or dialog.is_channel):
                continue

            entity = dialog.entity
            chat_id = int(dialog.id)
            title = str(dialog.title or f"Chat {chat_id}")
            username = getattr(entity, "username", None)
            is_forum = bool(getattr(entity, "forum", False))
            is_megagroup = bool(getattr(entity, "megagroup", False))
            participants_count = int(getattr(entity, "participants_count", 0) or 0)
            if is_forum:
                chat_type = "forum"
            elif is_megagroup:
                chat_type = "supergroup"
            elif dialog.is_channel:
                chat_type = "channel"
            else:
                chat_type = "group"

            # Inspect banned rights, admin rights & noforwards directly from Telegram entity
            noforwards = bool(getattr(entity, "noforwards", False))
            default_banned = getattr(entity, "default_banned_rights", None)
            admin_banned = getattr(entity, "banned_rights", None)
            admin_rights = getattr(entity, "admin_rights", None)
            is_creator = bool(getattr(entity, "creator", False))
            is_broadcast = bool(getattr(entity, "broadcast", False))

            def _flag(
                attr: str,
                _def_banned: Any = default_banned,
                _adm_banned: Any = admin_banned,
            ) -> bool:
                return bool(
                    getattr(_def_banned, attr, False)
                    or getattr(_adm_banned, attr, False)
                )

            # Determine role and per-account permissions in this chat
            if is_creator:
                role = "creator"
            elif admin_rights is not None:
                role = "admin"
            elif admin_banned is not None and any(
                getattr(admin_banned, k, False)
                for k in ("send_messages", "send_media", "send_stickers", "embed_links")
            ):
                role = "restricted"
            else:
                role = "member"

            # In broadcast channels, only creators/admins with post_messages can send
            if is_broadcast and not is_megagroup:
                can_post = is_creator or bool(getattr(admin_rights, "post_messages", False))
                can_send_msg = can_post
                can_send_med = can_post
                can_send_stk = can_post
                can_embed = can_post
            else:
                can_send_msg = is_creator or admin_rights is not None or not _flag("send_messages")
                can_send_med = can_send_msg and (
                    is_creator or admin_rights is not None or not (_flag("send_media") or _flag("send_photos") or _flag("send_docs"))
                )
                can_send_stk = can_send_msg and (
                    is_creator or admin_rights is not None or not (_flag("send_stickers") or _flag("send_gifs"))
                )
                can_embed = can_send_msg and (
                    is_creator or admin_rights is not None or not _flag("embed_links")
                )

            existing_rule = self._store.get_chat_rule(chat_id)
            rule = ChatRuleModel(
                chat_id=chat_id,
                no_links=existing_rule.no_links or _flag("embed_links"),
                no_stickers=existing_rule.no_stickers or _flag("send_stickers") or _flag("send_gifs"),
                no_forwards=existing_rule.no_forwards or noforwards,
                no_media=existing_rule.no_media or _flag("send_media") or _flag("send_photos") or _flag("send_docs"),
                no_bot_mentions=existing_rule.no_bot_mentions or _flag("send_inline"),
                slow_mode_seconds=int(
                    getattr(entity, "slowmode_seconds", 0) or existing_rule.slow_mode_seconds or 0
                ),
                banned_words=existing_rule.banned_words,
                auto_learned=True,
                notes=existing_rule.notes,
            )

            self._store.upsert_chat_group(
                ChatGroupUpsertRequest(
                    chat_id=chat_id,
                    title=title,
                    username=username,
                    chat_type=chat_type,
                    is_forum=is_forum,
                    participants_count=participants_count,
                    discovered_by_account_id=account_id,
                    rules=rule,
                )
            )

            self._store.upsert_account_membership(
                AccountMembershipModel(
                    account_id=account_id,
                    chat_id=chat_id,
                    role=role,
                    can_send_messages=can_send_msg,
                    can_send_media=can_send_med,
                    can_send_stickers=can_send_stk,
                    can_embed_links=can_embed,
                    is_member=True,
                )
            )

            if is_forum:
                try:
                    await self.scan_chat_topics(account_id, chat_id, log_activity=False)
                except Exception as exc:
                    logger.debug("Không thể quét forum topics cho %s: %s", chat_id, exc)

            refreshed = self._store.get_chat_group(chat_id)
            if refreshed:
                discovered.append(refreshed)

        self._store.add_execution_log(
            category="scanner",
            account_id=account_id,
            message=f"Đã quét {len(discovered)} nhóm/kênh, quyền thành viên & Forum Topics từ tài khoản #{account_id}.",
        )
        return discovered

    async def scan_chat_topics(
        self, account_id: int, chat_id: int, *, log_activity: bool = True
    ) -> list[dict[str, Any]]:
        """Fetches Forum Topics for a supergroup/forum and stores them in `chat_topics`."""
        client = await self.get_authorized_client(account_id)
        if not client:
            picked = await self.pick_any_authorized_client(preferred_account_id=account_id, target_chat_id=chat_id)
            if not picked:
                raise ValueError("Chưa có tài khoản Telegram nào kết nối để quét Forum Topics.")
            account_id, client = picked

        topics: list[ChatTopicModel] = []
        try:
            entity = await client.get_input_entity(chat_id)
            res = await client(
                functions.channels.GetForumTopicsRequest(
                    channel=entity,
                    offset_date=None,
                    offset_id=0,
                    offset_topic=0,
                    limit=100,
                    q="",
                )
            )
            for t in getattr(res, "topics", []) or []:
                t_id = getattr(t, "id", None)
                if t_id is None:
                    continue
                topics.append(
                    ChatTopicModel(
                        chat_id=chat_id,
                        topic_id=int(t_id),
                        title=str(getattr(t, "title", None) or f"Topic #{t_id}"),
                        icon_color=getattr(t, "icon_color", None),
                        is_closed=bool(getattr(t, "closed", False)),
                        is_pinned=bool(getattr(t, "pinned", False)),
                    )
                )
        except Exception as exc:
            logger.debug("GetForumTopicsRequest fallback for chat %s: %s", chat_id, exc)

        # Ensure General Topic #1 is always present for Forum groups if none returned
        if not topics:
            topics.append(
                ChatTopicModel(
                    chat_id=chat_id,
                    topic_id=1,
                    title="General (Mặc định)",
                    is_closed=False,
                    is_pinned=True,
                )
            )

        saved_topics = self._store.upsert_chat_topics(chat_id, topics)
        if log_activity:
            self._store.add_execution_log(
                category="scanner",
                account_id=account_id,
                chat_id=chat_id,
                message=f"Đã đồng bộ {len(saved_topics)} Forum Topics cho nhóm {chat_id}.",
            )
        return saved_topics

    async def create_forum_topic(
        self,
        account_id: int | None,
        chat_id: int,
        title: str,
        icon_color: int | None = None,
    ) -> dict[str, Any]:
        """Creates a new Forum Topic inside `chat_id` on Telegram and saves it to SQLite."""
        picked = await self.pick_any_authorized_client(
            preferred_account_id=account_id, target_chat_id=chat_id
        )
        if not picked:
            raise ValueError("Chưa có tài khoản Telegram nào kết nối để tạo Topic.")
        used_acc_id, client = picked

        entity = await client.get_input_entity(chat_id)
        kwargs: dict[str, Any] = {
            "channel": entity,
            "title": title.strip(),
            "random_id": random.randint(1, 2_000_000_000),
        }
        if icon_color is not None:
            kwargs["icon_color"] = int(icon_color)

        updates = await client(functions.channels.CreateForumTopicRequest(**kwargs))
        new_topic_id: int | None = None
        for upd in getattr(updates, "updates", []) or []:
            msg_obj = getattr(upd, "message", None)
            if msg_obj is not None and getattr(msg_obj, "id", None):
                new_topic_id = int(msg_obj.id)
                break
            if getattr(upd, "id", None):
                new_topic_id = int(upd.id)
                break

        if new_topic_id is None:
            # Refresh topics from server to discover the newly created topic
            refreshed = await self.scan_chat_topics(used_acc_id, chat_id, log_activity=False)
            for item in refreshed:
                if item["title"].lower() == title.strip().lower():
                    return item
            new_topic_id = int( int(time.time()) % 100000 )

        topic_model = ChatTopicModel(
            chat_id=chat_id,
            topic_id=new_topic_id,
            title=title.strip(),
            icon_color=icon_color,
            is_closed=False,
            is_pinned=False,
        )
        self._store.upsert_chat_topics(chat_id, [topic_model])
        self._store.add_execution_log(
            category="scanner",
            account_id=used_acc_id,
            chat_id=chat_id,
            topic_id=new_topic_id,
            message=f"Đã tạo Forum Topic mới '{title.strip()}' (#{new_topic_id}) trong nhóm {chat_id}.",
        )
        return topic_model.model_dump()

    # -------------------------------------------------------------------------
    # IMPORT TELEGRAM NATIVE FOLDERS -> INDEPENDENT WEB FOLDERS
    # -------------------------------------------------------------------------
    async def import_telegram_folders(self, account_id: int) -> list[dict[str, Any]]:
        """
        Reads native Telegram folders (`GetDialogFiltersRequest`) from `account_id`
        and clones each folder into an INDEPENDENT Web Panel Folder (`folders` table).
        After import, Web Panel Folders can be edited freely without affecting Telegram.
        """
        client = await self.get_authorized_client(account_id)
        if not client:
            raise ValueError(f"Tài khoản #{account_id} chưa kết nối Telegram.")

        # Make sure dialogs are cached in SQLite so chat_ids exist
        existing_chats = {int(c["chat_id"]) for c in self._store.list_chat_groups()}
        if not existing_chats:
            await self.scan_account_dialogs(account_id, limit=250)
            existing_chats = {int(c["chat_id"]) for c in self._store.list_chat_groups()}

        raw_result = await client(functions.messages.GetDialogFiltersRequest())
        filters_list = getattr(raw_result, "filters", None)
        if filters_list is None and isinstance(raw_result, list):
            filters_list = raw_result
        filters_list = filters_list or []

        imported_folders: list[dict[str, Any]] = []
        palette = ["#10B981", "#F59E0B", "#3B82F6", "#EF4444", "#14B8A6"]

        for idx, flt in enumerate(filters_list):
            cls_name = type(flt).__name__
            if cls_name == "DialogFilterDefault":
                continue

            folder_title = _extract_dialog_filter_title(getattr(flt, "title", None))
            include_peers = list(getattr(flt, "include_peers", []) or []) + list(
                getattr(flt, "pinned_peers", []) or []
            )

            chat_items: list[FolderChatEntry] = []
            seen_ids: set[int] = set()
            for peer in include_peers:
                try:
                    peer_id = int(utils.get_peer_id(peer))
                except Exception as exc:
                    logger.debug("Bỏ qua peer không hợp lệ trong DialogFilter: %s", exc)
                    continue
                if peer_id >= 0:
                    # Skip private 1-on-1 user chats
                    continue
                if peer_id in seen_ids:
                    continue
                seen_ids.add(peer_id)

                if peer_id not in existing_chats:
                    self._store.upsert_chat_group(
                        ChatGroupUpsertRequest(
                            chat_id=peer_id,
                            title=f"Group {peer_id}",
                            chat_type="supergroup",
                            discovered_by_account_id=account_id,
                        )
                    )
                    existing_chats.add(peer_id)

                chat_items.append(FolderChatEntry(chat_id=peer_id, topic_id=0))

            if not chat_items:
                continue

            created = self._store.create_folder(
                FolderCreateRequest(
                    name=f"[TG #{account_id}] {folder_title}",
                    color=palette[idx % len(palette)],
                    description=(
                        f"Bản sao độc lập từ Folder Telegram '{folder_title}' của tài khoản #{account_id}. "
                        "Bạn có thể thêm/bớt nhóm hoặc gán kịch bản riêng mà không ảnh hưởng tới Telegram."
                    ),
                    enabled=True,
                    chats=chat_items,
                )
            )
            imported_folders.append(created)

        self._store.add_execution_log(
            category="scanner",
            account_id=account_id,
            message=f"Đã import {len(imported_folders)} Folder từ Telegram thành Folder độc lập trên Web Panel.",
        )
        return imported_folders

    # -------------------------------------------------------------------------
    # BULK JOIN & CLONE GROUP MEMBERSHIPS
    # -------------------------------------------------------------------------
    async def bulk_join_chats(
        self,
        account_id: int,
        *,
        links_or_usernames: list[str] | None = None,
        clone_from_account_id: int | None = None,
        delay_min_sec: float = 2.0,
        delay_max_sec: float = 5.0,
    ) -> dict[str, Any]:
        """
        Joins multiple public `@username` / `t.me/...` / `t.me/+invite` links,
        or clones public group memberships from another account.
        """
        client = await self.get_authorized_client(account_id)
        if not client:
            raise ValueError(f"Tài khoản #{account_id} chưa kết nối Telegram.")

        targets: list[str] = [s.strip() for s in (links_or_usernames or []) if s and s.strip()]
        if clone_from_account_id is not None:
            source_chats = self._store.list_chat_groups(account_id=clone_from_account_id)
            for ch in source_chats:
                uname = ch.get("username")
                if uname and str(uname).strip():
                    targets.append(f"@{str(uname).strip().lstrip('@')}")

        # Deduplicate while preserving order
        deduped_targets = list(dict.fromkeys(targets))
        joined: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []

        for idx, raw_target in enumerate(deduped_targets):
            try:
                invite_match = INVITE_LINK_REGEX.search(raw_target)
                if invite_match:
                    invite_hash = invite_match.group(1)
                    await client(functions.messages.ImportChatInviteRequest(hash=invite_hash))
                else:
                    uname_match = USERNAME_LINK_REGEX.search(raw_target)
                    clean_target = uname_match.group(1) if uname_match else raw_target.lstrip("@").strip()
                    await client(functions.channels.JoinChannelRequest(channel=clean_target))

                joined.append({"target": raw_target, "status": "joined"})
            except Exception as exc:
                failed.append({"target": raw_target, "error": str(exc)})

            if idx < len(deduped_targets) - 1:
                await asyncio.sleep(random.uniform(max(0.5, delay_min_sec), max(delay_min_sec, delay_max_sec)))

        if joined:
            try:
                await self.scan_account_dialogs(account_id, limit=250)
            except Exception as exc:
                logger.debug("Re-scan after bulk join warning: %s", exc)

        self._store.add_execution_log(
            category="account",
            account_id=account_id,
            message=f"Bulk Join hoàn tất cho tài khoản #{account_id}: Thành công {len(joined)}, lỗi {len(failed)}.",
        )
        return {
            "account_id": account_id,
            "total_targets": len(deduped_targets),
            "joined_count": len(joined),
            "failed_count": len(failed),
            "joined": joined,
            "failed": failed,
        }

    # -------------------------------------------------------------------------
    # VISUAL MESSAGE PICKER (BROWSE RECENT CHAT MESSAGES)
    # -------------------------------------------------------------------------
    async def get_recent_chat_messages(
        self,
        chat_id: int,
        account_id: int | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """
        Fetches recent messages from `chat_id` so the user can visually pick a message
        for Forwarding/Copying in Scenarios without manually finding `msg_id`.
        """
        picked = await self.pick_any_authorized_client(
            preferred_account_id=account_id, target_chat_id=chat_id
        )
        if not picked:
            raise ValueError("Chưa có tài khoản Telegram nào kết nối để đọc tin nhắn mẫu.")
        _, client = picked

        items: list[dict[str, Any]] = []
        async for msg in client.iter_messages(chat_id, limit=min(max(limit, 1), 100)):
            text = str(getattr(msg, "message", "") or getattr(msg, "text", "") or "").strip()
            has_media = getattr(msg, "media", None) is not None
            media_label = "text"
            if getattr(msg, "photo", None) is not None:
                media_label = "photo"
            elif getattr(msg, "sticker", None) is not None:
                media_label = "sticker"
            elif getattr(msg, "video", None) is not None:
                media_label = "video"
            elif has_media:
                media_label = "document"

            if not text and not has_media:
                continue

            msg_date = getattr(msg, "date", None)
            date_iso = msg_date.isoformat() if hasattr(msg_date, "isoformat") else None
            items.append(
                {
                    "msg_id": int(msg.id),
                    "chat_id": int(chat_id),
                    "date": date_iso,
                    "media_type": media_label,
                    "text_preview": (text[:160] + "…") if len(text) > 160 else (text or f"[{media_label.upper()}]"),
                    "full_text": text,
                }
            )
        return items

    # -------------------------------------------------------------------------
    # ACCOUNT HEALTH & QUOTA MONITOR
    # -------------------------------------------------------------------------
    async def check_account_health(self, account_id: int) -> dict[str, Any]:
        """Checks connection latency, authorization status, FloodWait state, and quota usage."""
        account = self._store.get_account(account_id)
        if not account:
            raise ValueError(f"Không tìm thấy tài khoản #{account_id}")

        start_ts = time.perf_counter()
        authorized = False
        latency_ms: int | None = None
        username: str | None = account.get("tg_username")
        user_id: int | None = account.get("tg_user_id")
        error_note: str | None = None

        try:
            client = await self.get_authorized_client(account_id)
            if client:
                me = await client.get_me()
                latency_ms = int((time.perf_counter() - start_ts) * 1000)
                authorized = True
                username = getattr(me, "username", None)
                user_id = getattr(me, "id", None)
                self._store.update_account_status(
                    account_id,
                    "connected",
                    tg_user_id=user_id,
                    tg_username=username,
                    last_error=None,
                )
            else:
                error_note = "Chưa kết nối hoặc phiên đăng nhập hết hạn"
        except Exception as exc:
            error_note = str(exc)

        now_iso = datetime.now(UTC).replace(microsecond=0).isoformat()
        with self._store.transaction() as conn:
            conn.execute(
                "UPDATE accounts SET health_check_at = ? WHERE id = ?",
                (now_iso, account_id),
            )

        within_quota, quota_reason = self._store.is_account_within_quota(account_id)
        counts = self._store.get_account_send_counts(account_id)
        refreshed = self._store.get_account(account_id) or account

        return {
            "account_id": account_id,
            "label": refreshed["label"],
            "authorized": authorized,
            "status": refreshed["status"],
            "latency_ms": latency_ms,
            "tg_user_id": user_id,
            "tg_username": username,
            "within_quota": within_quota,
            "quota_note": quota_reason,
            "sent_last_hour": counts["sent_last_hour"],
            "sent_last_24h": counts["sent_last_24h"],
            "max_messages_per_hour": refreshed.get("max_messages_per_hour", 60),
            "max_messages_per_day": refreshed.get("max_messages_per_day", 500),
            "joined_groups_count": refreshed.get("joined_groups_count", 0),
            "checked_at": now_iso,
            "error": error_note,
        }

    # -------------------------------------------------------------------------
    # RELOAD / SYNC ALL CONNECTED ACCOUNTS DIALOGS
    # -------------------------------------------------------------------------
    async def scan_all_connected_accounts_dialogs(
        self, limit_per_account: int = 250
    ) -> dict[str, Any]:
        """Scans dialogs across all enabled & connected accounts to refresh group list."""
        accounts = self._store.list_accounts(enabled_only=True)
        scanned_accounts = 0
        total_discovered = 0
        errors: list[dict[str, Any]] = []

        for acc in accounts:
            acc_id = int(acc["id"])
            client = await self.get_authorized_client(acc_id)
            if not client:
                continue
            try:
                groups = await self.scan_account_dialogs(acc_id, limit=limit_per_account)
                scanned_accounts += 1
                total_discovered += len(groups)
            except Exception as exc:
                errors.append({"account_id": acc_id, "label": acc["label"], "error": str(exc)})

        all_chats = self._store.list_chat_groups()
        return {
            "scanned_accounts": scanned_accounts,
            "total_discovered": total_discovered,
            "total_groups_in_db": len(all_chats),
            "errors": errors,
            "chats": all_chats,
        }

    # -------------------------------------------------------------------------
    # 1,000-MESSAGE HISTORY PERMISSION ANALYZER (NORMAL USER CAPABILITY DETECTOR)
    # -------------------------------------------------------------------------
    async def analyze_chat_member_permissions_from_history(
        self,
        chat_id: int,
        account_id: int | None = None,
        limit: int = 1000,
        auto_apply_unlock: bool = True,
        strict_infer_blocks: bool = False,
    ) -> dict[str, Any]:
        """
        Scans up to `limit` (default 1000) recent messages in `chat_id`, filtering out
        Admins, Channel posts, and Bots, to see what NORMAL members actually send:
        - Links (`http://`, `https://`, `t.me/`, URL entities)
        - Forwards (`fwd_from` / `forward`)
        - Stickers (`sticker` / `DocumentAttributeSticker`)
        - Media (`photo`, `video`, `document`, `audio`, `voice`)
        - Bot mentions / Inline bots (`@xxxbot` or `via_bot_id`)
        If normal users can send these without being deleted, our accounts can too!
        """
        picked = await self.pick_any_authorized_client(
            preferred_account_id=account_id,
            target_chat_id=chat_id,
        )
        if not picked:
            raise ValueError(
                f"Không có tài khoản nào đang kết nối để quét lịch sử nhóm {chat_id}."
            )
        used_acc_id, client = picked

        # 1. Identify Admin / Creator IDs so we don't mistake Admin privileges for normal users
        admin_ids: set[int] = set()
        if hasattr(client, "iter_participants"):
            try:
                async for p in client.iter_participants(
                    chat_id, filter=types.ChannelParticipantsAdmins()
                ):
                    pid = getattr(p, "id", None)
                    if pid is not None:
                        admin_ids.add(int(pid))
            except Exception as exc:
                logger.debug("Không lấy được danh sách Admin nhóm %s: %s", chat_id, exc)

        # Also check our own known memberships in DB for admin/creator roles
        for mem in self._store.get_chat_memberships(chat_id):
            if mem.get("role") in ("creator", "admin"):
                acc_row = self._store.get_account(int(mem["account_id"]))
                if acc_row and acc_row.get("tg_user_id"):
                    admin_ids.add(int(acc_row["tg_user_id"]))

        url_re = re.compile(r"(?:https?://|t\.me/|telegram\.me/|www\.)\S+", re.IGNORECASE)
        bot_mention_re = re.compile(r"@[a-zA-Z0-9_]{3,}bot\b", re.IGNORECASE)

        clamped_limit = min(max(int(limit), 10), 3000)
        total_scanned = 0
        admin_or_bot_skipped = 0
        normal_user_messages = 0
        unique_normal_users: set[int] = set()

        links_count = 0
        forwards_count = 0
        stickers_count = 0
        media_count = 0
        bot_mentions_count = 0

        async for msg in client.iter_messages(chat_id, limit=clamped_limit):
            if getattr(msg, "action", None) is not None:
                continue
            total_scanned += 1

            # Skip channel posts or anonymous admin posts
            if getattr(msg, "post", False):
                admin_or_bot_skipped += 1
                continue

            sender = getattr(msg, "sender", None)
            sender_id = getattr(msg, "sender_id", None)
            if sender_id is None and sender is not None:
                sender_id = getattr(sender, "id", None)

            # Skip Bots and Channel identities
            if sender is not None and (
                getattr(sender, "bot", False) or isinstance(sender, types.Channel)
            ):
                admin_or_bot_skipped += 1
                continue

            if sender_id is not None:
                sid = int(sender_id)
                if sid < 0 or sid in admin_ids:
                    admin_or_bot_skipped += 1
                    continue
                unique_normal_users.add(sid)

            # Also check if message itself is marked as from an admin via from_id
            if bool(getattr(msg, "is_admin", False)):
                admin_or_bot_skipped += 1
                continue

            normal_user_messages += 1
            text = str(getattr(msg, "message", "") or getattr(msg, "text", "") or "")

            # 1) Check Link
            has_link = bool(url_re.search(text))
            if not has_link:
                entities = getattr(msg, "entities", None) or []
                for ent in entities:
                    ent_cls = type(ent).__name__
                    if ent_cls in ("MessageEntityUrl", "MessageEntityTextUrl"):
                        has_link = True
                        break
            if has_link:
                links_count += 1

            # 2) Check Forward
            if getattr(msg, "fwd_from", None) is not None or getattr(msg, "forward", None) is not None:
                forwards_count += 1

            # 3) Check Sticker vs Media
            is_sticker = getattr(msg, "sticker", None) is not None
            msg_media = getattr(msg, "media", None)
            if not is_sticker and msg_media is not None:
                doc = getattr(msg_media, "document", None)
                if doc is not None:
                    for attr in getattr(doc, "attributes", []) or []:
                        if type(attr).__name__ == "DocumentAttributeSticker":
                            is_sticker = True
                            break

            if is_sticker:
                stickers_count += 1
            else:
                has_real_media = (
                    getattr(msg, "photo", None) is not None
                    or getattr(msg, "video", None) is not None
                    or getattr(msg, "document", None) is not None
                    or getattr(msg, "audio", None) is not None
                    or getattr(msg, "voice", None) is not None
                    or (
                        msg_media is not None
                        and type(msg_media).__name__ not in ("MessageMediaWebPage", "MessageMediaEmpty")
                    )
                )
                if has_real_media:
                    media_count += 1

            # 4) Check Bot Mentions / Inline Bot (`via_bot_id` or `@...bot`)
            has_bot_tag = (
                getattr(msg, "via_bot_id", None) is not None
                or getattr(msg, "via_bot", None) is not None
                or bool(bot_mention_re.search(text))
            )
            if has_bot_tag:
                bot_mentions_count += 1

        observed_permissions = {
            "can_send_links": links_count > 0,
            "can_forward": forwards_count > 0,
            "can_send_stickers": stickers_count > 0,
            "can_send_media": media_count > 0,
            "can_mention_bots": bot_mentions_count > 0,
        }

        rule = self._store.get_chat_rule(chat_id)
        unlocked_list: list[str] = []
        restricted_list: list[str] = []

        new_no_links = rule.no_links
        new_no_forwards = rule.no_forwards
        new_no_stickers = rule.no_stickers
        new_no_media = rule.no_media
        new_no_bot_mentions = rule.no_bot_mentions

        if auto_apply_unlock:
            if links_count > 0 and new_no_links:
                new_no_links = False
                unlocked_list.append(f"Mở khoá Gửi Link ({links_count} tin có link)")
            if forwards_count > 0 and new_no_forwards:
                new_no_forwards = False
                unlocked_list.append(f"Mở khoá Forward ({forwards_count} tin forward)")
            if stickers_count > 0 and new_no_stickers:
                new_no_stickers = False
                unlocked_list.append(f"Mở khoá Sticker ({stickers_count} sticker)")
            if media_count > 0 and new_no_media:
                new_no_media = False
                unlocked_list.append(f"Mở khoá Media ({media_count} media)")
            if bot_mentions_count > 0 and new_no_bot_mentions:
                new_no_bot_mentions = False
                unlocked_list.append(f"Mở khoá Tag Bot ({bot_mentions_count} lần tag/via bot)")

        if strict_infer_blocks and normal_user_messages >= 30:
            if links_count == 0 and not new_no_links:
                new_no_links = True
                restricted_list.append("Khoá Gửi Link (0 link trong lịch sử member)")
            if forwards_count == 0 and not new_no_forwards:
                new_no_forwards = True
                restricted_list.append("Khoá Forward (0 forward trong lịch sử member)")
            if stickers_count == 0 and not new_no_stickers:
                new_no_stickers = True
                restricted_list.append("Khoá Sticker (0 sticker trong lịch sử member)")
            if bot_mentions_count == 0 and not new_no_bot_mentions:
                new_no_bot_mentions = True
                restricted_list.append("Khoá Tag Bot (0 bot tag trong lịch sử member)")

        summary_note = (
            f"[Quét {total_scanned} tin ({normal_user_messages} tin member): "
            f"Link={links_count}, Fwd={forwards_count}, Sticker={stickers_count}, "
            f"Media={media_count}, BotTag={bot_mentions_count}]"
        )

        if auto_apply_unlock or strict_infer_blocks:
            existing_notes = (rule.notes or "").strip()
            # Remove previous `[Quét ...]` note if any
            cleaned_notes = re.sub(r"\[Quét \d+ tin[^\]]*\]", "", existing_notes).strip("; ").strip()
            combined_notes = f"{cleaned_notes}; {summary_note}".strip("; ").strip()
            updated_rule_dict = self._store.update_chat_rule(
                chat_id,
                ChatRuleUpdateRequest(
                    no_links=new_no_links,
                    no_stickers=new_no_stickers,
                    no_forwards=new_no_forwards,
                    no_media=new_no_media,
                    no_bot_mentions=new_no_bot_mentions,
                    slow_mode_seconds=rule.slow_mode_seconds,
                    banned_words=rule.banned_words,
                    notes=combined_notes,
                ),
            )
            # Also update member permissions if unlocked
            for mem in self._store.get_chat_memberships(chat_id):
                self._store.upsert_account_membership(
                    AccountMembershipModel(
                        account_id=int(mem["account_id"]),
                        chat_id=chat_id,
                        role=str(mem.get("role") or "member"),
                        can_send_messages=bool(mem.get("can_send_messages", True)),
                        can_send_media=True if media_count > 0 else bool(mem.get("can_send_media", True)),
                        can_send_stickers=True if stickers_count > 0 else bool(mem.get("can_send_stickers", True)),
                        can_embed_links=True if links_count > 0 else bool(mem.get("can_embed_links", True)),
                    )
                )
        else:
            updated_rule_dict = rule.model_dump()

        self._store.add_execution_log(
            category="system",
            level="INFO",
            account_id=used_acc_id,
            chat_id=chat_id,
            status="success",
            message=(
                f"Đã phân tích {total_scanned} tin nhắn gần nhất nhóm {chat_id}: "
                f"{summary_note}"
                + (f" -> {', '.join(unlocked_list)}" if unlocked_list else "")
            ),
        )

        return {
            "chat_id": chat_id,
            "scanned_by_account_id": used_acc_id,
            "limit_requested": clamped_limit,
            "total_messages_scanned": total_scanned,
            "admin_or_bot_messages_skipped": admin_or_bot_skipped,
            "normal_user_messages": normal_user_messages,
            "unique_normal_users_count": len(unique_normal_users),
            "admins_detected_count": len(admin_ids),
            "observed_counts": {
                "links": links_count,
                "forwards": forwards_count,
                "stickers": stickers_count,
                "media": media_count,
                "bot_mentions": bot_mentions_count,
            },
            "inferred_normal_user_permissions": observed_permissions,
            "unlocked_permissions": unlocked_list,
            "inferred_restrictions": restricted_list,
            "updated_rule": updated_rule_dict,
            "summary": summary_note,
        }
