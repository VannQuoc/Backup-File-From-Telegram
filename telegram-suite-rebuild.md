# Kế Hoạch Tái Cấu Trúc Toàn Diện: Telegram Backup & Auto-Messaging Suite (Web Panel A–Z)

## 1. Overview (Tổng quan & Mục tiêu)
Đập đi xây lại toàn bộ hệ thống `Backup-File-From-Telegram` từ công cụ CLI đơn tài khoản thành **Web Application quản trị tập trung (All-in-One Telegram Automation & Backup Suite)**:
- **Quản lý Đa Tài Khoản (Multi-Account):** Đăng nhập trực tiếp trên Web (Phone $\rightarrow$ OTP $\rightarrow$ 2FA Password, hoặc import `.session`), gán Proxy riêng, theo dõi trạng thái sống/FloodWait của từng tài khoản.
- **Hệ thống Backup Mở Rộng Toàn Diện:** Cấu hình linh hoạt từng luồng Backup (chọn tài khoản đọc nguồn, tài khoản/bot gửi đích, chọn Group/Channel/Topic đích, lọc theo loại nội dung: Document theo đuôi file `.txt`/`.zip`/`.rar`/tùy chỉnh, Ảnh, Video, Text, Sticker, Voice; lọc từ khóa; chống trùng lặp bằng fingerprint; tự động Download & Re-upload khi nguồn bật *Protected Content*).
- **Hệ thống Auto-Messaging, Folder & Kịch Bản (Scenarios):**
  - Gom nhóm các Group/Topic thành **Folder** (nhiều-nhiều), gán kịch bản gửi tin cho cả Folder hoặc ghi đè (override) riêng cho từng Group.
  - Hỗ trợ nhiều **Kịch bản (Scenarios)**: Gửi Text, Media/File, Sticker, hoặc Forward từ kênh mẫu theo chu kỳ lặp lại (Interval + Jitter ngẫu nhiên) hoặc lịch cố định (Cron/Khung giờ).
- **Rule & Fallback Engine (Hướng 3 - Hybrid):**
  - Quản lý quy tắc hạn chế của từng nhóm (`no_links`, `no_stickers`, `no_forwards`, `no_media`, `no_bot_mentions`, `slow_mode`).
  - Kết hợp **Auto-Learn** (tự động phát hiện quyền cấm từ `ChatBannedRights` và lỗi RPC thực tế khi gửi) + **Auto-Transform** (tự đổi Forward sang Copy, tự lọc `@bot`, tự ẩn/xóa link) + **Custom Fallback Content** (nội dung dự phòng do người dùng soạn sẵn cho nhóm cấm link/sticker/media).

---

## 2. Project Type
- **Project Type:** **WEB + BACKEND (Full-Stack Local/Self-Hosted Web Application)**
- **Primary Agents:** `database-architect` (P0) $\rightarrow$ `backend-specialist` (P1) $\rightarrow$ `frontend-specialist` (P2) $\rightarrow$ `test-engineer` & `security-auditor` (P3)

---

## 3. Success Criteria (Tiêu chí Hoàn thành)
1. **Bảo mật Web Panel:** Xác thực bằng mật khẩu Admin, đối chiếu với chuỗi băm `WEB_ADMIN_PASSWORD_SHA256` trong `.env` (người dùng tự hash SHA-256), cấp Bearer Token (HMAC-signed session) cho REST API & WebSocket. Loại bỏ hoàn toàn Telegram Manager Bot cũ.
2. **Multi-Account:** Thêm, đăng nhập (OTP/2FA), bật/tắt, cấu hình proxy và quản lý nhiều `.session` trực tiếp trên Web Panel mà không cần dùng CLI.
3. **Database SQLite Mới Hoàn Toàn (WAL Mode):** Khởi tạo schema sạch trong `./data/state.sqlite` lưu trữ đầy đủ trạng thái tài khoản, danh sách nhóm, ma trận rule cấm của nhóm, folder, kịch bản gửi tin, cấu hình luồng backup, lịch sử file đã backup (`sync_state`, `file_fingerprints`) và nhật ký gửi tin (`execution_logs`).
4. **Backup Engine Toàn Diện:** Chạy song song cả Live Listener (bắt tin nhắn mới tức thì) và Reconcile/Catch-up backlog cho nhiều luồng backup; lọc đúng loại media/đuôi file, routing đúng Topic đích, xử lý mượt Protected Content.
5. **Auto-Message & Fallback Engine:** Gửi tự động theo lịch đến các Folder/Group; khi gặp nhóm cấm Forward/Sticker/Link/Tag Bot thì tự động kích hoạt chuỗi Fallback (biến đổi nội dung hoặc lấy bản tin dự phòng) và ghi nhận rule vào SQLite.
6. **Web Panel trực quan:** Có đầy đủ các trang Login, Dashboard, Quản lý Account, Quản lý Nhóm & Folder (kèm Rule Matrix), Quản lý Luồng Backup, Quản lý Kịch bản & Lịch Auto-Send, Logs real-time và Settings.

