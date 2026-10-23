"""
The browser visualiser: a small local web server around the Studio.

It serves the page in koii/static, streams studio events to it (Server-Sent
Events at /api/events), and accepts commands from it (JSON POSTs to /api/...).
It runs inside the MCP server process, so the browser sees exactly what Claude
does, and can also be run on its own:  python -m koii.visualiser

Only localhost is served. Commands must carry an X-Koii header, which browsers
won't send cross-origin without a CORS preflight that this server never
approves, and the Host header must be local, which blocks DNS rebinding.
"""

import argparse
import base64
import binascii
import io
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, urlparse

from koii.files import DeviceFileError
from koii.library import LibraryError
from koii.notation import NotationError
from koii.studio import Studio

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_PORT = 8133
PORT_ATTEMPTS = 10
HEARTBEAT_SECONDS = 15
COMMAND_HEADER = "X-Koii"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
_CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                  ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
_MAX_BODY_BYTES = 8_000_000  # room for a 20 s stereo upload, base64-encoded


class Visualiser:
    def __init__(self, studio: Studio, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        self.studio = studio
        self.host = host
        self.port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._stopping = threading.Event()

    @property
    def url(self) -> Optional[str]:
        return f"http://{self.host}:{self._server.server_address[1]}/" if self._server else None

    def start(self) -> str:
        """Start serving on the first free port from `port`. Returns the URL."""
        if self._server:
            return self.url
        handler = _make_handler(self)
        last_error: Optional[OSError] = None
        for port in range(self.port, self.port + PORT_ATTEMPTS):
            try:
                self._server = ThreadingHTTPServer((self.host, port), handler)
                break
            except OSError as e:
                last_error = e
        if self._server is None:
            raise OSError(f"no free port for the visualiser in {self.port}-{self.port + PORT_ATTEMPTS - 1}") from last_error
        self._server.daemon_threads = True
        self._stopping.clear()
        self._thread = threading.Thread(target=self._server.serve_forever, name="koii-visualiser", daemon=True)
        self._thread.start()
        logger.info("visualiser at %s", self.url)
        return self.url

    def stop(self) -> None:
        if self._server:
            self._stopping.set()
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()


def open_in_browser(url: str) -> None:
    """Open a URL without writing to stdout (which carries the MCP protocol)."""
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "darwin":
        subprocess.Popen(["open", url], **quiet)
    elif sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", url], **quiet)
    else:
        webbrowser.open(url)


# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------

class _BadRequest(ValueError):
    pass


def _commands(studio: Studio) -> Dict[str, Callable[[Dict[str, Any]], Any]]:
    """POST /api/<name> -> handler(body). Return values are sent back as {"ok": true, "result": ...}."""

    def required(body: Dict[str, Any], key: str) -> Any:
        if key not in body or body[key] in (None, ""):
            raise _BadRequest(f"'{key}' is required")
        return body[key]

    return {
        "check": lambda b: studio.check_pattern(required(b, "text")),
        "arrangement": lambda b: studio.arrangement_info(required(b, "arrangement"), b.get("bpm")),
        "play": lambda b: studio.play(required(b, "what"), int(b.get("repeat", 1)), bool(b.get("loop", False)),
                                      b.get("bpm")),
        "stop": lambda b: studio.stop(),
        "audition": lambda b: studio.audition(required(b, "sound"), int(b.get("velocity", 100)), b.get("note")),
        "save_pattern": lambda b: studio.save_pattern(required(b, "name"), required(b, "text")),
        "save_song": lambda b: studio.save_song(required(b, "name"), required(b, "arrangement"), b.get("bpm")),
        "delete": lambda b: studio.delete(required(b, "name")),
        "set_alias": lambda b: studio.set_alias(required(b, "name"), required(b, "target")),
        "remove_alias": lambda b: studio.remove_alias(required(b, "name")),
        "connect": lambda b: studio.connect(b.get("port") or None, int(b.get("channel", studio.channel))),
        "samples": lambda b: studio.samples.listing(refresh=bool(b.get("refresh"))),
        "play_sample": lambda b: studio.samples.audition(int(required(b, "slot"))),
        "backup": lambda b: studio.samples.start_backup(),
        "cancel_backup": lambda b: studio.samples.cancel_backup(),
        "backup_status": lambda b: studio.samples.backup_status(),
        "suggest_slot": lambda b: studio.samples.suggest_slot(),
        "upload_sample": lambda b: studio.samples.upload(int(required(b, "slot")), _pcm(required(b, "pcm")),
                                                         str(b.get("name") or "koii sound"), int(b.get("channels", 1))),
        "delete_upload": lambda b: studio.samples.delete_upload(int(required(b, "slot"))),
        "disconnect": lambda b: studio.disconnect(),
    }


def _pcm(encoded: str) -> bytes:
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise _BadRequest(f"'pcm' must be base64-encoded 16-bit audio ({error})") from error


# Commands that change something are shown in the activity feed.
_QUIET_COMMANDS = {"check", "arrangement", "samples", "backup_status", "suggest_slot"}


def full_state(studio: Studio) -> Dict[str, Any]:
    try:
        ports = studio.list_ports()
    except ValueError as e:
        ports, port_error = [], str(e)
    else:
        port_error = None
    return {
        "connection": studio.connection_state(),
        "ports": ports,
        "port_error": port_error,
        "playing": studio.player.status,
        "library": studio.library_state(),
        "kit": studio.kit_state(),
        "activity": studio.events.recent(),
        "pass": studio.events.current_pass(),
    }


def _make_handler(visualiser: Visualiser):
    studio = visualiser.studio
    commands = _commands(studio)

    class Handler(BaseHTTPRequestHandler):
        server_version = "koii"

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug("visualiser: " + format, *args)

        # -- safety ---------------------------------------------------------

        def _host_is_local(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
            return host in _LOCAL_HOSTS

        # -- responses ------------------------------------------------------

        def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_bytes(self, body: bytes, content_type: str, filename: Optional[str] = None) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str, issues=None) -> None:
            payload: Dict[str, Any] = {"ok": False, "error": message}
            if issues is not None:
                payload["issues"] = issues
            self._send_json(status, payload)

        # -- GET ------------------------------------------------------------

        def do_GET(self) -> None:
            if not self._host_is_local():
                return self._error(HTTPStatus.FORBIDDEN, "the visualiser only answers on localhost")
            url = urlparse(self.path)
            if url.path == "/api/events":
                return self._stream_events()
            if url.path == "/api/state":
                return self._send_json(HTTPStatus.OK, {"ok": True, "result": full_state(studio)})
            if url.path == "/api/midi":
                return self._download_midi(parse_qs(url.query))
            if url.path == "/api/musicxml":
                return self._download_musicxml(parse_qs(url.query))
            if url.path == "/api/sample.wav":
                return self._download_sample(parse_qs(url.query))
            return self._serve_static(url.path)

        def _serve_static(self, path: str) -> None:
            name = "index.html" if path in ("", "/") else path.lstrip("/")
            file = (STATIC_DIR / name).resolve()
            if STATIC_DIR.resolve() not in file.parents or not file.is_file():
                return self._error(HTTPStatus.NOT_FOUND, "not found")
            self._send_bytes(file.read_bytes(), _CONTENT_TYPES.get(file.suffix, "application/octet-stream"))

        def _download_midi(self, query: Dict[str, list]) -> None:
            what = (query.get("what") or [""])[0]
            if not what:
                return self._error(HTTPStatus.BAD_REQUEST, "'what' is required")
            try:
                midi, label, _ = studio.midi_file(what)
            except NotationError as e:
                return self._error(HTTPStatus.BAD_REQUEST, str(e))
            buffer = io.BytesIO()
            midi.save(file=buffer)
            filename = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:60] or "pattern"
            self._send_bytes(buffer.getvalue(), "audio/midi", f"{filename}.mid")

        def _download_musicxml(self, query: Dict[str, list]) -> None:
            what = (query.get("what") or [""])[0]
            if not what:
                return self._error(HTTPStatus.BAD_REQUEST, "'what' is required")
            try:
                xml, name = studio.musicxml(what)
            except (NotationError, LibraryError) as e:
                return self._error(HTTPStatus.BAD_REQUEST, str(e))
            filename = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60] or "pattern"
            self._send_bytes(xml.encode(), "application/vnd.recordare.musicxml+xml", f"{filename}.musicxml")

        def _download_sample(self, query: Dict[str, list]) -> None:
            try:
                slot = int((query.get("slot") or ["0"])[0])
                wav, name = studio.samples.wav(slot)
            except (ValueError, DeviceFileError) as e:
                return self._error(HTTPStatus.BAD_REQUEST, str(e))
            filename = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{slot:03d} {name}")[:60]
            self._send_bytes(wav, "audio/wav", f"{filename}.wav")

        def _stream_events(self) -> None:
            subscriber = studio.events.subscribe()
            try:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b"retry: 1000\n\n")
                self.wfile.flush()
                while not visualiser.stopping:
                    try:
                        event = subscriber.get(timeout=HEARTBEAT_SECONDS)
                        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                studio.events.unsubscribe(subscriber)

        # -- POST -----------------------------------------------------------

        def do_POST(self) -> None:
            if not self._host_is_local():
                return self._error(HTTPStatus.FORBIDDEN, "the visualiser only answers on localhost")
            if self.headers.get(COMMAND_HEADER) != "1":
                return self._error(HTTPStatus.FORBIDDEN, f"commands need the {COMMAND_HEADER} header")
            name = urlparse(self.path).path.removeprefix("/api/")
            command = commands.get(name)
            if command is None:
                return self._error(HTTPStatus.NOT_FOUND, f"unknown command '{name}'")
            body: Dict[str, Any] = {}
            try:
                body = self._read_json()
                result = command(body)
            except NotationError as e:
                self._record(name, body, error=str(e))
                issues = [{"line": i.line, "column": i.column, "message": i.message} for i in e.issues]
                return self._error(HTTPStatus.BAD_REQUEST, str(e), issues)
            except (ValueError, LibraryError, _BadRequest, DeviceFileError) as e:
                self._record(name, body, error=str(e))
                return self._error(HTTPStatus.BAD_REQUEST, str(e))
            except Exception as e:  # keep the server alive and tell the page what broke
                logger.exception("visualiser command '%s' failed", name)
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(e).__name__}: {e}")
            self._record(name, body, result=result)
            self._send_json(HTTPStatus.OK, {"ok": True, "result": result})

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length > _MAX_BODY_BYTES:
                raise _BadRequest("request too large")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError as e:
                raise _BadRequest(f"invalid JSON: {e}") from e
            if not isinstance(body, dict):
                raise _BadRequest("expected a JSON object")
            return body

        def _record(self, name: str, body: Dict[str, Any], result: Any = None, error: Optional[str] = None) -> None:
            if name in _QUIET_COMMANDS:
                return
            if isinstance(result, dict) and "message" in result:
                result = result["message"]
            summary = result.splitlines()[0] if isinstance(result, str) and result else None
            shown = {key: value for key, value in body.items() if key != "pcm"}
            studio.events.activity("browser", name, shown, result=summary, error=error)

    return Handler


def main() -> None:
    """Run the visualiser on its own (without Claude): python -m koii.visualiser"""
    parser = argparse.ArgumentParser(description="KOII visualiser for the EP-133 K.O. II")
    parser.add_argument("--port", type=int, default=int(os.environ.get("KOII_WEB_PORT", DEFAULT_PORT)))
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    options = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    studio = Studio()
    visualiser = Visualiser(studio, port=options.port)
    url = visualiser.start()
    print(f"KOII visualiser at {url} (Ctrl+C to stop)", flush=True)
    if not options.no_browser:
        open_in_browser(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        studio.disconnect()
        visualiser.stop()


if __name__ == "__main__":
    main()
