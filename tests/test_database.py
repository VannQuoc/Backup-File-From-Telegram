from __future__ import annotations

from pathlib import Path

from backend.database.db import DatabaseStore
from backend.database.models import (
    AccountCreateRequest,
    BackupFilterConfig,
    BackupJobCreateRequest,
    ChatGroupUpsertRequest,
    ChatRuleUpdateRequest,
    FallbackPolicyConfig,
    FolderChatEntry,
    FolderCreateRequest,
    ScenarioCreateRequest,
    ScenarioStepInput,
    ScenarioTargetInput,
)


def test_database_full_crud_and_stats(tmp_path: Path) -> None:
    store = DatabaseStore(tmp_path / "state.sqlite")
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # 1. Accounts
    acc = store.create_account(
        AccountCreateRequest(
            label="Nick Chính #1",
            phone="+84901234567",
            api_id=123456,
            api_hash="abcdef123456",
        ),
        sessions_dir,
    )
    assert acc["id"] == 1
    assert acc["status"] == "need_login"
    store.update_account_status(1, "connected", tg_user_id=999, tg_username="main_acc")
    assert store.get_account(1)["status"] == "connected"

    # 2. Chat Groups & Rules + Auto-Learn
    grp = store.upsert_chat_group(
        ChatGroupUpsertRequest(
            chat_id=-100111222333,
            title="Nhóm Mua Bán Toàn Quốc",
            username="muaban_vn",
            is_forum=True,
        )
    )
    assert grp["chat_id"] == -100111222333
    assert grp["rules"]["no_links"] is False

    store.update_chat_rule(
        -100111222333,
        ChatRuleUpdateRequest(
            no_links=True,
            no_stickers=True,
            no_forwards=False,
            no_media=False,
            no_bot_mentions=True,
            slow_mode_seconds=30,
            banned_words=[" lừa đảo ", "cờ bạc"],
            notes="Cấm link và sticker",
        ),
    )
    rule = store.get_chat_rule(-100111222333)
    assert rule.no_links is True
    assert rule.no_stickers is True
    assert rule.no_bot_mentions is True
    assert rule.slow_mode_seconds == 30
    assert "cờ bạc" in rule.banned_words

    learned = store.auto_learn_chat_restriction(
        -100111222333,
        no_forwards=True,
        reason_note="Auto-learned: Nhóm cấm Forward",
    )
    assert learned.no_forwards is True
    assert learned.auto_learned is True

    # 3. Folders
    folder = store.create_folder(
        FolderCreateRequest(
            name="Folder Nhóm Thương Mại",
            description="Các nhóm bán hàng",
            color="#10b981",
            chats=[FolderChatEntry(chat_id=-100111222333, topic_id=10)],
        )
    )
    assert folder["id"] == 1
    assert len(folder["chats"]) == 1
    assert folder["chats"][0]["chat_id"] == -100111222333

    # 4. Backup Jobs & Sync State & Fingerprints
    job = store.create_backup_job(
        BackupJobCreateRequest(
            label="Backup Kênh Tài Liệu VIP",
            reader_account_id=1,
            sender_account_id=1,
            source_chat_id=-100555666,
            dest_chat_id=-100777888,
            dest_topic_default=2085,
            dest_topic_archive=2088,
            filter_config=BackupFilterConfig(
                sync_documents=True,
                allowed_extensions=[".txt", ".zip", ".pdf"],
                sync_photos=True,
            ),
        )
    )
    assert job["id"] == 1
    store.record_sync_state(
        backup_job_id=1,
        source_chat_id=-100555666,
        source_msg_id=42,
        status="synced",
        content_type="document",
        extension=".txt",
        document_id=888,
        filename="combo.txt",
        normalized_filename="combo.txt",
        size=1024,
        dest_chat_id=-100777888,
        dest_topic_id=2085,
        dest_msg_id=101,
        fingerprint="doc:888:1024:combo.txt",
    )
    store.add_fingerprint(
        fingerprint="doc:888:1024:combo.txt",
        backup_job_id=1,
        source_chat_id=-100555666,
        first_source_msg_id=42,
        filename="combo.txt",
        dest_chat_id=-100777888,
        dest_topic_id=2085,
        dest_msg_id=101,
    )
    assert store.has_fingerprint("doc:888:1024:combo.txt") is True

    # 5. Scenarios
    scenario = store.create_scenario(
        ScenarioCreateRequest(
            name="Kịch bản Chào Buổi Sáng",
            sender_account_id=1,
            interval_seconds=900,
            steps=[
                ScenarioStepInput(
                    step_order=1,
                    name="Forward bài ghim",
                    action_type="forward_message",
                    forward_from_chat_id=-100999,
                    forward_from_msg_id=5,
                    fallback_policy=FallbackPolicyConfig(
                        on_no_forwards="copy_content",
                        on_no_links="strip_links",
                        fallback_text="Chào buổi sáng cả nhà!",
                    ),
                )
            ],
            targets=[ScenarioTargetInput(target_type="folder", target_id=1)],
        )
    )
    assert scenario["id"] == 1
    assert len(scenario["steps"]) == 1
    assert len(scenario["targets"]) == 1

    # 6. Dashboard stats
    stats = store.get_dashboard_stats()
    assert stats["accounts"]["total"] == 1
    assert stats["accounts"]["connected"] == 1
    assert stats["groups"]["with_rules"] == 1
    assert stats["backups"]["synced_items"] == 1
    assert stats["scenarios"]["total"] == 1

    store.checkpoint()
    store.close()

