from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    password: str = Field(..., min_length=1, description="Mật khẩu Admin hoặc chuỗi SHA-256")


class LoginResponse(BaseModel):
    token: str
    expires_in_seconds: int = 86400 * 7


class AccountCreateRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=5, max_length=32)
    api_id: int | None = None
    api_hash: str | None = None
    proxy_url: str | None = None
    max_messages_per_hour: int = Field(default=60, ge=1)
    max_messages_per_day: int = Field(default=500, ge=1)
    enabled: bool = True


class AccountUpdateRequest(BaseModel):
    label: str | None = None
    phone: str | None = None
    api_id: int | None = None
    api_hash: str | None = None
    proxy_url: str | None = None
    max_messages_per_hour: int | None = None
    max_messages_per_day: int | None = None
    enabled: bool | None = None


class AccountOtpSendRequest(BaseModel):
    phone: str | None = None


class AccountOtpVerifyRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=16)
    password_2fa: str | None = None


class BulkJoinRequest(BaseModel):
    links_or_usernames: list[str] = Field(default_factory=list)
    clone_from_account_id: int | None = None
    delay_min_sec: float = 2.0
    delay_max_sec: float = 5.0


class AccountMembershipModel(BaseModel):
    account_id: int
    chat_id: int
    role: str = "member"  # "creator" | "admin" | "member" | "restricted"
    can_send_messages: bool = True
    can_send_media: bool = True
    can_send_stickers: bool = True
    can_embed_links: bool = True
    updated_at: str | None = None


class ChatTopicModel(BaseModel):
    chat_id: int
    topic_id: int
    title: str
    icon_color: int | None = None
    is_closed: bool = False
    updated_at: str | None = None


class CreateTopicRequest(BaseModel):
    account_id: int
    title: str = Field(..., min_length=1, max_length=120)
    icon_color: int | None = None


class AnalyzeChatHistoryRequest(BaseModel):
    account_id: int | None = None
    limit: int = Field(default=1000, ge=10, le=3000)
    auto_apply_unlock: bool = True
    strict_infer_blocks: bool = False


class AnalyzeChatHistoryBatchRequest(BaseModel):
    chat_ids: list[int] = Field(default_factory=list)
    folder_id: int | None = None
    account_id: int | None = None
    limit_per_chat: int = Field(default=1000, ge=10, le=3000)
    auto_apply_unlock: bool = True
    strict_infer_blocks: bool = False


class ChatRuleModel(BaseModel):
    chat_id: int
    no_links: bool = False
    no_stickers: bool = False
    no_forwards: bool = False
    no_media: bool = False
    no_bot_mentions: bool = False
    slow_mode_seconds: int = 0
    banned_words: list[str] = Field(default_factory=list)
    auto_learned: bool = False
    notes: str | None = None
    updated_at: str | None = None


class ChatGroupUpsertRequest(BaseModel):
    chat_id: int
    title: str
    username: str | None = None
    chat_type: str = "supergroup"
    is_forum: bool = False
    participants_count: int | None = None
    default_topic_id: int | None = None
    discovered_by_account_id: int | None = None
    rules: ChatRuleModel | None = None


class ChatRuleUpdateRequest(BaseModel):
    no_links: bool = False
    no_stickers: bool = False
    no_forwards: bool = False
    no_media: bool = False
    no_bot_mentions: bool = False
    slow_mode_seconds: int = 0
    banned_words: list[str] = Field(default_factory=list)
    notes: str | None = None


class FolderChatEntry(BaseModel):
    chat_id: int
    topic_id: int = 0


class FolderCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    color: str = "#10b981"
    enabled: bool = True
    chats: list[FolderChatEntry] = Field(default_factory=list)


class FolderUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None
    enabled: bool | None = None
    chats: list[FolderChatEntry] | None = None


class BackupFilterConfig(BaseModel):
    sync_documents: bool = True
    allowed_extensions: list[str] = Field(default_factory=list)  # Empty = all extensions
    archive_extensions: list[str] = Field(default_factory=lambda: [".zip", ".rar", ".7z"])
    sync_photos: bool = False
    sync_videos: bool = False
    sync_text: bool = False
    sync_stickers: bool = False
    sync_voice: bool = False
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    min_file_size_bytes: int | None = None
    max_file_size_bytes: int | None = None
    min_msg_id: int | None = None
    max_msg_id: int | None = None
    min_date_iso: str | None = None
    max_date_iso: str | None = None
    content_hash_dedupe: bool = True
    rename_prefix: str = ""
    rename_suffix: str = ""
    caption_watermark: str = ""


class BackupJobCreateRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)
    enabled: bool = True
    reader_account_id: int
    sender_account_id: int | None = None  # Defaults to reader_account_id if None
    source_chat_id: int
    source_topic_id: int | None = None
    dest_chat_id: int
    dest_topic_default: int = 0
    dest_topic_archive: int = 0
    filter_config: BackupFilterConfig = Field(default_factory=BackupFilterConfig)
    caption_mode: Literal["preserve", "strip", "strip_for_txt", "custom_template"] = "strip_for_txt"
    custom_caption_template: str | None = None
    dedupe_enabled: bool = True
    allow_protected_fallback: bool = True
    send_delay_min_ms: int = 800
    send_delay_max_ms: int = 1500


class BackupJobUpdateRequest(BaseModel):
    label: str | None = None
    enabled: bool | None = None
    reader_account_id: int | None = None
    sender_account_id: int | None = None
    source_chat_id: int | None = None
    source_topic_id: int | None = None
    dest_chat_id: int | None = None
    dest_topic_default: int | None = None
    dest_topic_archive: int | None = None
    filter_config: BackupFilterConfig | None = None
    caption_mode: Literal["preserve", "strip", "strip_for_txt", "custom_template"] | None = None
    custom_caption_template: str | None = None
    dedupe_enabled: bool | None = None
    allow_protected_fallback: bool | None = None
    send_delay_min_ms: int | None = None
    send_delay_max_ms: int | None = None


class FallbackPolicyConfig(BaseModel):
    on_no_forwards: Literal["copy_content", "use_fallback_text", "skip"] = "copy_content"
    on_no_links: Literal["strip_links", "mask_links", "use_fallback_no_link_text", "skip"] = (
        "strip_links"
    )
    on_no_stickers: Literal["use_fallback_text", "skip"] = "use_fallback_text"
    on_no_media: Literal["use_fallback_text", "skip"] = "use_fallback_text"
    on_no_bot_mentions: Literal["strip_bot_mentions", "use_fallback_text", "skip"] = (
        "strip_bot_mentions"
    )
    fallback_text: str | None = None
    fallback_no_link_text: str | None = None


class ScenarioStepInput(BaseModel):
    step_order: int = 1
    name: str = "Bước 1"
    action_type: Literal["send_text", "send_media", "send_sticker", "forward_message"] = "send_text"
    text_content: str | None = None
    media_path: str | None = None
    sticker_id_or_path: str | None = None
    forward_from_chat_id: int | None = None
    forward_from_msg_id: int | None = None
    via_bot_username: str | None = None
    fallback_policy: FallbackPolicyConfig = Field(default_factory=FallbackPolicyConfig)


class ScenarioTargetInput(BaseModel):
    target_type: Literal["folder", "chat"] = "folder"
    target_id: int
    topic_id: int = 0
    override_step_order: int | None = None
    override_text_content: str | None = None
    interval_override_seconds: int | None = None
    enabled: bool = True


class ScenarioCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    enabled: bool = True
    sender_account_id: int | None = None  # None = smart auto-rotate across connected member accounts
    schedule_type: Literal["interval", "daily_times"] = "interval"
    interval_seconds: int = Field(default=1800, ge=10)
    jitter_min_sec: int = Field(default=5, ge=0)
    jitter_max_sec: int = Field(default=30, ge=0)
    daily_times: list[str] = Field(default_factory=list)
    active_hours_start: str | None = None  # e.g. "07:30"
    active_hours_end: str | None = None    # e.g. "22:30"
    delete_previous_sent_message: bool = False
    delete_if_within_x_messages: int = Field(default=0, ge=0)
    skip_if_within_x_messages: int = Field(default=0, ge=0)
    selection_mode: Literal["sequential", "random", "all_steps"] = "sequential"
    steps: list[ScenarioStepInput] = Field(default_factory=list)
    targets: list[ScenarioTargetInput] = Field(default_factory=list)


class ScenarioUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    sender_account_id: int | None = None
    schedule_type: Literal["interval", "daily_times"] | None = None
    interval_seconds: int | None = None
    jitter_min_sec: int | None = None
    jitter_max_sec: int | None = None
    daily_times: list[str] | None = None
    active_hours_start: str | None = None
    active_hours_end: str | None = None
    delete_previous_sent_message: bool | None = None
    delete_if_within_x_messages: int | None = None
    skip_if_within_x_messages: int | None = None
    selection_mode: Literal["sequential", "random", "all_steps"] | None = None
    steps: list[ScenarioStepInput] | None = None
    targets: list[ScenarioTargetInput] | None = None


class MediaLibraryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    item_type: Literal["text_template", "sticker", "media_file", "media"] = "text_template"
    content_or_path: str | None = None
    content: str | None = None
    caption: str | None = None
    tags: list[str] = Field(default_factory=list)


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, Any]
