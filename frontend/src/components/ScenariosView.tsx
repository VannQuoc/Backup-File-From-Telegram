import React, { useEffect, useState } from 'react';
import {
  ArrowDown,
  ArrowsClockwise,
  ArrowUp,
  BookBookmark,
  Copy,
  Flask,
  Lightning,
  ListMagnifyingGlass,
  PencilSimple,
  Play,
  Plus,
  ShieldCheck,
  Trash,
  X,
} from '@phosphor-icons/react';
import { api } from '../lib/api';
import type {
  Account,
  ChatGroup,
  FallbackPolicyConfig,
  Folder,
  MediaLibraryItem,
  RecentChatMessage,
  Scenario,
  ScenarioPreflightMatrix,
  ScenarioStep,
  ScenarioTarget,
} from '../types';

interface ScenariosViewProps {
  accounts: Account[];
  chats: ChatGroup[];
  folders: Folder[];
  scenarios: Scenario[];
  onRefresh: () => void;
}

const DEFAULT_FALLBACK: FallbackPolicyConfig = {
  on_no_forwards: 'copy_content',
  on_no_links: 'strip_links',
  on_no_stickers: 'use_fallback_text',
  on_no_media: 'use_fallback_text',
  on_no_bot_mentions: 'strip_bot_mentions',
  fallback_text: '',
  fallback_no_link_text: '',
};

const VARIABLE_PILLS = [
  { label: '+Spintax {A|B|C}', snippet: '{Xin chào|Chào anh em|Hello cả nhà} ' },
  { label: '{chat_title}', snippet: '{chat_title}' },
  { label: '{date}', snippet: '{date}' },
  { label: '{time}', snippet: '{time}' },
  { label: '{random_id}', snippet: '#{random_id}' },
  { label: '{account_name}', snippet: '{account_name}' },
];

const createEmptyStep = (order: number): ScenarioStep => ({
  step_order: order,
  name: `Bước ${order}`,
  action_type: 'send_text',
  text_content: '',
  media_path: null,
  sticker_id_or_path: null,
  forward_from_chat_id: null,
  forward_from_msg_id: null,
  via_bot_username: null,
  fallback_policy: { ...DEFAULT_FALLBACK },
});

