import React, { useEffect, useState } from 'react';
import {
  ArrowsClockwise,
  CloudArrowDown,
  Play,
  Plus,
  Trash,
} from '@phosphor-icons/react';
import { api } from '../lib/api';
import type { Account, BackupJob, ChatGroup, SyncStateItem } from '../types';

interface BackupJobsViewProps {
  accounts: Account[];
  chats: ChatGroup[];
  backups: BackupJob[];
  onRefresh: () => void;
}

export const BackupJobsView: React.FC<BackupJobsViewProps> = ({
  accounts,
  chats,
  backups,
  onRefresh,
}) => {
  const [label, setLabel] = useState('');
  const [readerAccountId, setReaderAccountId] = useState<number>(accounts[0]?.id || 1);
  const [senderAccountId, setSenderAccountId] = useState<number>(accounts[0]?.id || 1);
  const [sourceChatId, setSourceChatId] = useState('');
  const [sourceTopicId, setSourceTopicId] = useState('');
  const [destChatId, setDestChatId] = useState('');
  const [destTopicDefault, setDestTopicDefault] = useState('0');
  const [destTopicArchive, setDestTopicArchive] = useState('0');

  // Content type filters
  const [syncDocuments, setSyncDocuments] = useState(true);
  const [allowedExts, setAllowedExts] = useState('.txt, .zip, .rar');
  const [archiveExts, setArchiveExts] = useState('.zip, .rar, .7z');
  const [syncPhotos, setSyncPhotos] = useState(false);
  const [syncVideos, setSyncVideos] = useState(false);
  const [syncText, setSyncText] = useState(false);
  const [syncStickers, setSyncStickers] = useState(false);
  const [syncVoice, setSyncVoice] = useState(false);
  const [includeKeywords, setIncludeKeywords] = useState('');
  const [excludeKeywords, setExcludeKeywords] = useState('');
  const [captionMode, setCaptionMode] = useState<
    'preserve' | 'strip' | 'strip_for_txt' | 'custom_template'
  >('strip_for_txt');
  const [dedupeEnabled, setDedupeEnabled] = useState(true);
  const [contentHashDedupe, setContentHashDedupe] = useState(true);
  const [allowProtectedFallback, setAllowProtectedFallback] = useState(true);

  // Advanced Phase 2 Filters: Range, Rename & Watermark (Features #15, #16)
  const [minMsgId, setMinMsgId] = useState('');
  const [maxMsgId, setMaxMsgId] = useState('');
  const [minDateIso, setMinDateIso] = useState('');
  const [maxDateIso, setMaxDateIso] = useState('');
  const [renamePrefix, setRenamePrefix] = useState('');
  const [renameSuffix, setRenameSuffix] = useState('');
  const [captionWatermark, setCaptionWatermark] = useState('');

  const [history, setHistory] = useState<SyncStateItem[]>([]);
  const [selectedJobFilter, setSelectedJobFilter] = useState<number | undefined>(undefined);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [runningJobId, setRunningJobId] = useState<number | null>(null);

  const loadHistory = async (jobId?: number) => {
    try {
      const items = await api.listBackupHistory({ backup_job_id: jobId, limit: 100 });
      setHistory(items);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    loadHistory(selectedJobFilter);
  }, [selectedJobFilter, backups]);

  // Filter chats available to Reader and Sender accounts
  const readerChats = chats.filter(
    (c) =>
      !c.member_accounts?.length ||
      c.member_accounts.some((m) => m.account_id === Number(readerAccountId)) ||
      c.discovered_by_account_id === Number(readerAccountId),
  );
  const senderChats = chats.filter(
    (c) =>
      !c.member_accounts?.length ||
      c.member_accounts.some((m) => m.account_id === Number(senderAccountId)) ||
      c.discovered_by_account_id === Number(senderAccountId),
  );

  const selectedSourceChat = chats.find((c) => String(c.chat_id) === sourceChatId.trim());
  const selectedDestChat = chats.find((c) => String(c.chat_id) === destChatId.trim());

  const handleQuickCreateDestTopic = async (targetField: 'default' | 'archive') => {
    if (!destChatId.trim()) {
      setFeedback('Vui lòng chọn Nhóm Đích trước khi tạo Topic mới.');
      return;
    }
    const title = window.prompt('Nhập tên Forum Topic mới cần tạo trên Nhóm Đích:');
    if (!title || !title.trim()) return;
    try {
      const created = await api.createForumTopic(Number(destChatId.trim()), {
        title: title.trim(),
        account_id: Number(senderAccountId),
      });
      if (targetField === 'default') {
        setDestTopicDefault(String(created.topic_id));
      } else {
        setDestTopicArchive(String(created.topic_id));
      }
      setFeedback(`Đã tạo Topic "${created.title}" (#${created.topic_id}) và tự động điền ID!`);
      onRefresh();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : 'Lỗi tạo Topic mới');
    }
  };

  const handleCreateBackup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!label.trim() || !sourceChatId.trim() || !destChatId.trim()) return;
    const parseList = (str: string) =>
      str
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

    try {
      await api.createBackup({
        label: label.trim(),
        enabled: true,
        reader_account_id: Number(readerAccountId),
        sender_account_id: Number(senderAccountId || readerAccountId),
        source_chat_id: Number(sourceChatId.trim()),
        source_topic_id: sourceTopicId.trim() ? Number(sourceTopicId.trim()) : null,
        dest_chat_id: Number(destChatId.trim()),
        dest_topic_default: Number(destTopicDefault) || 0,
        dest_topic_archive: Number(destTopicArchive) || 0,
        caption_mode: captionMode,
        dedupe_enabled: dedupeEnabled,
        allow_protected_fallback: allowProtectedFallback,
        filter_config: {
          sync_documents: syncDocuments,
          allowed_extensions: parseList(allowedExts),
          archive_extensions: parseList(archiveExts),
          sync_photos: syncPhotos,
          sync_videos: syncVideos,
          sync_text: syncText,
          sync_stickers: syncStickers,
          sync_voice: syncVoice,
          include_keywords: parseList(includeKeywords),
          exclude_keywords: parseList(excludeKeywords),
          min_msg_id: minMsgId.trim() ? Number(minMsgId.trim()) : null,
          max_msg_id: maxMsgId.trim() ? Number(maxMsgId.trim()) : null,
          min_date_iso: minDateIso.trim() || null,
          max_date_iso: maxDateIso.trim() || null,
          content_hash_dedupe: contentHashDedupe,
          rename_prefix: renamePrefix.trim(),
          rename_suffix: renameSuffix.trim(),
          caption_watermark: captionWatermark.trim(),
        },
      });
      setLabel('');
      setFeedback('Đã tạo luồng Backup thành công!');
      onRefresh();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : 'Lỗi tạo luồng Backup');
    }
  };

  const handleRunNow = async (jobId: number) => {
    setRunningJobId(jobId);
    setFeedback(null);
    try {
      const res = await api.runBackupNow(jobId, 200);
      setFeedback(
        `Đã đồng bộ luồng #${jobId}: Synced=${res.synced ?? 0}, Skipped=${res.skipped ?? 0}, Failed=${res.failed ?? 0}`,
      );
      onRefresh();
      await loadHistory(selectedJobFilter);
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : 'Lỗi chạy đồng bộ');
    } finally {
      setRunningJobId(null);
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#27272A] pb-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">
            Hệ Thống Backup Mở Rộng Toàn Diện (Chọn Nhóm/Topic Trực Quan + SHA-256 Dedupe)
          </h2>
          <p className="text-sm text-[#A1A1AA]">
            Chọn trực tiếp Nhóm Nguồn & Nhóm Đích từ danh sách nhóm mà từng Nick đã tham gia, chọn
            hoặc tạo mới Forum Topic ngay trên Web, lọc theo Khoảng Ngày / Message ID, tự động đổi tên
            file (Prefix/Suffix), gắn Watermark Caption và chống trùng lặp bằng cả Metadata + SHA-256
            Content Hash.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            onRefresh();
            loadHistory(selectedJobFilter);
            setFeedback('Đã tải lại danh sách Nhóm & Luồng Backup mới nhất!');
          }}
          className="px-3.5 py-2 border border-[#27272A] hover:border-[#10B981] text-[#F4F4F5] text-xs font-mono flex items-center gap-1.5 cursor-pointer"
        >
          <ArrowsClockwise size={15} />
          <span>Reload Nhóm & Backup</span>
        </button>
      </div>

      {feedback && (
        <div className="p-3 border border-[#10B981] bg-[#10B981]/10 text-xs font-mono text-[#10B981]">
          {feedback}
        </div>
      )}

      {/* Create Backup Flow Form */}
      <form
        onSubmit={handleCreateBackup}
        className="p-5 border border-[#27272A] bg-[#121215] space-y-5"
      >
        <h3 className="text-sm font-mono uppercase tracking-wider text-[#10B981] flex items-center gap-2">
          <Plus size={16} weight="bold" />
          <span>Thiết Lập Luồng Backup Mới (Visual Group & Topic Picker)</span>
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label htmlFor="bk-label" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              Tên Luồng Backup *
            </label>
            <input
              id="bk-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="VD: Backup ULP & Archive sang Kho"
              className="w-full px-3 py-2 text-sm"
              required
            />
          </div>
          <div>
            <label htmlFor="bk-reader" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              1. Chọn Tài khoản Đọc Nguồn (Reader) *
            </label>
            <select
              id="bk-reader"
              value={readerAccountId}
              onChange={(e) => setReaderAccountId(Number(e.target.value))}
              className="w-full px-3 py-2 text-sm font-mono"
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  #{a.id} · {a.label} ({a.joined_groups_count ?? 0} nhóm)
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="bk-sender" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              2. Chọn Tài khoản Đẩy Đích (Sender)
            </label>
            <select
              id="bk-sender"
              value={senderAccountId}
              onChange={(e) => setSenderAccountId(Number(e.target.value))}
              className="w-full px-3 py-2 text-sm font-mono"
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  #{a.id} · {a.label} ({a.joined_groups_count ?? 0} nhóm)
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Visual Source & Destination Pickers (Features #1, #2, #13) */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Source Box */}
          <div className="p-3.5 border border-[#27272A] bg-[#09090B] space-y-3">
            <div className="text-xs font-mono text-[#10B981] uppercase font-bold">
              Nguồn Backup (Các nhóm Nick Reader #{readerAccountId} đã tham gia):
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] font-mono text-[#A1A1AA] mb-1">
                  Chọn nhanh từ danh sách Nhóm Nguồn:
                </label>
                <select
                  value={sourceChatId}
                  onChange={(e) => setSourceChatId(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs font-mono"
                >
                  <option value="">-- Chọn Nhóm Nguồn ({readerChats.length}) --</option>
                  {readerChats.map((c) => (
                    <option key={c.chat_id} value={String(c.chat_id)}>
                      {c.title} ({c.chat_id})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="bk-src-chat" className="block text-[11px] font-mono text-[#A1A1AA] mb-1">
                  Hoặc nhập Source Chat ID *:
                </label>
                <input
                  id="bk-src-chat"
                  type="number"
                  value={sourceChatId}
                  onChange={(e) => setSourceChatId(e.target.value)}
                  placeholder="VD: -1003488087171"
                  className="w-full px-2.5 py-1.5 text-xs font-mono"
                  required
                />
              </div>
            </div>
            <div>
              <label htmlFor="bk-src-topic" className="block text-[11px] font-mono text-[#A1A1AA] mb-1">
                Topic Nguồn (Để trống = Lấy toàn bộ nhóm nguồn):
              </label>
              {selectedSourceChat?.topics && selectedSourceChat.topics.length > 0 ? (
                <select
                  id="bk-src-topic"
                  value={sourceTopicId}
                  onChange={(e) => setSourceTopicId(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs font-mono"
                >
                  <option value="">Lấy tất cả Topics trong nhóm nguồn</option>
                  {selectedSourceChat.topics.map((tp) => (
                    <option key={tp.topic_id} value={String(tp.topic_id)}>
                      Topic #{tp.topic_id} · {tp.title}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  id="bk-src-topic"
                  type="number"
                  value={sourceTopicId}
                  onChange={(e) => setSourceTopicId(e.target.value)}
                  placeholder="Để trống = cả nhóm"
                  className="w-full px-2.5 py-1.5 text-xs font-mono"
                />
              )}
            </div>
          </div>

          {/* Destination Box */}
          <div className="p-3.5 border border-[#27272A] bg-[#09090B] space-y-3">
            <div className="text-xs font-mono text-[#F59E0B] uppercase font-bold">
              Đích Lưu Trữ (Các nhóm Nick Sender #{senderAccountId} đã tham gia):
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] font-mono text-[#A1A1AA] mb-1">
                  Chọn nhanh từ danh sách Nhóm Đích:
                </label>
                <select
                  value={destChatId}
                  onChange={(e) => setDestChatId(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs font-mono"
                >
                  <option value="">-- Chọn Nhóm Đích ({senderChats.length}) --</option>
                  {senderChats.map((c) => (
                    <option key={c.chat_id} value={String(c.chat_id)}>
                      {c.title} ({c.chat_id})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="bk-dest-chat" className="block text-[11px] font-mono text-[#A1A1AA] mb-1">
                  Hoặc nhập Dest Chat ID *:
                </label>
                <input
                  id="bk-dest-chat"
                  type="number"
                  value={destChatId}
                  onChange={(e) => setDestChatId(e.target.value)}
                  placeholder="VD: -1001878033586"
                  className="w-full px-2.5 py-1.5 text-xs font-mono"
                  required
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label htmlFor="bk-dest-def" className="text-[11px] font-mono text-[#A1A1AA]">
                    Topic Mặc Định:
                  </label>
                  <button
                    type="button"
                    onClick={() => handleQuickCreateDestTopic('default')}
                    className="text-[10px] font-mono text-[#10B981] hover:underline cursor-pointer"
                  >
                    + Tạo Topic Mới
                  </button>
                </div>
                {selectedDestChat?.topics && selectedDestChat.topics.length > 0 ? (
                  <select
                    id="bk-dest-def"
                    value={destTopicDefault}
                    onChange={(e) => setDestTopicDefault(e.target.value)}
                    className="w-full px-2.5 py-1.5 text-xs font-mono"
                  >
                    <option value="0">Nhánh chung (0)</option>
                    {selectedDestChat.topics.map((tp) => (
                      <option key={tp.topic_id} value={String(tp.topic_id)}>
                        Topic #{tp.topic_id} · {tp.title}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    id="bk-dest-def"
                    type="number"
                    value={destTopicDefault}
                    onChange={(e) => setDestTopicDefault(e.target.value)}
                    className="w-full px-2.5 py-1.5 text-xs font-mono"
                  />
                )}
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label htmlFor="bk-dest-arch" className="text-[11px] font-mono text-[#A1A1AA]">
                    Topic Lưu File Nén (.zip/.rar):
                  </label>
                  <button
                    type="button"
                    onClick={() => handleQuickCreateDestTopic('archive')}
                    className="text-[10px] font-mono text-[#F59E0B] hover:underline cursor-pointer"
                  >
                    + Tạo Topic Mới
                  </button>
                </div>
                {selectedDestChat?.topics && selectedDestChat.topics.length > 0 ? (
                  <select
                    id="bk-dest-arch"
                    value={destTopicArchive}
                    onChange={(e) => setDestTopicArchive(e.target.value)}
                    className="w-full px-2.5 py-1.5 text-xs font-mono"
                  >
                    <option value="0">Giống Topic Mặc Định (0)</option>
                    {selectedDestChat.topics.map((tp) => (
                      <option key={tp.topic_id} value={String(tp.topic_id)}>
                        Topic #{tp.topic_id} · {tp.title}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    id="bk-dest-arch"
                    type="number"
                    value={destTopicArchive}
                    onChange={(e) => setDestTopicArchive(e.target.value)}
                    className="w-full px-2.5 py-1.5 text-xs font-mono"
                  />
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Content Type Toggles & Advanced Filters */}
        <div className="p-4 border border-[#27272A] bg-[#09090B] space-y-4">
          <div className="text-xs font-mono uppercase text-[#A1A1AA]">
            Loại Nội Dung Cần Backup (Mở rộng toàn diện):
          </div>
          <div className="flex flex-wrap gap-4 text-xs font-mono">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={syncDocuments}
                onChange={(e) => setSyncDocuments(e.target.checked)}
              />
              <span>Tài liệu / File (Documents)</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={syncPhotos}
                onChange={(e) => setSyncPhotos(e.target.checked)}
              />
              <span>Hình ảnh (Photos)</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={syncVideos}
                onChange={(e) => setSyncVideos(e.target.checked)}
              />
              <span>Video</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={syncText}
                onChange={(e) => setSyncText(e.target.checked)}
              />
              <span>Tin nhắn Văn bản (Text)</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={syncStickers}
                onChange={(e) => setSyncStickers(e.target.checked)}
              />
              <span>Sticker</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={syncVoice}
                onChange={(e) => setSyncVoice(e.target.checked)}
              />
              <span>Voice / Audio</span>
            </label>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 pt-2">
            <div>
              <label htmlFor="bk-exts" className="block text-[11px] font-mono text-[#A1A1AA] mb-1">
                Đuôi File Cho Phép (Trống = Tất cả)
              </label>
              <input
                id="bk-exts"
                type="text"
                value={allowedExts}
                onChange={(e) => setAllowedExts(e.target.value)}
                placeholder=".txt, .zip, .rar, .pdf"
                className="w-full px-2.5 py-1.5 text-xs font-mono"
              />
            </div>
            <div>
              <label
                htmlFor="bk-arch-exts"
                className="block text-[11px] font-mono text-[#A1A1AA] mb-1"
              >
                Đuôi File đẩy vào Topic Archive
              </label>
              <input
                id="bk-arch-exts"
                type="text"
                value={archiveExts}
                onChange={(e) => setArchiveExts(e.target.value)}
                placeholder=".zip, .rar, .7z"
                className="w-full px-2.5 py-1.5 text-xs font-mono"
              />
            </div>
            <div>
              <label
                htmlFor="bk-inc-kw"
                className="block text-[11px] font-mono text-[#A1A1AA] mb-1"
              >
                Từ khóa Bắt buộc (Cách nhau dấu phẩy)
              </label>
              <input
                id="bk-inc-kw"
                type="text"
                value={includeKeywords}
                onChange={(e) => setIncludeKeywords(e.target.value)}
                placeholder="Để trống = lấy hết"
                className="w-full px-2.5 py-1.5 text-xs font-mono"
              />
            </div>
            <div>
              <label
                htmlFor="bk-exc-kw"
                className="block text-[11px] font-mono text-[#A1A1AA] mb-1"
              >
                Từ khóa Loại trừ (Bỏ qua nếu gặp)
              </label>
              <input
                id="bk-exc-kw"
                type="text"
                value={excludeKeywords}
                onChange={(e) => setExcludeKeywords(e.target.value)}
                placeholder="VD: quảng cáo, rác"
                className="w-full px-2.5 py-1.5 text-xs font-mono"
              />
            </div>
          </div>

          {/* Date Range, Message ID Range, Auto-Rename & Watermark (Features #15, #16) */}
          <div className="grid grid-cols-2 md:grid-cols-7 gap-3 pt-2 border-t border-[#27272A]">
            <div>
              <label className="block text-[10px] font-mono text-[#A1A1AA] mb-1">
                Từ Msg ID (Min)
              </label>
              <input
                type="number"
                value={minMsgId}
                onChange={(e) => setMinMsgId(e.target.value)}
                placeholder="VD: 100"
                className="w-full px-2 py-1 text-xs font-mono"
              />
            </div>
            <div>
              <label className="block text-[10px] font-mono text-[#A1A1AA] mb-1">
                Đến Msg ID (Max)
              </label>
              <input
                type="number"
                value={maxMsgId}
                onChange={(e) => setMaxMsgId(e.target.value)}
                placeholder="VD: 5000"
                className="w-full px-2 py-1 text-xs font-mono"
              />
            </div>
            <div>
              <label className="block text-[10px] font-mono text-[#A1A1AA] mb-1">
                Từ Ngày (YYYY-MM-DD)
              </label>
              <input
                type="date"
                value={minDateIso}
                onChange={(e) => setMinDateIso(e.target.value)}
                className="w-full px-2 py-1 text-xs font-mono"
              />
            </div>
            <div>
              <label className="block text-[10px] font-mono text-[#A1A1AA] mb-1">
                Đến Ngày (YYYY-MM-DD)
              </label>
              <input
                type="date"
                value={maxDateIso}
                onChange={(e) => setMaxDateIso(e.target.value)}
                className="w-full px-2 py-1 text-xs font-mono"
              />
            </div>
            <div>
              <label className="block text-[10px] font-mono text-[#A1A1AA] mb-1">
                Tiền tố đổi tên File (Prefix)
              </label>
              <input
                type="text"
                value={renamePrefix}
                onChange={(e) => setRenamePrefix(e.target.value)}
                placeholder="VD: [VIP]_"
                className="w-full px-2 py-1 text-xs font-mono"
              />
            </div>
            <div>
              <label className="block text-[10px] font-mono text-[#A1A1AA] mb-1">
                Hậu tố đổi tên File (Suffix)
              </label>
              <input
                type="text"
                value={renameSuffix}
                onChange={(e) => setRenameSuffix(e.target.value)}
                placeholder="VD: _backup"
                className="w-full px-2 py-1 text-xs font-mono"
              />
            </div>
            <div>
              <label className="block text-[10px] font-mono text-[#A1A1AA] mb-1">
                Chữ ký Caption (Watermark)
              </label>
              <input
                type="text"
                value={captionWatermark}
                onChange={(e) => setCaptionWatermark(e.target.value)}
                placeholder="VD: Nguồn @KhoTaiLieu"
                className="w-full px-2 py-1 text-xs font-mono"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-4 pt-2 border-t border-[#27272A]">
            <div className="flex flex-wrap items-center gap-5 text-xs font-mono">
              <div className="flex items-center gap-2">
                <span className="text-[#A1A1AA]">Xử lý Caption:</span>
                <select
                  value={captionMode}
                  onChange={(e) => setCaptionMode(e.target.value as typeof captionMode)}
                  className="px-2 py-1 text-xs font-mono"
                >
                  <option value="strip_for_txt">Xóa caption với .txt, giữ với file khác</option>
                  <option value="preserve">Giữ nguyên toàn bộ Caption</option>
                  <option value="strip">Xóa toàn bộ Caption</option>
                </select>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={dedupeEnabled}
                  onChange={(e) => setDedupeEnabled(e.target.checked)}
                />
                <span>Chống trùng lặp Metadata</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer text-[#10B981]">
                <input
                  type="checkbox"
                  checked={contentHashDedupe}
                  onChange={(e) => setContentHashDedupe(e.target.checked)}
                />
                <span>Băm SHA-256 Nội dung File (Chống trùng kể cả khi đổi tên file)</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer text-[#F59E0B]">
                <input
                  type="checkbox"
                  checked={allowProtectedFallback}
                  onChange={(e) => setAllowProtectedFallback(e.target.checked)}
                />
                <span>Protected Content Fallback (Tự tải & Re-upload)</span>
              </label>
            </div>

            <button
              type="submit"
              className="px-5 py-2 bg-[#10B981] hover:bg-[#059669] text-[#052E16] font-bold text-xs font-mono uppercase cursor-pointer"
            >
              Lưu Luồng Backup
            </button>
          </div>
        </div>
      </form>

      {/* Active Backup Jobs List */}
      <div className="border border-[#27272A] bg-[#121215] overflow-x-auto">
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="border-b border-[#27272A] bg-[#18181C] font-mono uppercase text-[#A1A1AA]">
              <th className="py-3 px-4">Luồng Backup</th>
              <th className="py-3 px-4">Nguồn &rarr; Đích (Topics)</th>
              <th className="py-3 px-4">Bộ Lọc Nội Dung & Đổi Tên</th>
              <th className="py-3 px-4">Tiến Độ / Cursor</th>
              <th className="py-3 px-4 text-right">Điều Khiển</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#27272A]">
            {backups.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-8 text-center font-mono text-[#A1A1AA]">
                  Chưa có luồng Backup nào.
                </td>
              </tr>
            ) : (
              backups.map((job) => (
                <tr key={job.id} className="hover:bg-[#18181C]/50">
                  <td className="py-3 px-4">
                    <div className="font-bold text-sm text-[#F4F4F5]">
                      #{job.id} · {job.label}
                    </div>
                    <div className="font-mono text-[#A1A1AA] mt-0.5">
                      Reader #{job.reader_account_id} &rarr; Sender #{job.sender_account_id}
                    </div>
                  </td>
                  <td className="py-3 px-4 font-mono">
                    <div>
                      Src: {job.source_chat_id}{' '}
                      {job.source_topic_id ? `(Topic #${job.source_topic_id})` : ''}
                    </div>
                    <div className="text-[#10B981]">
                      Dest: {job.dest_chat_id} (Def: {job.dest_topic_default} / Arch:{' '}
                      {job.dest_topic_archive})
                    </div>
                  </td>
                  <td className="py-3 px-4 font-mono">
                    <div className="flex flex-wrap gap-1">
                      {job.filter_config.sync_documents && (
                        <span className="px-1.5 py-0.5 bg-[#09090B] border border-[#27272A]">
                          DOCS ({job.filter_config.allowed_extensions.join(',') || 'ALL'})
                        </span>
                      )}
                      {job.filter_config.sync_photos && (
                        <span className="px-1.5 py-0.5 bg-[#09090B] border border-[#27272A]">
                          PHOTO
                        </span>
                      )}
                      {job.filter_config.sync_videos && (
                        <span className="px-1.5 py-0.5 bg-[#09090B] border border-[#27272A]">
                          VIDEO
                        </span>
                      )}
                      {job.filter_config.content_hash_dedupe && (
                        <span className="px-1.5 py-0.5 border border-[#10B981] text-[#10B981]">
                          SHA256-DEDUPE
                        </span>
                      )}
                      {(job.filter_config.rename_prefix || job.filter_config.rename_suffix) && (
                        <span className="px-1.5 py-0.5 border border-[#F59E0B] text-[#F59E0B]">
                          RENAME: {job.filter_config.rename_prefix}*{job.filter_config.rename_suffix}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="py-3 px-4 font-mono">
                    <div className="text-[#10B981] font-bold">
                      {job.total_synced_count} file đã backup
                    </div>
                    <div className="text-[#A1A1AA]">Cursor msg #{job.last_scanned_msg_id}</div>
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div className="inline-flex items-center gap-2">
                      <button
                        type="button"
                        disabled={runningJobId === job.id}
                        onClick={() => handleRunNow(job.id)}
                        className="px-2.5 py-1.5 bg-[#10B981] text-[#052E16] font-bold font-mono flex items-center gap-1 cursor-pointer"
                      >
                        <Play size={13} weight="fill" />
                        <span>{runningJobId === job.id ? 'Đang chạy...' : 'Sync Ngay'}</span>
                      </button>
                      <button
                        type="button"
                        onClick={async () => {
                          await api.updateBackup(job.id, { enabled: !job.enabled });
                          onRefresh();
                        }}
                        className="px-2.5 py-1.5 border border-[#27272A] font-mono cursor-pointer"
                      >
                        {job.enabled ? 'Tạm dừng' : 'Bật lại'}
                      </button>
                      <button
                        type="button"
                        onClick={async () => {
                          if (window.confirm(`Xóa luồng Backup "${job.label}"?`)) {
                            await api.deleteBackup(job.id);
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

      {/* Sync State File History */}
      <div className="border border-[#27272A] bg-[#121215] p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h3 className="text-sm font-mono uppercase tracking-wider text-[#F4F4F5] flex items-center gap-2">
            <CloudArrowDown size={18} className="text-[#10B981]" />
            <span>Lịch Sử File Đã Lưu Trong SQLite (sync_state)</span>
          </h3>
          <select
            value={selectedJobFilter || ''}
            onChange={(e) =>
              setSelectedJobFilter(e.target.value ? Number(e.target.value) : undefined)
            }
            className="px-3 py-1.5 text-xs font-mono"
          >
            <option value="">Tất cả luồng Backup</option>
            {backups.map((b) => (
              <option key={b.id} value={b.id}>
                Luồng #{b.id} · {b.label}
              </option>
            ))}
          </select>
        </div>

        <div className="overflow-x-auto max-h-80">
          <table className="w-full text-left border-collapse text-xs font-mono">
            <thead>
              <tr className="border-b border-[#27272A] bg-[#18181C] text-[#A1A1AA]">
                <th className="py-2 px-3">Job / Msg Nguồn</th>
                <th className="py-2 px-3">Tên File / Loại</th>
                <th className="py-2 px-3">Đích (Topic / Msg)</th>
                <th className="py-2 px-3">Fingerprint / SHA-256</th>
                <th className="py-2 px-3">Trạng thái</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#27272A]">
              {history.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-[#A1A1AA]">
                    Chưa có bản ghi lịch sử nào.
                  </td>
                </tr>
              ) : (
                history.map((h) => (
                  <tr key={`${h.backup_job_id}-${h.source_msg_id}`}>
                    <td className="py-2 px-3">
                      Job #{h.backup_job_id} · Src {h.source_chat_id} (#{h.source_msg_id})
                    </td>
                    <td className="py-2 px-3 text-[#F4F4F5]">
                      {h.filename || `[${h.content_type}]`}{' '}
                      {h.size ? `(${(h.size / 1024).toFixed(1)} KB)` : ''}
                    </td>
                    <td className="py-2 px-3">
                      {h.dest_chat_id || '—'} / Topic {h.dest_topic_id ?? 0} (#{h.dest_msg_id || '—'})
                    </td>
                    <td className="py-2 px-3 text-[#A1A1AA] truncate max-w-[180px]">
                      {h.fingerprint || '—'}
                    </td>
                    <td className="py-2 px-3">
                      <span
                        className={`px-1.5 py-0.5 border ${
                          h.status === 'synced'
                            ? 'border-[#10B981] text-[#10B981]'
                            : h.status === 'failed'
                              ? 'border-[#EF4444] text-[#EF4444]'
                              : 'border-[#27272A] text-[#A1A1AA]'
                        }`}
                      >
                        {h.status.toUpperCase()}
                      </span>
                      {h.error_text && <span className="ml-2 text-[#A1A1AA]">{h.error_text}</span>}
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
