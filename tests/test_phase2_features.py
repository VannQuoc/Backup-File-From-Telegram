from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.auth import hash_password_sha256
from backend.config import load_config
from backend.database.db import DatabaseStore
from backend.database.models import (
    AccountCreateRequest,
    AccountMembershipModel,
    BackupFilterConfig,
    BackupJobCreateRequest,
    ChatGroupUpsertRequest,
    ChatRuleModel,
    ChatTopicModel,
    FallbackPolicyConfig,
    FolderChatEntry,
    FolderCreateRequest,
    MediaLibraryCreateRequest,
    ScenarioCreateRequest,
    ScenarioStepInput,
    ScenarioTargetInput,
)
from backend.telegram.auto_sender import AutoSenderEngine, decode_bot_api_file_id
from backend.telegram.backup_engine import (
    BackupEngine,
    apply_filename_rename,
    compute_file_sha256,
    evaluate_message_for_backup,
)
from backend.telegram.rule_engine import (
    is_within_active_hours,
    render_spintax_and_variables,
    resolve_execution_plan,
)


def test_spintax_variables_and_active_hours() -> None:
    # Feature #7: Spintax & Dynamic Variables
    rendered = render_spintax_and_variables(
        "{Xin chào|Xin chào} {chat_title} ({chat_id}) từ {account_name}",
        context={
            "chat_title": "Nhóm VIP",
            "chat_id": -100999,
            "account_name": "Nick #1",
        },
    )
    assert rendered == "Xin chào Nhóm VIP (-100999) từ Nick #1"

    # Also test inside resolve_execution_plan with link stripping
    step = {
        "action_type": "send_text",
        "text_content": "{Khuyến mãi|Khuyến mãi} tại {chat_title} https://spam.com",
        "fallback_policy": FallbackPolicyConfig(on_no_links="strip_links").model_dump(),
    }
    plan = resolve_execution_plan(
        step,
        ChatRuleModel(chat_id=-1001, no_links=True),
        render_context={"chat_title": "Chợ Tốt", "chat_id": -1001},
    )
    assert plan.action_to_execute == "send_text"
    assert plan.text_content == "Khuyến mãi tại Chợ Tốt"

    # Feature #8: Active Hours / Quiet Hours window
    morning = datetime(2026, 5, 1, 9, 15)
    midnight = datetime(2026, 5, 1, 1, 30)
    assert is_within_active_hours("07:30", "22:30", now_dt=morning) is True
    assert is_within_active_hours("07:30", "22:30", now_dt=midnight) is False
    # Overnight window (22:00 -> 06:00)
    assert is_within_active_hours("22:00", "06:00", now_dt=midnight) is True
    assert is_within_active_hours("22:00", "06:00", now_dt=morning) is False


def test_backup_range_filter_rename_and_watermark(tmp_path: Path) -> None:
    # Features #14, #15, #16
    assert apply_filename_rename("data.zip", prefix="[VIP]_", suffix="_2026") == "[VIP]_data_2026.zip"

    sample_file = tmp_path / "sample.bin"
    sample_file.write_bytes(b"HELLO_TELE_SUITE")
    sha1 = compute_file_sha256(sample_file)
    assert len(sha1) == 64

    class DummyMsg:
        def __init__(self, msg_id: int, date_str: str) -> None:
            self.id = msg_id
            self.date = date_str
            self.message = "Tài liệu gốc"
            self.media = type("M", (), {"document": type("D", (), {"id": 55, "size": 1024, "attributes": []})()})()
            self.file = type("F", (), {"name": "report.txt", "size": 1024})()

    job = {
        "id": 1,
        "source_chat_id": -1001,
        "dest_topic_default": 10,
        "dest_topic_archive": 20,
        "caption_mode": "preserve",
        "dedupe_enabled": True,
        "filter_config": BackupFilterConfig(
            sync_documents=True,
            min_msg_id=100,
            max_msg_id=200,
            min_date_iso="2026-01-01",
            max_date_iso="2026-12-31",
            rename_prefix="BK_",
            rename_suffix="_OK",
            caption_watermark="Nguồn @TeleSuite",
            content_hash_dedupe=True,
        ).model_dump(),
    }

    # Out of ID range
    ev_low = evaluate_message_for_backup(DummyMsg(50, "2026-05-01"), job)
    assert ev_low.should_sync is False

    # Out of Date range
    ev_old = evaluate_message_for_backup(DummyMsg(150, "2025-05-01"), job)
    assert ev_old.should_sync is False

    # Valid message with rename & watermark
    ev_ok = evaluate_message_for_backup(DummyMsg(150, "2026-05-01"), job)
    assert ev_ok.should_sync is True
    assert ev_ok.renamed_filename == "BK_report_OK.txt"
    assert "Nguồn @TeleSuite" in ev_ok.caption_to_send
    assert ev_ok.content_hash_dedupe is True


