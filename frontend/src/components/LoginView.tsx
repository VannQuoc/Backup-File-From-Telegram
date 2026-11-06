import React, { useState } from 'react';
import { LockKey, ShieldCheck, TerminalWindow } from '@phosphor-icons/react';
import { api, setStoredToken } from '../lib/api';

interface LoginViewProps {
  onSuccess: () => void;
}

export const LoginView: React.FC<LoginViewProps> = ({ onSuccess }) => {
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.login(password.trim());
      setStoredToken(res.token);
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Đăng nhập thất bại');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[100dvh] bg-[#09090B] text-[#F4F4F5] flex items-center justify-center p-6">
      <div className="w-full max-w-md border border-[#27272A] bg-[#121215] p-8 rounded-sm">
        <div className="flex items-center gap-3 pb-6 mb-6 border-b border-[#27272A]">
          <div className="w-10 h-10 bg-[#10B981]/15 border border-[#10B981] flex items-center justify-center text-[#10B981]">
            <TerminalWindow size={22} weight="bold" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight">TELE-SUITE CONTROL</h1>
            <p className="text-xs font-mono text-[#A1A1AA]">
              MULTI-ACCOUNT BACKUP & AUTO-MESSAGING ENGINE
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label
              htmlFor="admin-password"
              className="block text-xs font-mono uppercase tracking-wider text-[#A1A1AA] mb-2"
            >
              Mật khẩu Quản trị (Hoặc chuỗi SHA-256)
            </label>
            <div className="relative">
              <input
                id="admin-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Nhập mật khẩu khớp với WEB_ADMIN_PASSWORD_SHA256..."
                className="w-full px-3.5 py-2.5 pl-10 bg-[#09090B] border border-[#27272A] text-sm font-mono text-[#F4F4F5] focus:border-[#10B981]"
                required
              />
              <LockKey
                size={18}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-[#A1A1AA]"
              />
            </div>
            <p className="mt-2 text-xs text-[#A1A1AA]">
              Hệ thống tự động băm SHA-256 mật khẩu bạn nhập và đối chiếu an toàn với biến{' '}
              <code className="font-mono text-[#10B981]">WEB_ADMIN_PASSWORD_SHA256</code> trong{' '}
              <code className="font-mono">.env</code> (mặc định mẫu: <code className="font-mono">admin123</code>).
            </p>
          </div>

          {error && (
            <div className="p-3 border border-[#EF4444] bg-[#EF4444]/10 text-xs text-[#EF4444] font-mono">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 px-4 bg-[#10B981] hover:bg-[#059669] active:translate-y-[1px] text-[#052E16] font-bold text-sm rounded-sm flex items-center justify-center gap-2 transition-colors cursor-pointer disabled:opacity-50"
          >
            <ShieldCheck size={18} weight="bold" />
            <span>{loading ? 'ĐANG XÁC THỰC...' : 'MỞ BẢNG ĐIỀU KHIỂN'}</span>
          </button>
        </form>
      </div>
    </div>
  );
};

