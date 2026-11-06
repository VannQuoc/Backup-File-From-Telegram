import React, { useEffect, useState } from 'react';
import {
  Database,
  DownloadSimple,
  Key,
  ListBullets,
  UploadSimple,
} from '@phosphor-icons/react';
import { api } from '../lib/api';
import type { ExecutionLog } from '../types';

interface LogsSettingsViewProps {
  onRefresh?: () => void;
}

export const LogsSettingsView: React.FC<LogsSettingsViewProps> = ({ onRefresh }) => {
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [categoryFilter, setCategoryFilter] = useState('');
  const [fallbackOnly, setFallbackOnly] = useState(false);

  // Settings & Hash Helper
  const [plainPassToHash, setPlainPassToHash] = useState('');
  const [generatedSha256, setGeneratedSha256] = useState('');
  const [envInfo, setEnvInfo] = useState<Record<string, unknown>>({});
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const loadLogsAndSettings = async () => {
    try {
      const [logData, settingsData] = await Promise.all([
        api.getLogs({
          category: categoryFilter || undefined,
          fallback_only: fallbackOnly,
          limit: 200,
        }),
        api.getSettings(),
      ]);
      setLogs(logData);
      setEnvInfo(settingsData.env_info || {});
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    loadLogsAndSettings();
  }, [categoryFilter, fallbackOnly]);

  const handleGenerateHash = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!plainPassToHash) return;
    const res = await api.hashPasswordHelper(plainPassToHash);
    setGeneratedSha256(res.sha256);
  };

  const handleCheckpoint = async () => {
    const res = await api.checkpointDb();
    setStatusMsg(res.message);
  };

  const handleExportJsonConfig = async () => {
    try {
      const bundle = await api.exportConfigBundle();
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `tele_suite_config_${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setStatusMsg('Đã xuất gói cấu hình JSON (Nhóm, Rule, Folder, Kịch bản, Kho mẫu) thành công!');
    } catch (err) {
      setStatusMsg(err instanceof Error ? err.message : 'Lỗi xuất cấu hình JSON');
    }
  };

  const handleImportJsonConfig = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as Record<string, unknown>;
      const res = await api.importConfigBundle(parsed);
      setStatusMsg(`Đã nạp gói cấu hình JSON thành công: ${JSON.stringify(res.imported)}`);
      if (onRefresh) onRefresh();
    } catch (err) {
      setStatusMsg(err instanceof Error ? err.message : 'File JSON không hợp lệ');
    } finally {
      e.target.value = '';
    }
  };

  return (
    <div className="space-y-8">
      <div className="border-b border-[#27272A] pb-4">
        <h2 className="text-2xl font-bold tracking-tight">
          Nhật Ký Hoạt Động (Execution Logs), Sao Lưu Cấu Hình & Cài Đặt Hệ Thống
        </h2>
        <p className="text-sm text-[#A1A1AA]">
          Theo dõi chi tiết mọi lượt gửi tin tự động, các lần kích hoạt Fallback khi nhóm cấm, xuất
          nhập toàn bộ cấu hình JSON 1-Click, tải bản sao SQLite và công cụ tạo mã băm SHA-256.
        </p>
      </div>

      {statusMsg && (
        <div className="p-3 border border-[#10B981] bg-[#10B981]/10 text-xs font-mono text-[#10B981]">
          {statusMsg}
        </div>
      )}

      {/* System Settings, 1-Click Export/Import & SHA-256 Utility */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="p-5 border border-[#27272A] bg-[#121215] space-y-4">
          <h3 className="text-sm font-mono uppercase tracking-wider text-[#10B981] flex items-center gap-2">
            <Database size={18} />
            <span>Quản Trị SQLite (WAL Mode) & Sao Lưu Cấu Hình 1-Click</span>
          </h3>
          <div className="space-y-2 text-xs font-mono">
            <div className="flex justify-between py-1.5 border-b border-[#27272A]">
              <span className="text-[#A1A1AA]">Đường dẫn SQLite DB:</span>
              <span className="text-[#F4F4F5]">{String(envInfo.db_path || './data/state.sqlite')}</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-[#27272A]">
              <span className="text-[#A1A1AA]">Thư mục lưu .session:</span>
              <span className="text-[#F4F4F5]">{String(envInfo.sessions_dir || './data/sessions')}</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-[#27272A]">
              <span className="text-[#A1A1AA]">Chu kỳ Reconcile Backup:</span>
              <span className="text-[#10B981]">
                {String(envInfo.backup_reconcile_interval_seconds || 120)} giây
              </span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-[#27272A]">
              <span className="text-[#A1A1AA]">Chu kỳ Quét Lịch Auto-Send:</span>
              <span className="text-[#10B981]">
                {String(envInfo.auto_send_tick_seconds || 5)} giây
              </span>
            </div>
          </div>

          <div className="flex flex-wrap gap-2 pt-2">
            <button
              type="button"
              onClick={handleExportJsonConfig}
              className="px-3 py-2 bg-[#10B981] text-[#052E16] font-bold text-xs font-mono uppercase flex items-center gap-1.5 cursor-pointer"
            >
              <DownloadSimple size={15} weight="bold" />
              <span>Xuất Cấu Hình (.JSON)</span>
            </button>

            <label className="px-3 py-2 border border-[#F59E0B] text-[#F59E0B] hover:bg-[#F59E0B]/15 text-xs font-mono uppercase flex items-center gap-1.5 cursor-pointer">
              <UploadSimple size={15} weight="bold" />
              <span>Nhập Cấu Hình (.JSON)</span>
              <input
                type="file"
                accept=".json"
                onChange={handleImportJsonConfig}
                className="hidden"
              />
            </label>

            <button
              type="button"
              onClick={() => api.downloadSqliteSnapshot()}
              className="px-3 py-2 border border-[#27272A] bg-[#18181C] hover:border-[#10B981] text-xs font-mono uppercase flex items-center gap-1.5 cursor-pointer"
            >
              <Database size={15} className="text-[#10B981]" />
              <span>Tải File .SQLITE</span>
            </button>

            <button
              type="button"
              onClick={handleCheckpoint}
              className="px-3 py-2 border border-[#27272A] hover:border-[#10B981] text-xs font-mono uppercase cursor-pointer"
            >
              WAL Checkpoint
            </button>
          </div>
        </div>

        <form
          onSubmit={handleGenerateHash}
          className="p-5 border border-[#27272A] bg-[#121215] space-y-4"
        >
          <h3 className="text-sm font-mono uppercase tracking-wider text-[#F59E0B] flex items-center gap-2">
            <Key size={18} />
            <span>Công Cụ Tạo Mã Băm Mật Khẩu SHA-256 Cho .env</span>
          </h3>
          <p className="text-xs text-[#A1A1AA]">
            Tạo nhanh chuỗi hex SHA-256 để bạn dán vào biến{' '}
            <code className="font-mono text-[#10B981]">WEB_ADMIN_PASSWORD_SHA256</code> trong file{' '}
            <code className="font-mono">.env</code>:
          </p>
          <div className="flex gap-2">
            <input
              type="text"
              value={plainPassToHash}
              onChange={(e) => setPlainPassToHash(e.target.value)}
              placeholder="Nhập mật khẩu bạn muốn băm SHA-256..."
              className="flex-1 px-3 py-2 text-xs font-mono"
            />
            <button
              type="submit"
              className="px-4 py-2 bg-[#F59E0B] text-[#09090B] font-bold text-xs font-mono uppercase cursor-pointer"
            >
              Tạo SHA-256
            </button>
          </div>
          {generatedSha256 && (
            <div className="p-3 border border-[#27272A] bg-[#09090B] text-xs font-mono break-all">
              <div className="text-[#A1A1AA] mb-1">Dán dòng này vào file .env:</div>
              <div className="text-[#10B981] select-all">
                WEB_ADMIN_PASSWORD_SHA256={generatedSha256}
              </div>
            </div>
          )}
        </form>
      </div>

      {/* Execution Logs Table */}
      <div className="border border-[#27272A] bg-[#121215] p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h3 className="text-sm font-mono uppercase tracking-wider text-[#F4F4F5] flex items-center gap-2">
            <ListBullets size={18} className="text-[#10B981]" />
            <span>Nhật Ký Thực Thi Chi Tiết ({logs.length} bản ghi)</span>
          </h3>

          <div className="flex flex-wrap items-center gap-3 text-xs font-mono">
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="px-2.5 py-1.5"
            >
              <option value="">Tất cả danh mục</option>
              <option value="auto_send">Auto-Send (Gửi tự động)</option>
              <option value="backup">Backup (Sao lưu File/Media)</option>
              <option value="account">Account (Tài khoản)</option>
              <option value="scanner">Scanner (Quét nhóm & Topic)</option>
              <option value="system">System (Hệ thống / Kill Switch)</option>
            </select>

            <label className="flex items-center gap-2 cursor-pointer text-[#F59E0B]">
              <input
                type="checkbox"
                checked={fallbackOnly}
                onChange={(e) => setFallbackOnly(e.target.checked)}
              />
              <span>Chỉ hiện các lượt đã kích hoạt Fallback</span>
            </label>

            <button
              type="button"
              onClick={loadLogsAndSettings}
              className="px-3 py-1.5 border border-[#27272A] bg-[#18181C] hover:border-[#10B981] cursor-pointer"
            >
              Tải lại
            </button>
          </div>
        </div>

        <div className="overflow-x-auto max-h-[480px]">
          <table className="w-full text-left border-collapse text-xs font-mono">
            <thead>
              <tr className="border-b border-[#27272A] bg-[#18181C] text-[#A1A1AA]">
                <th className="py-2.5 px-3">Thời gian</th>
                <th className="py-2.5 px-3">Danh mục</th>
                <th className="py-2.5 px-3">Nick / Nhóm</th>
                <th className="py-2.5 px-3">Hành động & Fallback</th>
                <th className="py-2.5 px-3">Chi tiết</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#27272A]">
              {logs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-[#A1A1AA]">
                    Chưa có nhật ký nào khớp bộ lọc.
                  </td>
                </tr>
              ) : (
                logs.map((log) => (
                  <tr key={log.id} className="hover:bg-[#18181C]/40">
                    <td className="py-2.5 px-3 text-[#A1A1AA] whitespace-nowrap">
                      {log.created_at.replace('T', ' ').slice(0, 19)}
                    </td>
                    <td className="py-2.5 px-3">
                      <span className="px-1.5 py-0.5 bg-[#09090B] border border-[#27272A]">
                        {log.category.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2.5 px-3">
                      Acc #{log.account_id || '—'} &rarr; Chat {log.chat_id || '—'}
                    </td>
                    <td className="py-2.5 px-3">
                      {log.fallback_applied ? (
                        <span className="text-[#F59E0B] font-bold">
                          ⚡ {log.action_attempted} &rarr; {log.action_executed}
                        </span>
                      ) : (
                        <span className="text-[#10B981]">
                          {log.action_executed || log.status}
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 px-3 text-[#F4F4F5]">{log.message}</td>
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