@pytest.mark.asyncio
async def test_phase2_auto_delete_prev_msg_and_sha256_dedupe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "state.sqlite"))
    cfg = load_config()
    store = DatabaseStore(cfg.db_path)

    acc = store.create_account(
        AccountCreateRequest(
            label="Acc Master",
            phone="+84911222333",
            api_id=123,
            api_hash="abc",
            max_messages_per_hour=50,
            max_messages_per_day=200,
        ),
        cfg.sessions_dir,
    )
    store.update_account_status(acc["id"], "connected")

    # Feature #1 & #2: Upsert group, membership, and forum topics
    store.upsert_chat_group(
        ChatGroupUpsertRequest(chat_id=-100500, title="Forum Mua Bán", chat_type="forum", is_forum=True)
    )
    store.upsert_account_membership(
        AccountMembershipModel(
            account_id=acc["id"],
            chat_id=-100500,
            role="admin",
            can_send_messages=True,
            can_send_media=True,
            can_send_stickers=True,
            can_embed_links=True,
        )
    )
    store.upsert_chat_topics(
        -100500,
        [ChatTopicModel(chat_id=-100500, topic_id=88, title="Nhánh Tài Liệu")],
    )

    chats_of_acc = store.list_chat_groups(account_id=acc["id"])
    assert len(chats_of_acc) == 1
    assert chats_of_acc[0]["topics"][0]["topic_id"] == 88
    assert chats_of_acc[0]["member_accounts"][0]["role"] == "admin"

    class FakeClient:
        def __init__(self) -> None:
            self.deleted_Ids: list[int] = []
            self.msg_counter = 1000
            self.uploaded_files: list[str] = []

        async def delete_messages(self, chat_id: int, msg_ids: list[int]) -> None:
            self.deleted_Ids.extend(msg_ids)

        async def send_message(self, **kwargs: Any) -> Any:
            self.msg_counter += 1
            return type("Sent", (), {"id": self.msg_counter})()

        async def download_media(self, message: Any, file: str) -> str:
            p = Path(file) / getattr(message.file, "name", "doc.zip")
            p.write_bytes(b"IDENTICAL_BINARY_CONTENT_FOR_SHA256")
            return str(p)

        async def send_file(self, **kwargs: Any) -> Any:
            self.uploaded_files.append(str(kwargs.get("file")))
            self.msg_counter += 1
            return type("Sent", (), {"id": self.msg_counter})()

    fake_client = FakeClient()

    class FakePool:
        async def get_authorized_client(self, account_id: int) -> Any:
            return fake_client

        async def pick_any_authorized_client(
            self,
            preferred_account_id: int | None = None,
            target_chat_id: int | None = None,
        ) -> tuple[int, Any]:
            return acc["id"], fake_client

    pool = FakePool()

    # Feature #10: Auto-Delete Previous Sent Message in Scenario
    folder = store.create_folder(
        FolderCreateRequest(
            name="Folder Độc Lập #1",
            chats=[FolderChatEntry(chat_id=-100500, topic_id=88)],
        )
    )
    sc = store.create_scenario(
        ScenarioCreateRequest(
            name="Scenario Auto Delete Old Msg",
            delete_previous_sent_message=True,
            steps=[
                ScenarioStepInput(
                    step_order=1,
                    name="Step 1",
                    action_type="send_text",
                    text_content="Tin nhắn cập nhật tại {chat_title}",
                )
            ],
            targets=[ScenarioTargetInput(target_type="folder", target_id=folder["id"])],
        )
    )

    auto_sender = AutoSenderEngine(store, pool, cfg)  # type: ignore[arg-type]
    await auto_sender.run_scenario_now(sc["id"])
    assert fake_client.deleted_Ids == []  # First send has no previous message

    # Second run should delete message #1001 before sending #1002
    await auto_sender.run_scenario_now(sc["id"])
    assert 1001 in fake_client.deleted_Ids

    # Feature #14 & #16: SHA-256 Content-Hash Deduplication even when filename & doc_id change
    bk_job = store.create_backup_job(
        BackupJobCreateRequest(
            label="SHA256 Dedupe Backup",
            reader_account_id=acc["id"],
            source_chat_id=-100500,
            dest_chat_id=-100600,
            filter_config=BackupFilterConfig(
                sync_documents=True,
                content_hash_dedupe=True,
                rename_prefix="SAFE_",
            ),
        )
    )
    backup_engine = BackupEngine(store, pool, cfg)  # type: ignore[arg-type]

    msg1 = type(
        "Msg",
        (),
        {
            "id": 10,
            "date": None,
            "message": "File 1",
            "noforwards": True,
            "media": type("M", (), {"document": type("D", (), {"id": 111, "size": 35, "attributes": []})()})(),
            "file": type("F", (), {"name": "first_name.zip", "size": 35})(),
        },
    )()
    msg2_renamed_same_bytes = type(
        "Msg",
        (),
        {
            "id": 11,
            "date": None,
            "message": "File 2 (cùng nội dung nhưng đổi tên & doc_id)",
            "noforwards": True,
            "media": type("M", (), {"document": type("D", (), {"id": 222, "size": 35, "attributes": []})()})(),
            "file": type("F", (), {"name": "completely_different_name.zip", "size": 35})(),
        },
    )()

    res1 = await backup_engine.process_single_message(bk_job, msg1)
    assert res1 == "synced"
    assert any("SAFE_first_name.zip" in p for p in fake_client.uploaded_files)

    # Second message has different doc_id (222) and different filename, but identical file bytes -> skipped by SHA-256!
    res2 = await backup_engine.process_single_message(bk_job, msg2_renamed_same_bytes)
    assert res2 == "skipped"


