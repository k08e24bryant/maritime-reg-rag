"""Demo server: FastAPI JSON API + Gradio UI in one process (models load once).

Usage: uv run maritime-demo [--config configs/demo.yaml] [--port N]
Then open http://127.0.0.1:7860 (UI at /ui, API docs at /docs).
"""

from __future__ import annotations

import argparse
import logging
import sys

from maritime_rag.config import load_config


def main() -> None:
    import gradio as gr
    import uvicorn

    from maritime_rag.answer.providers import ProviderError
    from maritime_rag.demo.api import create_app
    from maritime_rag.demo.service import DemoService
    from maritime_rag.demo.ui import build_ui

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="configs/demo.yaml")
    parser.add_argument("--port", type=int, help="override the configured port")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)

    service = DemoService.from_config(args.config)
    print("loading retrieval models (e5 + reranker)...", file=sys.stderr)
    print(f"loaded in {service.load():.1f} s", file=sys.stderr)
    try:
        service.answerer(cfg["default_llm"])  # key, model id and a tiny probe, before serving
    except ProviderError as e:
        sys.exit(f"error: {e}")

    app = create_app(service, cfg["ui_path"])
    ui = build_ui(service, cfg.get("eval_report"), cfg.get("figures"))
    ui.queue(default_concurrency_limit=1)  # one request at a time: retrieval shares one GPU
    app = gr.mount_gradio_app(app, ui, path=cfg["ui_path"], footer_links=["api"])
    port = args.port or cfg["port"]
    print(f"serving on http://{cfg['host']}:{port} (UI {cfg['ui_path']}, API docs /docs)", file=sys.stderr)
    uvicorn.run(app, host=cfg["host"], port=port, log_level="warning")


if __name__ == "__main__":
    main()
