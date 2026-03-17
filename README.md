# Telegram Channel Backup ULP

Tool nay gom 3 che do:

- `python -m tele_backup login`: dang nhap user session Telethon
- `python -m tele_backup sync`: chay backup one-shot cho tat ca source enabled
- `python main.py`: chay daemon 24/7, nghe tin nhan moi va nhan lenh quan tri qua bot Telegram neu co config

## Thay doi so voi ban dau

- Khong con mac dinh dung o `200` message. `SYNC_LIMIT` de trong se backup het backlog.
- Ho tro nhieu source cung luc thong qua bang `sources` trong SQLite.
- Ho tro daemon 24/7: startup catch-up, sau do nghe message moi va dong bo ngay.
- Ho tro manager bot de login session, them/bot source, doi destination, bat/tat source, trigger sync.
- Neu source bat `Protected Content`, Telegram khong cho resend media reference. Tool nay ho tro fallback download/re-upload rieng cho tung source neu ban bat `ALLOW_PROTECTED_FALLBACK` hoac `/setprotected`.

## Yeu cau

- Python 3.12+
- `api_id` va `api_hash` tu `https://my.telegram.org`
- Neu dung manager bot thi can bot token va `ADMIN_USER_IDS`

## Cai dat

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

## Cau hinh `.env`

```dotenv
TG_API_ID=123456
TG_API_HASH=your_hash
TG_PHONE=+84xxxxxxxxx
MANAGER_BOT_TOKEN=
ADMIN_USER_IDS=123456789
DB_PATH=./data/state.sqlite
SESSION_PATH=./data/user.session
MANAGER_BOT_SESSION_PATH=./data/manager_bot.session
LOG_PATH=./data/logs/sync.log
TEMP_DIR=./data/temp
SEND_DELAY_MIN_MS=800
SEND_DELAY_MAX_MS=1500
SYNC_LIMIT=
LIVE_RECONCILE_SECONDS=120

# Optional legacy bootstrap source
SOURCE_CHAT_ID=3488087171
DEST_CHAT_ID=-1001878033586
DEST_TOPIC_DEFAULT=2085
DEST_TOPIC_ARCHIVE=2088
SOURCE_LABEL=ulp
ALLOW_PROTECTED_FALLBACK=false
```

Giai thich nhanh:

- `SYNC_LIMIT=` de trong: one-shot sync se backup het backlog
- `ADMIN_USER_IDS`: danh sach Telegram user id duoc phep quan tri bot, cach nhau boi dau phay
- `SOURCE_*`: chi dung de bootstrap source dau tien. Sau do co the quan tri them/bot bang bot command
- `ALLOW_PROTECTED_FALLBACK=true`: cho phep source protected dung download/re-upload fallback

## Dang nhap user session

```powershell
python -m tele_backup login
```

Hoac neu da config manager bot va `ADMIN_USER_IDS`, co the login tu xa:

```text
/login
/code 12345
/password your_2fa_password
```

## One-shot sync

```powershell
python -m tele_backup sync
python -m tele_backup sync --source-chat-id 3488087171
python -m tele_backup sync --limit 100
```

## Chay daemon 24/7

```powershell
python main.py
```

Daemon se:

- bootstrap source legacy tu `.env` neu co
- startup catch-up toan bo backlog cua cac source enabled
- lang nghe message moi va xu ly ngay
- chay reconcile dinh ky de bat hut message neu bi reconnect
- khoi dong manager bot neu `MANAGER_BOT_TOKEN` duoc set

## Manager bot commands

Luon co:

- `/whoami`
- `/help`

Can nam trong `ADMIN_USER_IDS`:

- `/status`
- `/sources`
- `/login [phone]`
- `/code <otp_code>`
- `/password <twofa_password>`
- `/logout`
- `/addsource <source_chat_id> <dest_chat_id> <topic_default> <topic_archive> [protected_fallback 0|1] [label...]`
- `/setdest <source_chat_id> <dest_chat_id> <topic_default> <topic_archive>`
- `/setlabel <source_chat_id> <label...>`
- `/setprotected <source_chat_id> <0|1>`
- `/enable <source_chat_id>`
- `/disable <source_chat_id>`
- `/remove <source_chat_id>`
- `/syncall [limit]`
- `/sync <source_chat_id> [limit]`

## Cach routing file

- `.txt` -> `dest_topic_default`, bo caption, dedupe theo `document_id:size:normalized_filename`
- `.zip`, `.rar` -> `dest_topic_archive`, giu nguyen caption
- document khac -> `dest_topic_default`
- text-only, photo, video, sticker, voice, service message -> bo qua

## Gioi han ky thuat

- Source protected/no-forwards khong the server-side copy. Fallback download/re-upload la cach kha thi duy nhat.
- Dedupe `.txt` van la best-effort theo metadata, khong hash noi dung file.
- Tinh doc lap cua backup duoc dam bao boi viec tao message moi o destination, khong dung `forward_messages`.

## Bao mat

- Khong commit `.env`, `.session`, database, log, temp file.
- Neu bot token da tung bi lo, hay regenerate token trong BotFather.
