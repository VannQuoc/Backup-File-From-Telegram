from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import load_config


def test_api_auth_and_end_to_end_management(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom_pass = "my_super_secret_pass_2026"
    custom_hash = hashlib.sha256(custom_pass.encode("utf-8")).hexdigest()
    monkeypatch.setenv("WEB_ADMIN_PASSWORD_SHA256", custom_hash)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "state.sqlite"))

    cfg = load_config()
    app = create_app(cfg, start_background_workers=False)

    with TestClient(app) as client:
        # 0. Root serves compiled React SPA
        r_root = client.get("/")
        assert r_root.status_code == 200
        assert "TELE-SUITE" in r_root.text

        # 1. Protected route without token -> 401
        r_unauth = client.get("/api/system/dashboard")
        assert r_unauth.status_code == 401

        # 2. Wrong password -> 401
        r_bad = client.post("/api/auth/login", json={"password": "wrong"})
        assert r_bad.status_code == 401

        # 3. Correct password -> 200 + token
        r_login = client.post("/api/auth/login", json={"password": custom_pass})
        assert r_login.status_code == 200
        token = r_login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 4. Create Account
        r_acc = client.post(
            "/api/accounts",
            headers=headers,
            json={
                "label": "Nick Seeding #1",
                "phone": "+84912345678",
                "api_id": 12345,
                "api_hash": "hash12345",
            },
        )
        assert r_acc.status_code == 200
        acc_id = r_acc.json()["id"]

        # 5. Upsert Chat Group & Update Rules
        r_chat = client.post(
            "/api/chats",
            headers=headers,
            json={
                "chat_id": -100987654,
                "title": "Cộng Đồng Công Nghệ",
                "chat_type": "supergroup",
            },
        )
        assert r_chat.status_code == 200

        r_rule = client.put(
            "/api/chats/-100987654/rules",
            headers=headers,
            json={
                "no_links": True,
                "no_stickers": True,
                "no_forwards": True,
                "no_media": False,
                "no_bot_mentions": True,
                "slow_mode_seconds": 15,
                "banned_words": ["spam"],
                "notes": "Nhóm kiểm duyệt chặt",
            },
        )
        assert r_rule.status_code == 200
        assert r_rule.json()["rules"]["no_forwards"] is True

        # 6. Create Folder containing the chat
        r_folder = client.post(
            "/api/folders",
            headers=headers,
            json={
                "name": "Folder Cộng Đồng IT",
                "color": "#059669",
                "chats": [{"chat_id": -100987654, "topic_id": 0}],
            },
        )
        assert r_folder.status_code == 200
        folder_id = r_folder.json()["id"]

        # 7. Create Backup Job
        r_backup = client.post(
            "/api/backups",
            headers=headers,
            json={
                "label": "Backup Từ Kênh Nguồn",
                "reader_account_id": acc_id,
                "source_chat_id": -100111,
                "dest_chat_id": -100222,
                "dest_topic_default": 10,
                "dest_topic_archive": 20,
            },
        )
        assert r_backup.status_code == 200

        # 8. Create Auto-Send Scenario & Simulate Fallback
        r_scen = client.post(
            "/api/scenarios",
            headers=headers,
            json={
                "name": "Kịch bản Quảng Bá Sản Phẩm",
                "sender_account_id": acc_id,
                "interval_seconds": 600,
                "steps": [
                    {
                        "step_order": 1,
                        "name": "Forward Bài Viết Kèm Link",
                        "action_type": "forward_message",
                        "forward_from_chat_id": -100555,
                        "forward_from_msg_id": 12,
                        "text_content": "Xem chi tiết tại https://example.com với @helper_bot",
                        "fallback_policy": {
                            "on_no_forwards": "copy_content",
                            "on_no_links": "mask_links",
                            "on_no_bot_mentions": "strip_bot_mentions",
                            "fallback_text": "Bản tin dự phòng thuần văn bản",
                        },
                    }
                ],
                "targets": [{"target_type": "folder", "target_id": folder_id}],
            },
        )
        assert r_scen.status_code == 200

        r_sim = client.post(
            "/api/scenarios/simulate-fallback",
            headers=headers,
            json={
                "chat_id": -100987654,
                "step": r_scen.json()["steps"][0],
            },
        )
        assert r_sim.status_code == 200
        sim_data = r_sim.json()["resolved_plan"]
        assert sim_data["action_to_execute"] == "copy_source_message"
        assert sim_data["fallback_applied"] is True
        assert "example[.]com" in sim_data["text_content"]
        assert "@helper_bot" not in sim_data["text_content"]
