from __future__ import annotations

from backend.database.models import ChatRuleModel
from backend.telegram.rule_engine import (
    classify_telegram_error,
    resolve_execution_plan,
)


def test_forward_fallback_to_copy_and_strip_links_and_bot_mentions() -> None:
    step = {
        "action_type": "forward_message",
        "forward_from_chat_id": -100123,
        "forward_from_msg_id": 99,
        "text_content": "Liên hệ @helper_bot tại https://shop.example.com/deal ngay hôm nay!",
        "via_bot_username": "postbot",
        "fallback_policy": {
            "on_no_forwards": "copy_content",
            "on_no_links": "strip_links",
            "on_no_bot_mentions": "strip_bot_mentions",
            "fallback_text": "Liên hệ trực tiếp quản trị viên.",
        },
    }
    rule = ChatRuleModel(
        chat_id=-100555,
        no_forwards=True,
        no_links=True,
        no_bot_mentions=True,
    )

    plan = resolve_execution_plan(step, rule)
    assert plan.action_to_execute == "copy_source_message"
    assert plan.fallback_applied is True
    assert plan.via_bot_username is None
    assert "@helper_bot" not in (plan.text_content or "")
    assert "https://shop.example.com" not in (plan.text_content or "")
    assert plan.link_preview is False


def test_sticker_fallback_to_text() -> None:
    step = {
        "action_type": "send_sticker",
        "sticker_id_or_path": "CAACAgUAAxkBAA...",
        "fallback_policy": {
            "on_no_stickers": "use_fallback_text",
            "fallback_text": "Chúc mọi người ngày mới tốt lành!",
        },
    }
    rule = ChatRuleModel(chat_id=-100777, no_stickers=True)

    plan = resolve_execution_plan(step, rule)
    assert plan.action_to_execute == "send_text"
    assert plan.text_content == "Chúc mọi người ngày mới tốt lành!"
    assert plan.fallback_applied is True


def test_mask_links_and_banned_words() -> None:
    step = {
        "action_type": "send_text",
        "text_content": "Truy cập https://myweb.vn/km để nhận quà vip",
        "fallback_policy": {
            "on_no_links": "mask_links",
        },
    }
    rule = ChatRuleModel(
        chat_id=-100888,
        no_links=True,
        banned_words=["quà vip"],
    )

    plan = resolve_execution_plan(step, rule)
    assert plan.action_to_execute == "send_text"
    assert "myweb[.]vn/km" in (plan.text_content or "")
    assert "***" in (plan.text_content or "")
    assert plan.fallback_applied is True


def test_runtime_error_classifier_learns_restrictions() -> None:
    class ChatSendStickersForbiddenError(Exception):
        pass

    class ChatForwardsRestrictedError(Exception):
        pass

    class SlowModeWaitError(Exception):
        def __init__(self, seconds: int) -> None:
            super().__init__("SLOWMODE_WAIT")
            self.seconds = seconds

    res_sticker = classify_telegram_error(ChatSendStickersForbiddenError("CHAT_SEND_STICKERS_FORBIDDEN"))
    assert res_sticker.learned_any_rule is True
    assert res_sticker.no_stickers is True

    res_fwd = classify_telegram_error(ChatForwardsRestrictedError("CHAT_FORWARDS_RESTRICTED"))
    assert res_fwd.learned_any_rule is True
    assert res_fwd.no_forwards is True

    res_slow = classify_telegram_error(SlowModeWaitError(45))
    assert res_slow.learned_any_rule is True
    assert res_slow.slow_mode_seconds == 45

