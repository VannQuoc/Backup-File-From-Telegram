import React, { useState } from 'react';
import {
  ArrowsClockwise,
  CloudArrowDown,
  FolderPlus,
  FolderSimplePlus,
  Hash,
  MagnifyingGlass,
  Plus,
  Robot,
  ShieldCheck,
  Trash,
} from '@phosphor-icons/react';
import { api } from '../lib/api';
import type {
  Account,
  ChatGroup,
  ChatHistoryAnalysisResult,
  ChatRule,
  Folder,
} from '../types';

interface ChatsFoldersViewProps {
  accounts: Account[];
  chats: ChatGroup[];
  folders: Folder[];
  onRefresh: () => void;
}

const RULE_FLAGS: {
  key: keyof Pick<
    ChatRule,
    'no_links' | 'no_stickers' | 'no_forwards' | 'no_media' | 'no_bot_mentions'
  >;
  label: string;
  desc: string;
}[] = [
  { key: 'no_links', label: 'Cấm Link', desc: 'Tự xóa/che URL hoặc dùng bản không link' },
  { key: 'no_stickers', label: 'Cấm Sticker', desc: 'Đổi Sticker sang gửi Text dự phòng' },
  { key: 'no_forwards', label: 'Cấm Forward', desc: 'Tự chuyển Forward sang Copy nội dung' },
  { key: 'no_media', label: 'Cấm Ảnh/Media', desc: 'Chuyển sang gửi Text thuần' },
  { key: 'no_bot_mentions', label: 'Cấm Tag @Bot', desc: 'Tự xóa @...bot và inline bot' },
];

