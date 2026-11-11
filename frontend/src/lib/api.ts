import type {
  Account,
  BackupJob,
  ChatGroup,
  ChatHistoryAnalysisResult,
  ChatRule,
  ChatTopic,
  DashboardData,
  ExecutionLog,
  Folder,
  MediaLibraryItem,
  RecentChatMessage,
  Scenario,
  ScenarioLiveRun,
  ScenarioPreflightMatrix,
  ScenarioStep,
  SyncStateItem,
} from '../types';

const TOKEN_STORAGE_KEY = 'tele_suite_admin_token';

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getStoredToken();
  const headers = new Headers(init.headers || {});
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  if (!(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const res = await fetch(path, { ...init, headers });
  if (res.status === 401) {
    setStoredToken(null);
    window.dispatchEvent(new CustomEvent('tele-suite-unauthorized'));
  }
  if (!res.ok) {
    let errText = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      if (data?.detail) {
        errText = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      // ignore json parse failure
    }
    throw new Error(errText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  login: (password: string) =>
    apiFetch<{ token: string; expires_in_seconds: number }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),
  verifyAuth: () => apiFetch<{ authenticated: boolean }>('/api/auth/verify'),
  hashPasswordHelper: (password: string) =>
    apiFetch<{ sha256: string }>('/api/auth/hash-helper', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),

  // Dashboard & System
  getDashboard: () => apiFetch<DashboardData>('/api/system/dashboard'),
  toggleGlobalPause: (paused: boolean) =>
    apiFetch<{ global_paused: boolean }>('/api/system/global-pause', {
      method: 'POST',
      body: JSON.stringify({ paused }),
    }),
  getLogs: (params?: { category?: string; fallback_only?: boolean; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.category) qs.set('category', params.category);
    if (params?.fallback_only) qs.set('fallback_only', 'true');
    if (params?.limit) qs.set('limit', String(params.limit));
    return apiFetch<ExecutionLog[]>(`/api/system/logs?${qs.toString()}`);
  },
  getSettings: () =>
    apiFetch<{
      settings: Record<string, unknown>;
      global_paused: boolean;
      env_info: Record<string, unknown>;
    }>('/api/system/settings'),
  updateSettings: (settings: Record<string, unknown>) =>
    apiFetch<{ settings: Record<string, unknown> }>('/api/system/settings', {
      method: 'PUT',
      body: JSON.stringify({ settings }),
    }),
  checkpointDb: () =>
    apiFetch<{ status: string; message: string }>('/api/system/checkpoint', {
      method: 'POST',
    }),
  exportConfigBundle: () => apiFetch<Record<string, unknown>>('/api/system/export-config'),
  importConfigBundle: (bundle: Record<string, unknown>) =>
    apiFetch<{ status: string; imported: Record<string, number> }>('/api/system/import-config', {
      method: 'POST',
      body: JSON.stringify(bundle),
    }),
  downloadSqliteSnapshot: async () => {
    const token = getStoredToken();
    const res = await fetch('/api/system/download-db', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `tele_suite_${new Date().toISOString().slice(0, 10)}.sqlite`;
    a.click();
    URL.revokeObjectURL(url);
  },

  // Accounts
  listAccounts: () => apiFetch<Account[]>('/api/accounts'),
  createAccount: (payload: Partial<Account>) =>
    apiFetch<Account>('/api/accounts', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateAccount: (id: number, payload: Partial<Account>) =>
    apiFetch<Account>(`/api/accounts/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  deleteAccount: (id: number) =>
    apiFetch<{ deleted: boolean }>(`/api/accounts/${id}`, { method: 'DELETE' }),
  listAccountJoinedGroups: (id: number) =>
    apiFetch<ChatGroup[]>(`/api/accounts/${id}/groups`),
  connectAccount: (id: number) =>
    apiFetch<Account>(`/api/accounts/${id}/connect`, { method: 'POST' }),
  checkAccountHealth: (id: number) =>
    apiFetch<{
      account_id: number;
      label: string;
      authorized: boolean;
      status: string;
      latency_ms: number | null;
      within_quota: boolean;
      quota_note: string | null;
      sent_last_hour: number;
      sent_last_24h: number;
      max_messages_per_hour: number;
      max_messages_per_day: number;
      joined_groups_count: number;
      error: string | null;
    }>(`/api/accounts/${id}/health-check`, { method: 'POST' }),
  sendOtp: (id: number, phone?: string) =>
    apiFetch<{ status: string; message: string; account: Account }>(
      `/api/accounts/${id}/send-otp`,
      {
        method: 'POST',
        body: JSON.stringify({ phone }),
      },
    ),
  verifyOtp: (id: number, code: string, password_2fa?: string) =>
    apiFetch<{ status: string; message: string; account: Account }>(
      `/api/accounts/${id}/verify-otp`,
      {
        method: 'POST',
        body: JSON.stringify({ code, password_2fa: password_2fa || null }),
      },
    ),
  scanDialogs: (id: number, limit = 250) =>
    apiFetch<{ count: number; groups: ChatGroup[] }>(
      `/api/accounts/${id}/scan-dialogs?limit=${limit}`,
      { method: 'POST' },
    ),
  scanAllConnectedDialogs: (limitPerAccount = 250) =>
    apiFetch<{
      scanned_accounts: number;
      total_discovered: number;
      total_groups_in_db: number;
      errors: { account_id: number; label: string; error: string }[];
      chats: ChatGroup[];
    }>(`/api/accounts/scan-all-dialogs?limit_per_account=${limitPerAccount}`, {
      method: 'POST',
    }),
  importTelegramFolders: (id: number) =>
    apiFetch<{ imported_count: number; folders: Folder[] }>(
      `/api/accounts/${id}/import-telegram-folders`,
      { method: 'POST' },
    ),
  bulkJoinGroups: (
    id: number,
    payload: {
      links_or_usernames: string[];
      clone_from_account_id?: number | null;
      clone_strategy?: 'smart_auto' | 'invite_only' | 'share_folder';
      create_share_folder?: boolean;
      share_folder_title?: string | null;
      max_self_joins_per_run?: number;
      delay_min_sec?: number;
      delay_max_sec?: number;
    },
  ) =>
    apiFetch<{
      account_id: number;
      clone_strategy: string;
      total_targets: number;
      joined_count: number;
      invited_by_source_count: number;
      self_joined_count: number;
      manual_pack_count: number;
      failed_count: number;
      joined: { target: string; status: string; method?: string }[];
      invited_by_source: { target: string; chat_id: number; title: string; status: string }[];
      failed: { target: string; error: string }[];
      share_folder_link: string | null;
      created_web_folder: Folder | null;
      manual_join_links: {
        chat_id: number | null;
        title: string;
        username: string | null;
        join_link: string | null;
        note: string;
      }[];
    }>(`/api/accounts/${id}/bulk-join`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  importSessionFile: (formData: FormData) =>
    apiFetch<Account>('/api/accounts/import-session', {
      method: 'POST',
      body: formData,
    }),

  // Chats, Topics & Folders
  listChats: (accountId?: number) => {
    const qs = accountId ? `?account_id=${accountId}` : '';
    return apiFetch<ChatGroup[]>(`/api/chats${qs}`);
  },
  upsertChat: (payload: {
    chat_id: number;
    title: string;
    username?: string | null;
    chat_type?: string;
    is_forum?: boolean;
  }) =>
    apiFetch<ChatGroup>('/api/chats', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateChatRules: (chatId: number, rules: Partial<ChatRule>) =>
    apiFetch<ChatGroup>(`/api/chats/${chatId}/rules`, {
      method: 'PUT',
      body: JSON.stringify(rules),
    }),
  deleteChat: (chatId: number) =>
    apiFetch<{ deleted: boolean }>(`/api/chats/${chatId}`, { method: 'DELETE' }),
  listChatTopics: (chatId: number) =>
    apiFetch<ChatTopic[]>(`/api/chats/${chatId}/topics`),
  scanChatTopics: (chatId: number, accountId?: number) => {
    const qs = accountId ? `?account_id=${accountId}` : '';
    return apiFetch<{ chat_id: number; count: number; topics: ChatTopic[] }>(
      `/api/chats/${chatId}/scan-topics${qs}`,
      { method: 'POST' },
    );
  },
  createForumTopic: (
    chatId: number,
    payload: { title: string; account_id?: number | null; icon_color?: number | null },
  ) =>
    apiFetch<ChatTopic>(`/api/chats/${chatId}/create-topic`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getRecentChatMessages: (chatId: number, accountId?: number, limit = 25) => {
    const qs = new URLSearchParams({ limit: String(limit) });
    if (accountId) qs.set('account_id', String(accountId));
    return apiFetch<{ chat_id: number; count: number; messages: RecentChatMessage[] }>(
      `/api/chats/${chatId}/recent-messages?${qs.toString()}`,
    );
  },
  analyzeChatHistory: (
    chatId: number,
    payload?: {
      account_id?: number | null;
      limit?: number;
      auto_apply_unlock?: boolean;
      strict_infer_blocks?: boolean;
    },
  ) =>
    apiFetch<ChatHistoryAnalysisResult>(`/api/chats/${chatId}/analyze-history`, {
      method: 'POST',
      body: JSON.stringify({
        limit: 1000,
        auto_apply_unlock: true,
        strict_infer_blocks: false,
        ...payload,
      }),
    }),
  analyzeChatHistoryBatch: (payload?: {
    chat_ids?: number[];
    folder_id?: number | null;
    account_id?: number | null;
    limit_per_chat?: number;
    auto_apply_unlock?: boolean;
    strict_infer_blocks?: boolean;
  }) =>
    apiFetch<{
      scanned_count: number;
      failed_count: number;
      results: ChatHistoryAnalysisResult[];
      errors: { chat_id: number; error: string }[];
    }>('/api/chats/analyze-history-batch', {
      method: 'POST',
      body: JSON.stringify({
        limit_per_chat: 1000,
        auto_apply_unlock: true,
        strict_infer_blocks: false,
        ...payload,
      }),
    }),

  listFolders: () => apiFetch<Folder[]>('/api/folders'),
  createFolder: (payload: {
    name: string;
    description?: string | null;
    color?: string;
    enabled?: boolean;
    chats: { chat_id: number; topic_id: number }[];
  }) =>
    apiFetch<Folder>('/api/folders', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateFolder: (
    id: number,
    payload: {
      name?: string;
      description?: string | null;
      color?: string;
      enabled?: boolean;
      chats?: { chat_id: number; topic_id: number }[];
    },
  ) =>
    apiFetch<Folder>(`/api/folders/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  deleteFolder: (id: number) =>
    apiFetch<{ deleted: boolean }>(`/api/folders/${id}`, { method: 'DELETE' }),

  // Backups
  listBackups: () => apiFetch<BackupJob[]>('/api/backups'),
  createBackup: (payload: Record<string, unknown>) =>
    apiFetch<BackupJob>('/api/backups', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateBackup: (id: number, payload: Record<string, unknown>) =>
    apiFetch<BackupJob>(`/api/backups/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  deleteBackup: (id: number) =>
    apiFetch<{ deleted: boolean }>(`/api/backups/${id}`, { method: 'DELETE' }),
  runBackupNow: (id: number, limit = 100) =>
    apiFetch<Record<string, unknown>>(`/api/backups/${id}/run?limit=${limit}`, {
      method: 'POST',
    }),
  runAllBackups: (limit = 100) =>
    apiFetch<Record<string, unknown>[]>(`/api/backups/run-all?limit_per_job=${limit}`, {
      method: 'POST',
    }),
  listBackupHistory: (params?: { backup_job_id?: number; status?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.backup_job_id) qs.set('backup_job_id', String(params.backup_job_id));
    if (params?.status) qs.set('status', params.status);
    if (params?.limit) qs.set('limit', String(params.limit));
    return apiFetch<SyncStateItem[]>(`/api/backups/history?${qs.toString()}`);
  },

  // Scenarios & Template Library
  listScenarios: () => apiFetch<Scenario[]>('/api/scenarios'),
  createScenario: (payload: Record<string, unknown>) =>
    apiFetch<Scenario>('/api/scenarios', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateScenario: (id: number, payload: Record<string, unknown>) =>
    apiFetch<Scenario>(`/api/scenarios/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  deleteScenario: (id: number) =>
    apiFetch<{ deleted: boolean }>(`/api/scenarios/${id}`, { method: 'DELETE' }),
  runScenarioNow: (id: number, wait = false) =>
    apiFetch<{
      scenario_id: number;
      status?: string;
      background?: boolean;
      total_destinations?: number;
      executed_count: number;
      live_run?: ScenarioLiveRun;
      logs: ExecutionLog[];
    }>(`/api/scenarios/${id}/run${wait ? '?wait=true' : ''}`, { method: 'POST' }),
  getScenarioRunStatus: (id: number) =>
    apiFetch<ScenarioLiveRun>(`/api/scenarios/${id}/run-status`),
  cloneScenario: (id: number) =>
    apiFetch<Scenario>(`/api/scenarios/${id}/clone`, { method: 'POST' }),
  preflightCheckScenario: (id: number) =>
    apiFetch<ScenarioPreflightMatrix>(`/api/scenarios/${id}/preflight-check`),
  simulateFallback: (payload: {
    step: ScenarioStep;
    chat_id?: number;
    custom_rule?: Partial<ChatRule>;
    override_text_content?: string;
  }) =>
    apiFetch<{
      chat_rule_applied: ChatRule;
      resolved_plan: {
        action_to_execute: string;
        text_content: string | null;
        fallback_applied: boolean;
        fallback_reasons: string[];
      };
    }>('/api/scenarios/simulate-fallback', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listMediaLibrary: (itemType?: string) => {
    const qs = itemType ? `?item_type=${itemType}` : '';
    return apiFetch<MediaLibraryItem[]>(`/api/scenarios/library/items${qs}`);
  },
  createMediaLibraryItem: (payload: {
    name: string;
    item_type: 'text_template' | 'sticker' | 'media';
    content: string;
    caption?: string | null;
    tags?: string[];
  }) =>
    apiFetch<MediaLibraryItem>('/api/scenarios/library/items', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  deleteMediaLibraryItem: (id: number) =>
    apiFetch<{ deleted: boolean }>(`/api/scenarios/library/items/${id}`, {
      method: 'DELETE',
    }),
};
