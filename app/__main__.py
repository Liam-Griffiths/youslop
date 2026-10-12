"""Start the server without a shell script.

`run.sh` has been the only way to launch this, which is fine on the machine it
was written on and no use anywhere else: it builds a venv, shells out to
macOS-only networking commands, and hardcodes a relative path to a uvicorn
binary. A packaged application has none of that, so the server needs to be
startable from Python — by `python -m app`, and by the desktop shell, which
calls `serve()` in a thread and then opens a window onto it.

    python -m app                 loopback, a free port, opens nothing
    python -m app --port 8420     the familiar address
    python -m app --open          and show it in a browser

Binding a *free* port by default rather than 8420 is deliberate: an installed
app that refuses to start because something else has the port, or worse quietly
attaches to another copy of itself, is a bad first five minutes.
"""
from __future__ import annotations

import argparse
import logging
import os
import secrets
import socket
import threading
import webbrowser
from pathlib import Path

from .config import CACHE_DIR, LOG_DIR, ensure_dirs, ffmpeg_ready
from .paths import describe


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _log_file() -> Path:
    """One rolling log in the data folder, because a windowed app has no
    terminal to print a traceback to."""
    path = LOG_DIR / "youslop.log"
    if path.exists() and path.stat().st_size > 4_000_000:
        path.replace(path.with_suffix(".log.1"))
    return path


def configure(port: int | None = None, token: str | None = None,
              quiet: bool = False) -> tuple[int, str]:
    """Prepare the data folders, logging and the access token.

    Returns the port and token the server will use. The token is minted per
    launch rather than kept on disk: nothing but this process and whatever it
    hands the URL to has any business reaching the API, and a secret that does
    not outlive the run cannot leak from a file somebody forgot about.
    """
    ensure_dirs()
    handlers: list[logging.Handler] = [logging.FileHandler(_log_file())]
    if not quiet:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO, handlers=handlers, force=True,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("youslop")
    for key, value in describe().items():
        log.info("paths: %s = %s", key, value)
    ok, said = ffmpeg_ready()
    log.info("ffmpeg: %s", said) if ok else log.error("ffmpeg: %s", said)
    port = port or free_port()
    token = token if token is not None else secrets.token_hex(12)
    if token:
        os.environ["VB_TOKEN"] = token
    return port, token


def serve(port: int, host: str = "127.0.0.1", ssl: tuple[str, str] | None = None,
          ready: threading.Event | None = None) -> None:
    """Run uvicorn in this thread. Blocks until the server stops."""
    import uvicorn

    from .main import app

    class _Ready(uvicorn.Server):
        async def startup(self, sockets=None):      # type: ignore[override]
            await super().startup(sockets)
            if ready is not None:
                ready.set()

    config = uvicorn.Config(app, host=host, port=port, log_config=None,
                            ssl_keyfile=ssl[0] if ssl else None,
                            ssl_certfile=ssl[1] if ssl else None)
    _Ready(config).run()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m app", description="Start Youslop.")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 0),
                    help="0 (the default) picks a free one")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--open", action="store_true", help="open a browser on it")
    ap.add_argument("--no-token", action="store_true",
                    help="skip the access token (loopback only, for development)")
    args = ap.parse_args(argv)

    port, token = configure(args.port or None, "" if args.no_token else None)
    url = f"http://{args.host}:{port}/" + (f"?t={token}" if token else "")
    print(f"→ {url}")
    if args.open:
        threading.Timer(1.0, webbrowser.open, (url,)).start()
    serve(port, args.host)


if __name__ == "__main__":
    main()