def test_phase2_api_endpoints_library_pause_and_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_input_phrase = "admin_demo_2026"
    monkeypatch.setenv("WEB_ADMIN_PASSWORD_SHA256", hash_password_sha256(admin_input_phrase))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "state.sqlite"))

    app = create_app()
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"password": admin_input_phrase})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['token']}"}

        # Feature #17: Global Pause / Kill Switch
        pause_res = client.post("/api/system/global-pause", json={"paused": True}, headers=headers)
        assert pause_res.status_code == 200
        assert pause_res.json()["global_paused"] is True

        resume_res = client.post("/api/system/global-pause", json={"paused": False}, headers=headers)
        assert resume_res.status_code == 200
        assert resume_res.json()["global_paused"] is False

        # Feature #12: Media & Spintax Template Library
        lib_create = client.post(
            "/api/scenarios/library/items",
            json={
                "name": "Mẫu Chào Buổi Sáng",
                "item_type": "text_template",
                "content": "{Chào buổi sáng|Chúc ngày mới tốt lành} {chat_title}!",
            },
            headers=headers,
        )
        assert lib_create.status_code == 200
        lib_id = lib_create.json()["id"]

        lib_list = client.get("/api/scenarios/library/items", headers=headers)
        assert lib_list.status_code == 200
        assert len(lib_list.json()) == 1

        # Feature #18: Config Export & Import + SQLite Snapshot Download
        exported = client.get("/api/system/export-config", headers=headers)
        assert exported.status_code == 200
        bundle = exported.json()
        assert "media_library" in bundle

        imported = client.post("/api/system/import-config", json=bundle, headers=headers)
        assert imported.status_code == 200
        assert imported.json()["status"] == "ok"

        db_dl = client.get("/api/system/download-db", headers=headers)
        assert db_dl.status_code == 200
        assert len(db_dl.content) > 0

        del_lib = client.delete(f"/api/scenarios/library/items/{lib_id}", headers=headers)
        assert del_lib.status_code == 200

        # Test Account Health Check (/api/accounts/{id}/health-check) & Scenario Run (/api/scenarios/{id}/run)
        acc_res = client.post(
            "/api/accounts",
            json={
                "label": "Nick Test Health & Run",
                "phone": "+84988777666",
                "api_id": 12345,
                "api_hash": "hash123",
                "max_messages_per_hour": 60,
                "max_messages_per_day": 500,
                "enabled": True,
            },
            headers=headers,
        )
        assert acc_res.status_code == 200
        acc_id = acc_res.json()["id"]

        hc_res = client.post(f"/api/accounts/{acc_id}/health-check", headers=headers)
        assert hc_res.status_code == 200
        hc_data = hc_res.json()
        assert hc_data["account_id"] == acc_id
        assert hc_data["within_quota"] is True

        chat_res = client.post(
            "/api/chats",
            json={"chat_id": -100777888, "title": "Nhóm Test Run Scenario", "chat_type": "supergroup"},
            headers=headers,
        )
        assert chat_res.status_code == 200

        sc_res = client.post(
            "/api/scenarios",
            json={
                "name": "Kịch bản Sticker CAACAgUAA...",
                "enabled": True,
                "steps": [
                    {
                        "step_order": 1,
                        "name": "Gửi Sticker",
                        "action_type": "send_sticker",
                        "sticker_id_or_path": "CAACAgUAAxkBAAEIHa5q7IhlxMXTn6SIKdDwIqKX7aXOOAACdiIAAoGuIVSJWgxnPD5-_j0E",
                    }
                ],
                "targets": [{"target_type": "chat", "target_id": -100777888, "topic_id": 0, "enabled": True}],
            },
            headers=headers,
        )
        assert sc_res.status_code == 200
        sc_id = sc_res.json()["id"]

        run_res = client.post(f"/api/scenarios/{sc_id}/run", headers=headers)
        assert run_res.status_code == 200

        # Test Edit Scenario (PUT), Clone Scenario (POST /clone), & Pre-Flight Check (GET /preflight-check)
        edit_res = client.put(
            f"/api/scenarios/{sc_id}",
            json={
                "name": "Kịch bản Đã Chỉnh Sửa",
                "sender_account_id": None,
                "delete_if_within_x_messages": 15,
                "skip_if_within_x_messages": 3,
                "steps": [
                    {
                        "step_order": 1,
                        "name": "Bước Đã Sửa",
                        "action_type": "send_text",
                        "text_content": "Xin chào {chat_title} https://example.com",
                    }
                ],
                "targets": [{"target_type": "chat", "target_id": -100777888, "topic_id": 0, "enabled": True}],
            },
            headers=headers,
        )
        assert edit_res.status_code == 200
        edited_sc = edit_res.json()
        assert edited_sc["name"] == "Kịch bản Đã Chỉnh Sửa"
        assert edited_sc["delete_if_within_x_messages"] == 15
        assert edited_sc["skip_if_within_x_messages"] == 3

        clone_res = client.post(f"/api/scenarios/{sc_id}/clone", headers=headers)
        assert clone_res.status_code == 200
        cloned_sc = clone_res.json()
        assert cloned_sc["id"] != sc_id
        assert cloned_sc["delete_if_within_x_messages"] == 15

        pf_res = client.get(f"/api/scenarios/{sc_id}/preflight-check", headers=headers)
        assert pf_res.status_code == 200
        pf_data = pf_res.json()
        assert pf_data["total_destinations"] == 1
        assert pf_data["summary"]["native_count"] == 1

        scan_all_res = client.post("/api/accounts/scan-all-dialogs", headers=headers)
        assert scan_all_res.status_code == 200