export const ChatsFoldersView: React.FC<ChatsFoldersViewProps> = ({
  accounts,
  chats,
  folders,
  onRefresh,
}) => {
  // Filter by Account membership
  const [filterAccountId, setFilterAccountId] = useState<string>('');
  const [importFromAccId, setImportFromAccId] = useState<string>(
    accounts[0]?.id ? String(accounts[0].id) : '',
  );

  // Manual Chat Add state
  const [newChatId, setNewChatId] = useState('');
  const [newChatTitle, setNewChatTitle] = useState('');
  const [newChatType, setNewChatType] = useState('supergroup');
  const [searchQuery, setSearchQuery] = useState('');

  // Folder Create/Edit state
  const [editingFolderId, setEditingFolderId] = useState<number | null>(null);
  const [folderName, setFolderName] = useState('');
  const [folderDesc, setFolderDesc] = useState('');
  const [selectedChatIds, setSelectedChatIds] = useState<Record<number, number>>({}); // chat_id -> topic_id
  const [feedback, setFeedback] = useState<string | null>(null);

  // Reload & 1,000-Message History Permission Scanner state
  const [reloadingChats, setReloadingChats] = useState(false);
  const [scanningAllDialogs, setScanningAllDialogs] = useState(false);
  const [analyzingChatId, setAnalyzingChatId] = useState<number | null>(null);
  const [batchAnalyzing, setBatchAnalyzing] = useState(false);
  const [historyScanLimit, setHistoryScanLimit] = useState<number>(1000);
  const [strictInferBlocks, setStrictInferBlocks] = useState<boolean>(false);
  const [analysisResults, setAnalysisResults] = useState<ChatHistoryAnalysisResult[]>([]);

  const handleReloadFromDb = () => {
    setReloadingChats(true);
    try {
      onRefresh();
      setFeedback('Đã tải lại danh sách Nhóm, Folder & Quy tắc mới nhất từ Database!');
    } finally {
      setTimeout(() => setReloadingChats(false), 300);
    }
  };

  const handleSyncAllDialogsFromTelegram = async () => {
    setScanningAllDialogs(true);
    try {
      const res = await api.scanAllConnectedDialogs(250);
      setFeedback(
        `Đã đồng bộ lại từ ${res.scanned_accounts} tài khoản kết nối: tổng cộng ${res.total_groups_in_db} nhóm trong danh bạ!`,
      );
      onRefresh();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : 'Lỗi đồng bộ danh sách nhóm từ Telegram');
    } finally {
      setScanningAllDialogs(false);
    }
  };

  const handleAnalyzeChatHistory = async (chat: ChatGroup) => {
    setAnalyzingChatId(chat.chat_id);
    try {
      const res = await api.analyzeChatHistory(chat.chat_id, {
        limit: historyScanLimit || 1000,
        auto_apply_unlock: true,
        strict_infer_blocks: strictInferBlocks,
      });
      setAnalysisResults((prev) => [
        res,
        ...prev.filter((item) => item.chat_id !== chat.chat_id),
      ]);
      const unlockedText =
        res.unlocked_permissions.length > 0
          ? ` -> Đã tự mở khóa: ${res.unlocked_permissions.join(', ')}`
          : ' -> Giữ nguyên Rule hiện tại';
      setFeedback(`Quét ${res.total_messages_scanned} tin nhóm "${chat.title}": ${res.summary}${unlockedText}`);
      onRefresh();
    } catch (err) {
      setFeedback(
        err instanceof Error
          ? err.message
          : `Không thể quét lịch sử nhóm "${chat.title}" (Hãy đảm bảo có ít nhất 1 Nick đã kết nối)`,
      );
    } finally {
      setAnalyzingChatId(null);
    }
  };

  const handleBatchAnalyzeHistory = async (chatIds: number[], label: string) => {
    if (chatIds.length === 0) return;
    setBatchAnalyzing(true);
    try {
      const res = await api.analyzeChatHistoryBatch({
        chat_ids: chatIds,
        limit_per_chat: historyScanLimit || 1000,
        auto_apply_unlock: true,
        strict_infer_blocks: strictInferBlocks,
      });
      setAnalysisResults(res.results);
      setFeedback(
        `Đã quét lịch sử ${historyScanLimit} tin cho ${res.scanned_count}/${chatIds.length} nhóm (${label})!`,
      );
      onRefresh();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : 'Lỗi quét lịch sử hàng loạt');
    } finally {
      setBatchAnalyzing(false);
    }
  };

  const handleAddChat = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newChatId.trim() || !newChatTitle.trim()) return;
    await api.upsertChat({
      chat_id: Number(newChatId.trim()),
      title: newChatTitle.trim(),
      chat_type: newChatType,
      is_forum: newChatType === 'forum',
    });
    setNewChatId('');
    setNewChatTitle('');
    setFeedback('Đã lưu nhóm vào danh bạ.');
    onRefresh();
  };

  const handleImportTgFolders = async () => {
    const accId = Number(importFromAccId || accounts[0]?.id || 0);
    if (!accId) return;
    try {
      const res = await api.importTelegramFolders(accId);
      setFeedback(
        `Đã sao chép ${res.imported_count} Folder từ Telegram của Nick #${accId} thành Folder Độc Lập trên Web Panel!`,
      );
      onRefresh();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : 'Lỗi import Folder từ Telegram');
    }
  };

  const handleScanTopicsForChat = async (chat: ChatGroup) => {
    try {
      const res = await api.scanChatTopics(chat.chat_id);
      setFeedback(`Đã quét & đồng bộ ${res.count} Forum Topics cho nhóm "${chat.title}"!`);
      onRefresh();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : 'Không thể quét Topic của nhóm này');
    }
  };

  const handleCreateTopicPrompt = async (chat: ChatGroup) => {
    const title = window.prompt(`Nhập tên Topic mới cần tạo trên nhóm "${chat.title}":`);
    if (!title || !title.trim()) return;
    try {
      const created = await api.createForumTopic(chat.chat_id, { title: title.trim() });
      setFeedback(`Đã tạo Topic "${created.title}" (#${created.topic_id}) trên nhóm "${chat.title}"!`);
      onRefresh();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : 'Lỗi tạo Topic mới');
    }
  };

  const handleToggleRule = async (
    chat: ChatGroup,
    flagKey: keyof Pick<
      ChatRule,
      'no_links' | 'no_stickers' | 'no_forwards' | 'no_media' | 'no_bot_mentions'
    >,
  ) => {
    const current = chat.rules;
    await api.updateChatRules(chat.chat_id, {
      ...current,
      [flagKey]: !current[flagKey],
    });
    onRefresh();
  };

  const handleUpdateSlowModeOrBannedWords = async (
    chat: ChatGroup,
    slowMode: number,
    bannedWordsRaw: string,
  ) => {
    const words = bannedWordsRaw
      .split(',')
      .map((w) => w.trim())
      .filter(Boolean);
    await api.updateChatRules(chat.chat_id, {
      ...chat.rules,
      slow_mode_seconds: slowMode,
      banned_words: words,
    });
    setFeedback(`Đã cập nhật quy tắc nâng cao cho nhóm "${chat.title}"`);
    onRefresh();
  };

  const handleStartEditFolder = (folder?: Folder) => {
    if (!folder) {
      setEditingFolderId(null);
      setFolderName('');
      setFolderDesc('');
      setSelectedChatIds({});
      return;
    }
    setEditingFolderId(folder.id);
    setFolderName(folder.name);
    setFolderDesc(folder.description || '');
    const map: Record<number, number> = {};
    for (const item of folder.chats) {
      map[item.chat_id] = item.topic_id || 0;
    }
    setSelectedChatIds(map);
  };

  const handleToggleChatInFolder = (chatId: number) => {
    setSelectedChatIds((prev) => {
      const next = { ...prev };
      if (chatId in next) {
        delete next[chatId];
      } else {
        next[chatId] = 0;
      }
      return next;
    });
  };

  const handleSetTopicInFolder = (chatId: number, topicId: number) => {
    setSelectedChatIds((prev) => ({
      ...prev,
      [chatId]: topicId,
    }));
  };

  const handleSaveFolder = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!folderName.trim()) return;
    const chatList = Object.entries(selectedChatIds).map(([cid, tid]) => ({
      chat_id: Number(cid),
      topic_id: Number(tid) || 0,
    }));

    if (editingFolderId) {
      await api.updateFolder(editingFolderId, {
        name: folderName.trim(),
        description: folderDesc.trim() || null,
        chats: chatList,
      });
      setFeedback(`Đã cập nhật Folder độc lập "${folderName}"`);
    } else {
      await api.createFolder({
        name: folderName.trim(),
        description: folderDesc.trim() || null,
        chats: chatList,
      });
      setFeedback(`Đã tạo Folder độc lập "${folderName}"`);
    }
    handleStartEditFolder(undefined);
    onRefresh();
  };

  const filteredChats = chats.filter((c) => {
    const matchesQuery =
      c.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      String(c.chat_id).includes(searchQuery) ||
      (c.username && c.username.toLowerCase().includes(searchQuery.toLowerCase()));
    if (!matchesQuery) return false;
    if (!filterAccountId) return true;
    const accIdNum = Number(filterAccountId);
    return (
      c.member_accounts?.some((m) => m.account_id === accIdNum) ||
      c.discovered_by_account_id === accIdNum
    );
  });

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#27272A] pb-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">
            Danh Bạ Nhóm Theo Tài Khoản, Folder Độc Lập & Ma Trận Rule Cấm
          </h2>
          <p className="text-sm text-[#A1A1AA]">
            Xem ngay Nick nào đã tham gia những nhóm nào mà không cần tự đi mò Chat ID. Bạn có thể
            Import nhanh Folder từ Telegram hoặc tự tạo nhiều Folder độc lập trên Web để gán các
            kịch bản (Script) khác nhau.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleReloadFromDb}
            className="px-3 py-2 border border-[#27272A] hover:border-[#10B981] text-[#F4F4F5] text-xs font-mono flex items-center gap-1.5 cursor-pointer"
            title="Tải lại danh sách nhóm & folder từ Database"
          >
            <ArrowsClockwise size={15} className={reloadingChats ? 'animate-spin text-[#10B981]' : ''} />
            <span>Reload Danh Sách Nhóm</span>
          </button>

          <button
            type="button"
            disabled={scanningAllDialogs}
            onClick={handleSyncAllDialogsFromTelegram}
            className="px-3 py-2 border border-[#10B981] text-[#10B981] hover:bg-[#10B981]/15 text-xs font-mono flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
            title="Quét lại toàn bộ các nhóm từ tất cả tài khoản Telegram đang kết nối"
          >
            <CloudArrowDown size={16} className={scanningAllDialogs ? 'animate-bounce' : ''} />
            <span>{scanningAllDialogs ? 'Đang quét từ Telegram...' : 'Đồng Bộ Nhóm Từ Tất Cả Nick'}</span>
          </button>

          {/* One-Click Import Telegram Folders as Independent Web Folders (Feature #3) */}
          {accounts.length > 0 && (
            <div className="flex items-center gap-2 p-1.5 border border-[#27272A] bg-[#121215]">
              <select
                value={importFromAccId}
                onChange={(e) => setImportFromAccId(e.target.value)}
                className="px-2.5 py-1 text-xs font-mono"
              >
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    Nick #{a.id} · {a.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={handleImportTgFolders}
                className="px-3 py-1 border border-[#F59E0B] text-[#F59E0B] hover:bg-[#F59E0B]/15 text-xs font-mono flex items-center gap-1.5 cursor-pointer"
              >
                <FolderSimplePlus size={15} />
                <span>Copy Folder từ Telegram</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {feedback && (
        <div className="p-3 border border-[#10B981] bg-[#10B981]/10 text-xs font-mono text-[#10B981]">
          {feedback}
        </div>
      )}

      {/* SECTION 1: INDEPENDENT WEB FOLDER MANAGEMENT */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <form
          onSubmit={handleSaveFolder}
          className="lg:col-span-5 p-5 border border-[#27272A] bg-[#121215] space-y-4"
        >
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-mono uppercase tracking-wider text-[#10B981] flex items-center gap-2">
              <FolderPlus size={18} />
              <span>
                {editingFolderId
                  ? `Sửa Folder Web #${editingFolderId}`
                  : 'Tạo Folder Kịch Bản Độc Lập Trên Web'}
              </span>
            </h3>
            {editingFolderId && (
              <button
                type="button"
                onClick={() => handleStartEditFolder(undefined)}
                className="text-xs font-mono text-[#A1A1AA] hover:text-white cursor-pointer"
              >
                [Hủy sửa]
              </button>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="folder-name" className="block text-xs font-mono text-[#A1A1AA] mb-1">
                Tên Folder Web *
              </label>
              <input
                id="folder-name"
                type="text"
                value={folderName}
                onChange={(e) => setFolderName(e.target.value)}
                placeholder="VD: Folder Chạy Kịch Bản Khuyến Mãi"
                className="w-full px-3 py-2 text-sm"
                required
              />
            </div>
            <div>
              <label htmlFor="folder-desc" className="block text-xs font-mono text-[#A1A1AA] mb-1">
                Ghi chú kịch bản áp dụng
              </label>
              <input
                id="folder-desc"
                type="text"
                value={folderDesc}
                onChange={(e) => setFolderDesc(e.target.value)}
                placeholder="Độc lập với Folder trên ứng dụng Telegram"
                className="w-full px-3 py-2 text-sm"
              />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between text-xs font-mono text-[#A1A1AA] mb-1.5">
              <span>
                Tick chọn Nhóm & Topic đưa vào Folder ({Object.keys(selectedChatIds).length} nhóm):
              </span>
              <select
                value={filterAccountId}
                onChange={(e) => setFilterAccountId(e.target.value)}
                className="px-2 py-0.5 text-[11px] font-mono"
              >
                <option value="">Tất cả Nick ({chats.length} nhóm)</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    Lọc nhóm của #{a.id} {a.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="max-h-56 overflow-y-auto border border-[#27272A] bg-[#09090B] divide-y divide-[#27272A]">
              {filteredChats.length === 0 ? (
                <div className="p-3 text-xs font-mono text-[#A1A1AA]">
                  Chưa có nhóm nào. Hãy bấm &quot;Quét Nhóm &amp; Topic&quot; ở mục Tài khoản.
                </div>
              ) : (
                filteredChats.map((c) => {
                  const checked = c.chat_id in selectedChatIds;
                  return (
                    <div
                      key={c.chat_id}
                      className="p-2 flex items-center justify-between gap-2 text-xs"
                    >
                      <label className="flex items-center gap-2 cursor-pointer truncate">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => handleToggleChatInFolder(c.chat_id)}
                        />
                        <span className="truncate font-medium">{c.title}</span>
                        <span className="font-mono text-[#A1A1AA]">({c.chat_id})</span>
                      </label>
                      {checked &&
                        (c.topics && c.topics.length > 0 ? (
                          <select
                            value={selectedChatIds[c.chat_id] || 0}
                            onChange={(e) =>
                              handleSetTopicInFolder(c.chat_id, Number(e.target.value))
                            }
                            className="w-36 px-1.5 py-0.5 text-[11px] font-mono"
                          >
                            <option value={0}>Nhánh chung (0)</option>
                            {c.topics.map((tp) => (
                              <option key={tp.topic_id} value={tp.topic_id}>
                                #{tp.topic_id} · {tp.title}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <input
                            type="number"
                            value={selectedChatIds[c.chat_id] || 0}
                            onChange={(e) =>
                              handleSetTopicInFolder(c.chat_id, Number(e.target.value))
                            }
                            placeholder="Topic ID"
                            title="Topic ID (Để 0 nếu gửi vào nhánh chung)"
                            className="w-20 px-2 py-0.5 text-xs font-mono"
                          />
                        ))}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          <button
            type="submit"
            className="w-full py-2 bg-[#10B981] hover:bg-[#059669] text-[#052E16] font-bold text-xs font-mono uppercase cursor-pointer"
          >
            {editingFolderId ? 'Lưu Cập Nhật Folder Web' : 'Tạo Folder Kịch Bản Độc Lập'}
          </button>
        </form>

        {/* Folders List */}
        <div className="lg:col-span-7 border border-[#27272A] bg-[#121215] p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-mono uppercase tracking-wider text-[#F4F4F5]">
              Danh Sách Folder Độc Lập Trên Web ({folders.length})
            </h3>
            <span className="text-[11px] font-mono text-[#10B981]">
              1 Nhóm có thể nằm ở nhiều Folder để chạy nhiều Kịch bản khác nhau
            </span>
          </div>
          {folders.length === 0 ? (
            <p className="text-xs font-mono text-[#A1A1AA] py-8 text-center">
              Chưa có Folder nào. Bạn có thể tạo mới hoặc bấm &quot;Copy Folder từ Telegram sang
              Web&quot; ở góc phải bên trên.
            </p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {folders.map((f) => (
                <div
                  key={f.id}
                  className="p-4 border border-[#27272A] bg-[#18181C] flex flex-col justify-between gap-3"
                >
                  <div>
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-base text-[#10B981]">
                        #{f.id} · {f.name}
                      </span>
                      <span className="text-xs font-mono px-2 py-0.5 border border-[#27272A] bg-[#09090B]">
                        {f.chats.length} nhóm
                      </span>
                    </div>
                    {f.description && (
                      <p className="text-xs text-[#A1A1AA] mt-1">{f.description}</p>
                    )}
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {f.chats.slice(0, 6).map((fc) => (
                        <span
                          key={`${fc.chat_id}-${fc.topic_id}`}
                          className="text-[11px] font-mono px-2 py-0.5 bg-[#09090B] border border-[#27272A]"
                        >
                          {fc.title || fc.chat_id}
                          {fc.topic_id ? ` (Topic #${fc.topic_id})` : ''}
                        </span>
                      ))}
                      {f.chats.length > 6 && (
                        <span className="text-[11px] font-mono text-[#A1A1AA]">
                          +{f.chats.length - 6} nhóm khác
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-wrap justify-end gap-2 pt-2 border-t border-[#27272A]">
                    <button
                      type="button"
                      disabled={batchAnalyzing || f.chats.length === 0}
                      onClick={() =>
                        handleBatchAnalyzeHistory(
                          f.chats.map((c) => c.chat_id),
                          `Folder ${f.name}`,
                        )
                      }
                      className="px-2.5 py-1 border border-[#F59E0B] text-[#F59E0B] hover:bg-[#F59E0B]/15 text-xs font-mono flex items-center gap-1 cursor-pointer disabled:opacity-40"
                      title="Quét 1.000 tin nhắn gần nhất của mọi nhóm trong Folder này để phát hiện quyền gửi Link/Forward/Sticker/Tag Bot của User thường"
                    >
                      <MagnifyingGlass size={13} />
                      <span>Check 1K Tin Folder</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleStartEditFolder(f)}
                      className="px-2.5 py-1 border border-[#27272A] hover:border-[#10B981] text-xs font-mono cursor-pointer"
                    >
                      Chỉnh sửa / Thêm bớt nhóm
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        if (window.confirm(`Xóa Folder "${f.name}"?`)) {
                          await api.deleteFolder(f.id);
                          onRefresh();
                        }
                      }}
                      className="px-2 py-1 border border-[#27272A] hover:border-[#EF4444] text-[#EF4444] text-xs font-mono cursor-pointer"
                    >
                      <Trash size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* SECTION 2: GROUP EXPLORER BY ACCOUNT & RULE MATRIX */}
      <div className="border border-[#27272A] bg-[#121215] p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h3 className="text-base font-bold flex items-center gap-2">
              <ShieldCheck size={20} className="text-[#10B981]" />
              <span>
                Khám Phá Nhóm Theo Tài Khoản, Forum Topics & Ma Trận Rule Cấm ({filteredChats.length}{' '}
                nhóm)
              </span>
            </h3>
            <p className="text-xs text-[#A1A1AA]">
              Chọn tài khoản để xem tài khoản đó đang ở những nhóm nào, quyền hạn gì, có những
              Topic nào và bật/tắt Rule cấm tương ứng.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleReloadFromDb}
              className="px-2.5 py-1.5 border border-[#27272A] hover:border-[#10B981] text-xs font-mono flex items-center gap-1 cursor-pointer"
              title="Tải lại danh sách nhóm"
            >
              <ArrowsClockwise size={14} className={reloadingChats ? 'animate-spin text-[#10B981]' : ''} />
              <span>Reload</span>
            </button>
            <select
              value={filterAccountId}
              onChange={(e) => setFilterAccountId(e.target.value)}
              className="px-3 py-1.5 text-xs font-mono"
            >
              <option value="">-- Xem tất cả Nhóm của mọi Nick --</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  Chỉ hiện nhóm của Nick #{a.id} · {a.label} ({a.joined_groups_count ?? 0})
                </option>
              ))}
            </select>
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Tìm tên nhóm, @username hoặc ID..."
              className="px-3 py-1.5 text-xs font-mono w-64"
            />
          </div>
        </div>

        {/* 1,000-MESSAGE NORMAL USER PERMISSION ANALYZER BAR */}
        <div className="p-3.5 border border-[#F59E0B]/60 bg-[#18181C] flex flex-wrap items-center justify-between gap-3 text-xs font-mono">
          <div className="space-y-1">
            <div className="text-[#F59E0B] font-bold flex items-center gap-1.5">
              <MagnifyingGlass size={16} weight="bold" />
              <span>
                TỰ ĐỘNG CHECK 1.000 TIN NHẮN GẦN NHẤT CỦA NHÓM (Suy luận quyền thực tế từ User
                thường)
              </span>
            </div>
            <div className="text-[11px] text-[#A1A1AA]">
              Hệ thống tự loại trừ tin nhắn của Admin/Chủ nhóm/Bot và kiểm tra trong 1.000 tin gần
              nhất xem các <strong>member thường khác</strong> có gửi được{' '}
              <span className="text-[#10B981]">Link, Forward, Sticker, Media, Tag @Bot</span> mà
              không bị xóa hay không. Nếu member thường gửi được ➔ Mình cũng gửi được (tự động mở
              khóa Rule)!
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span className="text-[#A1A1AA]">Số tin quét:</span>
              <input
                type="number"
                min={50}
                max={3000}
                step={100}
                value={historyScanLimit}
                onChange={(e) => setHistoryScanLimit(Number(e.target.value) || 1000)}
                className="w-20 px-2 py-1 text-xs font-mono text-center"
              />
            </div>

            <label
              className="flex items-center gap-1.5 cursor-pointer text-[#A1A1AA]"
              title="Nếu bật: Khi nhóm có trên 30 tin của member thường mà hoàn toàn 0 có ai gửi Link/Forward nào còn sót lại, hệ thống sẽ tự bật cờ nghi cấm"
            >
              <input
                type="checkbox"
                checked={strictInferBlocks}
                onChange={(e) => setStrictInferBlocks(e.target.checked)}
              />
              <span>Tự khóa nếu 0% member gửi</span>
            </label>

            <button
              type="button"
              disabled={batchAnalyzing || filteredChats.length === 0}
              onClick={() =>
                handleBatchAnalyzeHistory(
                  filteredChats.map((c) => c.chat_id),
                  `${filteredChats.length} nhóm đang hiển thị`,
                )
              }
              className="px-3.5 py-1.5 bg-[#F59E0B] text-[#09090B] font-bold font-mono flex items-center gap-1.5 cursor-pointer disabled:opacity-40"
            >
              <MagnifyingGlass size={14} weight="bold" />
              <span>
                {batchAnalyzing
                  ? 'Đang quét 1K tin...'
                  : `Check ${historyScanLimit} Tin Cho Tất Cả (${filteredChats.length} Nhóm)`}
              </span>
            </button>
          </div>
        </div>

        {/* 1,000-Message Analysis Results Drawer */}
        {analysisResults.length > 0 && (
          <div className="p-4 border-2 border-[#10B981] bg-[#09090B] space-y-3 text-xs font-mono">
            <div className="flex items-center justify-between">
              <span className="text-[#10B981] font-bold uppercase">
                📊 Kết Quả Phân Tích Lịch Sử Tin Nhắn Của User Thường ({analysisResults.length} nhóm):
              </span>
              <button
                type="button"
                onClick={() => setAnalysisResults([])}
                className="text-[#A1A1AA] hover:text-white cursor-pointer"
              >
                [Đóng kết quả]
              </button>
            </div>
            <div className="max-h-60 overflow-y-auto divide-y divide-[#27272A]">
              {analysisResults.map((r) => {
                const chatObj = chats.find((c) => c.chat_id === r.chat_id);
                return (
                  <div key={r.chat_id} className="py-2.5 flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <span className="font-bold text-[#F4F4F5]">
                        {chatObj?.title || `Chat ${r.chat_id}`}
                      </span>{' '}
                      <span className="text-[#A1A1AA]">
                        (Quét {r.total_messages_scanned} tin · {r.normal_user_messages} tin của{' '}
                        {r.unique_normal_users_count} User thường · Bỏ qua{' '}
                        {r.admin_or_bot_messages_skipped} tin Admin/Bot)
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span
                        className={`px-2 py-0.5 border ${
                          r.observed_counts.links > 0
                            ? 'border-[#10B981] text-[#10B981]'
                            : 'border-[#27272A] text-[#A1A1AA]'
                        }`}
                      >
                        Link: {r.observed_counts.links}
                      </span>
                      <span
                        className={`px-2 py-0.5 border ${
                          r.observed_counts.forwards > 0
                            ? 'border-[#10B981] text-[#10B981]'
                            : 'border-[#27272A] text-[#A1A1AA]'
                        }`}
                      >
                        Forward: {r.observed_counts.forwards}
                      </span>
                      <span
                        className={`px-2 py-0.5 border ${
                          r.observed_counts.stickers > 0
                            ? 'border-[#10B981] text-[#10B981]'
                            : 'border-[#27272A] text-[#A1A1AA]'
                        }`}
                      >
                        Sticker: {r.observed_counts.stickers}
                      </span>
                      <span
                        className={`px-2 py-0.5 border ${
                          r.observed_counts.media > 0
                            ? 'border-[#10B981] text-[#10B981]'
                            : 'border-[#27272A] text-[#A1A1AA]'
                        }`}
                      >
                        Media: {r.observed_counts.media}
                      </span>
                      <span
                        className={`px-2 py-0.5 border ${
                          r.observed_counts.bot_mentions > 0
                            ? 'border-[#10B981] text-[#10B981]'
                            : 'border-[#27272A] text-[#A1A1AA]'
                        }`}
                      >
                        Tag @Bot: {r.observed_counts.bot_mentions}
                      </span>
                      {r.unlocked_permissions.length > 0 && (
                        <span className="px-2 py-0.5 bg-[#10B981] text-[#052E16] font-bold">
                          ✓ {r.unlocked_permissions.join(', ')}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Manual Quick Add Chat */}
        <form
          onSubmit={handleAddChat}
          className="p-3 border border-[#27272A] bg-[#18181C] flex flex-wrap items-end gap-3"
        >
          <div>
            <label htmlFor="manual-chat-id" className="block text-[11px] font-mono text-[#A1A1AA]">
              Chat ID (Chỉ dùng khi muốn thêm thủ công)
            </label>
            <input
              id="manual-chat-id"
              type="number"
              value={newChatId}
              onChange={(e) => setNewChatId(e.target.value)}
              placeholder="-100..."
              className="px-2.5 py-1.5 text-xs font-mono w-48"
              required
            />
          </div>
          <div className="flex-1 min-w-[200px]">
            <label
              htmlFor="manual-chat-title"
              className="block text-[11px] font-mono text-[#A1A1AA]"
            >
              Tên Nhóm / Kênh
            </label>
            <input
              id="manual-chat-title"
              type="text"
              value={newChatTitle}
              onChange={(e) => setNewChatTitle(e.target.value)}
              placeholder="Nhập tên nhóm..."
              className="px-2.5 py-1.5 text-xs w-full"
              required
            />
          </div>
          <div>
            <label
              htmlFor="manual-chat-type"
              className="block text-[11px] font-mono text-[#A1A1AA]"
            >
              Loại hình
            </label>
            <select
              id="manual-chat-type"
              value={newChatType}
              onChange={(e) => setNewChatType(e.target.value)}
              className="px-2.5 py-1.5 text-xs font-mono"
            >
              <option value="supergroup">Supergroup</option>
              <option value="forum">Forum (Có Topic)</option>
              <option value="channel">Channel</option>
              <option value="group">Group thường</option>
            </select>
          </div>
          <button
            type="submit"
            className="px-4 py-1.5 bg-[#10B981] text-[#052E16] font-bold text-xs font-mono flex items-center gap-1 cursor-pointer"
          >
            <Plus size={14} weight="bold" />
            <span>Thêm Nhóm Thủ Công</span>
          </button>
        </form>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-[#27272A] bg-[#18181C] font-mono uppercase text-[#A1A1AA]">
                <th className="py-2.5 px-3">Nhóm / Nick Đã Tham Gia / Topics</th>
                <th className="py-2.5 px-3">Các Quy Tắc Cấm (Click để Bật/Tắt)</th>
                <th className="py-2.5 px-3">SlowMode & Từ Cấm Riêng</th>
                <th className="py-2.5 px-3 text-right">Thao Tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#27272A]">
              {filteredChats.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-8 text-center font-mono text-[#A1A1AA]">
                    Chưa có nhóm nào khớp bộ lọc.
                  </td>
                </tr>
              ) : (
                filteredChats.map((chat) => (
                  <tr key={chat.chat_id} className="hover:bg-[#18181C]/50">
                    <td className="py-3 px-3 space-y-1">
                      <div className="font-semibold text-sm text-[#F4F4F5] flex flex-wrap items-center gap-2">
                        <span>{chat.title}</span>
                        {chat.username && (
                          <span className="text-xs font-mono text-[#10B981]">@{chat.username}</span>
                        )}
                        {chat.rules.auto_learned && (
                          <span
                            title={chat.rules.notes || 'Đã tự động học quy tắc từ Telegram'}
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-mono border border-[#F59E0B] text-[#F59E0B]"
                          >
                            <Robot size={12} />
                            AUTO-LEARNED
                          </span>
                        )}
                      </div>
                      <div className="font-mono text-[#A1A1AA]">
                        ID: <span className="select-all text-[#F4F4F5]">{chat.chat_id}</span> ·{' '}
                        {chat.chat_type.toUpperCase()}
                        {chat.participants_count ? ` · ${chat.participants_count} TV` : ''}
                      </div>

                      {/* Member Accounts Badges (Feature #1) */}
                      {chat.member_accounts && chat.member_accounts.length > 0 && (
                        <div className="flex flex-wrap gap-1 pt-0.5">
                          {chat.member_accounts.map((m) => (
                            <span
                              key={m.account_id}
                              className="px-1.5 py-0.5 text-[10px] font-mono bg-[#09090B] border border-[#27272A] text-[#10B981]"
                            >
                              ✓ #{m.account_id} {m.account_label || ''} ({m.role})
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Forum Topics Badges (Feature #2) */}
                      {chat.topics && chat.topics.length > 0 && (
                        <div className="flex flex-wrap gap-1 pt-0.5">
                          {chat.topics.map((tp) => (
                            <span
                              key={tp.topic_id}
                              className="px-1.5 py-0.5 text-[10px] font-mono bg-[#18181C] border border-[#F59E0B]/40 text-[#F59E0B]"
                            >
                              #Topic {tp.topic_id}: {tp.title}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="py-3 px-3">
                      <div className="flex flex-wrap gap-1.5">
                        {RULE_FLAGS.map((rf) => {
                          const active = chat.rules[rf.key];
                          return (
                            <button
                              key={rf.key}
                              type="button"
                              title={rf.desc}
                              onClick={() => handleToggleRule(chat, rf.key)}
                              className={`px-2.5 py-1 font-mono text-[11px] border transition-colors cursor-pointer ${
                                active
                                  ? 'border-[#F59E0B] bg-[#F59E0B]/20 text-[#F59E0B] font-bold'
                                  : 'border-[#27272A] bg-[#09090B] text-[#A1A1AA] hover:border-[#F4F4F5]'
                              }`}
                            >
                              {active ? `⛔ ${rf.label}` : `✓ ${rf.label}`}
                            </button>
                          );
                        })}
                      </div>
                    </td>
                    <td className="py-3 px-3">
                      <div className="flex items-center gap-2">
                        <input
                          type="number"
                          defaultValue={chat.rules.slow_mode_seconds}
                          onBlur={(e) =>
                            handleUpdateSlowModeOrBannedWords(
                              chat,
                              Number(e.target.value) || 0,
                              chat.rules.banned_words.join(', '),
                            )
                          }
                          title="SlowMode (giây)"
                          className="w-16 px-2 py-1 font-mono text-xs"
                        />
                        <span className="font-mono text-[#A1A1AA]">s</span>
                        <input
                          type="text"
                          defaultValue={chat.rules.banned_words.join(', ')}
                          onBlur={(e) =>
                            handleUpdateSlowModeOrBannedWords(
                              chat,
                              chat.rules.slow_mode_seconds,
                              e.target.value,
                            )
                          }
                          placeholder="Từ cấm (cách nhau dấu phẩy)"
                          className="px-2 py-1 font-mono text-xs flex-1 min-w-[140px]"
                        />
                      </div>
                    </td>
                    <td className="py-3 px-3 text-right">
                      <div className="inline-flex flex-wrap items-center justify-end gap-1.5">
                        <button
                          type="button"
                          disabled={analyzingChatId === chat.chat_id}
                          onClick={() => handleAnalyzeChatHistory(chat)}
                          title={`Quét ${historyScanLimit} tin nhắn gần nhất của nhóm này để xem User thường có gửi được Link, Forward, Sticker, Tag Bot không`}
                          className="px-2 py-1 border border-[#F59E0B] bg-[#09090B] hover:bg-[#F59E0B]/15 text-[#F59E0B] font-mono text-[11px] flex items-center gap-1 cursor-pointer disabled:opacity-50"
                        >
                          <MagnifyingGlass size={12} />
                          <span>
                            {analyzingChatId === chat.chat_id ? 'Đang quét...' : 'Check 1K Tin'}
                          </span>
                        </button>
                        <button
                          type="button"
                          onClick={() => handleScanTopicsForChat(chat)}
                          title="Quét danh sách Forum Topics của nhóm này"
                          className="px-2 py-1 border border-[#27272A] bg-[#09090B] hover:border-[#10B981] font-mono text-[11px] flex items-center gap-1 cursor-pointer"
                        >
                          <Hash size={12} className="text-[#10B981]" />
                          <span>Topics</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => handleCreateTopicPrompt(chat)}
                          title="Tạo Topic mới trên nhóm Forum này"
                          className="px-2 py-1 border border-[#27272A] bg-[#09090B] hover:border-[#F59E0B] text-[#F59E0B] font-mono text-[11px] cursor-pointer"
                        >
                          +Topic
                        </button>
                        <button
                          type="button"
                          onClick={async () => {
                            if (window.confirm(`Xóa nhóm "${chat.title}"?`)) {
                              await api.deleteChat(chat.chat_id);
                              onRefresh();
                            }
                          }}
                          className="p-1.5 border border-[#27272A] hover:border-[#EF4444] text-[#EF4444] cursor-pointer"
                        >
                          <Trash size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
