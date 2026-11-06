# TELE-SUITE v2.0 — Hệ Thống Web Quản Lý Đa Tài Khoản, Backup Toàn Diện & Auto-Messaging (A–Z)

Bộ công cụ Web Panel hoàn chỉnh (FastAPI + Telethon Async + React + SQLite WAL) hỗ trợ:

1. **Bảo mật Web Panel bằng SHA-256:**
   - Mật khẩu quản trị được băm SHA-256 và cấu hình qua biến `WEB_ADMIN_PASSWORD_SHA256` trong `.env`.
   - Khi đăng nhập trên Web, bạn có thể nhập mật khẩu gốc (server tự băm SHA-256 và đối chiếu bằng `hmac.compare_digest`) hoặc dán trực tiếp chuỗi SHA-256.
2. **Quản lý Đa Tài Khoản (Multi-Account):**
   - Thêm không giới hạn tài khoản Telegram.
   - Đăng nhập trực tiếp trên Web Panel (Gửi mã OTP $\rightarrow$ Nhập OTP $\rightarrow$ Nhập mật khẩu 2FA nếu có) hoặc tải lên file `.session` sẵn có.
   - Hỗ trợ cấu hình Proxy riêng (`socks5://...`, `http://...`) cho từng tài khoản.
   - Tính năng **Quét Nhóm & Rule Tự Động**: Tự động lấy danh sách Group/Supergroup/Forum/Channel và tự động đọc `ChatBannedRights` + `noforwards`.
3. **Hệ thống Backup Mở Rộng Toàn Diện:**
   - Chỉ định tài khoản đọc nguồn (`reader_account_id`) và tài khoản đẩy đích (`sender_account_id`).
   - Hỗ trợ lọc theo loại nội dung: **Tài liệu/File** (theo đuôi `.txt`, `.zip`, `.rar` hoặc mọi đuôi), **Hình ảnh**, **Video**, **Văn bản (Text)**, **Sticker**, **Voice/Audio**.
   - Định tuyến thông minh: Đẩy file nén (`.zip`, `.rar`, `.7z`) vào Topic Archive riêng, các nội dung khác vào Topic Mặc định.
   - Hỗ trợ lọc từ khóa bắt buộc / từ khóa loại trừ, tùy chỉnh chế độ Caption, chống trùng lặp bằng `file_fingerprints`.
   - **Protected Content Fallback:** Tự động tải tạm về máy và Re-upload lên nhóm đích khi nhóm nguồn bật chế độ chống sao chép/chuyển tiếp (`noforwards`).
4. **Hệ thống Auto-Messaging, Folder Gom Nhóm & Hybrid Rule Fallback (Hướng 3):**
   - **Folder Gom Nhóm:** Gom nhiều nhóm vào 1 Folder (VD: *Folder Nhóm Mua Bán*, *Folder Nhóm Cộng Đồng*).
   - **Kịch bản Đa bước (Scenarios):** Hỗ trợ gửi Text, Ảnh/Video/File, Sticker, hoặc Forward tin nhắn từ kênh mẫu theo chu kỳ lặp lại (`interval` + `jitter` ngẫu nhiên chống spam).
   - **Phân phối linh hoạt:** Gán kịch bản cho cả Folder hoặc chỉ định riêng từng nhóm gửi nội dung ghi đè (`override_text_content`).
   - **Hybrid Rule & Fallback Engine (Hướng 3):**
     - **Lớp 1 (Pre-Send Transform):** Tự động kiểm tra quy tắc của nhóm trong SQLite (`no_links`, `no_stickers`, `no_forwards`, `no_media`, `no_bot_mentions`, `banned_words`) để biến đổi tin nhắn (Đổi Forward $\rightarrow$ Copy nội dung; xóa hoặc che link `domain[.]com` hoặc dùng `fallback_no_link_text`; xóa `@bot`; đổi Sticker/Media sang `fallback_text`).
     - **Lớp 2 (Runtime Auto-Learn & Retry):** Nếu khi gửi thực tế bị Telegram từ chối (VD: `CHAT_SEND_STICKERS_FORBIDDEN`, `CHAT_FORWARDS_RESTRICTED`), hệ thống tự động lưu cờ cấm vào SQLite (`auto_learned = 1`) và lập tức gửi lại bằng phương án dự phòng!

---

## Cài Đặt & Khởi Chạy

### 1. Cài đặt thư viện Backend & Build Frontend

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env

cd frontend
npm install
npm run build
cd ..
```

### 2. Cấu hình `.env`

Tạo mã SHA-256 cho mật khẩu của bạn (ví dụ bằng PowerShell hoặc trong mục **Cài đặt** của Web Panel):

```powershell
python -c "import hashlib; print(hashlib.sha256(b'mat_khau_cua_ban').hexdigest())"
```

Cập nhật vào `.env`:

```dotenv
# Mặc định mẫu bên dưới là SHA-256 của "admin123"
WEB_ADMIN_PASSWORD_SHA256=240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9
WEB_SESSION_SECRET=change-this-secret-key-for-hmac-token-signing

WEB_HOST=127.0.0.1
WEB_PORT=8000

DEFAULT_TG_API_ID=123456
DEFAULT_TG_API_HASH=your_api_hash
```

### 3. Khởi chạy Hệ thống

```powershell
python main.py
```

Sau đó mở trình duyệt tại: **`http://127.0.0.1:8000`**

---

## Kiểm Thử (Unit & Integration Tests)

```powershell
python -m pytest -v
python -m ruff check backend tests main.py
```
