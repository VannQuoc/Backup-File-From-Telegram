import React, { useCallback, useEffect, useState } from 'react';
import {
  ChatCircleDots,
  CloudArrowDown,
  FolderOpen,
  Gauge,
  GearSix,
  PauseCircle,
  PlayCircle,
  SignOut,
  TerminalWindow,
  UsersThree,
} from '@phosphor-icons/react';
import { AccountsView } from './components/AccountsView';
import { BackupJobsView } from './components/BackupJobsView';
import { ChatsFoldersView } from './components/ChatsFoldersView';
import { DashboardView } from './components/DashboardView';
import { LoginView } from './components/LoginView';
import { LogsSettingsView } from './components/LogsSettingsView';
import { ScenariosView } from './components/ScenariosView';
import { api, getStoredToken, setStoredToken } from './lib/api';
import type {
  Account,
  BackupJob,
  ChatGroup,
  DashboardData,
  Folder,
  Scenario,
} from './types';

export const App: React.FC = () => {
  const [authenticated, setAuthenticated] = useState<boolean>(Boolean(getStoredToken()));
  const [activeTab, setActiveTab] = useState<string>('dashboard');

  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [chats, setChats] = useState<ChatGroup[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [backups, setBackups] = useState<BackupJob[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);

  const loadAllData = useCallback(async () => {
    if (!getStoredToken()) return;
    try {
      const [dash, accs, chs, flds, bks, scs] = await Promise.all([
        api.getDashboard(),
        api.listAccounts(),
        api.listChats(),
        api.listFolders(),
        api.listBackups(),
        api.listScenarios(),
      ]);
      setDashboard(dash);
      setAccounts(accs);
      setChats(chs);
      setFolders(flds);
      setBackups(bks);
      setScenarios(scs);
    } catch {
      // handled by 401 listener if token invalid
    }
  }, []);

  useEffect(() => {
    const onUnauthorized = () => setAuthenticated(false);
    window.addEventListener('tele-suite-unauthorized', onUnauthorized);
    return () => window.removeEventListener('tele-suite-unauthorized', onUnauthorized);
  }, []);

  useEffect(() => {
    if (authenticated) {
      loadAllData();
      const timer = window.setInterval(loadAllData, 15000);
      return () => window.clearInterval(timer);
    }
  }, [authenticated, loadAllData]);

  if (!authenticated) {
    return <LoginView onSuccess={() => setAuthenticated(true)} />;
  }

  const globalPaused = Boolean(dashboard?.stats?.global_paused);

  const handleToggleGlobalPause = async () => {
    try {
      await api.toggleGlobalPause(!globalPaused);
      await loadAllData();
    } catch {
      // ignore
    }
  };

  const navItems = [
    { id: 'dashboard', label: 'Tổng Quan', icon: Gauge },
    { id: 'accounts', label: `Tài Khoản (${accounts.length})`, icon: UsersThree },
    { id: 'chats', label: `Nhóm, Folder & Rule (${chats.length})`, icon: FolderOpen },
    { id: 'backups', label: `Luồng Backup (${backups.length})`, icon: CloudArrowDown },
    { id: 'scenarios', label: `Auto-Send & Fallback (${scenarios.length})`, icon: ChatCircleDots },
    { id: 'logs', label: 'Nhật Ký & Cài Đặt', icon: GearSix },
  ];

  return (
    <div className="min-h-[100dvh] bg-[#09090B] text-[#F4F4F5] flex flex-col lg:flex-row">
      {/* Left Technical Command Rail */}
      <aside className="w-full lg:w-64 shrink-0 border-b lg:border-b-0 lg:border-r border-[#27272A] bg-[#121215] flex flex-col justify-between">
        <div>
          <div className="p-4 border-b border-[#27272A] flex items-center justify-between gap-2">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 bg-[#10B981] text-[#052E16] flex items-center justify-center font-bold">
                <TerminalWindow size={18} weight="bold" />
              </div>
              <div>
                <div className="font-bold text-sm tracking-tight">TELE-SUITE v2.1</div>
                <div
                  className={`text-[10px] font-mono ${
                    globalPaused ? 'text-[#EF4444]' : 'text-[#10B981]'
                  }`}
                >
                  {globalPaused ? 'SYSTEM // PAUSED' : 'SQLITE WAL // ACTIVE'}
                </div>
              </div>
            </div>
          </div>

          {/* Global Panic / Kill Switch (Feature #17) */}
          <div className="p-2.5 border-b border-[#27272A]">
            <button
              type="button"
              onClick={handleToggleGlobalPause}
              className={`w-full px-3 py-2 text-xs font-mono font-bold uppercase flex items-center justify-center gap-2 border cursor-pointer transition-colors ${
                globalPaused
                  ? 'border-[#10B981] bg-[#10B981]/20 text-[#10B981]'
                  : 'border-[#EF4444] bg-[#EF4444]/15 text-[#EF4444] hover:bg-[#EF4444]/25'
              }`}
            >
              {globalPaused ? (
                <>
                  <PlayCircle size={16} weight="fill" />
                  <span>Tiếp Tục Hệ Thống</span>
                </>
              ) : (
                <>
                  <PauseCircle size={16} weight="fill" />
                  <span>Kill Switch (Dừng Khẩn)</span>
                </>
              )}
            </button>
          </div>

          <nav className="p-2 flex lg:flex-col gap-1 overflow-x-auto">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveTab(item.id)}
                  className={`px-3 py-2.5 text-left text-xs font-mono flex items-center gap-2.5 whitespace-nowrap transition-colors cursor-pointer ${
                    isActive
                      ? 'bg-[#10B981]/15 border-l-2 border-[#10B981] text-[#10B981] font-bold'
                      : 'text-[#A1A1AA] hover:bg-[#18181C] hover:text-[#F4F4F5]'
                  }`}
                >
                  <Icon size={17} />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        <div className="p-3 border-t border-[#27272A] hidden lg:block">
          <button
            type="button"
            onClick={() => {
              setStoredToken(null);
              setAuthenticated(false);
            }}
            className="w-full px-3 py-2 border border-[#27272A] hover:border-[#EF4444] text-xs font-mono text-[#A1A1AA] hover:text-[#EF4444] flex items-center justify-center gap-2 cursor-pointer"
          >
            <SignOut size={15} />
            <span>Đăng xuất Admin</span>
          </button>
        </div>
      </aside>

      {/* Main Workspace */}
      <main className="flex-1 p-6 lg:p-8 max-w-[1440px] w-full mx-auto space-y-4">
        {globalPaused && (
          <div className="p-3 border-2 border-[#EF4444] bg-[#EF4444]/15 flex items-center justify-between gap-4 text-xs font-mono text-[#EF4444]">
            <span>
              ⚠️ CHẾ ĐỘ TẠM DỪNG KHẨN CẤP (GLOBAL KILL SWITCH) ĐANG BẬT: Mọi luồng Auto-Send &
              Backup tự động đang được giữ yên.
            </span>
            <button
              type="button"
              onClick={handleToggleGlobalPause}
              className="px-3 py-1 bg-[#10B981] text-[#052E16] font-bold uppercase cursor-pointer"
            >
              Chạy lại ngay
            </button>
          </div>
        )}

        {activeTab === 'dashboard' && (
          <DashboardView
            data={dashboard}
            onNavigate={setActiveTab}
            onRefresh={loadAllData}
          />
        )}
        {activeTab === 'accounts' && (
          <AccountsView accounts={accounts} onRefresh={loadAllData} />
        )}
        {activeTab === 'chats' && (
          <ChatsFoldersView
            accounts={accounts}
            chats={chats}
            folders={folders}
            onRefresh={loadAllData}
          />
        )}
        {activeTab === 'backups' && (
          <BackupJobsView
            accounts={accounts}
            chats={chats}
            backups={backups}
            onRefresh={loadAllData}
          />
        )}
        {activeTab === 'scenarios' && (
          <ScenariosView
            accounts={accounts}
            chats={chats}
            folders={folders}
            scenarios={scenarios}
            onRefresh={loadAllData}
          />
        )}
        {activeTab === 'logs' && <LogsSettingsView onRefresh={loadAllData} />}
      </main>
    </div>
  );
};
