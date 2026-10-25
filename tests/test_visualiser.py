import http.client
import json
import threading
import time

import pytest

from koii_studio.library import Library
from koii_studio.studio import Studio
from koii_studio.visualiser import Visualiser


@pytest.fixture
def visualiser(tmp_path):
    studio = Studio(library=Library(tmp_path), list_outputs=lambda: [], open_input=None)
    server = Visualiser(studio, port=18733)
    server.start()
    yield server
    studio.disconnect()
    server.stop()


def request(visualiser, method, path, body=None, headers=None):
    port = int(visualiser.url.rsplit(":", 1)[1].strip("/"))
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps(body).encode() if body is not None else None
    all_headers = {"Content-Type": "application/json", **(headers or {})}
    connection.request(method, path, body=payload, headers=all_headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, response.getheader("Content-Type"), data


def command(visualiser, name, body=None):
    status, _, data = request(visualiser, "POST", f"/api/{name}", body or {}, {"X-Koii-Studio": "1"})
    return status, json.loads(data)


def test_serves_the_page_and_its_scripts(visualiser):
    status, content_type, body = request(visualiser, "GET", "/")
    assert status == 200 and content_type.startswith("text/html") and b"<title>koii studio</title>" in body
    status, content_type, _ = request(visualiser, "GET", "/app.js")
    assert status == 200 and content_type.startswith("text/javascript")


def test_cannot_read_files_outside_the_static_folder(visualiser):
    status, _, _ = request(visualiser, "GET", "/../library.py")
    assert status == 404


def test_commands_from_other_websites_are_refused(visualiser):
    status, _, data = request(visualiser, "POST", "/api/stop", {})
    assert status == 403 and b"X-Koii-Studio" in data
    status, _, _ = request(visualiser, "GET", "/api/state", headers={"Host": "attacker.example"})
    assert status == 403


def test_check_returns_the_parsed_pattern_or_located_errors(visualiser):
    status, data = command(visualiser, "check", {"text": "kick: x...x...\nhat: x."})
    assert status == 200 and data["result"]["length"] == 8
    assert data["result"]["tracks"][0]["target"]["label"] == "A."
    status, data = command(visualiser, "check", {"text": "kick: x.v."})
    assert status == 400 and data["issues"][0]["column"] == 9


def test_playing_from_the_browser_streams_events_and_is_logged(visualiser):
    port = int(visualiser.url.rsplit(":", 1)[1].strip("/"))
    events = []
    connected = threading.Event()

    def read_stream():
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/api/events")
        response = connection.getresponse()
        connected.set()
        while len(events) < 30:
            line = response.fp.readline()
            if not line:
                break
            if line.startswith(b"data: "):
                events.append(json.loads(line[6:]))

    reader = threading.Thread(target=read_stream, daemon=True)
    reader.start()
    connected.wait(5)
    time.sleep(0.1)
    assert command(visualiser, "connect", {"port": "simulator"})[0] == 200
    assert command(visualiser, "play", {"what": "@bpm 300\nkick: x.x.", "loop": False})[0] == 200
    deadline = time.time() + 5
    while time.time() < deadline and not any(e["type"] == "stopped" for e in events):
        time.sleep(0.05)
    types = [e["type"] for e in events]
    assert "pass" in types and "stopped" in types
    assert sum(1 for e in events if e["type"] == "note" and e["on"]) == 2
    activity = [e for e in events if e["type"] == "activity"]
    assert [a["action"] for a in activity] == ["connect", "play"] and activity[0]["source"] == "browser"


def test_saving_and_downloading_midi(visualiser):
    assert command(visualiser, "save_pattern", {"name": "verse", "text": "kick: x...x...x...x..."})[0] == 200
    status, data = command(visualiser, "save_pattern", {"name": "bad name", "text": "kick: x"})
    assert status == 400 and "isn't a valid name" in data["error"]
    status, content_type, body = request(visualiser, "GET", "/api/midi?what=verse%20x2")
    assert status == 200 and content_type == "audio/midi" and body.startswith(b"MThd")
    status, data = command(visualiser, "nonsense")
    assert status == 404


def test_downloading_sheet_music(visualiser):
    status, content_type, body = request(visualiser, "GET", "/api/musicxml?what=kick%3A%20x...")
    assert status == 200 and "musicxml" in content_type and b"<score-partwise" in body
    status, _, _ = request(visualiser, "GET", "/api/musicxml?what=nothing-saved")
    assert status == 400


def test_the_browser_can_upload_a_sound_to_an_empty_slot(visualiser, tmp_path, monkeypatch):
    import base64
    from koii_studio import files
    from koii_studio.backup import backup_device
    from koii_studio.samples import DeviceLibrary
    from fake_device import FakeEP133, client_for, sound
    for name in ("PAGE_PAUSE_SECONDS", "PUT_PAGE_PAUSE_SECONDS", "PREFLIGHT_SECONDS"):
        monkeypatch.setattr(files, name, 0)
    fake = FakeEP133({1: sound("micro kick", b"\x01\x00" * 100)})
    client = client_for(fake, tmp_path / "lock")
    visualiser.studio.samples = DeviceLibrary(visualiser.studio.events, tmp_path, client)
    pcm = b"\x10\x00\xf0\xff" * 1000
    status, data = command(visualiser, "upload_sample", {"slot": 700, "name": "koii", "pcm": base64.b64encode(pcm).decode()})
    assert status == 400 and "backup first" in data["error"]
    backup_device(client, tmp_path / "backups")
    status, data = command(visualiser, "upload_sample", {"slot": 700, "name": "koii", "pcm": base64.b64encode(pcm).decode()})
    assert status == 200 and fake.sounds[700][1] == pcm and "slot 700" in data["result"]["message"]
    status, data = command(visualiser, "suggest_slot")
    assert data["result"] == 600
    status, data = command(visualiser, "upload_sample", {"slot": 1, "name": "x", "pcm": base64.b64encode(pcm).decode()})
    assert status == 400 and "didn't put there" in data["error"]
