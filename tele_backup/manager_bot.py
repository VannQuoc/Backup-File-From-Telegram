from __future__ import annotations

import logging

from telethon import events
from telethon.tl.custom import Button
from telethon.errors import SessionPasswordNeededError

from .config import Settings
from .telegram_client import clear_persisted_session, connect_client, persist_session, start_bot_client

logger = logging.getLogger(__name__)


class ManagerBotController:
    def __init__(self, *, settings: Settings, bot_client, user_client, service, daemon) -> None:
        self.settings = settings
        self.bot_client = bot_client
        self.user_client = user_client
        self.service = service
        self.daemon = daemon
        self._pending_phone: str | None = None
        self._pending_phone_code_hash: str | None = None
        self._waiting_for_password = False
        
        # Thêm biến lưu trạng thái chat của mỗi admin
        self._admin_states: dict[int, str] = {}

    async def start(self) -> None:
        await start_bot_client(self.bot_client, self.settings.manager_bot_token)
        self.bot_client.add_event_handler(self._on_message, events.NewMessage(incoming=True))
        self.bot_client.add_event_handler(self._on_callback, events.CallbackQuery())
        logger.info('Manager bot da khoi dong (Che do Menu).')

    async def stop(self) -> None:
        await self.bot_client.disconnect()

    async def run_until_disconnected(self) -> None:
        await self.bot_client.run_until_disconnected()

    def _is_admin(self, sender_id: int | None) -> bool:
        return sender_id is not None and sender_id in self.settings.admin_user_ids

    def _get_main_menu_buttons(self):
        return [
            [Button.inline('📊 Trạng thái', b'cmd_status'), Button.inline('📋 Danh sách', b'cmd_sources')],
            [Button.inline('⚡ Đồng bộ Tất cả', b'cmd_syncall'), Button.inline('🔄 Đồng bộ Nguồn', b'prompt_sync')],
            [Button.inline('➕ Thêm Nguồn', b'prompt_addsource'), Button.inline('❌ Xóa Nguồn', b'prompt_remove')],
            [Button.inline('🔑 Đăng nhập User', b'prompt_login'), Button.inline('🚪 Đăng xuất User', b'cmd_logout')],
            [Button.inline('⚙️ Bật/Tắt Nguồn', b'prompt_toggle'), Button.inline('💾 Backup DB', b'cmd_backup_db')],
        ]

    def _get_toggle_sources_buttons(self):
        sources = self.service.list_sources(enabled_only=None)
        buttons = []
        for source in sources:
            label = source.label or 'Unknown'
            status_emoji = '✅' if source.enabled else '❌'
            text = f'{status_emoji} {label} ({source.source_chat_id})'
            buttons.append([Button.inline(text, f'toggle_{source.source_chat_id}'.encode('utf-8'))])
        buttons.append([Button.inline('🔙 Quay lại', b'cmd_cancel')])
        return buttons

    def _get_cancel_button(self):
        return [Button.inline('❌ Hủy bỏ', b'cmd_cancel')]

    async def _send_main_menu(self, event):
        text = '👋 **Menu Quản Trị Backup ULP**\n\nVui lòng chọn chức năng bên dưới. Nếu đang kẹt ở thao tác nào, chọn "Hủy bỏ" hoặc gõ /cancel.'
        await event.respond(text, buttons=self._get_main_menu_buttons())

    def _clear_state(self, user_id: int):
        self._admin_states.pop(user_id, None)

    async def _on_message(self, event) -> None:
        if not event.is_private:
            return

        sender_id = event.sender_id
        text = (event.raw_text or '').strip()
        
        if text.startswith('/whoami'):
            await event.respond(f'Your Telegram user id: {sender_id}')
            return

        if not self._is_admin(sender_id):
            if text.startswith('/'):
                await event.respond(f'Bạn không có quyền truy cập. User id: {sender_id}')
            return

        if text.lower() in {'/start', '/help', '/menu', '/cancel', 'hủy bỏ', 'huy bo'}:
            self._clear_state(sender_id)
            await self._send_main_menu(event)
            return

        state = self._admin_states.get(sender_id)
        if not state:
            if text.startswith('/'):
                await event.respond('❌ Lệnh không hợp lệ. Vui lòng gõ /menu để mở bảng điều khiển.')
            return

        try:
            if state == 'waiting_for_login_phone':
                await self._handle_input_login_phone(event, text)
            elif state == 'waiting_for_login_code':
                await self._handle_input_login_code(event, text)
            elif state == 'waiting_for_login_password':
                await self._handle_input_login_password(event, text)
            elif state == 'waiting_for_sync_source':
                await self._handle_input_sync_source(event, text)
            elif state == 'waiting_for_remove_source':
                await self._handle_input_remove_source(event, text)
            elif state == 'waiting_for_addsource_payload':
                await self._handle_input_addsource(event, text)
        except Exception as exc:
            logger.exception('Lỗi khi xử lý thao tác (state %s)', state)
            await event.respond(f'❌ Lỗi: {exc}', buttons=self._get_cancel_button())

    async def _on_callback(self, event: events.CallbackQuery.Event) -> None:
        sender_id = event.sender_id
        if not self._is_admin(sender_id):
            await event.answer('Không có quyền.', alert=True)
            return

        data = event.data.decode('utf-8')
        
        if data == 'cmd_cancel':
            self._clear_state(sender_id)
            await event.edit('🛑 Đã quay lại menu chính.', buttons=self._get_main_menu_buttons())
            return

        if data.startswith('toggle_'):
            source_chat_id = int(data[len('toggle_'):])
            source = self.service.get_source(source_chat_id)
            if source:
                new_status = not source.enabled
                self.service.set_source_enabled(source_chat_id, new_status)
                buttons = self._get_toggle_sources_buttons()
                await event.edit('⚙️ **BẬT/TẮT NGUỒN**\n\nChọn thay đổi trạng thái nguồn:', buttons=buttons)
            return

        # Huỷ state cũ nếu bấm nút khác trên menu
        self._clear_state(sender_id)

        try:
            if data == 'cmd_status':
                text = await self.daemon.status_text()
                await event.edit(f'📊 **Trạng thái:**\n```\n{text}\n```', buttons=self._get_main_menu_buttons())
            
            elif data == 'cmd_sources':
                text = self._sources_text()
                await event.edit(f'📋 **Danh sách Nguồn:**\n```\n{text}\n```', buttons=self._get_main_menu_buttons())

            elif data == 'cmd_syncall':
                if self.daemon.is_busy():
                    await event.answer('⏳ Hiện đang có tiến trình sync đang chạy, vui lòng thử lại sau.', alert=True)
                else:
                    await self.daemon.schedule_sync(limit=None, wait=False)
                    await event.answer('✅ Đã xếp hàng đồng bộ tất cả Nguồn.', alert=True)

            elif data == 'prompt_sync':
                self._admin_states[sender_id] = 'waiting_for_sync_source'
                await event.edit('🔄 **ĐỒNG BỘ NGUỒN**\n\nVui lòng nhập `source_chat_id` cần đồng bộ (hoặc nhập kèm giới hạn tin nhắn VD: `12345 100`):', buttons=self._get_cancel_button())

            elif data == 'prompt_remove':
                self._admin_states[sender_id] = 'waiting_for_remove_source'
                await event.edit('❌ **XÓA NGUỒN**\n\nVui lòng nhập `source_chat_id` muốn xóa:', buttons=self._get_cancel_button())

            elif data == 'prompt_toggle':
                self._clear_state(sender_id)
                buttons = self._get_toggle_sources_buttons()
                await event.edit('⚙️ **BẬT/TẮT NGUỒN**\n\nChọn thay đổi trạng thái nguồn:', buttons=buttons)

            elif data == 'cmd_backup_db':
                db_path = self.settings.db_path
                if db_path.exists():
                    self.service.store.checkpoint()
                    await event.respond('💾 Đang gửi file cơ sở dữ liệu backup...', file=str(db_path))
                    await event.answer('✅ Đã gửi file DB', alert=False)
                else:
                    await event.answer('❌ Không tìm thấy file DB!', alert=True)

            elif data == 'prompt_addsource':
                self._admin_states[sender_id] = 'waiting_for_addsource_payload'
                msg = (
                    '➕ **THÊM NGUỒN (ĐƠN GIẢN)**\n\n'
                    'Chỉ cần gửi tôi `source_chat_id` (Ví dụ: `-100123456` hoặc `@ChannelName`). '
                    'Đích đến và Topic sẽ tự động nạp từ file cấu hình của bạn.'
                )
                await event.edit(msg, buttons=self._get_cancel_button())

            elif data == 'prompt_login':
                self._admin_states[sender_id] = 'waiting_for_login_phone'
                await event.edit('🔑 **ĐĂNG NHẬP USER**\n\nVui lòng nhập Số điện thoại tài khoản (bắt đầu bằng mã vùng, Vd: +84...), hoặc gõ chữ `mac_dinh` để dùng thông tin từ file config.', buttons=self._get_cancel_button())
                
            elif data == 'cmd_logout':
                await self.user_client.log_out()
                clear_persisted_session(self.user_client)
                await self.user_client.disconnect()
                await connect_client(self.user_client)
                self._clear_login_state()
                await event.edit('🚪 Đã đăng xuất User Session bảo mật.', buttons=self._get_main_menu_buttons())

        except Exception as exc:
            logger.exception('Lỗi callback: %s', data)
            await event.answer(f'Lỗi: {exc}', alert=True)

    def _sources_text(self) -> str:
        sources = self.service.list_sources(enabled_only=None)
        if not sources:
            return 'Chưa có source nào được cài đặt trong cơ sở dữ liệu.'

        lines = []
        for source in sources:
            label = f' ({source.label})' if source.label else ''
            lines.append(
                f'- {source.source_chat_id}{label} | enabled={source.enabled} | '
                f'dest={source.dest_chat_id} | topics={source.dest_topic_default}/{source.dest_topic_archive} | '
                f'protected_fallback={source.allow_protected_fallback}'
            )
        return '\n'.join(lines)

    # --- HANDLERS DỮ LIỆU ĐẦU VÀO TỪ TRẠNG THÁI ---

    async def _handle_input_login_phone(self, event, text: str):
        phone = self.settings.phone if text.lower() in ('mac_dinh', 'mac dinh', 'macdinh') else text
        await event.respond(f'⏳ Đang yêu cầu gửi mã OTP tới tài khoản `{phone}`...')
        await connect_client(self.user_client)
        result = await self.user_client.send_code_request(phone)
        persist_session(self.user_client)
        
        self._pending_phone = phone
        self._pending_phone_code_hash = result.phone_code_hash
        self._waiting_for_password = False
        
        self._admin_states[event.sender_id] = 'waiting_for_login_code'
        await event.respond('📩 **Đã gửi mã OTP đến phiên Telegram của User.**\n\nHãy nhập mã OTP vừa nhận để tiếp tục (Có thể chèn thêm chữ trước số để tránh Telegram tự định dạng, Vd: `MA 12345`):', buttons=self._get_cancel_button())

    async def _handle_input_login_code(self, event, text: str):
        if not self._pending_phone or not self._pending_phone_code_hash:
            self._clear_state(event.sender_id)
            raise RuntimeError('Lỗi phiên đăng nhập (Hết hạn hoặc mất tín hiệu). Hãy thử đăng nhập lại.')

        code = ''.join(filter(str.isdigit, text))
        if not code:
            raise RuntimeError('Vui lòng cung cấp mã OTP hợp lệ (Gồm các chữ số).')

        try:
            await event.respond('⏳ Đang giao tiếp với máy chủ để cấp quyền...')
            await self.user_client.sign_in(
                phone=self._pending_phone,
                code=code,
                phone_code_hash=self._pending_phone_code_hash,
            )
            persist_session(self.user_client)
        except SessionPasswordNeededError:
            self._waiting_for_password = True
            self._admin_states[event.sender_id] = 'waiting_for_login_password'
            await event.respond('🔒 Tài khoản User này có bảo mật 2 Lớp (2FA).\n\nVui lòng nhập Mật khẩu 2FA:', buttons=self._get_cancel_button())
            return

        self._clear_login_state()
        self._clear_state(event.sender_id)
        await self.daemon.on_user_authorized()
        await event.respond('✅ Đăng nhập User Session thành công!', buttons=self._get_main_menu_buttons())

    async def _handle_input_login_password(self, event, text: str):
        if not self._waiting_for_password:
            self._clear_state(event.sender_id)
            raise RuntimeError('Lỗi cảnh báo: Không có yêu cầu mật khẩu nào đang tồn tại.')

        await event.respond('⏳ Đang xác nhận Mật khẩu 2FA...')
        await self.user_client.sign_in(password=text)
        persist_session(self.user_client)
        
        self._clear_login_state()
        self._clear_state(event.sender_id)
        await self.daemon.on_user_authorized()
        await event.respond('✅ Đăng nhập Mật khẩu 2FA thành công!', buttons=self._get_main_menu_buttons())

    async def _handle_input_sync_source(self, event, text: str):
        parts = text.split()
        source_chat_id = int(parts[0])
        limit = int(parts[1]) if len(parts) > 1 else None
        
        if self.daemon.is_busy():
            await event.respond('⏳ Bot hiện đang bận xử lý một tác vụ đồng bộ khác, xin thử lại sau.', buttons=self._get_cancel_button())
            return
            
        await self.daemon.schedule_sync(source_chat_id=source_chat_id, limit=limit, wait=False)
        self._clear_state(event.sender_id)
        await event.respond(f'✅ Đã phát lệnh xếp hàng đồng bộ Nguồn `{source_chat_id}`.', buttons=self._get_main_menu_buttons())

    async def _handle_input_remove_source(self, event, text: str):
        source_chat_id = int(text.strip())
        self.service.remove_source(source_chat_id)
        self._clear_state(event.sender_id)
        await event.respond(f'🗑 Đã xóa toàn bộ dữ liệu cài đặt của nguồn `{source_chat_id}`.', buttons=self._get_main_menu_buttons())

    async def _handle_input_addsource(self, event, text: str):
        # 1. Parsing single target properly:
        try:
            source_ref = int(text.strip())
        except ValueError:
            source_ref = text.strip()

        # 2. Check defaults
        legacy = self.settings.legacy_source
        if not legacy:
            raise RuntimeError('Vui lòng khai báo DEST_CHAT_ID, DEST_TOPIC_DEFAULT, DEST_TOPIC_ARCHIVE trong file .env trước để sử dụng tính năng Add Nguồn Đơn Giản.')

        dest_ref = legacy.dest_chat_id
        topic_default = legacy.dest_topic_default
        topic_archive = legacy.dest_topic_archive

        await event.respond('⏳ Đang tra cứu thông tin Channel từ Telegram, vui lòng đợi...')
        
        # Lấy entity và title từ Client
        try:
            entity = await self.user_client.get_entity(source_ref)
            label = getattr(entity, 'title', None)
        except Exception as e:
            raise RuntimeError(f'Lỗi kết nối tới Group/Channel: {e}')

        source = await self.service.add_or_update_source(
            source_ref,
            dest_ref,
            topic_default,
            topic_archive,
            label=label or "KhongTheLayTen",
            enabled=True,
            allow_protected_fallback=False, # Tắt mặc định chặn download
        )
        await self.daemon.schedule_sync(source_chat_id=source.source_chat_id, wait=False)
        self._clear_state(event.sender_id)
        
        success_msg = (
            f'✅ **Thêm Nguồn Thành Công & Tự Động Định Tuyến Sync**\n\n'
            f'- **Nguồn phụ trách**: `{source.source_chat_id}` (_{label}_)\n'
            f'- Điểm đến nhóm: `{dest_ref}`\n'
            f'- Chủ đề chính/Archive: `{topic_default}`/`{topic_archive}`\n\n'
            '🔄 Hệ thống đã đẩy nguồn này vào hàng đợi quét message.'
        )
        await event.respond(success_msg, buttons=self._get_main_menu_buttons())

    def _clear_login_state(self) -> None:
        self._pending_phone = None
        self._pending_phone_code_hash = None
        self._waiting_for_password = False

    def _parse_optional_bool(self, value: str) -> bool | None:
        lowered = value.strip().lower()
        if lowered in {'1', 'true', 'yes', 'y', 'on'}:
            return True
        if lowered in {'0', 'false', 'no', 'n', 'off'}:
            return False
        return None
