from __future__ import annotations

import random
import re
import string
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.database.models import ChatRuleModel, FallbackPolicyConfig

URL_REGEX = re.compile(
    r"(?:https?://|www\.|t\.me/|telegram\.me/)[^\s<>\"']+"
    r"|\b[a-zA-Z0-9.-]+\.(?:com|net|org|io|me|vn|xyz|info|biz|co|app|dev)(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)

BOT_MENTION_REGEX = re.compile(r"@[a-zA-Z0-9_]*bot\b", re.IGNORECASE)

SPINTAX_PATTERN = re.compile(r"\{([^{}]*\|[^{}]*)\}")


def render_spintax_and_variables(
    text: str | None,
    context: dict[str, Any] | None = None,
) -> str:
    """
    Renders Spintax `{Option A|Option B|Option C}` and dynamic variables:
    `{chat_title}`, `{chat_id}`, `{date}`, `{time}`, `{random_id}`, `{account_name}`.
    """
    if not text:
        return ""

    ctx = context or {}
    now = datetime.now()
    rand_token = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

    rendered = text
    # 1. Resolve dynamic variables first
    replacements = {
        "{chat_title}": str(ctx.get("chat_title") or f"Chat {ctx.get('chat_id', '')}").strip(),
        "{chat_id}": str(ctx.get("chat_id") or ""),
        "{account_name}": str(ctx.get("account_name") or ""),
        "{date}": str(ctx.get("date") or now.strftime("%Y-%m-%d")),
        "{time}": str(ctx.get("time") or now.strftime("%H:%M")),
        "{random_id}": str(ctx.get("random_id") or rand_token),
    }
    for key, val in replacements.items():
        if key in rendered:
            rendered = rendered.replace(key, val)

    # 2. Resolve Spintax `{a|b|c}` (supports nested blocks up to 10 levels)
    for _ in range(10):
        if not SPINTAX_PATTERN.search(rendered):
            break
        rendered = SPINTAX_PATTERN.sub(
            lambda m: random.choice([part for part in m.group(1).split("|")]),
            rendered,
        )

    return rendered


def is_within_active_hours(
    start_hhmm: str | None,
    end_hhmm: str | None,
    now_dt: datetime | None = None,
) -> bool:
    """
    Checks whether `now_dt` (local time by default) falls within `[start_hhmm, end_hhmm]`.
    Supports standard windows (e.g. `07:30` -> `22:30`) and overnight windows (`22:00` -> `06:00`).
    Returns True if either bound is empty/None.
    """
    if not start_hhmm or not end_hhmm:
        return True
    s_clean = start_hhmm.strip()
    e_clean = end_hhmm.strip()
    if not s_clean or not e_clean:
        return True
    try:
        s_parts = [int(p) for p in s_clean.split(":")]
        e_parts = [int(p) for p in e_clean.split(":")]
        start_minutes = s_parts[0] * 60 + (s_parts[1] if len(s_parts) > 1 else 0)
        end_minutes = e_parts[0] * 60 + (e_parts[1] if len(e_parts) > 1 else 0)
    except (ValueError, IndexError):
        return True

    current = now_dt or datetime.now()
    current_minutes = current.hour * 60 + current.minute

    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes <= end_minutes
    # Overnight window (e.g. 22:00 to 06:00)
    return current_minutes >= start_minutes or current_minutes <= end_minutes


def contains_links(text: str | None) -> bool:
    if not text:
        return False
    return bool(URL_REGEX.search(text))


def strip_links_from_text(text: str | None) -> str:
    if not text:
        return ""
    cleaned = URL_REGEX.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def mask_links_in_text(text: str | None) -> str:
    if not text:
        return ""

    def _mask(match: re.Match[str]) -> str:
        raw = match.group(0)
        raw = re.sub(r"^https?://", "", raw, flags=re.IGNORECASE)
        return raw.replace(".", "[.]")

    return URL_REGEX.sub(_mask, text).strip()


def contains_bot_mentions(text: str | None, via_bot_username: str | None = None) -> bool:
    if via_bot_username:
        return True
    if not text:
        return False
    return bool(BOT_MENTION_REGEX.search(text))


def strip_bot_mentions_from_text(text: str | None) -> str:
    if not text:
        return ""
    cleaned = BOT_MENTION_REGEX.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def strip_banned_words(text: str | None, banned_words: list[str]) -> tuple[str, bool]:
    if not text or not banned_words:
        return text or "", False
    modified = text
    changed = False
    for word in banned_words:
        w = word.strip()
        if not w:
            continue
        pattern = re.compile(re.escape(w), re.IGNORECASE)
        if pattern.search(modified):
            modified = pattern.sub("***", modified)
            changed = True
    return modified.strip(), changed


@dataclass
class ResolvedSendPlan:
    action_to_execute: str  # "send_text" | "send_media" | "send_sticker" | "forward_message" | "copy_source_message" | "skip"
    text_content: str | None = None
    media_path: str | None = None
    sticker_id_or_path: str | None = None
    forward_from_chat_id: int | None = None
    forward_from_msg_id: int | None = None
    via_bot_username: str | None = None
    link_preview: bool = True
    fallback_applied: bool = False
    fallback_reasons: list[str] = field(default_factory=list)

    @property
    def fallback_reason_summary(self) -> str | None:
        return "; ".join(self.fallback_reasons) if self.fallback_reasons else None


def resolve_execution_plan(
    step: dict[str, Any],
    chat_rule: ChatRuleModel,
    *,
    override_text_content: str | None = None,
    render_context: dict[str, Any] | None = None,
) -> ResolvedSendPlan:
    """
    Hybrid Rule & Fallback Resolver (Hướng 3):
    Combines automatic content transformation based on ChatRule with user-provided fallback texts,
     plus Spintax `{A|B|C}` and dynamic variable rendering.
    """
    policy_raw = step.get("fallback_policy") or {}
    policy = (
        policy_raw
        if isinstance(policy_raw, FallbackPolicyConfig)
        else FallbackPolicyConfig.model_validate(policy_raw)
    )

    action = str(step.get("action_type") or "send_text")
    text = (
        override_text_content
        if override_text_content is not None
        else step.get("text_content")
    )
    media_path = step.get("media_path")
    sticker = step.get("sticker_id_or_path")
    fwd_chat_id = step.get("forward_from_chat_id")
    fwd_msg_id = step.get("forward_from_msg_id")
    via_bot = step.get("via_bot_username")

    reasons: list[str] = []

    # 1. Handle Forward restriction (`no_forwards`)
    if action == "forward_message" and chat_rule.no_forwards:
        if policy.on_no_forwards == "copy_content":
            if fwd_chat_id and fwd_msg_id:
                action = "copy_source_message"
                reasons.append("Nhóm cấm Forward -> Chuyển sang Copy/Gửi lại nội dung gốc")
            elif policy.fallback_text or text:
                action = "send_text"
                text = policy.fallback_text or text
                reasons.append("Nhóm cấm Forward -> Dùng văn bản dự phòng")
            else:
                return ResolvedSendPlan(
                    action_to_execute="skip",
                    fallback_applied=True,
                    fallback_reasons=["Nhóm cấm Forward và không có nguồn copy/text dự phòng"],
                )
        elif policy.on_no_forwards == "use_fallback_text":
            fallback_txt = policy.fallback_text or text
            if fallback_txt:
                action = "send_text"
                text = fallback_txt
                reasons.append("Nhóm cấm Forward -> Chuyển sang gửi Text dự phòng")
            else:
                return ResolvedSendPlan(
                    action_to_execute="skip",
                    fallback_applied=True,
                    fallback_reasons=["Nhóm cấm Forward nhưng chưa cấu hình fallback_text"],
                )
        else:
            return ResolvedSendPlan(
                action_to_execute="skip",
                fallback_applied=True,
                fallback_reasons=["Nhóm cấm Forward -> Bỏ qua theo cấu hình"],
            )

    # 2. Handle Sticker restriction (`no_stickers`)
    if action == "send_sticker" and chat_rule.no_stickers:
        if policy.on_no_stickers == "use_fallback_text" and (policy.fallback_text or text):
            action = "send_text"
            text = policy.fallback_text or text
            sticker = None
            reasons.append("Nhóm cấm Sticker -> Chuyển sang gửi Text dự phòng")
        else:
            return ResolvedSendPlan(
                action_to_execute="skip",
                fallback_applied=True,
                fallback_reasons=["Nhóm cấm Sticker -> Bỏ qua bước gửi Sticker"],
            )

    # 3. Handle Media restriction (`no_media`)
    if action in ("send_media", "copy_source_message") and chat_rule.no_media:
        if policy.on_no_media == "use_fallback_text" and (policy.fallback_text or text):
            action = "send_text"
            text = policy.fallback_text or text
            media_path = None
            reasons.append("Nhóm cấm Media/Ảnh/File -> Chuyển sang gửi Text thuần")
        elif action == "copy_source_message":
            reasons.append("Nhóm cấm Media -> Chỉ copy phần văn bản từ tin nhắn mẫu")
        else:
            return ResolvedSendPlan(
                action_to_execute="skip",
                fallback_applied=True,
                fallback_reasons=["Nhóm cấm Media và không có Text dự phòng"],
            )

    # Render Spintax & dynamic variables before link/bot/word checks so generated text is also sanitized
    if text:
        text = render_spintax_and_variables(text, render_context)

    # 4. Handle Bot Mention / Inline Bot restriction (`no_bot_mentions`)
    if chat_rule.no_bot_mentions and contains_bot_mentions(text, via_bot):
        if policy.on_no_bot_mentions == "strip_bot_mentions":
            if via_bot:
                via_bot = None
                reasons.append("Nhóm cấm Tag/Inline Bot -> Bỏ gửi qua via_bot")
            if text and BOT_MENTION_REGEX.search(text):
                text = strip_bot_mentions_from_text(text)
                reasons.append("Nhóm cấm Tag Bot -> Tự động xóa @username_bot trong tin nhắn")
        elif policy.on_no_bot_mentions == "use_fallback_text" and policy.fallback_text:
            text = render_spintax_and_variables(policy.fallback_text, render_context)
            via_bot = None
            reasons.append("Nhóm cấm Tag Bot -> Chuyển sang dùng Text dự phòng")
        elif policy.on_no_bot_mentions == "skip":
            return ResolvedSendPlan(
                action_to_execute="skip",
                fallback_applied=True,
                fallback_reasons=["Nhóm cấm Tag Bot -> Bỏ qua theo cấu hình"],
            )

    # 5. Handle Link restriction (`no_links`)
    link_preview = not chat_rule.no_links
    if chat_rule.no_links and contains_links(text):
        if policy.on_no_links == "use_fallback_no_link_text" and (
            policy.fallback_no_link_text or policy.fallback_text
        ):
            text = render_spintax_and_variables(
                policy.fallback_no_link_text or policy.fallback_text, render_context
            )
            reasons.append("Nhóm cấm gửi Link -> Chuyển sang bản tin không chứa Link")
        elif policy.on_no_links == "mask_links":
            text = mask_links_in_text(text)
            reasons.append("Nhóm cấm gửi Link -> Tự động che Link (domain[.]com)")
        elif policy.on_no_links == "strip_links":
            text = strip_links_from_text(text)
            if not text and (policy.fallback_no_link_text or policy.fallback_text):
                text = render_spintax_and_variables(
                    policy.fallback_no_link_text or policy.fallback_text, render_context
                )
            reasons.append("Nhóm cấm gửi Link -> Tự động lọc bỏ URL khỏi nội dung")
        elif policy.on_no_links == "skip":
            return ResolvedSendPlan(
                action_to_execute="skip",
                fallback_applied=True,
                fallback_reasons=["Nhóm cấm gửi Link -> Bỏ qua theo cấu hình"],
            )

    # 6. Handle custom banned words in group
    if text and chat_rule.banned_words:
        cleaned_text, word_filtered = strip_banned_words(text, chat_rule.banned_words)
        if word_filtered:
            text = cleaned_text
            reasons.append("Tự động che từ khóa bị cấm trong nhóm")

    # Ensure send_text has non-empty text
    if action == "send_text" and not (text and text.strip()):
        if policy.fallback_text and policy.fallback_text.strip():
            text = render_spintax_and_variables(policy.fallback_text.strip(), render_context)
            reasons.append("Sử dụng fallback_text do nội dung chính trống sau khi lọc")
        else:
            return ResolvedSendPlan(
                action_to_execute="skip",
                fallback_applied=True,
                fallback_reasons=reasons + ["Nội dung trống sau khi áp dụng bộ lọc quy tắc nhóm"],
            )

    return ResolvedSendPlan(
        action_to_execute=action,
        text_content=text,
        media_path=media_path,
        sticker_id_or_path=sticker,
        forward_from_chat_id=fwd_chat_id,
        forward_from_msg_id=fwd_msg_id,
        via_bot_username=via_bot,
        link_preview=link_preview,
        fallback_applied=len(reasons) > 0,
        fallback_reasons=reasons,
    )


@dataclass(frozen=True)
class LearnedErrorResult:
    learned_any_rule: bool
    no_links: bool | None = None
    no_stickers: bool | None = None
    no_forwards: bool | None = None
    no_media: bool | None = None
    no_bot_mentions: bool | None = None
    slow_mode_seconds: int | None = None
    flood_wait_seconds: int | None = None
    reason_note: str | None = None


def classify_telegram_error(exc: Exception) -> LearnedErrorResult:
    """
    Inspects a Telegram/Telethon exception at runtime and extracts restriction flags
    so the system can auto-learn group rules into SQLite and immediately retry with fallback.
    """
    err_name = type(exc).__name__
    err_text = str(exc).upper()
    seconds = getattr(exc, "seconds", None)

    if "FLOODWAIT" in err_name.upper() or "FLOOD_WAIT" in err_text:
        return LearnedErrorResult(
            learned_any_rule=False,
            flood_wait_seconds=int(seconds or 30),
            reason_note=f"FloodWait {seconds or 30}s",
        )

    if "SLOWMODEWAIT" in err_name.upper() or "SLOWMODE_WAIT" in err_text:
        wait_sec = int(seconds or 60)
        return LearnedErrorResult(
            learned_any_rule=True,
            slow_mode_seconds=wait_sec,
            reason_note=f"Auto-learned SlowMode ({wait_sec}s)",
        )

    if (
        "STICKER" in err_name.upper()
        or "CHAT_SEND_STICKERS_FORBIDDEN" in err_text
        or "CHAT_SEND_GIFS_FORBIDDEN" in err_text
    ):
        return LearnedErrorResult(
            learned_any_rule=True,
            no_stickers=True,
            reason_note="Auto-learned: Nhóm cấm gửi Sticker/GIF",
        )

    if (
        "FORWARDS_RESTRICTED" in err_text
        or "CHAT_FORWARDS_RESTRICTED" in err_text
        or "CHATFORWARDSRESTRICTED" in err_name.upper()
    ):
        return LearnedErrorResult(
            learned_any_rule=True,
            no_forwards=True,
            reason_note="Auto-learned: Nhóm cấm Forward",
        )

    if (
        "SEND_MEDIA_FORBIDDEN" in err_text
        or "CHAT_SEND_MEDIA_FORBIDDEN" in err_text
        or "CHAT_SEND_PHOTOS_FORBIDDEN" in err_text
        or "CHAT_SEND_VIDEOS_FORBIDDEN" in err_text
        or "CHAT_SEND_DOCS_FORBIDDEN" in err_text
        or "CHATSENDMEDIAFORBIDDEN" in err_name.upper()
    ):
        return LearnedErrorResult(
            learned_any_rule=True,
            no_media=True,
            reason_note="Auto-learned: Nhóm cấm gửi Media/File",
        )

    if (
        "INLINE_FORBIDDEN" in err_text
        or "CHAT_SEND_INLINE_FORBIDDEN" in err_text
        or "BOT_METHOD_INVALID" in err_text
        or "BOT_MENTION_FORBIDDEN" in err_text
    ):
        return LearnedErrorResult(
            learned_any_rule=True,
            no_bot_mentions=True,
            reason_note="Auto-learned: Nhóm cấm Inline/Tag Bot",
        )

    if (
        "WEBPAGE" in err_text
        or "LINK_FORBIDDEN" in err_text
        or "CHAT_SEND_LINKS_FORBIDDEN" in err_text
        or "ENTITY_MENTION_USER_INVALID" in err_text
    ):
        return LearnedErrorResult(
            learned_any_rule=True,
            no_links=True,
            reason_note="Auto-learned: Nhóm cấm gửi Link/Embed",
        )

    return LearnedErrorResult(learned_any_rule=False)