---

## 4. Tech Stack (Công nghệ Sử dụng)

| Tầng | Công nghệ | Lý do lựa chọn |
|------|-----------|----------------|
| **Backend API & Lifespan** | **Python 3.12+ / FastAPI + Uvicorn + WebSockets** | Chạy chung `asyncio` event loop với các `TelegramClient` của Telethon, hỗ trợ đẩy log và trạng thái real-time qua WebSocket. |
| **Telegram Core** | **Telethon (Async)** | Hỗ trợ đầy đủ Userbot MTProto, đọc lịch sử, tải Protected Content, gửi Sticker/File, Forward và đọc `ChatBannedRights`. |
| **Scheduler** | **Asyncio Scheduler Engine / APScheduler** | Điều phối lịch gửi tin tự động theo từng nhóm/folder với độ trễ ngẫu nhiên (jitter) và tôn trọng `FloodWaitError` / `SlowModeWaitError`. |
| **Database** | **SQLite 3 (WAL Mode + Foreign Keys)** | Lưu trữ gọn nhẹ trong `./data/state.sqlite`, truy xuất nhanh, không cần cài đặt DB server rời, hỗ trợ migration từ DB cũ. |
| **Frontend Web UI** | **React 19 + Vite + TypeScript + Tailwind CSS + Lucide Icons** | Giao diện SPA tốc độ cao, dễ thao tác với bảng Rule Matrix, trình dựng kịch bản đa bước (Scenario Builder) và quản lý Folder. |

---

## 5. Thiết kế Database SQLite (`./data/state.sqlite`)

1. **`accounts`**: `id`, `label`, `phone`, `api_id`, `api_hash`, `session_path`, `is_bot`, `proxy_config_json`, `status` (`connected`, `need_login`, `flood_wait`, `disabled`), `flood_wait_until`, `created_at`, `updated_at`.
2. **`chat_groups`**: `chat_id` (PK), `title`, `username`, `chat_type` (`group`, `supergroup`, `channel`, `forum`), `is_forum`, `default_topic_id`, `discovered_by_account_id`, `updated_at`.
3. **`chat_rules`**: `chat_id` (PK, FK $\rightarrow$ `chat_groups`), `no_links`, `no_stickers`, `no_forwards`, `no_media`, `no_bot_mentions`, `slow_mode_seconds`, `custom_banned_words_json`, `auto_learned` (bool), `updated_at`.
4. **`folders`**: `id` (PK), `name`, `description`, `color`, `enabled`, `created_at`, `updated_at`.
5. **`folder_chats`**: `folder_id` (FK), `chat_id` (FK), `topic_id` (nullable), PK (`folder_id`, `chat_id`, `topic_id`).
6. **`backup_jobs`**:
   - `id` (PK), `label`, `enabled`, `reader_account_id` (FK), `sender_account_id` (FK)
   - `source_chat_id`, `source_topic_id` (nullable), `dest_chat_id`, `dest_topic_default`, `dest_topic_archive`
   - `filter_config_json` (chọn loại media: `documents`, `extensions`, `photos`, `videos`, `text`, `stickers`, `voice`, `include_keywords`, `exclude_keywords`)
   - `caption_mode` (`preserve`, `strip`, `strip_for_txt`, `custom_template`), `dedupe_enabled`, `allow_protected_fallback`, `send_delay_min_ms`, `send_delay_max_ms`, `last_scanned_msg_id`
