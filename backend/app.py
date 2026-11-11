from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.auth import verify_session_token
from backend.config import AppConfig, load_config
from backend.database.db import DatabaseStore
from backend.routers import accounts, backups, chats_folders, scenarios, system
from backend.telegram.auto_sender import AutoSenderEngine
from backend.telegram.backup_engine import BackupEngine
from backend.telegram.client_pool import TelegramClientPool


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


def create_app(
    config: AppConfig | None = None,
    *,
    start_background_workers: bool = True,
) -> FastAPI:
    cfg = config or load_config()
    store = DatabaseStore(cfg.db_path)
    ws_manager = WebSocketManager()
    pool = TelegramClientPool(store, cfg)
    backup_engine = BackupEngine(
        store, pool, cfg, event_broadcaster=ws_manager.broadcast
    )
    auto_sender = AutoSenderEngine(
        store, pool, cfg, event_broadcaster=ws_manager.broadcast
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if start_background_workers:
            await pool.connect_all_enabled()
            await backup_engine.start()
            await auto_sender.start()
        try:
            yield
        finally:
            await auto_sender.stop()
            if start_background_workers:
                await backup_engine.stop()
                await pool.disconnect_all()
            store.close()

    app = FastAPI(
        title="Telegram Backup & Auto-Messaging Suite API",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.state.config = cfg
    app.state.store = store
    app.state.pool = pool
    app.state.backup_engine = backup_engine
    app.state.auto_sender = auto_sender
    app.state.ws_manager = ws_manager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.router)
    app.include_router(accounts.router)
    app.include_router(chats_folders.router)
    app.include_router(backups.router)
    app.include_router(scenarios.router)

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        token = websocket.query_params.get("token")
        if not verify_session_token(token, cfg.web_session_secret):
            await websocket.close(code=1008)
            return
        await ws_manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)

    # Serve compiled React frontend if built
    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.exists() and (frontend_dist / "index.html").exists():
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str) -> FileResponse:
            candidate = frontend_dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(frontend_dist / "index.html"))

    return app
