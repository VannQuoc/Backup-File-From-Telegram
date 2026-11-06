from __future__ import annotations

import uvicorn

from backend.app import create_app
from backend.config import load_config


def main() -> None:
    cfg = load_config()
    app = create_app(cfg, start_background_workers=True)
    uvicorn.run(
        app,
        host=cfg.web_host,
        port=cfg.web_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