7. **`sync_state`** & **`file_fingerprints`**: Lưu lịch sử từng `source_msg_id` của mỗi `backup_job_id`, trạng thái (`synced`, `skipped`, `failed`), `dest_msg_id`, `fingerprint` để chống trùng lặp.
8. **`scenarios` (Kịch bản gửi tin)**:
   - `id` (PK), `name`, `description`, `enabled`, `sender_account_id` (FK hoặc `auto_rotate`)
   - `schedule_type` (`interval`, `daily_times`, `cron`), `interval_seconds`, `jitter_min_sec`, `jitter_max_sec`, `daily_times_json`
   - `selection_mode` (`sequential`, `random`, `all_steps`)
9. **`scenario_steps` (Nội dung & Fallback trong kịch bản)**:
   - `id` (PK), `scenario_id` (FK), `step_order`, `action_type` (`send_text`, `send_media`, `send_sticker`, `forward_message`)
   - `primary_content_json` (text, media_path, sticker_file_id/source_msg, forward_from_chat_id + msg_id)
   - `fallback_policy_json` (cấu hình Hướng 3: `on_no_forward`: `copy_content` | `use_fallback_text`; `on_no_links`: `strip_links` | `mask_links` | `use_fallback_text`; `on_no_sticker`: `use_fallback_text` | `skip`; `on_no_media`: `use_fallback_text`; `on_no_bot_mention`: `strip_bot_tags`; kèm `fallback_text`, `fallback_no_link_text`)
10. **`scenario_targets` (Gán kịch bản cho Folder hoặc Group riêng)**:
    - `id` (PK), `scenario_id` (FK), `target_type` (`folder` | `chat`), `target_id` (`folder_id` hoặc `chat_id`), `topic_id` (nullable), `override_step_id` (nullable - cho phép chỉ định riêng chat này gửi nội dung gì), `enabled`, `last_sent_at`, `next_run_at`.
11. **`execution_logs` & `app_settings`**: Lưu nhật ký gửi tin/backup (kèm lý do fallback nếu có) và cấu hình chung.

---

## 6. File Structure (Cấu trúc Thư mục Dự kiến)

```text
d:\Code\Backup-File-From-Telegram\
├── backend/
│   ├── __init__.py
│   ├── app.py                  # FastAPI entry, lifespan, CORS, static serving
│   ├── config.py               # Cấu hình hệ thống & đường dẫn data
│   ├── database/
│   │   ├── db.py               # SQLite connection manager (WAL mode) & migrations
│   │   ├── models.py           # Dataclasses / Pydantic schemas
│   │   └── repositories/       # Truy vấn cho Accounts, Chats/Rules, Folders, Backup, Scenarios, Logs
│   ├── telegram/
│   │   ├── client_pool.py      # Quản lý đa tài khoản Telethon + Login flow (OTP/2FA)
│   │   ├── dialog_scanner.py   # Quét danh sách nhóm, forum topics & tự đọc ChatBannedRights
│   │   ├── rule_engine.py      # Hybrid Rule & Fallback Resolver (Forward->Copy, Strip Link/Bot, Sticker->Text)
│   │   ├── backup_engine.py    # Live listener + Catch-up sync toàn diện (File, Media, Text, Protected fallback)
│   │   └── auto_sender.py      # Scheduler chạy kịch bản theo Folder/Chat, xử lý SlowMode/FloodWait
│   └── routers/
│       ├── accounts.py         # API quản lý account & login OTP/2FA
│       ├── chats_folders.py    # API quản lý nhóm, đồng bộ dialog, Folder & Rule Matrix
│       ├── backups.py          # API quản lý luồng Backup, trạng thái sync, trigger chạy ngay
│       ├── scenarios.py        # API quản lý kịch bản Auto-Send, bước kịch bản, gán Folder/Chat
│       └── system.py           # API dashboard stats, real-time logs (WS), settings
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── api/                # Fetch client kết nối FastAPI
│       ├── pages/
│       │   ├── DashboardPage.tsx       # Tổng quan tài khoản, luồng backup, lịch sắp chạy, log mới nhất
│       │   ├── AccountsPage.tsx        # Thêm/xoá nick, nhập OTP/2FA trên Web, cấu hình Proxy
│       │   ├── ChatsFoldersPage.tsx    # Gom nhóm vào Folder, bật/tắt Rule cấm từng nhóm (Link/Sticker/Forward/Bot)
│       │   ├── BackupJobsPage.tsx      # Tạo/sửa luồng Backup toàn diện, xem lịch sử file đã backup
│       │   ├── ScenariosPage.tsx       # Tạo kịch bản gửi tin, cấu hình Fallback (Hướng 3), gán Folder/Group
│       │   ├── LogsPage.tsx            # Nhật ký hoạt động & lịch sử kích hoạt Fallback
│       │   └── SettingsPage.tsx        # Cài đặt chung, độ trễ mặc định, sao lưu DB
│       └── components/         # Giao diện dùng chung, Modal, Bảng Rule Matrix
├── tests/                      # Unit & Integration tests cho DB, Rule Fallback Engine, Backup & API
├── main.py                     # Script khởi chạy hợp nhất (FastAPI + Background Workers)
└── requirements.txt
```

