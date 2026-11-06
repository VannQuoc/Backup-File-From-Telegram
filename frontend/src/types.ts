export interface Account {
  id: number;
  label: string;
  phone: string;
  api_id: number | null;
  api_hash: string | null;
  session_path: string;
  proxy_url: string | null;
  status: 'connected' | 'need_login' | 'otp_sent' | 'need_2fa' | 'flood_wait' | 'disabled';
  tg_user_id: number | null;
  tg_username: string | null;
  flood_wait_until: string | null;
  enabled: boolean;
  max_messages_per_hour: number;
  max_messages_per_day: number;
  sent_last_hour?: number;
  sent_last_24h?: number;
  joined_groups_count?: number;
  health_check_at?: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface AccountMembership {
  account_id: number;
  account_label?: string;
  account_phone?: string;
  account_status?: string;
  role: 'creator' | 'admin' | 'member' | 'restricted';
  can_send_messages: number | boolean;
  can_send_media: number | boolean;
  can_send_stickers: number | boolean;
  can_embed_links: number | boolean;
}

export interface ChatTopic {
  chat_id: number;
  topic_id: number;
  title: string;
  icon_color?: number | null;
  is_closed: number | boolean;
  is_pinned: number | boolean;
  updated_at?: string;
}

export interface ChatRule {
  chat_id: number;
  no_links: boolean;
  no_stickers: boolean;
  no_forwards: boolean;
  no_media: boolean;
  no_bot_mentions: boolean;
  slow_mode_seconds: number;
  banned_words: string[];
  auto_learned: boolean;
  notes: string | null;
  updated_at?: string | null;
}

export interface ChatGroup {
  chat_id: number;
  title: string;
  username: string | null;
  chat_type: string;
  is_forum: boolean;
  participants_count?: number | null;
  default_topic_id: number | null;
  discovered_by_account_id: number | null;
  updated_at: string;
  rules: ChatRule;
  member_accounts?: AccountMembership[];
  topics?: ChatTopic[];
}

export interface FolderChatItem {
  chat_id: number;
  topic_id: number;
  title?: string;
  username?: string | null;
}

export interface Folder {
  id: number;
  name: string;
  description: string | null;
  color: string;
  enabled: boolean;
  chats: FolderChatItem[];
  created_at: string;
  updated_at: string;
}

export interface BackupFilterConfig {
  sync_documents: boolean;
  allowed_extensions: string[];
  archive_extensions: string[];
  sync_photos: boolean;
  sync_videos: boolean;
  sync_text: boolean;
  sync_stickers: boolean;
  sync_voice: boolean;
  include_keywords: string[];
  exclude_keywords: string[];
  min_file_size_bytes: number | null;
  max_file_size_bytes: number | null;
  min_msg_id?: number | null;
  max_msg_id?: number | null;
  min_date_iso?: string | null;
  max_date_iso?: string | null;
  content_hash_dedupe?: boolean;
  rename_prefix?: string;
  rename_suffix?: string;
  caption_watermark?: string;
}

export interface BackupJob {
  id: number;
  label: string;
  enabled: boolean;
  reader_account_id: number;
  sender_account_id: number;
  source_chat_id: number;
  source_topic_id: number | null;
  dest_chat_id: number;
  dest_topic_default: number;
  dest_topic_archive: number;
  filter_config: BackupFilterConfig;
  caption_mode: 'preserve' | 'strip' | 'strip_for_txt' | 'custom_template';
  custom_caption_template: string | null;
  dedupe_enabled: boolean;
  allow_protected_fallback: boolean;
  send_delay_min_ms: number;
  send_delay_max_ms: number;
  last_scanned_msg_id: number;
  total_synced_count: number;
  last_sync_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SyncStateItem {
  backup_job_id: number;
  source_chat_id: number;
  source_msg_id: number;
  status: 'synced' | 'skipped' | 'failed';
  content_type: string;
  extension: string | null;
  document_id: number | null;
  filename: string | null;
  normalized_filename: string;
  size: number | null;
  dest_chat_id: number | null;
  dest_topic_id: number | null;
  dest_msg_id: number | null;
  fingerprint: string | null;
  used_protected_fallback: number | boolean;
  error_text: string | null;
  synced_at: string;
}

export interface FallbackPolicyConfig {
  on_no_forwards: 'copy_content' | 'use_fallback_text' | 'skip';
  on_no_links: 'strip_links' | 'mask_links' | 'use_fallback_no_link_text' | 'skip';
  on_no_stickers: 'use_fallback_text' | 'skip';
  on_no_media: 'use_fallback_text' | 'skip';
  on_no_bot_mentions: 'strip_bot_mentions' | 'use_fallback_text' | 'skip';
  fallback_text: string | null;
  fallback_no_link_text: string | null;
}

export interface ScenarioStep {
  id?: number;
  step_order: number;
  name: string;
  action_type: 'send_text' | 'send_media' | 'send_sticker' | 'forward_message';
  text_content: string | null;
  media_path: string | null;
  sticker_id_or_path: string | null;
  forward_from_chat_id: number | null;
  forward_from_msg_id: number | null;
  via_bot_username: string | null;
  fallback_policy: FallbackPolicyConfig;
}

export interface ScenarioTarget {
  id?: number;
  target_type: 'folder' | 'chat';
  target_id: number;
  topic_id: number;
  override_step_order: number | null;
  override_text_content: string | null;
  interval_override_seconds: number | null;
  enabled: boolean;
  last_sent_at?: string | null;
  next_run_at?: string | null;
}

export interface Scenario {
  id: number;
  name: string;
  description: string | null;
  enabled: boolean;
  sender_account_id: number | null;
  schedule_type: 'interval' | 'daily_times';
  interval_seconds: number;
  jitter_min_sec: number;
  jitter_max_sec: number;
  daily_times: string[];
  active_hours_start: string | null;
  active_hours_end: string | null;
  delete_previous_sent_message: boolean;
  delete_if_within_x_messages?: number;
  skip_if_within_x_messages?: number;
  selection_mode: 'sequential' | 'random' | 'all_steps';
  step_cursor: number;
  total_sent_count: number;
  last_run_at: string | null;
  steps: ScenarioStep[];
  targets: ScenarioTarget[];
}

export interface ChatHistoryAnalysisResult {
  chat_id: number;
  scanned_by_account_id: number;
  limit_requested: number;
  total_messages_scanned: number;
  admin_or_bot_messages_skipped: number;
  normal_user_messages: number;
  unique_normal_users_count: number;
  admins_detected_count: number;
  observed_counts: {
    links: number;
    forwards: number;
    stickers: number;
    media: number;
    bot_mentions: number;
  };
  inferred_normal_user_permissions: {
    can_send_links: boolean;
    can_forward: boolean;
    can_send_stickers: boolean;
    can_send_media: boolean;
    can_mention_bots: boolean;
  };
  unlocked_permissions: string[];
  inferred_restrictions: string[];
  updated_rule: ChatRule;
  summary: string;
}

export interface ScenarioPreflightMatrix {
  scenario_id: number;
  scenario_name: string;
  total_destinations: number;
  summary: {
    native_count: number;
    fallback_count: number;
    skip_count: number;
  };
  destinations: {
    chat_id: number;
    chat_title: string;
    topic_id: number;
    folder_name: string | null;
    eligible_member_accounts: string[];
    last_sent_msg_id: number | null;
    steps: {
      step_order: number;
      step_name: string;
      original_action: string;
      action_to_execute: string;
      fallback_applied: boolean;
      fallback_reasons: string[];
      preview_text: string;
    }[];
  }[];
}

export interface MediaLibraryItem {
  id: number;
  name: string;
  item_type: 'text_template' | 'sticker' | 'media';
  content: string;
  caption: string | null;
  tags: string[];
  created_at: string;
}

export interface RecentChatMessage {
  msg_id: number;
  chat_id: number;
  date: string | null;
  media_type: string;
  text_preview: string;
  full_text: string;
}

export interface ExecutionLog {
  id: number;
  category: string;
  level: string;
  account_id: number | null;
  chat_id: number | null;
  topic_id: number | null;
  scenario_id: number | null;
  backup_job_id: number | null;
  action_attempted: string | null;
  action_executed: string | null;
  fallback_applied: boolean;
  fallback_reason: string | null;
  status: string;
  message: string;
  created_at: string;
}

export interface DashboardData {
  stats: {
    global_paused?: boolean;
    accounts: { total: number; connected: number };
    groups: { total: number; with_rules: number; forum_topics?: number };
    folders: { total: number };
    backups: { total_jobs: number; active_jobs: number; synced_items: number };
    scenarios: {
      total: number;
      active: number;
      messages_sent: number;
      fallbacks_triggered: number;
    };
  };
  recent_logs: ExecutionLog[];
  recent_backups: SyncStateItem[];
}