export const ScenariosView: React.FC<ScenariosViewProps> = ({
  accounts,
  chats,
  folders,
  scenarios,
  onRefresh,
}) => {
  const [editingScenarioId, setEditingScenarioId] = useState<number | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [senderAccountId, setSenderAccountId] = useState<string>(''); // '' = smart rotate by membership & quota
  const [intervalSeconds, setIntervalSeconds] = useState(1800);
  const [jitterMin, setJitterMin] = useState(5);
  const [jitterMax, setJitterMax] = useState(30);
  const [activeHoursStart, setActiveHoursStart] = useState('07:30');
  const [activeHoursEnd, setActiveHoursEnd] = useState('22:30');
  const [deletePreviousMsg, setDeletePreviousMsg] = useState(false);
  const [deleteIfWithinXMessages, setDeleteIfWithinXMessages] = useState<number>(0);
  const [skipIfWithinXMessages, setSkipIfWithinXMessages] = useState<number>(0);
  const [selectionMode, setSelectionMode] = useState<'sequential' | 'random' | 'all_steps'>(
    'sequential',
  );

  const [steps, setSteps] = useState<ScenarioStep[]>([createEmptyStep(1)]);
  const [targets, setTargets] = useState<ScenarioTarget[]>([]);

  // Pre-Flight Compatibility Matrix state
  const [preflightData, setPreflightData] = useState<ScenarioPreflightMatrix | null>(null);
  const [reloadingGroups, setReloadingGroups] = useState(false);

  // Visual Message Picker state (Feature #5)
  const [pickerStepIndex, setPickerStepIndex] = useState<number | null>(null);
  const [pickerMessages, setPickerMessages] = useState<RecentChatMessage[]>([]);
  const [loadingPicker, setLoadingPicker] = useState(false);

  // Template Library state (Feature #12)
  const [libraryItems, setLibraryItems] = useState<MediaLibraryItem[]>([]);
  const [showLibrary, setShowLibrary] = useState(false);
  const [libName, setLibName] = useState('');
  const [libType, setLibType] = useState<'text_template' | 'sticker' | 'media'>('text_template');
  const [libContent, setLibContent] = useState('');

  // Simulator state
  const [simChatId, setSimChatId] = useState<number>(chats[0]?.chat_id || 0);
  const [simResult, setSimResult] = useState<{
    action_to_execute: string;
    text_content: string | null;
    fallback_applied: boolean;
    fallback_reasons: string[];
  } | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [triggeringId, setTriggeringId] = useState<number | null>(null);

  const hasAnyRunningScenario = scenarios.some((s) => Boolean(s.live_run?.running));

  useEffect(() => {
    if (!hasAnyRunningScenario) return;
    const timer = window.setInterval(() => {
      onRefresh();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [hasAnyRunningScenario, onRefresh]);

  const loadLibrary = async () => {
    try {
      const items = await api.listMediaLibrary();
      setLibraryItems(items);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    loadLibrary();
  }, []);

  const handleUpdateStep = (index: number, patch: Partial<ScenarioStep>) => {
    setSteps((prev) => prev.map((s, idx) => (idx === index ? { ...s, ...patch } : s)));
  };

  const handleMoveStep = (index: number, direction: -1 | 1) => {
    setSteps((prev) => {
      const targetIdx = index + direction;
      if (targetIdx < 0 || targetIdx >= prev.length) return prev;
      const cloned = [...prev];
      const temp = cloned[index];
      cloned[index] = cloned[targetIdx];
      cloned[targetIdx] = temp;
      return cloned.map((s, idx) => ({ ...s, step_order: idx + 1 }));
    });
  };

  const handleStartEditScenario = (sc: Scenario) => {
    setEditingScenarioId(sc.id);
    setName(sc.name);
    setDescription(sc.description || '');
    setSenderAccountId(sc.sender_account_id ? String(sc.sender_account_id) : '');
    setIntervalSeconds(sc.interval_seconds || 1800);
    setJitterMin(sc.jitter_min_sec ?? 5);
    setJitterMax(sc.jitter_max_sec ?? 30);
    setActiveHoursStart(sc.active_hours_start || '');
    setActiveHoursEnd(sc.active_hours_end || '');
    setDeletePreviousMsg(Boolean(sc.delete_previous_sent_message));
    setDeleteIfWithinXMessages(Number(sc.delete_if_within_x_messages || 0));
    setSkipIfWithinXMessages(Number(sc.skip_if_within_x_messages || 0));
    setSelectionMode(sc.selection_mode || 'sequential');
    setSteps(
      sc.steps && sc.steps.length > 0
        ? sc.steps.map((s, idx) => ({
            ...s,
            step_order: idx + 1,
            fallback_policy: { ...DEFAULT_FALLBACK, ...(s.fallback_policy || {}) },
          }))
        : [createEmptyStep(1)],
    );
    setTargets(
      (sc.targets || []).map((t) => ({
        ...t,
        topic_id: t.topic_id || 0,
      })),
    );
    setFeedback(`Đang chỉnh sửa kịch bản #${sc.id}: "${sc.name}"`);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleCancelEdit = () => {
    setEditingScenarioId(null);
    setName('');
    setDescription('');
    setSenderAccountId('');
    setIntervalSeconds(1800);
    setJitterMin(5);
    setJitterMax(30);
    setActiveHoursStart('07:30');
    setActiveHoursEnd('22:30');
    setDeletePreviousMsg(false);
    setDeleteIfWithinXMessages(0);
    setSkipIfWithinXMessages(0);
    setSelectionMode('sequential');
    setSteps([createEmptyStep(1)]);
    setTargets([]);
    setFeedback('Đã hủy chế độ chỉnh sửa, quay về tạo kịch bản mới.');
  };

  const handleUpdateStepPolicy = (index: number, patch: Partial<FallbackPolicyConfig>) => {
    setSteps((prev) =>
      prev.map((s, idx) =>
        idx === index
          ? { ...s, fallback_policy: { ...s.fallback_policy, ...patch } }
          : s,
      ),
    );
  };

  const handleOpenMessagePicker = async (stepIdx: number) => {
    const step = steps[stepIdx];
    const srcChatId = step.forward_from_chat_id || chats[0]?.chat_id;
    if (!srcChatId) {
      setFeedback('Vui lòng chọn Nhóm/Kênh Nguồn trước khi duyệt bài viết mẫu.');
      return;
    }
    setPickerStepIndex(stepIdx);
    setLoadingPicker(true);
    try {
      const res = await api.getRecentChatMessages(
        Number(srcChatId),
        senderAccountId ? Number(senderAccountId) : undefined,
        25,
      );
      setPickerMessages(res.messages);
    } catch (err) {
      setFeedback(
        err instanceof Error
          ? err.message
          : 'Không thể tải danh sách tin nhắn từ nhóm nguồn (Hãy đảm bảo có ít nhất 1 Nick đã kết nối)',
      );
      setPickerMessages([]);
    } finally {
      setLoadingPicker(false);
    }
  };

  const handleAddLibraryItem = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!libName.trim() || !libContent.trim()) return;
    try {
      await api.createMediaLibraryItem({
        name: libName.trim(),
        item_type: libType,
        content: libContent.trim(),
      });
      setLibName('');
      setLibContent('');
      setFeedback('Đã lưu mẫu vào Thư viện dùng chung!');
      await loadLibrary();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : 'Lỗi lưu mẫu thư viện');
    }
  };

  const handleApplyLibraryItemToStep = (stepIdx: number, item: MediaLibraryItem) => {
    if (item.item_type === 'text_template') {
      handleUpdateStep(stepIdx, {
        action_type: 'send_text',
        text_content: item.content,
      });
    } else if (item.item_type === 'sticker') {
      handleUpdateStep(stepIdx, {
        action_type: 'send_sticker',
        sticker_id_or_path: item.content,
      });
    } else {
      handleUpdateStep(stepIdx, {
        action_type: 'send_media',
        media_path: item.content,
      });
    }
    setFeedback(`Đã nạp mẫu "${item.name}" vào Bước #${stepIdx + 1}`);
  };

  const handleAddTarget = (type: 'folder' | 'chat') => {
    const defaultId = type === 'folder' ? folders[0]?.id || 0 : chats[0]?.chat_id || 0;
    setTargets((prev) => [
      ...prev,
      {
        target_type: type,
        target_id: defaultId,
        topic_id: 0,
        override_step_order: null,
        override_text_content: null,
        interval_override_seconds: null,
        enabled: true,
      },
    ]);
  };

  const handleUpdateTarget = (index: number, patch: Partial<ScenarioTarget>) => {
    setTargets((prev) => prev.map((t, idx) => (idx === index ? { ...t, ...patch } : t)));
  };

  const handleSaveScenario = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    const normalizedSteps = steps.map((s, idx) => ({ ...s, step_order: idx + 1 }));
    const payload = {
      name: name.trim(),
      description: description.trim() || null,
      enabled: true,
      sender_account_id: senderAccountId ? Number(senderAccountId) : null,
      schedule_type: 'interval',
      interval_seconds: Number(intervalSeconds) || 1800,
      jitter_min_sec: Number(jitterMin) || 0,
      jitter_max_sec: Number(jitterMax) || 0,
      active_hours_start: activeHoursStart.trim() || null,
      active_hours_end: activeHoursEnd.trim() || null,
      delete_previous_sent_message: deletePreviousMsg,
      delete_if_within_x_messages: Math.max(0, Number(deleteIfWithinXMessages) || 0),
      skip_if_within_x_messages: Math.max(0, Number(skipIfWithinXMessages) || 0),
      selection_mode: selectionMode,
      steps: normalizedSteps,
      targets,
    };
    try {
      if (editingScenarioId !== null) {
        await api.updateScenario(editingScenarioId, payload);
        setFeedback(`Đã cập nhật Kịch bản #${editingScenarioId} ("${name.trim()}") thành công!`);
      } else {
        await api.createScenario(payload);
        setFeedback('Đã tạo Kịch bản Auto-Send & Cấu hình Fallback thành công!');
      }
      setEditingScenarioId(null);
      setName('');
      setDescription('');
      setDeletePreviousMsg(false);
      setDeleteIfWithinXMessages(0);
      setSkipIfWithinXMessages(0);
      setSteps([createEmptyStep(1)]);
      setTargets([]);
      onRefresh();
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : 'Lỗi lưu kịch bản');
    }
  };

  const handleSimulateStep = async (step: ScenarioStep) => {
    try {
      const res = await api.simulateFallback({
        step,
        chat_id: simChatId ? Number(simChatId) : undefined,
      });
      setSimResult(res.resolved_plan);
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : 'Lỗi mô phỏng Fallback');
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#27272A] pb-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">
            Kịch Bản Auto-Messaging, Spintax, Chọn Tin Forward Trực Quan & Hybrid Fallback
          </h2>
          <p className="text-sm text-[#A1A1AA]">
            Gán kịch bản khác nhau cho từng Folder Độc Lập trên Web hoặc từng Nhóm lẻ. Hỗ trợ biến
            động Spintax <code className="font-mono">{'{A|B|C}'}</code>, Khung Giờ Hoạt Động, Tự
            Xóa Tin Cũ chống rác nhóm, Tự động chọn Nick đã vào nhóm và Duyệt chọn tin Forward trực
            quan không cần nhớ Message ID.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={reloadingGroups}
            onClick={async () => {
              setReloadingGroups(true);
              try {
                onRefresh();
                setFeedback('Đã tải lại danh sách Nhóm, Folder & Kịch bản mới nhất từ hệ thống!');
              } finally {
                setReloadingGroups(false);
              }
            }}
            className="px-3 py-2 border border-[#27272A] hover:border-[#10B981] text-[#F4F4F5] text-xs font-mono flex items-center gap-1.5 cursor-pointer"
          >
            <ArrowsClockwise size={15} className={reloadingGroups ? 'animate-spin' : ''} />
            <span>Reload Nhóm & Folder</span>
          </button>
          <button
            type="button"
            onClick={() => setShowLibrary(!showLibrary)}
            className="px-3.5 py-2 border border-[#F59E0B] text-[#F59E0B] hover:bg-[#F59E0B]/15 text-xs font-mono flex items-center gap-2 cursor-pointer"
          >
            <BookBookmark size={16} />
            <span>
              {showLibrary
                ? 'Ẩn Kho Mẫu (Library)'
                : `Kho Mẫu Text / Sticker (${libraryItems.length})`}
            </span>
          </button>
        </div>
      </div>

      {feedback && (
        <div className="p-3 border border-[#10B981] bg-[#10B981]/10 text-xs font-mono text-[#10B981]">
          {feedback}
        </div>
      )}

      {/* Media, Sticker & Spintax Template Library Drawer (Feature #12) */}
      {showLibrary && (
        <div className="p-5 border-2 border-[#F59E0B] bg-[#121215] space-y-4">
          <h3 className="text-sm font-mono uppercase text-[#F59E0B] flex items-center gap-2">
            <BookBookmark size={18} />
            <span>Kho Lưu Trữ Mẫu Tin Nhắn Spintax, Sticker & Media Dùng Chung</span>
          </h3>
          <form onSubmit={handleAddLibraryItem} className="grid grid-cols-1 md:grid-cols-5 gap-3">
            <div>
              <input
                type="text"
                value={libName}
                onChange={(e) => setLibName(e.target.value)}
                placeholder="Tên mẫu (VD: Mẫu chào buổi sáng)"
                className="w-full px-3 py-1.5 text-xs"
                required
              />
            </div>
            <div>
              <select
                value={libType}
                onChange={(e) => setLibType(e.target.value as typeof libType)}
                className="w-full px-3 py-1.5 text-xs font-mono"
              >
                <option value="text_template">Mẫu Văn Bản / Spintax</option>
                <option value="sticker">Mẫu Sticker (Path/File ID)</option>
                <option value="media">Mẫu Media (Đường dẫn ảnh/video)</option>
              </select>
            </div>
            <div className="md:col-span-2">
              <input
                type="text"
                value={libContent}
                onChange={(e) => setLibContent(e.target.value)}
                placeholder="Nội dung Spintax {Chào|Hello} {chat_title} hoặc đường dẫn..."
                className="w-full px-3 py-1.5 text-xs font-mono"
                required
              />
            </div>
            <button
              type="submit"
              className="px-4 py-1.5 bg-[#F59E0B] text-[#09090B] font-bold text-xs font-mono uppercase cursor-pointer"
            >
              + Lưu Vào Kho Mẫu
            </button>
          </form>

          {libraryItems.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2 pt-2">
              {libraryItems.map((item) => (
                <div
                  key={item.id}
                  className="p-2.5 border border-[#27272A] bg-[#09090B] flex items-center justify-between gap-2 text-xs font-mono"
                >
                  <div className="truncate">
                    <div className="font-bold text-[#10B981]">
                      [{item.item_type}] {item.name}
                    </div>
                    <div className="text-[#A1A1AA] truncate">{item.content}</div>
                  </div>
                  <button
                    type="button"
                    onClick={async () => {
                      await api.deleteMediaLibraryItem(item.id);
                      await loadLibrary();
                    }}
                    className="text-[#EF4444] p-1 cursor-pointer"
                  >
                    <Trash size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Visual Message Picker Modal for Forwarding (Feature #5) */}
      {pickerStepIndex !== null && (
        <div className="p-5 border-2 border-[#10B981] bg-[#18181C] space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-mono uppercase text-[#10B981] flex items-center gap-2">
              <ListMagnifyingGlass size={18} />
              <span>
                Chọn Trực Quan Bài Viết Cần Forward Cho Bước #{pickerStepIndex + 1} (Không cần tự mò
                Message ID)
              </span>
            </h3>
            <button
              type="button"
              onClick={() => setPickerStepIndex(null)}
              className="text-xs font-mono text-[#A1A1AA] hover:text-white cursor-pointer"
            >
              [Đóng]
            </button>
          </div>
          {loadingPicker ? (
            <div className="py-6 text-center text-xs font-mono text-[#A1A1AA]">
              Đang tải 25 tin nhắn gần nhất từ nhóm nguồn...
            </div>
          ) : pickerMessages.length === 0 ? (
            <div className="py-4 text-xs font-mono text-[#A1A1AA]">
              Không tìm thấy tin nhắn nào hoặc Nick chưa kết nối.
            </div>
          ) : (
            <div className="max-h-64 overflow-y-auto border border-[#27272A] bg-[#09090B] divide-y divide-[#27272A]">
              {pickerMessages.map((m) => (
                <div
                  key={m.msg_id}
                  className="p-2.5 flex items-center justify-between gap-3 text-xs font-mono hover:bg-[#121215]"
                >
                  <div className="truncate">
                    <span className="text-[#10B981] font-bold">Msg #{m.msg_id}</span> ·{' '}
                    <span className="px-1.5 py-0.5 bg-[#18181C] border border-[#27272A]">
                      {m.media_type.toUpperCase()}
                    </span>{' '}
                    <span className="font-sans text-[#F4F4F5]">{m.text_preview}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      if (steps[pickerStepIndex]?.action_type === 'send_sticker') {
                        handleUpdateStep(pickerStepIndex, {
                          sticker_id_or_path: `${m.chat_id}:${m.msg_id}`,
                        });
                        setPickerStepIndex(null);
                        setFeedback(`Đã chọn Sticker tại #${m.msg_id} (${m.chat_id}:${m.msg_id})!`);
                        return;
                      }
                      handleUpdateStep(pickerStepIndex, {
                        forward_from_chat_id: m.chat_id,
                        forward_from_msg_id: m.msg_id,
                        text_content: steps[pickerStepIndex].text_content || m.full_text,
                      });
                      setPickerStepIndex(null);
                      setFeedback(`Đã chọn bài viết #${m.msg_id} làm nguồn Forward!`);
                    }}
                    className="px-3 py-1 bg-[#10B981] text-[#052E16] font-bold shrink-0 cursor-pointer"
                  >
                    Chọn bài này
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Scenario Builder Form */}
      <form
        onSubmit={handleSaveScenario}
        className={`p-5 border ${
          editingScenarioId !== null ? 'border-2 border-[#F59E0B]' : 'border-[#27272A]'
        } bg-[#121215] space-y-6`}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-mono uppercase tracking-wider text-[#10B981] flex items-center gap-2">
            <Lightning size={18} weight="fill" />
            <span>
              {editingScenarioId !== null
                ? `Đang Chỉnh Sửa Kịch Bản #${editingScenarioId} (Chế Độ Edit)`
                : 'Trình Thiết Kế Kịch Bản Đa Bước & Fallback (Scenario Builder)'}
            </span>
          </h3>
          {editingScenarioId !== null && (
            <button
              type="button"
              onClick={handleCancelEdit}
              className="px-3 py-1 border border-[#EF4444] text-[#EF4444] text-xs font-mono flex items-center gap-1 cursor-pointer"
            >
              <X size={14} />
              <span>Hủy Chỉnh Sửa (Tạo Mới)</span>
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <div className="lg:col-span-2">
            <label htmlFor="sc-name" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              Tên Kịch Bản *
            </label>
            <input
              id="sc-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="VD: Kịch bản Seeding Khung Giờ Vàng"
              className="w-full px-3 py-2 text-sm"
              required
            />
          </div>
          <div>
            <label htmlFor="sc-acc" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              Tài khoản Gửi (Smart Failover)
            </label>
            <select
              id="sc-acc"
              value={senderAccountId}
              onChange={(e) => setSenderAccountId(e.target.value)}
              className="w-full px-3 py-2 text-xs font-mono"
            >
              <option value="">Tự chọn Nick đã vào nhóm & còn Quota</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  #{a.id} · {a.label} ({a.joined_groups_count ?? 0} nhóm)
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="sc-interval" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              Chu kỳ gửi lại (Giây)
            </label>
            <input
              id="sc-interval"
              type="number"
              min={10}
              value={intervalSeconds}
              onChange={(e) => setIntervalSeconds(Number(e.target.value))}
              className="w-full px-3 py-2 text-sm font-mono"
            />
          </div>
          <div>
            <label htmlFor="sc-jitter" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              Độ trễ ngẫu nhiên (Min-Max s)
            </label>
            <div className="flex items-center gap-1">
              <input
                id="sc-jitter"
                type="number"
                value={jitterMin}
                onChange={(e) => setJitterMin(Number(e.target.value))}
                className="w-1/2 px-2 py-2 text-xs font-mono"
              />
              <input
                type="number"
                value={jitterMax}
                onChange={(e) => setJitterMax(Number(e.target.value))}
                className="w-1/2 px-2 py-2 text-xs font-mono"
              />
            </div>
          </div>
          <div>
            <label htmlFor="sc-mode" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              Chế độ chọn bước
            </label>
            <select
              id="sc-mode"
              value={selectionMode}
              onChange={(e) => setSelectionMode(e.target.value as typeof selectionMode)}
              className="w-full px-2.5 py-2 text-xs font-mono"
            >
              <option value="sequential">Tuần tự từng bước (Xoay vòng)</option>
              <option value="random">Ngẫu nhiên 1 bước mỗi lượt</option>
              <option value="all_steps">Gửi tất cả các bước cùng lúc</option>
            </select>
          </div>
        </div>

        {/* Active Hours Window & Smart Distance Auto-Delete / Cooldown (Features #8, #10 + X-Messages Distance) */}
        <div className="p-3.5 border border-[#27272A] bg-[#09090B] space-y-3 text-xs font-mono">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-[#10B981] font-bold">⏰ KHUNG GIỜ HOẠT ĐỘNG (Active Hours):</span>
              <div className="flex items-center gap-1.5">
                <span>Từ:</span>
                <input
                  type="time"
                  value={activeHoursStart}
                  onChange={(e) => setActiveHoursStart(e.target.value)}
                  className="px-2 py-1 text-xs font-mono"
                />
                <span>Đến:</span>
                <input
                  type="time"
                  value={activeHoursEnd}
                  onChange={(e) => setActiveHoursEnd(e.target.value)}
                  className="px-2 py-1 text-xs font-mono"
                />
              </div>
              <span className="text-[#A1A1AA]">(Ngoài giờ này hệ thống sẽ tự nghỉ Quiet Hours)</span>
            </div>

            <label className="flex items-center gap-2 cursor-pointer text-[#F59E0B]">
              <input
                type="checkbox"
                checked={deletePreviousMsg}
                onChange={(e) => setDeletePreviousMsg(e.target.checked)}
              />
              <span>
                🗑️ Luôn xóa tin nhắn cũ của kịch bản này trước khi gửi tin mới
              </span>
            </label>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-[#27272A]">
            <div className="p-2.5 border border-[#27272A] bg-[#121215] flex items-center justify-between gap-3">
              <div>
                <div className="text-[#F59E0B] font-bold">
                  🎯 Tự xóa tin cũ nếu chưa cách quá X tin nhắn:
                </div>
                <div className="text-[11px] text-[#A1A1AA]">
                  Nếu từ lần gửi trước đến hiện tại trong nhóm chưa có quá X tin nhắn mới (nhóm vắng),
                  hệ thống tự xóa tin cũ rồi mới gửi tin mới để không bị 2 tin nằm sát nhau. (0 = Tắt)
                </div>
              </div>
              <input
                type="number"
                min={0}
                max={2000}
                value={deleteIfWithinXMessages}
                onChange={(e) => setDeleteIfWithinXMessages(Math.max(0, Number(e.target.value)))}
                className="w-24 px-2.5 py-1.5 text-sm font-mono text-center shrink-0"
                placeholder="VD: 15"
              />
            </div>

            <div className="p-2.5 border border-[#27272A] bg-[#121215] flex items-center justify-between gap-3">
              <div>
                <div className="text-[#10B981] font-bold">
                  🛡️ Tạm bỏ qua lượt gửi nếu chưa cách quá Y tin nhắn:
                </div>
                <div className="text-[11px] text-[#A1A1AA]">
                  Nếu tin gửi lần trước vẫn còn nằm trong Y tin nhắn gần nhất dưới đáy nhóm, tạm
                  Skip lượt gửi này để tiết kiệm Quota và chống lộ бот. (0 = Tắt)
                </div>
              </div>
              <input
                type="number"
                min={0}
                max={2000}
                value={skipIfWithinXMessages}
                onChange={(e) => setSkipIfWithinXMessages(Math.max(0, Number(e.target.value)))}
                className="w-24 px-2.5 py-1.5 text-sm font-mono text-center shrink-0"
                placeholder="VD: 5"
              />
            </div>
          </div>
        </div>

        {/* STEPS BUILDER */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono uppercase text-[#F4F4F5]">
              1. Nội dung các Bước Gửi, Biến Động Spintax & Cấu hình Fallback (Hướng 3 - Hybrid):
            </span>
            <button
              type="button"
              onClick={() => setSteps((prev) => [...prev, createEmptyStep(prev.length + 1)])}
              className="px-3 py-1 border border-[#10B981] text-[#10B981] text-xs font-mono flex items-center gap-1 cursor-pointer"
            >
              <Plus size={14} />
              <span>Thêm Bước Nội Dung</span>
            </button>
          </div>

          {steps.map((step, idx) => (
            <div key={idx} className="p-4 border border-[#27272A] bg-[#09090B] space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#27272A] pb-3">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="px-2 py-0.5 bg-[#10B981] text-[#052E16] font-mono font-bold text-xs">
                    BƯỚC #{idx + 1}
                  </span>
                  <input
                    type="text"
                    value={step.name}
                    onChange={(e) => handleUpdateStep(idx, { name: e.target.value })}
                    className="px-2.5 py-1 text-xs font-semibold"
                    placeholder="Tên bước..."
                  />
                  <select
                    value={step.action_type}
                    onChange={(e) =>
                      handleUpdateStep(idx, {
                        action_type: e.target.value as ScenarioStep['action_type'],
                      })
                    }
                    className="px-2.5 py-1 text-xs font-mono text-[#10B981]"
                  >
                    <option value="send_text">Gửi Tin Nhắn Văn Bản / Spintax (Text)</option>
                    <option value="forward_message">Forward Tin Nhắn từ Kênh/Nhóm Mẫu</option>
                    <option value="send_sticker">Gửi Sticker</option>
                    <option value="send_media">Gửi Ảnh / Video / File Đính Kèm</option>
                  </select>

                  {libraryItems.length > 0 && (
                    <select
                      defaultValue=""
                      onChange={(e) => {
                        const found = libraryItems.find((li) => li.id === Number(e.target.value));
                        if (found) handleApplyLibraryItemToStep(idx, found);
                        e.target.value = '';
                      }}
                      className="px-2 py-1 text-xs font-mono text-[#F59E0B]"
                    >
                      <option value="">-- Nạp nhanh từ Kho Mẫu --</option>
                      {libraryItems.map((li) => (
                        <option key={li.id} value={li.id}>
                          [{li.item_type}] {li.name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  {steps.length > 1 && (
                    <div className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        disabled={idx === 0}
                        onClick={() => handleMoveStep(idx, -1)}
                        className="p-1 border border-[#27272A] text-[#A1A1AA] hover:text-white disabled:opacity-30 cursor-pointer"
                        title="Đẩy bước này lên trên"
                      >
                        <ArrowUp size={13} />
                      </button>
                      <button
                        type="button"
                        disabled={idx === steps.length - 1}
                        onClick={() => handleMoveStep(idx, 1)}
                        className="p-1 border border-[#27272A] text-[#A1A1AA] hover:text-white disabled:opacity-30 cursor-pointer"
                        title="Đẩy bước này xuống dưới"
                      >
                        <ArrowDown size={13} />
                      </button>
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={() => handleSimulateStep(step)}
                    className="px-2.5 py-1 border border-[#F59E0B] text-[#F59E0B] text-xs font-mono flex items-center gap-1 cursor-pointer"
                  >
                    <Flask size={14} />
                    <span>Mô phỏng Spintax & Fallback</span>
                  </button>
                  {steps.length > 1 && (
                    <button
                      type="button"
                      onClick={() => setSteps((prev) => prev.filter((_, i) => i !== idx))}
                      className="p-1 text-[#EF4444] cursor-pointer"
                    >
                      <Trash size={15} />
                    </button>
                  )}
                </div>
              </div>

              {/* Step Action Specific Inputs */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-3">
                  {step.action_type === 'forward_message' && (
                    <div className="space-y-2 p-2.5 border border-[#27272A] bg-[#121215]">
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        <div>
                          <label className="block text-[11px] font-mono text-[#A1A1AA] mb-1">
                            Chọn Kênh/Nhóm Nguồn lấy bài Forward *
                          </label>
                          <select
                            value={step.forward_from_chat_id || ''}
                            onChange={(e) =>
                              handleUpdateStep(idx, {
                                forward_from_chat_id: Number(e.target.value) || null,
                              })
                            }
                            className="w-full px-2 py-1.5 text-xs font-mono"
                          >
                            <option value="">-- Chọn Nhóm/Kênh Nguồn --</option>
                            {chats.map((c) => (
                              <option key={c.chat_id} value={c.chat_id}>
                                {c.title} ({c.chat_id})
                              </option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="block text-[11px] font-mono text-[#A1A1AA] mb-1">
                            Message ID bài cần Forward *
                          </label>
                          <div className="flex gap-1">
                            <input
                              type="number"
                              value={step.forward_from_msg_id || ''}
                              onChange={(e) =>
                                handleUpdateStep(idx, {
                                  forward_from_msg_id: Number(e.target.value) || null,
                                })
                              }
                              placeholder="VD: 125"
                              className="w-full px-2 py-1.5 text-xs font-mono"
                            />
                            <button
                              type="button"
                              onClick={() => handleOpenMessagePicker(idx)}
                              className="px-2.5 py-1.5 bg-[#10B981] text-[#052E16] font-mono font-bold text-[11px] shrink-0 cursor-pointer"
                              title="Duyệt 25 tin nhắn gần nhất trong nhóm nguồn để chọn bài trực quan"
                            >
                              Chọn Bài
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {step.action_type === 'send_sticker' && (
                    <div className="space-y-1.5">
                      <label className="block text-[11px] font-mono text-[#A1A1AA]">
                        Mã File ID (CAACAg...), Tham chiếu (me:ID / -100xxx:ID) hoặc Đường dẫn (.webp/.tgs) *
                      </label>
                      <input
                        type="text"
                        value={step.sticker_id_or_path || ''}
                        onChange={(e) =>
                          handleUpdateStep(idx, { sticker_id_or_path: e.target.value })
                        }
                        placeholder="VD: CAACAgUAAxk... hoặc me:125 hoặc data/sticker.webp"
                        className="w-full px-2.5 py-1.5 text-xs font-mono"
                      />
                    </div>
                  )}

                  {step.action_type === 'send_media' && (
                    <div>
                      <label className="block text-[11px] font-mono text-[#A1A1AA] mb-1">
                        Đường dẫn File Media / Ảnh trên máy *
                      </label>
                      <input
                        type="text"
                        value={step.media_path || ''}
                        onChange={(e) => handleUpdateStep(idx, { media_path: e.target.value })}
                        placeholder="./data/uploads/banner.jpg"
                        className="w-full px-2.5 py-1.5 text-xs font-mono"
                      />
                    </div>
                  )}

                  <div>
                    <div className="flex flex-wrap items-center justify-between gap-1 mb-1">
                      <label className="text-[11px] font-mono text-[#A1A1AA]">
                        Nội dung Tin nhắn Chính / Caption (Hỗ trợ Spintax & Biến động):
                      </label>
                      <div className="flex flex-wrap gap-1">
                        {VARIABLE_PILLS.map((vp) => (
                          <button
                            key={vp.label}
                            type="button"
                            onClick={() =>
                              handleUpdateStep(idx, {
                                text_content: `${step.text_content || ''}${vp.snippet}`,
                              })
                            }
                            className="px-1.5 py-0.5 text-[10px] font-mono border border-[#27272A] bg-[#121215] hover:border-[#10B981] text-[#10B981] cursor-pointer"
                          >
                            {vp.label}
                          </button>
                        ))}
                      </div>
                    </div>
                    <textarea
                      rows={3}
                      value={step.text_content || ''}
                      onChange={(e) => handleUpdateStep(idx, { text_content: e.target.value })}
                      placeholder="VD: {Xin chào|Hello} anh em nhóm {chat_title}! Hôm nay ngày {date}..."
                      className="w-full px-2.5 py-1.5 text-xs"
                    />
                  </div>
                </div>

                {/* Hybrid Fallback Policy Config (Hướng 3) */}
                <div className="p-3 border border-[#27272A] bg-[#121215] space-y-2.5">
                  <div className="text-[11px] font-mono uppercase text-[#F59E0B] font-bold">
                    Quy tắc Fallback Tự Động & Nội Dung Dự Phòng (Hướng 3):
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs font-mono">
                    <div>
                      <span className="text-[10px] text-[#A1A1AA] block">Khi nhóm CẤM FORWARD:</span>
                      <select
                        value={step.fallback_policy.on_no_forwards}
                        onChange={(e) =>
                          handleUpdateStepPolicy(idx, {
                            on_no_forwards:
                              e.target.value as FallbackPolicyConfig['on_no_forwards'],
                          })
                        }
                        className="w-full px-2 py-1 text-[11px]"
                      >
                        <option value="copy_content">Tự Copy & Gửi thành tin mới</option>
                        <option value="use_fallback_text">Gửi Văn bản dự phòng bên dưới</option>
                        <option value="skip">Bỏ qua nhóm này</option>
                      </select>
                    </div>

                    <div>
                      <span className="text-[10px] text-[#A1A1AA] block">Khi nhóm CẤM LINK:</span>
                      <select
                        value={step.fallback_policy.on_no_links}
                        onChange={(e) =>
                          handleUpdateStepPolicy(idx, {
                            on_no_links: e.target.value as FallbackPolicyConfig['on_no_links'],
                          })
                        }
                        className="w-full px-2 py-1 text-[11px]"
                      >
                        <option value="strip_links">Tự động xóa URL khỏi tin nhắn</option>
                        <option value="mask_links">Tự che Link (domain[.]com)</option>
                        <option value="use_fallback_no_link_text">Dùng bản tin Không-Link riêng</option>
                        <option value="skip">Bỏ qua nhóm này</option>
                      </select>
                    </div>

                    <div>
                      <span className="text-[10px] text-[#A1A1AA] block">Khi nhóm CẤM STICKER:</span>
                      <select
                        value={step.fallback_policy.on_no_stickers}
                        onChange={(e) =>
                          handleUpdateStepPolicy(idx, {
                            on_no_stickers:
                              e.target.value as FallbackPolicyConfig['on_no_stickers'],
                          })
                        }
                        className="w-full px-2 py-1 text-[11px]"
                      >
                        <option value="use_fallback_text">Chuyển sang gửi Text dự phòng</option>
                        <option value="skip">Bỏ qua bước gửi Sticker</option>
                      </select>
                    </div>

                    <div>
                      <span className="text-[10px] text-[#A1A1AA] block">Khi nhóm CẤM TAG @BOT:</span>
                      <select
                        value={step.fallback_policy.on_no_bot_mentions}
                        onChange={(e) =>
                          handleUpdateStepPolicy(idx, {
                            on_no_bot_mentions:
                              e.target.value as FallbackPolicyConfig['on_no_bot_mentions'],
                          })
                        }
                        className="w-full px-2 py-1 text-[11px]"
                      >
                        <option value="strip_bot_mentions">Tự xóa @...bot khỏi nội dung</option>
                        <option value="use_fallback_text">Dùng Text dự phòng</option>
                        <option value="skip">Bỏ qua</option>
                      </select>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                    <div>
                      <label className="block text-[10px] font-mono text-[#A1A1AA] mb-1">
                        Văn bản Dự phòng chung (Hỗ trợ cả Spintax):
                      </label>
                      <input
                        type="text"
                        value={step.fallback_policy.fallback_text || ''}
                        onChange={(e) =>
                          handleUpdateStepPolicy(idx, { fallback_text: e.target.value })
                        }
                        placeholder="Nội dung thuần text thay thế..."
                        className="w-full px-2 py-1 text-xs"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] font-mono text-[#A1A1AA] mb-1">
                        Bản tin Dự phòng Không-Link (Khi nhóm cấm Link):
                      </label>
                      <input
                        type="text"
                        value={step.fallback_policy.fallback_no_link_text || ''}
                        onChange={(e) =>
                          handleUpdateStepPolicy(idx, { fallback_no_link_text: e.target.value })
                        }
                        placeholder="Bản tin hướng dẫn liên hệ bio..."
                        className="w-full px-2 py-1 text-xs"
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* TARGETS BUILDER: INDEPENDENT WEB FOLDER & INDIVIDUAL CHAT OVERRIDES */}
        <div className="space-y-3 pt-2 border-t border-[#27272A]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <span className="text-xs font-mono uppercase text-[#F4F4F5]">
                2. Chỉ định Folder Web Độc Lập hoặc Nhóm Lẻ (Folder nào chạy kịch bản nào, Chat nào
                gửi cái gì):
              </span>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => handleAddTarget('folder')}
                className="px-3 py-1 border border-[#10B981] text-[#10B981] text-xs font-mono cursor-pointer"
              >
                + Gán Folder Nhóm (Độc lập trên Web)
              </button>
              <button
                type="button"
                onClick={() => handleAddTarget('chat')}
                className="px-3 py-1 border border-[#27272A] bg-[#18181C] text-xs font-mono cursor-pointer"
              >
                + Chỉ định Nhóm Lẻ (Kèm Topic & nội dung riêng)
              </button>
            </div>
          </div>

          {targets.length === 0 ? (
            <div className="p-3 border border-[#27272A] bg-[#09090B] text-xs font-mono text-[#A1A1AA]">
              Hãy bấm &quot;+ Gán Folder Nhóm&quot; hoặc &quot;+ Chỉ định Nhóm Lẻ&quot; để chọn đích
              gửi cho kịch bản.
            </div>
          ) : (
            <div className="space-y-2">
              {targets.map((t, idx) => {
                const targetChatObj =
                  t.target_type === 'chat'
                    ? chats.find((c) => c.chat_id === Number(t.target_id))
                    : undefined;
                return (
                  <div
                    key={idx}
                    className="p-3 border border-[#27272A] bg-[#09090B] grid grid-cols-1 md:grid-cols-12 gap-3 items-center text-xs"
                  >
                    <div className="md:col-span-2 font-mono uppercase text-[#10B981]">
                      {t.target_type === 'folder' ? '📁 FOLDER WEB' : '💬 NHÓM LẺ'}
                    </div>
                    <div className="md:col-span-4">
                      {t.target_type === 'folder' ? (
                        <select
                          value={t.target_id}
                          onChange={(e) =>
                            handleUpdateTarget(idx, { target_id: Number(e.target.value) })
                          }
                          className="w-full px-2.5 py-1.5 font-mono"
                        >
                          <option value={0}>-- Chọn Folder Web --</option>
                          {folders.map((f) => (
                            <option key={f.id} value={f.id}>
                              Folder #{f.id} · {f.name} ({f.chats.length} nhóm)
                            </option>
                          ))}
                        </select>
                      ) : (
                        <div className="flex gap-1.5">
                          <select
                            value={t.target_id}
                            onChange={(e) =>
                              handleUpdateTarget(idx, { target_id: Number(e.target.value) })
                            }
                            className="w-full px-2.5 py-1.5 font-mono"
                          >
                            <option value={0}>-- Chọn Nhóm --</option>
                            {chats.map((c) => (
                              <option key={c.chat_id} value={c.chat_id}>
                                {c.title} ({c.chat_id})
                              </option>
                            ))}
                          </select>
                          {targetChatObj?.topics && targetChatObj.topics.length > 0 && (
                            <select
                              value={t.topic_id || 0}
                              onChange={(e) =>
                                handleUpdateTarget(idx, { topic_id: Number(e.target.value) })
                              }
                              className="w-36 px-2 py-1.5 font-mono text-[#F59E0B]"
                            >
                              <option value={0}>Topic chung (0)</option>
                              {targetChatObj.topics.map((tp) => (
                                <option key={tp.topic_id} value={tp.topic_id}>
                                  #{tp.topic_id} {tp.title}
                                </option>
                              ))}
                            </select>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="md:col-span-5">
                      <input
                        type="text"
                        value={t.override_text_content || ''}
                        onChange={(e) =>
                          handleUpdateTarget(idx, {
                            override_text_content: e.target.value || null,
                          })
                        }
                        placeholder="Ghi đè nội dung riêng cho mục tiêu này (Hỗ trợ Spintax)..."
                        className="w-full px-2.5 py-1.5"
                      />
                    </div>
                    <div className="md:col-span-1 text-right">
                      <button
                        type="button"
                        onClick={() => setTargets((prev) => prev.filter((_, i) => i !== idx))}
                        className="p-1 text-[#EF4444] cursor-pointer"
                      >
                        <Trash size={15} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Fallback Simulator Preview Bar */}
        <div className="p-3 border border-[#F59E0B]/50 bg-[#18181C] flex flex-wrap items-center justify-between gap-3 text-xs font-mono">
          <div className="flex items-center gap-2">
            <Flask size={16} className="text-[#F59E0B]" />
            <span>Chọn nhóm để test thử nút &quot;Mô phỏng Spintax &amp; Fallback&quot;:</span>
            <select
              value={simChatId}
              onChange={(e) => setSimChatId(Number(e.target.value))}
              className="px-2 py-1 text-xs font-mono"
            >
              <option value={0}>-- Chọn Nhóm Kiểm Thử --</option>
              {chats.map((c) => (
                <option key={c.chat_id} value={c.chat_id}>
                  {c.title} ({c.chat_id})
                </option>
              ))}
            </select>
          </div>
          {simResult && (
            <div className="text-[#F59E0B]">
              Kết quả dự kiến: Hành động = <strong>{simResult.action_to_execute}</strong> | Nội dung
              = <code>{simResult.text_content || '(media/forward)'}</code>
              {simResult.fallback_reasons.length > 0 &&
                ` [${simResult.fallback_reasons.join('; ')}]`}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-3">
          {editingScenarioId !== null && (
            <button
              type="button"
              onClick={handleCancelEdit}
              className="px-5 py-2.5 border border-[#27272A] text-[#A1A1AA] hover:text-white font-mono text-xs uppercase cursor-pointer"
            >
              Hủy Sửa
            </button>
          )}
          <button
            type="submit"
            className="px-6 py-2.5 bg-[#10B981] hover:bg-[#059669] text-[#052E16] font-bold text-xs font-mono uppercase cursor-pointer"
          >
            {editingScenarioId !== null
              ? `Lưu Cập Nhật Kịch Bản #${editingScenarioId}`
              : 'Lưu Kịch Bản & Bắt Đầu Lịch Tự Động'}
          </button>
        </div>
      </form>

      {/* Pre-Flight Compatibility Matrix Modal */}
      {preflightData && (
        <div className="p-5 border-2 border-[#10B981] bg-[#121215] space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#27272A] pb-3">
            <div>
              <h3 className="text-sm font-mono uppercase text-[#10B981] flex items-center gap-2">
                <ShieldCheck size={18} weight="fill" />
                <span>
                  Ma Trận Kiểm Tra Tương Thích Kịch Bản: #{preflightData.scenario_id} ·{' '}
                  {preflightData.scenario_name}
                </span>
              </h3>
              <p className="text-xs font-mono text-[#A1A1AA] mt-1">
                Tổng đích: <strong>{preflightData.total_destinations}</strong> nhóm | Gửi Gốc:{' '}
                <strong className="text-[#10B981]">{preflightData.summary.native_count}</strong> |
                Tự Động Fallback:{' '}
                <strong className="text-[#F59E0B]">{preflightData.summary.fallback_count}</strong> |
                Bị Skip: <strong className="text-[#EF4444]">{preflightData.summary.skip_count}</strong>
              </p>
            </div>
            <button
              type="button"
              onClick={() => setPreflightData(null)}
              className="px-3 py-1 border border-[#27272A] text-xs font-mono text-[#A1A1AA] hover:text-white cursor-pointer"
            >
              [Đóng Báo Cáo]
            </button>
          </div>

          <div className="max-h-72 overflow-y-auto divide-y divide-[#27272A] border border-[#27272A] bg-[#09090B] text-xs font-mono">
            {preflightData.destinations.map((d, idx) => (
              <div key={idx} className="p-3 space-y-1.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <span className="font-bold text-[#F4F4F5]">{d.chat_title}</span>{' '}
                    <span className="text-[#A1A1AA]">({d.chat_id})</span>
                    {d.folder_name && (
                      <span className="ml-2 px-1.5 py-0.5 bg-[#18181C] border border-[#27272A]">
                        📁 {d.folder_name}
                      </span>
                    )}
                    {d.last_sent_msg_id && (
                      <span className="ml-2 text-[#F59E0B]">
                        [Tin gửi gần nhất: #{d.last_sent_msg_id}]
                      </span>
                    )}
                  </div>
                  <div className="text-[11px]">
                    Nick đủ quyền gửi:{' '}
                    {d.eligible_member_accounts.length > 0 ? (
                      <span className="text-[#10B981]">
                        {d.eligible_member_accounts.join(', ')}
                      </span>
                    ) : (
                      <span className="text-[#F59E0B]">Dùng Nick Mặc Định (Chưa quét member)</span>
                    )}
                  </div>
                </div>
                {d.steps.map((st) => (
                  <div key={st.step_order} className="pl-3 text-[11px] text-[#A1A1AA]">
                    • Bước #{st.step_order} ({st.step_name}): {st.original_action} ➔{' '}
                    <strong
                      className={
                        st.action_to_execute === 'skip'
                          ? 'text-[#EF4444]'
                          : st.fallback_applied
                            ? 'text-[#F59E0B]'
                            : 'text-[#10B981]'
                      }
                    >
                      {st.action_to_execute}
                    </strong>
                    {st.fallback_reasons.length > 0 && ` [${st.fallback_reasons.join('; ')}]`}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Scenarios List */}
      <div className="border border-[#27272A] bg-[#121215] overflow-x-auto">
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="border-b border-[#27272A] bg-[#18181C] font-mono uppercase text-[#A1A1AA]">
              <th className="py-3 px-4">Kịch Bản & Tùy Chọn</th>
              <th className="py-3 px-4">Các Bước Nội Dung</th>
              <th className="py-3 px-4">Mục Tiêu (Folder Web / Chat)</th>
              <th className="py-3 px-4">Lịch & Khung Giờ</th>
              <th className="py-3 px-4 text-right">Thao Tác</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#27272A]">
            {scenarios.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-8 text-center font-mono text-[#A1A1AA]">
                  Chưa có kịch bản gửi tin tự động nào.
                </td>
              </tr>
            ) : (
              scenarios.map((sc) => (
                <tr key={sc.id} className="hover:bg-[#18181C]/50">
                  <td className="py-3 px-4">
                    <div className="font-bold text-sm text-[#F4F4F5]">
                      #{sc.id} · {sc.name}
                    </div>
                    <div className="font-mono text-[#A1A1AA]">
                      Nick:{' '}
                      {sc.sender_account_id ? `#${sc.sender_account_id}` : 'Smart Membership Rotate'}{' '}
                      · {sc.selection_mode}
                    </div>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {sc.delete_previous_sent_message && (
                        <span className="px-1.5 py-0.5 text-[10px] font-mono border border-[#F59E0B] text-[#F59E0B]">
                          LUÔN XÓA TIN CŨ
                        </span>
                      )}
                      {(sc.delete_if_within_x_messages ?? 0) > 0 && (
                        <span className="px-1.5 py-0.5 text-[10px] font-mono border border-[#F59E0B] text-[#F59E0B]">
                          XÓA TIN CŨ NẾU ≤ {sc.delete_if_within_x_messages} TIN
                        </span>
                      )}
                      {(sc.skip_if_within_x_messages ?? 0) > 0 && (
                        <span className="px-1.5 py-0.5 text-[10px] font-mono border border-[#10B981] text-[#10B981]">
                          SKIP NẾU ≤ {sc.skip_if_within_x_messages} TIN
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="py-3 px-4 font-mono">
                    {sc.steps.map((s) => (
                      <div key={s.step_order} className="truncate max-w-[260px]">
                        • [{s.action_type}] {s.name}:{' '}
                        {s.text_content || s.sticker_id_or_path || `Fwd #${s.forward_from_msg_id}`}
                      </div>
                    ))}
                  </td>
                  <td className="py-3 px-4 font-mono">
                    {sc.targets.map((t, i) => (
                      <div key={i}>
                        {t.target_type === 'folder'
                          ? `📁 Folder Web #${t.target_id}`
                          : `💬 Chat ${t.target_id}`}
                        {t.topic_id ? ` (Topic #${t.topic_id})` : ''}
                        {t.override_text_content ? ' (Có nội dung riêng)' : ''}
                      </div>
                    ))}
                  </td>
                  <td className="py-3 px-4 font-mono space-y-1">
                    <div className="text-[#10B981] font-bold">
                      Đã gửi: {sc.total_sent_count} lượt
                    </div>
                    <div className="text-[#A1A1AA]">
                      Mỗi {sc.interval_seconds}s (+{sc.jitter_min_sec}..{sc.jitter_max_sec}s)
                    </div>
                    {sc.active_hours_start && sc.active_hours_end && (
                      <div
                        className={
                          sc.within_active_hours === false ? 'text-[#EF4444] font-bold' : 'text-[#F59E0B]'
                        }
                      >
                        Giờ chạy: {sc.active_hours_start} - {sc.active_hours_end}
                        {sc.enabled && sc.within_active_hours === false && ' (Đang ngoài khung giờ)'}
                      </div>
                    )}
                    {sc.next_run_at && sc.enabled && (
                      <div className="text-[11px] text-[#A1A1AA]">
                        Kế tiếp: {new Date(sc.next_run_at).toLocaleTimeString('vi-VN')}
                      </div>
                    )}
                    {sc.live_run?.running && (
                      <div className="px-2 py-1 bg-[#10B981]/15 border border-[#10B981] text-[#10B981] text-[11px] font-bold">
                        ⚡ ĐANG CHẠY NGẦM: {sc.live_run.processed}/{sc.live_run.total_destinations} nhóm
                        (OK: {sc.live_run.sent_count} · Skip: {sc.live_run.skipped_count} · Lỗi:{' '}
                        {sc.live_run.failed_count})
                      </div>
                    )}
                    {!sc.live_run?.running && sc.live_run?.last_message && (
                      <div className="text-[11px] text-[#A1A1AA]">{sc.live_run.last_message}</div>
                    )}
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div className="inline-flex flex-wrap items-center justify-end gap-1.5">
                      <button
                        type="button"
                        disabled={triggeringId === sc.id || Boolean(sc.live_run?.running)}
                        onClick={async () => {
                          setTriggeringId(sc.id);
                          try {
                            const res = await api.runScenarioNow(sc.id);
                            if (res.status === 'already_running') {
                              setFeedback(
                                `Kịch bản "${sc.name}" đang chạy ngầm (${res.executed_count}/${
                                  res.total_destinations ?? 0
                                } nhóm)...`,
                              );
                            } else {
                              setFeedback(
                                `⚡ Đã kích hoạt chạy ngầm kịch bản "${sc.name}" cho ${
                                  res.total_destinations ?? res.executed_count
                                } nhóm đích! Tiến độ sẽ tự cập nhật trực tiếp mỗi 2.5s.`,
                              );
                            }
                            onRefresh();
                          } catch (err) {
                            setFeedback(
                              `❌ Lỗi chạy kịch bản "${sc.name}": ${
                                err instanceof Error ? err.message : 'Không xác định'
                              }`,
                            );
                          } finally {
                            setTriggeringId(null);
                          }
                        }}
                        className="px-2.5 py-1.5 bg-[#10B981] disabled:opacity-50 text-[#052E16] font-bold font-mono flex items-center gap-1 cursor-pointer"
                      >
                        <Play size={13} weight="fill" />
                        <span>{sc.live_run?.running ? 'Đang Gửi...' : 'Gửi Ngay'}</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleStartEditScenario(sc)}
                        className="px-2.5 py-1.5 border border-[#F59E0B] text-[#F59E0B] hover:bg-[#F59E0B]/15 font-mono flex items-center gap-1 cursor-pointer"
                        title="Chỉnh sửa toàn bộ kịch bản này"
                      >
                        <PencilSimple size={13} />
                        <span>Sửa</span>
                      </button>
                      <button
                        type="button"
                        onClick={async () => {
                          const cloned = await api.cloneScenario(sc.id);
                          setFeedback(`Đã nhân bản kịch bản thành #${cloned.id}: "${cloned.name}"!`);
                          onRefresh();
                        }}
                        className="px-2 py-1.5 border border-[#27272A] hover:border-[#10B981] text-[#A1A1AA] hover:text-[#10B981] font-mono flex items-center gap-1 cursor-pointer"
                        title="Nhân bản kịch bản này"
                      >
                        <Copy size={13} />
                        <span>Nhân bản</span>
                      </button>
                      <button
                        type="button"
                        onClick={async () => {
                          const matrix = await api.preflightCheckScenario(sc.id);
                          setPreflightData(matrix);
                        }}
                        className="px-2 py-1.5 border border-[#27272A] hover:border-[#10B981] text-[#10B981] font-mono flex items-center gap-1 cursor-pointer"
                        title="Kiểm tra tương thích kịch bản với toàn bộ nhóm đích"
                      >
                        <ShieldCheck size={14} />
                        <span>Check Đích</span>
                      </button>
                      <button
                        type="button"
                        onClick={async () => {
                          await api.updateScenario(sc.id, { enabled: !sc.enabled });
                          onRefresh();
                        }}
                        className="px-2.5 py-1.5 border border-[#27272A] font-mono cursor-pointer"
                      >
                        {sc.enabled ? 'Tạm dừng' : 'Bật lại'}
                      </button>
                      <button
                        type="button"
                        onClick={async () => {
                          if (window.confirm(`Xóa kịch bản "${sc.name}"?`)) {
                            await api.deleteScenario(sc.id);
                            if (editingScenarioId === sc.id) handleCancelEdit();
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
  );
};
