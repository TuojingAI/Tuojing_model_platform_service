from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn

from .config import DEFAULT_META_DIR, DEFAULT_RELEASE_DIR, DEFAULT_WORKSPACE_ROOT


def api_main() -> None:
    parser = argparse.ArgumentParser(description="Run the model registry API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--meta-dir", default=str(DEFAULT_META_DIR))
    parser.add_argument("--release-dir", default=str(DEFAULT_RELEASE_DIR))
    parser.add_argument("--workspace-root", default=str(DEFAULT_WORKSPACE_ROOT))
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    os.environ["MODEL_PLATFORM_META_DIR"] = args.meta_dir
    os.environ["MODEL_PLATFORM_RELEASE_DIR"] = args.release_dir
    os.environ["MODEL_PLATFORM_WORKSPACE_ROOT"] = args.workspace_root

    uvicorn.run(
        "tuojing_model_platform_service.api:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        workers=args.workers,
    )


def ui_main() -> None:
    parser = argparse.ArgumentParser(description="Run the model registry Streamlit UI")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    os.environ["MODEL_PLATFORM_API_URL"] = args.api_url.rstrip("/")
    app_path = Path(__file__).with_name("streamlit_app.py")
    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.address",
        args.host,
        "--server.port",
        str(args.port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    from streamlit.web import cli as streamlit_cli

    raise SystemExit(streamlit_cli.main())