---

## 7. Task Breakdown (Chi tiết Công việc)

### Task 1: Thiết kế & Khởi tạo SQLite Schema Mới + Migration (P0)
- **Agent:** `database-architect` | **Skill:** `database-design`, `clean-code`
- **Priority:** P0 | **Dependencies:** None
- **INPUT:** Cấu trúc DB cũ trong `tele_backup/store.py` và yêu cầu 11 bảng mới.
- **OUTPUT:** `backend/database/db.py`, `backend/database/models.py`, và các repository quản lý Accounts, Chats/Rules, Folders, Backup Jobs, Scenarios, Logs; tự động migrate dữ liệu từ `sources`/`sync_state` cũ nếu có.
- **VERIFY:** Chạy pytest kiểm tra khởi tạo bảng, CRUD cho tất cả thực thể và WAL checkpoint thành công.

### Task 2: Xây dựng Telethon Multi-Account Pool & Web Login Flow (P1)
- **Agent:** `backend-specialist` | **Skill:** `python-patterns`, `clean-code`
- **Priority:** P1 | **Dependencies:** Task 1
- **INPUT:** Danh sách tài khoản trong bảng `accounts` và file `.session`.
- **OUTPUT:** `backend/telegram/client_pool.py` hỗ trợ kết nối nhiều tài khoản cùng lúc, đăng nhập qua Web (`send_code` $\rightarrow$ `sign_in` OTP $\rightarrow$ `sign_in` 2FA password), quét danh sách Group/Channel/Topic (`dialog_scanner.py`) và tự động đọc `ChatBannedRights` của từng nhóm.
- **VERIFY:** Test mock client pool: khởi tạo session, xử lý luồng login 2 bước và lấy danh sách dialog + quyền cấm của nhóm.

### Task 3: Xây dựng Hybrid Rule & Fallback Engine - Hướng 3 (P1)
- **Agent:** `backend-specialist` | **Skill:** `python-patterns`, `clean-code`
- **Priority:** P1 | **Dependencies:** Task 1, Task 2
- **INPUT:** Một bước trong kịch bản (`ScenarioStep` gồm nội dung chính + cấu hình fallback) và quy tắc của nhóm đích (`ChatRule`).
- **OUTPUT:** `backend/telegram/rule_engine.py`:
  1. **Pre-send Transform:** Kiểm tra rule của nhóm trong DB (`no_forwards`, `no_links`, `no_stickers`, `no_media`, `no_bot_mentions`) để tự động chuyển đổi (VD: đổi Forward sang Copy; xóa/ẩn link hoặc chuyển sang `fallback_no_link_text`; xóa `@bot`; đổi Sticker/Media sang `fallback_text`).
  2. **Runtime Error Auto-Learn & Retry:** Nếu khi gửi thực tế bị Telegram trả lỗi (`ChatForwardsRestrictedError`, `ChatSendStickersForbiddenError`, `ChatSendMediaForbiddenError`, v.v.), tự động cập nhật cờ cấm vào bảng `chat_rules` trong SQLite và thực hiện gửi lại ngay bằng phương án Fallback.
- **VERIFY:** Unit test đầy đủ các kịch bản cấm Link, cấm Sticker, cấm Forward, cấm Tag Bot và kiểm tra DB tự động cập nhật rule sau khi bắt lỗi RPC.

