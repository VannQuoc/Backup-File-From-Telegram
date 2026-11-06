from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from backend.config import load_config
from backend.database.db import DatabaseStore
from backend.database.models import (
    AccountCreateRequest,
    BackupFilterConfig,
    BackupJobCreateRequest,
    ChatGroupUpsertRequest,
    FallbackPolicyConfig,
    FolderChatEntry,
    FolderCreateRequest,
    ScenarioCreateRequest,
    ScenarioStepInput,
    ScenarioTargetInput,
)
from backend.telegram.auto_sender import AutoSenderEngine
from backend.telegram.backup_engine import BackupEngine, evaluate_message_for_backup


@dataclass
class FakeFileAttr:
    name: str | None = None
    size: int | None = None


@dataclass
class FakeDoc:
    id: int
    size: int
    attributes: list[Any]


@dataclass
class FakeMedia:
    document: FakeDoc | None = None


@dataclass
class FakeMessage:
    id: int
    message: str = ""
    media: Any = None
    file: FakeFileAttr | None = None
    noforwards: bool = False
    photo: Any = None


def test_evaluate_message_for_backup_comprehensive() -> None:
    job = {
        "id": 1,
        "source_chat_id": -100111,
        "dest_chat_id": -100222,
        "dest_topic_default": 100,
        "dest_topic_archive": 200,
        "caption_mode": "strip_for_txt",
        "dedupe_enabled": True,
        "filter_config": BackupFilterConfig(
            sync_documents=True,
            allowed_extensions=[".txt", ".zip", ".rar"],
            archive_extensions=[".zip", ".rar"],
            sync_photos=False,
            sync_text=True,
            exclude_keywords=["spam_ads"],
        ).model_dump(),
    }

    # 1. .txt file -> default topic 100, caption stripped, fingerprint generated
    msg_txt = FakeMessage(
        id=10,
        message="Caption cần bỏ",
        media=FakeMedia(document=FakeDoc(id=555, size=2048, attributes=[])),
        file=FakeFileAttr(name="ULP_Data.TXT", size=2048),
    )
    eval_txt = evaluate_message_for_backup(msg_txt, job)
    assert eval_txt.should_sync is True
    assert eval_txt.target_topic_id == 100
    assert eval_txt.caption_to_send == ""
    assert eval_txt.fingerprint == "doc:555:2048:ulp_data.txt"

    # 2. .zip archive -> archive topic 200, caption preserved
    msg_zip = FakeMessage(
        id=11,
        message="Pass giải nén: 123",
        media=FakeMedia(document=FakeDoc(id=556, size=9999, attributes=[])),
        file=FakeFileAttr(name="pack.zip", size=9999),
    )
    eval_zip = evaluate_message_for_backup(msg_zip, job)
    assert eval_zip.should_sync is True
    assert eval_zip.target_topic_id == 200
    assert eval_zip.caption_to_send == "Pass giải nén: 123"

    # 3. Excluded keyword -> skipped
    msg_spam = FakeMessage(id=12, message="Tin nhắn chứa spam_ads bị chặn")
    eval_spam = evaluate_message_for_backup(msg_spam, job)
    assert eval_spam.should_sync is False


@pytest.mark.asyncio
async def test_backup_protected_fallback_and_autosend_runtime_learning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "state.sqlite"))
    cfg = load_config()
    store = DatabaseStore(cfg.db_path)

    acc = store.create_account(
        AccountCreateRequest(label="Acc Test", phone="+84999888777", api_id=111, api_hash="hash"),
        cfg.sessions_dir,
    )
    store.update_account_status(acc["id"], "connected")

    class FakeTelethonClient:
        def __init__(self) -> None:
            self.sent_files: list[dict[str, Any]] = []
            self.sent_messages: list[dict[str, Any]] = []
            self.fail_sticker_once = True

        async def download_media(self, message: Any, file: str) -> str:
            out = Path(file) / "downloaded.zip"
            out.write_bytes(b"PK_FAKE_ARCHIVE")
            return str(out)

        async def send_file(self, entity: int, file: Any, caption: str | None = None, reply_to: int | None = None) -> Any:
            if self.fail_sticker_once and str(file) == "STICKER_ID_1":
                self.fail_sticker_once = False
                raise RuntimeError("CHAT_SEND_STICKERS_FORBIDDEN")
            self.sent_files.append({"entity": entity, "file": str(file), "caption": caption, "reply_to": reply_to})
            return FakeMessage(id=777)

        async def send_message(self, entity: int, message: str, reply_to: int | None = None, link_preview: bool = True) -> Any:
            self.sent_messages.append({"entity": entity, "message": message, "reply_to": reply_to, "link_preview": link_preview})
            return FakeMessage(id=888)

    fake_client = FakeTelethonClient()

    class FakePool:
        async def get_authorized_client(self, account_id: int) -> Any:
            return fake_client

        async def pick_any_authorized_client(self, preferred_account_id: int | None = None) -> tuple[int, Any]:
            return acc["id"], fake_client

    pool = FakePool()

    # A. Test BackupEngine Protected Content download/re-upload fallback
    job = store.create_backup_job(
        BackupJobCreateRequest(
            label="Protected Source Backup",
            reader_account_id=acc["id"],
            source_chat_id=-10010,
            dest_chat_id=-10020,
            dest_topic_default=5,
            dest_topic_archive=6,
            allow_protected_fallback=True,
        )
    )
    backup_engine = BackupEngine(store, pool, cfg)  # type: ignore[arg-type]
    protected_msg = FakeMessage(
        id=50,
        message="Protected Archive",
        media=FakeMedia(document=FakeDoc(id=900, size=512, attributes=[])),
        file=FakeFileAttr(name="secret.zip", size=512),
        noforwards=True,
    )
    outcome = await backup_engine.process_single_message(job, protected_msg)
    assert outcome == "synced"
    sync_rec = store.get_sync_state(job["id"], 50)
    assert sync_rec is not None
    assert bool(sync_rec["used_protected_fallback"]) is True

    # B. Test AutoSenderEngine runtime error learning (Sticker forbidden -> auto-learn -> retry with fallback_text)
    store.upsert_chat_group(ChatGroupUpsertRequest(chat_id=-10030, title="Group Cấm Ngầm Sticker"))
    folder = store.create_folder(
        FolderCreateRequest(
            name="Folder Auto",
            chats=[FolderChatEntry(chat_id=-10030, topic_id=0)],
        )
    )
    scenario = store.create_scenario(
        ScenarioCreateRequest(
            name="Gửi Sticker Có Fallback",
            sender_account_id=acc["id"],
            steps=[
                ScenarioStepInput(
                    step_order=1,
                    name="Bước Sticker",
                    action_type="send_sticker",
                    sticker_id_or_path="STICKER_ID_1",
                    fallback_policy=FallbackPolicyConfig(
                        on_no_stickers="use_fallback_text",
                        fallback_text="Xin chào (tin nhắn thay thế khi cấm sticker)!",
                    ),
                )
            ],
            targets=[ScenarioTargetInput(target_type="folder", target_id=folder["id"])],
        )
    )

    auto_sender = AutoSenderEngine(store, pool, cfg)  # type: ignore[arg-type]
    logs = await auto_sender.run_scenario_now(scenario["id"])
    assert len(logs) == 1
    assert logs[0]["status"] == "success"
    assert logs[0]["fallback_applied"] is True
    assert logs[0]["action_executed"] == "send_text"
    # Verify group rule was automatically learned into SQLite
    learned_rule = store.get_chat_rule(-10030)
    assert learned_rule.no_stickers is True
    assert learned_rule.auto_learned is True
    store.close()

