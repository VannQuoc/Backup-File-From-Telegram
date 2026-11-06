import React from 'react';
import {
  ArrowsLeftRight,
  ChatCircleDots,
  CheckCircle,
  CloudArrowDown,
  FolderOpen,
  ShieldWarning,
  UsersThree,
  WarningCircle,
} from '@phosphor-icons/react';
import type { DashboardData } from '../types';

interface DashboardViewProps {
  data: DashboardData | null;
  onNavigate: (tab: string) => void;
  onRefresh: () => void;
}

export const DashboardView: React.FC<DashboardViewProps> = ({
  data,
  onNavigate,
  onRefresh,
}) => {
  if (!data) {
    return (
      <div className="p-6 border border-[#27272A] bg-[#121215] text-sm font-mono text-[#A1A1AA]">
        Đang tải dữ liệu trung tâm điều hành...
      </div>
    );
  }

  const { stats, recent_logs, recent_backups } = data;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#27272A] pb-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Trung Tâm Điều Hành (A–Z)</h2>
          <p className="text-sm text-[#A1A1AA]">
            Giám sát trạng thái Đa tài khoản, Luồng Backup File/Media, Kịch bản Auto-Send & Rule Fallback
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="px-4 py-2 border border-[#27272A] bg-[#18181C] hover:border-[#10B981] text-xs font-mono uppercase tracking-wider cursor-pointer"
        >
          Làm mới dữ liệu
        </button>
      </div>

      {/* KPI Metric Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <div
          onClick={() => onNavigate('accounts')}
          className="p-4 border border-[#27272A] bg-[#121215] hover:border-[#10B981] transition-colors cursor-pointer"
        >
          <div className="flex items-center justify-between text-[#A1A1AA] text-xs font-mono uppercase">
            <span>Tài khoản Telethon</span>
            <UsersThree size={18} className="text-[#10B981]" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-bold font-mono text-[#10B981]">
              {stats.accounts.connected}
            </span>
            <span className="text-sm font-mono text-[#A1A1AA]">
              / {stats.accounts.total} kết nối
            </span>
          </div>
        </div>

        <div
          onClick={() => onNavigate('chats')}
          className="p-4 border border-[#27272A] bg-[#121215] hover:border-[#10B981] transition-colors cursor-pointer"
        >
          <div className="flex items-center justify-between text-[#A1A1AA] text-xs font-mono uppercase">
            <span>Nhóm & Rule Cấm</span>
            <ShieldWarning size={18} className="text-[#F59E0B]" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-bold font-mono">{stats.groups.total}</span>
            <span className="text-xs font-mono text-[#F59E0B]">
              ({stats.groups.with_rules} nhóm có Rule)
            </span>
          </div>
        </div>

        <div
          onClick={() => onNavigate('chats')}
          className="p-4 border border-[#27272A] bg-[#121215] hover:border-[#10B981] transition-colors cursor-pointer"
        >
          <div className="flex items-center justify-between text-[#A1A1AA] text-xs font-mono uppercase">
            <span>Folder Gom Nhóm</span>
            <FolderOpen size={18} className="text-[#10B981]" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-bold font-mono">{stats.folders.total}</span>
            <span className="text-xs font-mono text-[#A1A1AA]">folders</span>
          </div>
        </div>

        <div
          onClick={() => onNavigate('backups')}
          className="p-4 border border-[#27272A] bg-[#121215] hover:border-[#10B981] transition-colors cursor-pointer"
        >
          <div className="flex items-center justify-between text-[#A1A1AA] text-xs font-mono uppercase">
            <span>File/Media Đã Backup</span>
            <CloudArrowDown size={18} className="text-[#10B981]" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-bold font-mono text-[#10B981]">
              {stats.backups.synced_items}
            </span>
            <span className="text-xs font-mono text-[#A1A1AA]">
              ({stats.backups.active_jobs}/{stats.backups.total_jobs} luồng chạy)
            </span>
          </div>
        </div>

        <div
          onClick={() => onNavigate('scenarios')}
          className="p-4 border border-[#27272A] bg-[#121215] hover:border-[#10B981] transition-colors cursor-pointer"
        >
          <div className="flex items-center justify-between text-[#A1A1AA] text-xs font-mono uppercase">
            <span>Auto-Send & Fallback</span>
            <ChatCircleDots size={18} className="text-[#10B981]" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-bold font-mono">{stats.scenarios.messages_sent}</span>
            <span className="text-xs font-mono text-[#F59E0B]">
              ({stats.scenarios.fallbacks_triggered} lần Fallback)
            </span>
          </div>
        </div>
      </div>

      {/* Two-column activity monitor */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-7 border border-[#27272A] bg-[#121215] p-5">
          <div className="flex items-center justify-between mb-4 pb-3 border-b border-[#27272A]">
            <h3 className="text-sm font-mono uppercase tracking-wider text-[#F4F4F5] flex items-center gap-2">
              <ArrowsLeftRight size={16} className="text-[#10B981]" />
              <span>Nhật ký Hoạt động & Kích hoạt Fallback Mới Nhất</span>
            </h3>
            <button
              type="button"
              onClick={() => onNavigate('logs')}
              className="text-xs font-mono text-[#10B981] hover:underline cursor-pointer"
            >
              Xem toàn bộ &rarr;
            </button>
          </div>

          {recent_logs.length === 0 ? (
            <p className="text-xs font-mono text-[#A1A1AA] py-6">
              Chưa có nhật ký hoạt động nào.
            </p>
          ) : (
            <div className="divide-y divide-[#27272A] max-h-[380px] overflow-y-auto">
              {recent_logs.map((log) => (
                <div key={log.id} className="py-2.5 flex items-start justify-between gap-3 text-xs">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono px-1.5 py-0.5 bg-[#18181C] border border-[#27272A] text-[#A1A1AA]">
                        {log.category.toUpperCase()}
                      </span>
                      {log.fallback_applied && (
                        <span className="font-mono px-1.5 py-0.5 bg-[#F59E0B]/15 border border-[#F59E0B] text-[#F59E0B]">
                          FALLBACK: {log.action_attempted} &rarr; {log.action_executed}
                        </span>
                      )}
                      {log.chat_id && (
                        <span className="font-mono text-[#A1A1AA]">Chat: {log.chat_id}</span>
                      )}
                    </div>
                    <p className="text-[#F4F4F5]">{log.message}</p>
                  </div>
                  <span className="font-mono text-[11px] text-[#A1A1AA] shrink-0">
                    {log.created_at.replace('T', ' ').slice(0, 19)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="lg:col-span-5 border border-[#27272A] bg-[#121215] p-5">
          <div className="flex items-center justify-between mb-4 pb-3 border-b border-[#27272A]">
            <h3 className="text-sm font-mono uppercase tracking-wider text-[#F4F4F5] flex items-center gap-2">
              <CloudArrowDown size={16} className="text-[#10B981]" />
              <span>File & Media Vừa Backup</span>
            </h3>
            <button
              type="button"
              onClick={() => onNavigate('backups')}
              className="text-xs font-mono text-[#10B981] hover:underline cursor-pointer"
            >
              Quản lý Backup &rarr;
            </button>
          </div>

          {recent_backups.length === 0 ? (
            <p className="text-xs font-mono text-[#A1A1AA] py-6">
              Chưa có lịch sử file backup nào.
            </p>
          ) : (
            <div className="divide-y divide-[#27272A] max-h-[380px] overflow-y-auto">
              {recent_backups.map((item) => (
                <div
                  key={`${item.backup_job_id}-${item.source_msg_id}`}
                  className="py-2.5 flex items-center justify-between gap-2 text-xs"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      {item.status === 'synced' ? (
                        <CheckCircle size={14} className="text-[#10B981] shrink-0" />
                      ) : (
                        <WarningCircle size={14} className="text-[#F59E0B] shrink-0" />
                      )}
                      <span className="font-mono font-medium truncate">
                        {item.filename || `[${item.content_type}] msg #${item.source_msg_id}`}
                      </span>
                    </div>
                    <p className="text-[11px] font-mono text-[#A1A1AA] mt-0.5">
                      Src: {item.source_chat_id} (#{item.source_msg_id}) &rarr; Dest:{' '}
                      {item.dest_chat_id || '-'} (Topic {item.dest_topic_id ?? 0})
                    </p>
                  </div>
                  <span
                    className={`font-mono text-[11px] px-1.5 py-0.5 border ${
                      item.status === 'synced'
                        ? 'border-[#10B981] text-[#10B981]'
                        : item.status === 'failed'
                          ? 'border-[#EF4444] text-[#EF4444]'
                          : 'border-[#27272A] text-[#A1A1AA]'
                    }`}
                  >
                    {item.status.toUpperCase()}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