### Task 4: Xây dựng Backup Engine Mở Rộng Toàn Diện (P1)
- **Agent:** `backend-specialist` | **Skill:** `python-patterns`, `clean-code`
- **Priority:** P1 | **Dependencies:** Task 2
- **INPUT:** Cấu hình `backup_jobs` từ SQLite.
- **OUTPUT:** `backend/telegram/backup_engine.py` hỗ trợ:
  - Chọn tài khoản đọc nguồn & tài khoản đẩy đích.
  - Bộ lọc đa năng: Document (theo đuôi `.txt`, `.zip`, `.rar` hoặc mọi đuôi), Photo, Video, Text, Sticker, Voice + Lọc từ khóa.
  - Định tuyến Topic đích theo loại file (Archive topic vs Default topic), chế độ xử lý Caption, Dedupe bằng fingerprint, và Protected Content fallback (Download tạm $\rightarrow$ Re-upload).
- **VERIFY:** Unit test bộ lọc nội dung, định tuyến topic, dedupe và luồng fallback khi `noforwards=True`.

### Task 5: Xây dựng Auto-Messaging Scheduler & Scenario Runner (P1)
- **Agent:** `backend-specialist` | **Skill:** `python-patterns`, `clean-code`
- **Priority:** P1 | **Dependencies:** Task 3
- **INPUT:** Danh sách `scenarios`, `scenario_steps`, `scenario_targets` (Folder & Group overrides).
- **OUTPUT:** `backend/telegram/auto_sender.py` chạy nền định kỳ:
  - Giải nén các Folder thành danh sách Group/Topic mục tiêu (ưu tiên cấu hình override riêng của từng chat nếu có).
  - Thực thi gửi Text / Media / Sticker / Forward thông qua `rule_engine.py`.
  - Hỗ trợ lịch lặp lại (`interval` + random `jitter`), khung giờ cố định, tự động chờ khi gặp `SlowModeWaitError` hoặc `FloodWaitError`, và ghi log chi tiết vào `execution_logs`.
- **VERIFY:** Test lập lịch, giải nén Folder + Chat override, và thực thi kịch bản qua Rule Engine.

### Task 6: Xây dựng FastAPI REST API & Real-time WebSocket (P1)
- **Agent:** `backend-specialist` | **Skill:** `api-patterns`, `clean-code`
- **Priority:** P1 | **Dependencies:** Task 2, Task 3, Task 4, Task 5
- **INPUT:** Các module core trong `backend/database` và `backend/telegram`.
- **OUTPUT:** `backend/app.py` và các routers (`accounts`, `chats_folders`, `backups`, `scenarios`, `system`) cung cấp đầy đủ API quản lý từ A–Z và WebSocket stream log thời gian thực.
- **VERIFY:** Test toàn bộ endpoints với `TestClient` của FastAPI (trả về 200 OK, đúng schema JSON).

### Task 7: Xây dựng Giao diện Web Panel (React + Vite + Tailwind) (P2)
- **Agent:** `frontend-specialist` | **Skill:** `frontend-design`, `frontend-architecture`, `clean-code`
- **Priority:** P2 | **Dependencies:** Task 6
- **INPUT:** REST API từ Backend.
- **OUTPUT:** Ứng dụng Frontend trong `frontend/` với thiết kế Dashboard kỹ thuật hiện đại (Dark/Light chuẩn, **không dùng màu tím/purple**), gồm 7 phân khu:
  1. **Tổng quan (Dashboard):** Thống kê tài khoản, số file đã backup, số tin tự động đã gửi, trạng thái worker.
  2. **Tài khoản (Accounts):** Thêm nick, nhập OTP/2FA trực tiếp trên modal, import `.session` sẵn có, gắn proxy.
  3. **Nhóm & Folder (Chats & Folders):** Quét nhóm từ Telegram, tạo Folder, gán nhóm vào Folder, và **Bảng Ma Trận Rule (Rule Matrix)** cho phép bật/tắt nhanh: *Cấm Link, Cấm Sticker, Cấm Forward, Cấm Media, Cấm Tag Bot* cho từng nhóm.
  4. **Quản lý Backup (Backup Flows):** Tạo luồng backup từ nhóm nguồn $\rightarrow$ nhóm/topic đích, chọn loại file/media cần lấy, bật Protected Fallback, nút "Sync Ngay" và xem danh sách file đã backup.
  5. **Kịch bản Auto-Send (Scenarios & Schedules):** Tạo nhiều kịch bản (Text, Ảnh/File, Sticker, Forward), cấu hình chu kỳ gửi lại, cấu hình **Rule Fallback (Hướng 3)** cho từng bước, và gán kịch bản cho Folder hoặc từng Chat.
  6. **Nhật ký & Lịch sử (Logs & History):** Xem lịch sử file đã backup và lịch sử gửi tin tự động (hiển thị rõ tin nào gửi gốc, tin nào đã qua Fallback).
  7. **Cài đặt (Settings):** Cấu hình thông số hệ thống, xuất/sao lưu SQLite DB.