def test_decode_modern_bot_api_v4_sticker_file_id() -> None:
    sticker_id = "CAACAgUAAxkBAAEIHa5q7IhlxMXTn6SIKdDwIqKX7aXOOAACdiIAAoGuIVSJWgxnPD5-_j0E"
    decoded = decode_bot_api_file_id(sticker_id)
    assert decoded is not None
    assert getattr(decoded, "id", 0) != 0
    assert getattr(decoded, "access_hash", 0) != 0
    assert len(getattr(decoded, "file_reference", b"")) == 25


@pytest.mark.asyncio
async def test_smart_distance_delete_and_1000_msg_history_analyzer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "state.sqlite"))
    cfg = load_config()
    store = DatabaseStore(cfg.db_path)

    acc = store.create_account(
        AccountCreateRequest(
            label="Acc Scanner",
            phone="+84900111222",
            api_id=123,
            api_hash="abc",
        ),
        cfg.sessions_dir,
    )
    store.update_account_status(acc["id"], "connected")

    # Initially lock all rules on chat -100999
    store.upsert_chat_group(
        ChatGroupUpsertRequest(
            chat_id=-100999,
            title="Nhóm Kiểm Tra 1K Tin",
            rules=ChatRuleModel(
                chat_id=-100999,
                no_links=True,
                no_forwards=True,
                no_stickers=True,
                no_media=True,
                no_bot_mentions=True,
            ),
        )
    )

    class FakeHistoryClient:
        def __init__(self) -> None:
            self.deleted_ids: list[int] = []
            self.msg_counter = 500

        async def delete_messages(self, chat_id: int, msg_ids: list[int]) -> None:
            self.deleted_ids.extend(msg_ids)

        async def send_message(self, **kwargs: Any) -> Any:
            self.msg_counter += 1
            return type("Sent", (), {"id": self.msg_counter})()

        async def iter_participants(self, chat_id: int, filter: Any = None):
            # User 9999 is an Admin
            yield type("AdminUser", (), {"id": 9999})()

        async def iter_messages(self, chat_id: int, limit: int = 1000, **kwargs: Any):
            min_id = kwargs.get("min_id")
            if min_id is not None:
                # Used by _count_messages_since_last_sent
                for mid in range(int(min_id) + 1, self.msg_counter + 1):
                    yield type("M", (), {"id": mid})()
                return

            # 1) Admin message with link (should be skipped!)
            yield type(
                "Msg",
                (),
                {
                    "id": 1,
                    "action": None,
                    "post": False,
                    "sender_id": 9999,
                    "sender": type("U", (), {"id": 9999, "bot": False})(),
                    "message": "Admin link https://admin.only",
                    "fwd_from": None,
                    "sticker": None,
                    "media": None,
                    "photo": None,
                    "video": None,
                    "document": None,
                    "via_bot_id": None,
                },
            )()
            # 2) Normal member #1001 sends a link & mentions @helper_bot
            yield type(
                "Msg",
                (),
                {
                    "id": 2,
                    "action": None,
                    "post": False,
                    "sender_id": 1001,
                    "sender": type("U", (), {"id": 1001, "bot": False})(),
                    "message": "Anh em vào xem https://t.me/group_vip hoặc gọi @my_helper_bot nhé",
                    "fwd_from": None,
                    "sticker": None,
                    "media": None,
                    "photo": None,
                    "video": None,
                    "document": None,
                    "via_bot_id": None,
                },
            )()
            # 3) Normal member #1002 forwards a message and sends a sticker
            yield type(
                "Msg",
                (),
                {
                    "id": 3,
                    "action": None,
                    "post": False,
                    "sender_id": 1002,
                    "sender": type("U", (), {"id": 1002, "bot": False})(),
                    "message": "",
                    "fwd_from": type("Fwd", (), {})(),
                    "sticker": type("Stk", (), {})(),
                    "media": None,
                    "photo": None,
                    "video": None,
                    "document": None,
                    "via_bot_id": None,
                },
            )()

    fake_client = FakeHistoryClient()

    from backend.telegram.client_pool import TelegramClientPool

    pool = TelegramClientPool(store, cfg)
    monkeypatch.setattr(
        pool,
        "pick_any_authorized_client",
        lambda preferred_account_id=None, target_chat_id=None: asyncio.sleep(
            0, result=(acc["id"], fake_client)
        ),
    )

    import asyncio

    # Test 1: Analyze 1,000 recent messages -> Normal users sent links, forwards, stickers, and @bot mentions!
    analysis = await pool.analyze_chat_member_permissions_from_history(
        chat_id=-100999,
        limit=1000,
        auto_apply_unlock=True,
    )
    assert analysis["admin_or_bot_messages_skipped"] == 1
    assert analysis["normal_user_messages"] == 2
    assert analysis["observed_counts"]["links"] == 1
    assert analysis["observed_counts"]["forwards"] == 1
    assert analysis["observed_counts"]["stickers"] == 1
    assert analysis["observed_counts"]["bot_mentions"] == 1

    # Verify rules were automatically unlocked because normal users could send them!
    updated_rule = store.get_chat_rule(-100999)
    assert updated_rule.no_links is False
    assert updated_rule.no_forwards is False
    assert updated_rule.no_stickers is False
    assert updated_rule.no_bot_mentions is False

    # Test 2: Smart Message-Distance Deletion (`delete_if_within_x_messages = 10`)
    sc = store.create_scenario(
        ScenarioCreateRequest(
            name="Test X-Message Distance Delete",
            delete_previous_sent_message=False,
            delete_if_within_x_messages=10,
            steps=[
                ScenarioStepInput(
                    step_order=1,
                    name="Step 1",
                    action_type="send_text",
                    text_content="Tin nhắn tự động",
                )
            ],
            targets=[ScenarioTargetInput(target_type="chat", target_id=-100999)],
        )
    )
    auto_sender = AutoSenderEngine(store, pool, cfg)

    # Run #1: Sends message #501
    await auto_sender.run_scenario_now(sc["id"])
    assert fake_client.deleted_ids == []

    # Simulate only 3 other messages in the group (msg_counter = 504 -> distance = 3 <= 10)
    fake_client.msg_counter = 504
    # Run #2: Since distance (3) <= 10, message #501 MUST be deleted before sending #505!
    await auto_sender.run_scenario_now(sc["id"])
    assert 501 in fake_client.deleted_ids

    # Simulate 25 other messages in the group after #505 (msg_counter = 530 -> distance = 25 > 10)
    fake_client.msg_counter = 530
    # Run #3: Since distance (25) > 10, message #505 MUST NOT be deleted!
    await auto_sender.run_scenario_now(sc["id"])
    assert 505 not in fake_client.deleted_ids


