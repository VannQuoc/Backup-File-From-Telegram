import React, { useState } from 'react';
import {
  CheckCircle,
  FolderSimplePlus,
  Heartbeat,
  Key,
  MagnifyingGlass,
  Plug,
  Plus,
  Trash,
  UploadSimple,
  UsersFour,
  WarningCircle,
} from '@phosphor-icons/react';
import { api } from '../lib/api';
import type { Account, ChatGroup } from '../types';

interface AccountsViewProps {
  accounts: Account[];
  onRefresh: () => void;
}

export const AccountsView: React.FC<AccountsViewProps> = ({ accounts, onRefresh }) => {
  const [label, setLabel] = useState('');
  const [phone, setPhone] = useState('');
  const [apiId, setApiId] = useState('');
  const [apiHash, setApiHash] = useState('');
  const [proxyUrl, setProxyUrl] = useState('');
  const [maxPerHour, setMaxPerHour] = useState(60);
  const [maxPerDay, setMaxPerDay] = useState(500);

  // Session file import state
  const [showImport, setShowImport] = useState(false);
  const [sessionFile, setSessionFile] = useState<File | null>(null);

  // OTP Login modal state
  const [loginAcc, setLoginAcc] = useState<Account | null>(null);
  const [otpCode, setOtpCode] = useState('');
  const [password2fa, setPassword2fa] = useState('');

  // Account Joined Groups Inspector Modal (Feature #1)
  const [inspectAcc, setInspectAcc] = useState<Account | null>(null);
  const [inspectGroups, setInspectGroups] = useState<ChatGroup[]>([]);

  // Bulk Join & Clone Modal (Feature #4)
  const [bulkJoinAcc, setBulkJoinAcc] = useState<Account | null>(null);
  const [bulkLinksText, setBulkLinksText] = useState('');
  const [cloneFromAccId, setCloneFromAccId] = useState<string>('');
  const [joinDelayMin, setJoinDelayMin] = useState(2);
  const [joinDelayMax, setJoinDelayMax] = useState(5);

  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const handleAddAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setStatusMsg(null);
    try {
      if (showImport && sessionFile) {
        const fd = new FormData();
        fd.append('label', label.trim());
        fd.append('phone', phone.trim());
        if (apiId.trim()) fd.append('api_id', apiId.trim());
        if (apiHash.trim()) fd.append('api_hash', apiHash.trim());
        if (proxyUrl.trim()) fd.append('proxy_url', proxyUrl.trim());
        fd.append('session_file', sessionFile);
        await api.importSessionFile(fd);
        setStatusMsg('Đã import file .session và tạo tài khoản thành công.');
      } else {
        await api.createAccount({
          label: label.trim(),
          phone: phone.trim(),
          api_id: apiId.trim() ? Number(apiId.trim()) : null,
          api_hash: apiHash.trim() || null,
          proxy_url: proxyUrl.trim() || null,
          max_messages_per_hour: Number(maxPerHour) || 60,
          max_messages_per_day: Number(maxPerDay) || 500,
          enabled: true,
        });
        setStatusMsg('Đã thêm tài khoản mới. Hãy bấm "Gửi OTP" để xác thực phiên.');
      }
      setLabel('');
      setPhone('');
      setApiId('');
      setApiHash('');
      setProxyUrl('');
      setSessionFile(null);
      onRefresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Lỗi thêm tài khoản');
    }
  };

  const handleSendOtp = async (acc: Account) => {
    setBusyId(acc.id);
    setErrorMsg(null);
    setStatusMsg(null);
    try {
      const res = await api.sendOtp(acc.id, acc.phone);
      setStatusMsg(res.message);
      setLoginAcc(res.account);
      onRefresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Không gửi được OTP');
    } finally {
      setBusyId(null);
    }
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!loginAcc) return;
    setBusyId(loginAcc.id);
    setErrorMsg(null);
    try {
      const res = await api.verifyOtp(loginAcc.id, otpCode, password2fa || undefined);
      setStatusMsg(res.message);
      if (res.status === 'connected') {
        setLoginAcc(null);
        setOtpCode('');
        setPassword2fa('');
      } else {
        setLoginAcc(res.account);
      }
      onRefresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Xác thực OTP thất bại');
    } finally {
      setBusyId(null);
    }
  };

  const handleConnect = async (acc: Account) => {
    setBusyId(acc.id);
    setErrorMsg(null);
    try {
      await api.connectAccount(acc.id);
      setStatusMsg(`Đã kiểm tra kết nối cho ${acc.label}`);
      onRefresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Lỗi kết nối');
    } finally {
      setBusyId(null);
    }
  };

  const handleHealthCheck = async (acc: Account) => {
    setBusyId(acc.id);
    setErrorMsg(null);
    try {
      const h = await api.checkAccountHealth(acc.id);
      setStatusMsg(
        `[Health Check #${acc.id}] Trạng thái: ${h.status.toUpperCase()} | Ping: ${
          h.latency_ms ?? '—'
        }ms | Đã gửi: ${h.sent_last_hour}/${h.max_messages_per_hour} (1h), ${h.sent_last_24h}/${
          h.max_messages_per_day
        } (24h) | Số nhóm đã tham gia: ${h.joined_groups_count}`,
      );
      onRefresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Lỗi kiểm tra sức khỏe tài khoản');
    } finally {
      setBusyId(null);
    }
  };

  const handleScanDialogs = async (acc: Account) => {
    setBusyId(acc.id);
    setErrorMsg(null);
    try {
      const res = await api.scanDialogs(acc.id, 300);
      setStatusMsg(
        `Đã quét ${res.count} nhóm/kênh, quyền thành viên, Rule cấm & Forum Topics từ nick "${acc.label}"!`,
      );
      onRefresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Lỗi quét danh sách nhóm');
    } finally {
      setBusyId(null);
    }
  };

  const handleImportTelegramFolders = async (acc: Account) => {
    setBusyId(acc.id);
    setErrorMsg(null);
    try {
      const res = await api.importTelegramFolders(acc.id);
      setStatusMsg(
        `Đã import ${res.imported_count} Folder từ Telegram của "${acc.label}" thành Folder độc lập trên Web Panel!`,
      );
      onRefresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Lỗi import Folder từ Telegram');
    } finally {
      setBusyId(null);
    }
  };

  const handleOpenJoinedGroups = async (acc: Account) => {
    setInspectAcc(acc);
    try {
      const list = await api.listAccountJoinedGroups(acc.id);
      setInspectGroups(list);
    } catch {
      setInspectGroups([]);
    }
  };

  const handleExecuteBulkJoin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!bulkJoinAcc) return;
    setBusyId(bulkJoinAcc.id);
    setErrorMsg(null);
    try {
      const links = bulkLinksText
        .split(/\r?\n|,/)
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await api.bulkJoinGroups(bulkJoinAcc.id, {
        links_or_usernames: links,
        clone_from_account_id: cloneFromAccId ? Number(cloneFromAccId) : null,
        delay_min_sec: Number(joinDelayMin) || 2,
        delay_max_sec: Number(joinDelayMax) || 5,
      });
      setStatusMsg(
        `Bulk Join cho "${bulkJoinAcc.label}": Thành công ${res.joined_count}/${res.total_targets} nhóm (Lỗi: ${res.failed_count}).`,
      );
      setBulkJoinAcc(null);
      setBulkLinksText('');
      onRefresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Lỗi tham gia nhóm hàng loạt');
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (acc: Account) => {
    if (!window.confirm(`Xóa tài khoản "${acc.label}" (${acc.phone})?`)) return;
    try {
      await api.deleteAccount(acc.id);
      onRefresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Không thể xóa tài khoản');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#27272A] pb-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">
            Quản Lý Đa Tài Khoản, Khám Phá Nhóm Đã Tham Gia & Hạn Mức Quota
          </h2>
          <p className="text-sm text-[#A1A1AA]">
            Thêm nhiều tài khoản Telegram, xem chi tiết từng Nick đang ở những nhóm nào & quyền hạn
            gì, Import Folder từ Telegram, Bulk Join / Clone nhóm giữa các Nick và kiểm soát Quota
            chống FloodWait.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowImport(!showImport)}
          className="px-3.5 py-2 border border-[#27272A] bg-[#18181C] hover:border-[#10B981] text-xs font-mono flex items-center gap-2 cursor-pointer"
        >
          <UploadSimple size={16} className="text-[#10B981]" />
          <span>{showImport ? 'Chuyển sang Tạo mới OTP' : 'Import sẵn file .session'}</span>
        </button>
      </div>

      {statusMsg && (
        <div className="p-3 border border-[#10B981] bg-[#10B981]/10 text-xs font-mono text-[#10B981]">
          {statusMsg}
        </div>
      )}
      {errorMsg && (
        <div className="p-3 border border-[#EF4444] bg-[#EF4444]/10 text-xs font-mono text-[#EF4444]">
          {errorMsg}
        </div>
      )}

      {/* Add Account Form */}
      <form
        onSubmit={handleAddAccount}
        className="p-5 border border-[#27272A] bg-[#121215] space-y-4"
      >
        <h3 className="text-sm font-mono uppercase tracking-wider text-[#10B981] flex items-center gap-2">
          <Plus size={16} weight="bold" />
          <span>
            {showImport ? 'Import Tài Khoản từ File .session' : 'Thêm Tài Khoản Telegram Mới'}
          </span>
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-4 lg:grid-cols-7 gap-3">
          <div className="lg:col-span-2">
            <label htmlFor="acc-label" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              Tên gợi nhớ *
            </label>
            <input
              id="acc-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="VD: Nick Seeding #1"
              className="w-full px-3 py-2 text-sm"
              required
            />
          </div>
          <div>
            <label htmlFor="acc-phone" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              Số điện thoại (+84...) *
            </label>
            <input
              id="acc-phone"
              type="text"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+84901234567"
              className="w-full px-3 py-2 text-sm font-mono"
              required
            />
          </div>
          <div>
            <label htmlFor="acc-api-id" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              API ID (Tùy chọn)
            </label>
            <input
              id="acc-api-id"
              type="number"
              value={apiId}
              onChange={(e) => setApiId(e.target.value)}
              placeholder="Mặc định .env"
              className="w-full px-3 py-2 text-sm font-mono"
            />
          </div>
          <div>
            <label htmlFor="acc-api-hash" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              API Hash (Tùy chọn)
            </label>
            <input
              id="acc-api-hash"
              type="text"
              value={apiHash}
              onChange={(e) => setApiHash(e.target.value)}
              placeholder="Mặc định .env"
              className="w-full px-3 py-2 text-sm font-mono"
            />
          </div>
          <div>
            <label htmlFor="acc-quota-h" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              Quota (Tin / Giờ)
            </label>
            <input
              id="acc-quota-h"
              type="number"
              min={1}
              value={maxPerHour}
              onChange={(e) => setMaxPerHour(Number(e.target.value))}
              className="w-full px-3 py-2 text-sm font-mono"
            />
          </div>
          <div>
            <label htmlFor="acc-quota-d" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              Quota (Tin / 24h)
            </label>
            <input
              id="acc-quota-d"
              type="number"
              min={1}
              value={maxPerDay}
              onChange={(e) => setMaxPerDay(Number(e.target.value))}
              className="w-full px-3 py-2 text-sm font-mono"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 items-end">
          <div>
            <label htmlFor="acc-proxy" className="block text-xs font-mono text-[#A1A1AA] mb-1">
              Proxy riêng cho Nick này (Tùy chọn: socks5://user:pass@ip:port)
            </label>
            <input
              id="acc-proxy"
              type="text"
              value={proxyUrl}
              onChange={(e) => setProxyUrl(e.target.value)}
              placeholder="Để trống nếu dùng mạng trực tiếp"
              className="w-full px-3 py-2 text-sm font-mono"
            />
          </div>

          {showImport ? (
            <div>
              <label
                htmlFor="acc-session-file"
                className="block text-xs font-mono text-[#A1A1AA] mb-1"
              >
                Chọn file Telethon .session *
              </label>
              <input
                id="acc-session-file"
                type="file"
                accept=".session"
                onChange={(e) => setSessionFile(e.target.files?.[0] || null)}
                className="text-xs font-mono p-2 w-full"
                required
              />
            </div>
          ) : (
            <div className="flex justify-end">
              <button
                type="submit"
                className="px-5 py-2.5 bg-[#10B981] hover:bg-[#059669] text-[#052E16] font-bold text-xs font-mono uppercase tracking-wider cursor-pointer"
              >
                Thêm Tài Khoản
              </button>
            </div>
          )}
        </div>

        {showImport && (
          <div className="flex justify-end">
            <button
              type="submit"
              className="px-5 py-2 bg-[#10B981] hover:bg-[#059669] text-[#052E16] font-bold text-xs font-mono uppercase tracking-wider cursor-pointer"
            >
              Tải lên & Lưu Tài Khoản
            </button>
          </div>
        )}
      </form>

      {/* OTP / 2FA Modal Box */}
      {loginAcc && (
        <form
          onSubmit={handleVerifyOtp}
          className="p-5 border-2 border-[#F59E0B] bg-[#18181C] space-y-4"
        >
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-mono uppercase text-[#F59E0B] flex items-center gap-2">
              <Key size={18} />
              <span>
                Xác thực OTP / 2FA cho tài khoản #{loginAcc.id} ({loginAcc.phone})
              </span>
            </h3>
            <button
              type="button"
              onClick={() => setLoginAcc(null)}
              className="text-xs font-mono text-[#A1A1AA] hover:text-white cursor-pointer"
            >
              [Đóng]
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label htmlFor="otp-code" className="block text-xs font-mono text-[#A1A1AA] mb-1">
                Mã OTP gửi về Telegram / SMS *
              </label>
              <input
                id="otp-code"
                type="text"
                value={otpCode}
                onChange={(e) => setOtpCode(e.target.value)}
                placeholder="Nhập 5 chữ số OTP..."
                className="w-full px-3 py-2 text-sm font-mono"
                required
              />
            </div>
            <div>
              <label htmlFor="otp-2fa" className="block text-xs font-mono text-[#A1A1AA] mb-1">
                Mật khẩu 2FA (Nếu tài khoản có đặt Cloud Password)
              </label>
              <input
                id="otp-2fa"
                type="password"
                value={password2fa}
                onChange={(e) => setPassword2fa(e.target.value)}
                placeholder="Để trống nếu không bật 2FA..."
                className="w-full px-3 py-2 text-sm font-mono"
              />
            </div>
          </div>
          <div className="flex justify-end gap-3">
            <button
              type="submit"
              disabled={busyId === loginAcc.id}
              className="px-5 py-2 bg-[#F59E0B] text-[#09090B] font-bold text-xs font-mono uppercase cursor-pointer"
            >
              Xác nhận Đăng nhập
            </button>
          </div>
        </form>
      )}

      {/* Bulk Join & Clone Modal (Feature #4) */}
      {bulkJoinAcc && (
        <form
          onSubmit={handleExecuteBulkJoin}
          className="p-5 border-2 border-[#10B981] bg-[#18181C] space-y-4"
        >
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-mono uppercase text-[#10B981] flex items-center gap-2">
              <UsersFour size={18} />
              <span>
                Bulk Join & Nhân Bản Nhóm cho Nick #{bulkJoinAcc.id} ({bulkJoinAcc.label})
              </span>
            </h3>
            <button
              type="button"
              onClick={() => setBulkJoinAcc(null)}
              className="text-xs font-mono text-[#A1A1AA] hover:text-white cursor-pointer"
            >
              [Đóng]
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-mono text-[#A1A1AA] mb-1">
                Danh sách @username hoặc link t.me/+invite (Mỗi dòng 1 nhóm):
              </label>
              <textarea
                rows={4}
                value={bulkLinksText}
                onChange={(e) => setBulkLinksText(e.target.value)}
                placeholder="@nhom_mua_ban_1&#10;https://t.me/+AbCdEfGhIjK&#10;t.me/kenh_tin_tuc"
                className="w-full px-3 py-2 text-xs font-mono"
              />
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-mono text-[#A1A1AA] mb-1">
                  Hoặc Clone (Sao chép) toàn bộ nhóm Public từ Tài khoản khác:
                </label>
                <select
                  value={cloneFromAccId}
                  onChange={(e) => setCloneFromAccId(e.target.value)}
                  className="w-full px-3 py-2 text-xs font-mono"
                >
                  <option value="">-- Không dùng Clone từ nick khác --</option>
                  {accounts
                    .filter((a) => a.id !== bulkJoinAcc.id)
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        Clone từ #{a.id} · {a.label} ({a.joined_groups_count ?? 0} nhóm)
                      </option>
                    ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs font-mono text-[#A1A1AA] mb-1">
                    Delay tối thiểu (giây)
                  </label>
                  <input
                    type="number"
                    min={1}
                    value={joinDelayMin}
                    onChange={(e) => setJoinDelayMin(Number(e.target.value))}
                    className="w-full px-2.5 py-1.5 text-xs font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-mono text-[#A1A1AA] mb-1">
                    Delay tối đa (giây)
                  </label>
                  <input
                    type="number"
                    min={1}
                    value={joinDelayMax}
                    onChange={(e) => setJoinDelayMax(Number(e.target.value))}
                    className="w-full px-2.5 py-1.5 text-xs font-mono"
                  />
                </div>
              </div>
              <button
                type="submit"
                disabled={busyId === bulkJoinAcc.id}
                className="w-full py-2 bg-[#10B981] text-[#052E16] font-bold text-xs font-mono uppercase cursor-pointer"
              >
                {busyId === bulkJoinAcc.id ? 'Đang tham gia tuần tự...' : 'Bắt đầu Bulk Join'}
              </button>
            </div>
          </div>
        </form>
      )}

      {/* Account Joined Groups Inspector Drawer (Feature #1) */}
      {inspectAcc && (
        <div className="p-5 border-2 border-[#10B981] bg-[#121215] space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-mono uppercase text-[#10B981]">
              Danh Sách Nhóm Mà Nick #{inspectAcc.id} ({inspectAcc.label}) Đã Tham Gia (
              {inspectGroups.length} nhóm)
            </h3>
            <button
              type="button"
              onClick={() => setInspectAcc(null)}
              className="text-xs font-mono text-[#A1A1AA] hover:text-white cursor-pointer"
            >
              [Đóng danh sách]
            </button>
          </div>
          {inspectGroups.length === 0 ? (
            <p className="text-xs font-mono text-[#A1A1AA]">
              Chưa có dữ liệu nhóm cho nick này. Hãy bấm nút &quot;Quét Nhóm &amp; Topic&quot; trên
              dòng tài khoản để đồng bộ!
            </p>
          ) : (
            <div className="max-h-72 overflow-y-auto border border-[#27272A] bg-[#09090B]">
              <table className="w-full text-left border-collapse text-xs font-mono">
                <thead>
                  <tr className="border-b border-[#27272A] bg-[#18181C] text-[#A1A1AA]">
                    <th className="py-2 px-3">Tên Nhóm / Kênh</th>
                    <th className="py-2 px-3">Chat ID</th>
                    <th className="py-2 px-3">Loại / Forum Topics</th>
                    <th className="py-2 px-3">Vai Trò & Quyền Gửi Của Nick</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#27272A]">
                  {inspectGroups.map((g) => {
                    const mem = g.member_accounts?.find((m) => m.account_id === inspectAcc.id);
                    return (
                      <tr key={g.chat_id}>
                        <td className="py-2 px-3 font-sans font-semibold text-[#F4F4F5]">
                          {g.title}{' '}
                          {g.username && (
                            <span className="font-mono text-[#10B981]">@{g.username}</span>
                          )}
                        </td>
                        <td className="py-2 px-3 text-[#A1A1AA]">{g.chat_id}</td>
                        <td className="py-2 px-3">
                          {g.chat_type.toUpperCase()}
                          {g.is_forum && ` (${g.topics?.length || 0} Topics)`}
                        </td>
                        <td className="py-2 px-3">
                          {mem ? (
                            <div className="flex flex-wrap gap-1.5">
                              <span className="px-1.5 py-0.5 border border-[#10B981] text-[#10B981]">
                                {mem.role.toUpperCase()}
                              </span>
                              <span className="text-[#A1A1AA]">
                                Text:{mem.can_send_messages ? '✓' : '✗'} | Media:
                                {mem.can_send_media ? '✓' : '✗'} | Sticker:
                                {mem.can_send_stickers ? '✓' : '✗'} | Link:
                                {mem.can_embed_links ? '✓' : '✗'}
                              </span>
                            </div>
                          ) : (
                            'Member'
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Accounts Table */}
      <div className="border border-[#27272A] bg-[#121215] overflow-x-auto">
        <table className="w-full text-left border-collapse text-sm">
          <thead>
            <tr className="border-b border-[#27272A] bg-[#18181C] text-xs font-mono uppercase text-[#A1A1AA]">
              <th className="py-3 px-4">ID / Nhãn</th>
              <th className="py-3 px-4">SĐT / Username</th>
              <th className="py-3 px-4">Nhóm Đã Vào</th>
              <th className="py-3 px-4">Quota Gửi (1h / 24h)</th>
              <th className="py-3 px-4">Trạng Thái</th>
              <th className="py-3 px-4 text-right">Thao Tác Điều Khiển</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#27272A]">
            {accounts.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-8 text-center text-xs font-mono text-[#A1A1AA]">
                  Chưa có tài khoản nào. Hãy thêm tài khoản ở biểu mẫu phía trên.
                </td>
              </tr>
            ) : (
              accounts.map((acc) => (
                <tr key={acc.id} className="hover:bg-[#18181C]/60">
                  <td className="py-3 px-4">
                    <div className="font-semibold text-[#F4F4F5]">
                      #{acc.id} · {acc.label}
                    </div>
                    <div className="text-[11px] font-mono text-[#A1A1AA] truncate max-w-[200px]">
                      {acc.proxy_url || 'Direct IP'}
                    </div>
                  </td>
                  <td className="py-3 px-4 font-mono text-xs">
                    <div>{acc.phone}</div>
                    <div className="text-[#10B981]">
                      {acc.tg_username ? `@${acc.tg_username}` : acc.tg_user_id || '—'}
                    </div>
                  </td>
                  <td className="py-3 px-4 font-mono text-xs">
                    <button
                      type="button"
                      onClick={() => handleOpenJoinedGroups(acc)}
                      className="px-2.5 py-1 border border-[#27272A] bg-[#09090B] hover:border-[#10B981] text-[#10B981] cursor-pointer"
                    >
                      {acc.joined_groups_count ?? 0} nhóm (Xem)
                    </button>
                  </td>
                  <td className="py-3 px-4 font-mono text-xs">
                    <div>
                      1h:{' '}
                      <span className="text-[#10B981] font-bold">{acc.sent_last_hour ?? 0}</span> /{' '}
                      {acc.max_messages_per_hour ?? 60}
                    </div>
                    <div className="text-[#A1A1AA]">
                      24h: {acc.sent_last_24h ?? 0} / {acc.max_messages_per_day ?? 500}
                    </div>
                  </td>
                  <td className="py-3 px-4">
                    <span
                      className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-mono border ${
                        acc.status === 'connected'
                          ? 'border-[#10B981] bg-[#10B981]/10 text-[#10B981]'
                          : 'border-[#F59E0B] bg-[#F59E0B]/10 text-[#F59E0B]'
                      }`}
                    >
                      {acc.status === 'connected' ? (
                        <CheckCircle size={13} />
                      ) : (
                        <WarningCircle size={13} />
                      )}
                      {acc.status.toUpperCase()}
                    </span>
                    {acc.last_error && (
                      <div className="text-[11px] text-[#EF4444] mt-1">{acc.last_error}</div>
                    )}
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div className="inline-flex items-center gap-1.5 flex-wrap justify-end">
                      {acc.status !== 'connected' && (
                        <button
                          type="button"
                          disabled={busyId === acc.id}
                          onClick={() => handleSendOtp(acc)}
                          className="px-2 py-1 border border-[#F59E0B] text-[#F59E0B] hover:bg-[#F59E0B]/15 text-xs font-mono flex items-center gap-1 cursor-pointer"
                        >
                          <Key size={13} />
                          <span>Gửi OTP</span>
                        </button>
                      )}
                      <button
                        type="button"
                        disabled={busyId === acc.id}
                        onClick={() => handleConnect(acc)}
                        className="px-2 py-1 border border-[#27272A] bg-[#18181C] hover:border-[#10B981] text-xs font-mono flex items-center gap-1 cursor-pointer"
                        title="Kết nối phiên Telethon"
                      >
                        <Plug size={13} className="text-[#10B981]" />
                        <span>Kết nối</span>
                      </button>
                      <button
                        type="button"
                        disabled={busyId === acc.id}
                        onClick={() => handleHealthCheck(acc)}
                        className="px-2 py-1 border border-[#27272A] bg-[#18181C] hover:border-[#10B981] text-xs font-mono flex items-center gap-1 cursor-pointer"
                        title="Kiểm tra Ping, Sức khỏe & Quota"
                      >
                        <Heartbeat size={13} className="text-[#10B981]" />
                        <span>Health</span>
                      </button>
                      <button
                        type="button"
                        disabled={busyId === acc.id}
                        onClick={() => handleScanDialogs(acc)}
                        className="px-2 py-1 border border-[#10B981] text-[#10B981] hover:bg-[#10B981]/15 text-xs font-mono flex items-center gap-1 cursor-pointer"
                        title="Tự động lấy danh sách nhóm nick đã vào, quyền hạn, Rule cấm & Forum Topics"
                      >
                        <MagnifyingGlass size={13} />
                        <span>Quét Nhóm & Topic</span>
                      </button>
                      <button
                        type="button"
                        disabled={busyId === acc.id}
                        onClick={() => handleImportTelegramFolders(acc)}
                        className="px-2 py-1 border border-[#F59E0B] text-[#F59E0B] hover:bg-[#F59E0B]/15 text-xs font-mono flex items-center gap-1 cursor-pointer"
                        title="Copy các Folder sẵn có trên Telegram của nick này thành Folder độc lập trên Web Panel"
                      >
                        <FolderSimplePlus size={13} />
                        <span>Import Folder TG</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setBulkJoinAcc(acc)}
                        className="px-2 py-1 border border-[#27272A] bg-[#18181C] hover:border-[#10B981] text-xs font-mono flex items-center gap-1 cursor-pointer"
                        title="Tham gia nhiều nhóm hoặc Clone nhóm từ nick khác"
                      >
                        <UsersFour size={13} />
                        <span>Bulk Join</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(acc)}
                        className="px-2 py-1 border border-[#27272A] hover:border-[#EF4444] text-[#EF4444] text-xs font-mono cursor-pointer"
                        title="Xóa tài khoản"
                      >
                        <Trash size={13} />
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