- **VERIFY:** `npm run build` thành công không lỗi TypeScript, FastAPI mount bản build tĩnh và truy cập mượt trên trình duyệt.

### Task 8: Tích hợp Khởi chạy Hợp nhất & Kiểm thử Toàn diện (Phase X)
- **Agent:** `test-engineer` | **Skill:** `testing-patterns`, `verify-changes`, `lint-and-validate`
- **Priority:** P3 | **Dependencies:** Task 7
- **INPUT:** Toàn bộ Backend + Frontend.
- **OUTPUT:** Cập nhật `main.py` và `README.md` để khởi chạy Web Panel + Background Daemon dễ dàng; chạy bộ test `pytest`, `ruff`, `npm run build` và các script kiểm tra chất lượng.
- **VERIFY:** Tất cả unit/integration tests pass, build frontend sạch, server chạy thực tế phản hồi tốt.

---

## 8. Phase X: Verification Checklist
- [x] Database schema mới khởi tạo sạch (`state.sqlite` WAL mode)
- [x] Tất cả bài test `pytest` cho SQLite, Rule Fallback Engine, Backup Engine, Auto-Sender và FastAPI đều PASS (`8 passed`)
- [x] Lint & Format (`ruff check` / `tsc --noEmit`) không có lỗi
- [x] Frontend build (`npm run build`) thành công, không dùng màu purple/violet, bố cục chuẩn kỹ thuật (`DESIGN.md`)
- [x] Security scan (`security_scan.py`) không lộ credentials hay lỗi bảo mật (`[OK] SECURE`)

---

## 9. Giai Đoạn Mở Rộng (18 Tính Năng Thực Chiến & Quản Lý Membership/Topic Trực Quan)
- [ ] **Membership & Topic Discovery (`account_memberships`, `chat_topics`):** Lưu chi tiết từng Account tham gia nhóm nào, quyền gửi tin, danh sách Forum Topic; chọn Nhóm/Topic bằng Dropdown theo Account thay vì nhập ID thủ công.
- [ ] **Import Folder từ Telegram sang Folder Web Độc Lập:** Cho phép copy nhanh Folder từ Telegram làm mẫu nhưng quản lý hoàn toàn độc lập trên Web theo từng kịch bản.
- [ ] **18 Tính Năng Nâng Cao:**
  1. Account Membership Explorer (Lọc nhóm theo từng Account, xem vai trò & quyền hạn)
  2. Forum Topic Inspector (Tự động lấy danh sách Topic con của nhóm Forum)
  3. Import Telegram Native Folders thành Folder Web độc lập
  4. Bulk Join & Clone Memberships giữa các Account
  5. Visual Message Picker (Duyệt tin nhắn gần nhất của nhóm/kênh trên Web để chọn bài Forward)
  6. Account Health Check & Quota Monitor
  7. Spintax (`{A|B|C}`) & Dynamic Variables (`{chat_title}`, `{date}`, `{time}`, `{random_id}`)
  8. Active Hours / Quiet Hours Window (Khung giờ hoạt động cho kịch bản)
  9. Daily / Hourly Rate Limit Quota cho từng Account
  10. Auto-Delete Previous Sent Message (Tự xóa tin nhắn cũ của lượt trước trong nhóm)
  11. Smart Account Rotation & Membership-Aware Failover (Chỉ xoay vòng các nick đã ở trong nhóm đích & còn hạn mức)
  12. Media & Sticker Template Library (`media_library`)
  13. Auto-Create Destination Forum Topic ngay trên Web
  14. Content-Hash SHA-256 Deduplication khi tải file Backup
  15. Date Range & Message ID Range Backup Filter
  16. Auto-Rename File (Prefix/Suffix) & Caption Watermark khi Backup
  17. Global Panic / Kill Switch trên thanh điều khiển
  18. One-Click Config JSON Export/Import & Tải trực tiếp file `.sqlite` snapshot



