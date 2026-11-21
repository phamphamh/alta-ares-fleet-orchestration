"""Tests for the live-board client: the validation set, the login file and `submit` against a stub server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from fleetkit import submit as sub
from fleetkit.cli import main as cli_main
from fleetkit.validation import VALIDATION_SET, parse_scenario_id, scenario_id, validation_ids


class Stub:
    """A server that records what it receives and answers with a canned reply."""

    def __init__(self, status=200, reply=None, too_fast=0):
        self.received = []
        self.too_fast = too_fast
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers["Content-Length"])
                outer.received.append(json.loads(self.rfile.read(n)))
                if outer.too_fast > 0:
                    outer.too_fast -= 1
                    msg = json.dumps({"error": "too fast"}).encode()
                    self.send_response(429)
                    self.send_header("Content-Length", str(len(msg)))
                    self.end_headers()
                    self.wfile.write(msg)
                    return
                body = json.dumps(reply if reply is not None else {"valid": True, "score": 123.4, "violations": [], "improved": True, "best": 123.4}).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sub, "CONFIG_NAMES", (".fleetkit-board.json", str(tmp_path / "home.json")))
    for k in ("SERVER", "TEAM", "TOKEN"):
        monkeypatch.delenv(f"FLEETKIT_BOARD_{k}", raising=False)
    return tmp_path


def test_the_validation_set_is_eight_public_scenarios():
    assert len(VALIDATION_SET) == 8 and validation_ids() == ["L1-101", "L2-201", "L2-202", "L3-301", "L3-302", "L3-303", "L4-401", "L4-402"]
    assert [lv for lv, _ in VALIDATION_SET].count("L3") == 3 and scenario_id("L3", 301) == "L3-301"
    assert parse_scenario_id("L4-402") == ("L4", 402)
    for bad in ("L5-1", "L3", "L3-x", "", "x-12"):
        with pytest.raises(ValueError):
            parse_scenario_id(bad)


def test_login_is_saved_and_environment_variables_win(home, monkeypatch):
    assert sub.load_config() == {}
    path = sub.save_config("http://10.0.0.5:8080/", "Alpha", "tok")
    assert sub.load_config() == {"server": "http://10.0.0.5:8080", "team": "Alpha", "token": "tok"} and path.exists()
    monkeypatch.setenv("FLEETKIT_BOARD_TOKEN", "other")
    assert sub.load_config()["token"] == "other"
    (home / ".fleetkit-board.json").write_text(json.dumps({"server": "http://local", "team": "L", "token": "t"}))
    assert sub.load_config()["server"] == "http://local"                 # the folder's file comes first


def test_post_plan_sends_the_json_and_maps_refusals(home):
    ok = Stub()
    try:
        r = sub.post_plan(ok.url, "Alpha", "tok", "L1-101", {"seed": 101, "routes": []})
        assert r["valid"] and ok.received == [{"team": "Alpha", "token": "tok", "scenario": "L1-101", "plan": {"seed": 101, "routes": []}}]
    finally:
        ok.stop()
    refuse = Stub(403, {"error": "unknown team or wrong token"})
    try:
        with pytest.raises(RuntimeError, match=r"403.*wrong token"):
            sub.post_plan(refuse.url, "A", "x", "L1-101", {})
    finally:
        refuse.stop()
    with pytest.raises(RuntimeError, match="cannot reach"):
        sub.post_plan("http://127.0.0.1:9", "A", "x", "L1-101", {}, timeout=2)


def test_the_cli_writes_the_validation_set_and_checks_plans_locally(home, capsys):
    folder = home / "val"
    assert cli_main(["validation-set", "-o", str(folder)]) == 0
    assert sorted(p.name for p in folder.glob("*.json")) == sorted(f"{n}.json" for n in validation_ids())
    # one plan that is valid and one that is not
    assert cli_main(["baseline", str(folder / "L1-101.json"), "-o", str(home / "L1-101.json")]) == 0
    bad = json.loads((home / "L1-101.json").read_text())
    bad["seed"] = 5
    (home / "bad.json").write_text(json.dumps(bad))
    stub = Stub()
    try:
        common = ["--server", stub.url, "--team", "Alpha", "--token", "tok"]
        assert cli_main(["submit", "L1-101", str(home / "L1-101.json"), *common]) == 0
        assert "score 123.4 (new best)" in capsys.readouterr().out
        assert cli_main(["submit", "L1-101", str(home / "bad.json"), *common]) == 1       # not sent: invalid locally
        assert "not sent" in capsys.readouterr().out and len(stub.received) == 1
        assert cli_main(["submit", "L1-101", str(home / "bad.json"), *common, "--force"]) == 0 and len(stub.received) == 2
        assert cli_main(["submit", "L9-1", str(home / "bad.json"), *common]) == 1
        # a folder: only the files that exist are sent, the rest are skipped
        plans = home / "plans"
        plans.mkdir()
        (plans / "L1-101.json").write_text((home / "L1-101.json").read_text())
        before = len(stub.received)
        assert cli_main(["submit-all", str(plans), *common]) == 0
        out = capsys.readouterr().out
        assert len(stub.received) == before + 1 and "L2-201: no file" in out and "1 plans accepted" in out
    finally:
        stub.stop()


def test_submit_without_a_login_explains_how_to_log_in(home):
    with pytest.raises(SystemExit, match="board-login"):
        cli_main(["submit", "L1-101", "plan.json"])


def test_board_login_command_saves_the_file(home, capsys):
    assert cli_main(["board-login", "--server", "http://x:1", "--team", "T", "--token", "K"]) == 0
    assert json.loads((home / "home.json").read_text()) == {"server": "http://x:1", "team": "T", "token": "K"}


def test_a_too_fast_answer_is_retried_then_given_up(home):
    stub = Stub(too_fast=2)
    try:
        r = sub.post_plan(stub.url, "A", "t", "L1-101", {}, wait_s=0.01)
        assert r["valid"] and len(stub.received) == 3
    finally:
        stub.stop()
    stuck = Stub(too_fast=99)
    try:
        with pytest.raises(RuntimeError, match="429"):
            sub.post_plan(stuck.url, "A", "t", "L1-101", {}, retries=2, wait_s=0.01)
        assert len(stuck.received) == 3
    finally:
        stuck.stop()


def test_plans_can_be_written_into_a_folder_that_does_not_exist_yet(home):
    assert cli_main(["generate", "L1", "101", "-o", str(home / "val" / "L1-101.json")]) == 0
    assert cli_main(["baseline", str(home / "val" / "L1-101.json"), "-o", str(home / "my-plans" / "L1-101.json")]) == 0
    assert json.loads((home / "my-plans" / "L1-101.json").read_text())["routes"]


def test_the_login_file_is_private_from_the_first_byte_even_over_a_loose_one(home):
    import os
    old = os.umask(0o022)
    try:
        from pathlib import Path
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "chmod", lambda *a, **k: None)         # no later chmod: the creation itself must be private
            fresh = sub.save_config("http://x:1", "Alpha", "tok")
            assert fresh.stat().st_mode & 0o777 == 0o600
            fresh.unlink()
        path = sub.save_config("http://x:1", "Alpha", "tok")
        assert path.stat().st_mode & 0o777 == 0o600
        path.chmod(0o644)                                         # a looser file that already exists is tightened
        sub.save_config("http://x:1", "Alpha", "tok2")
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        os.umask(old)


def test_board_login_asks_for_the_token_when_it_is_left_out(home, monkeypatch):
    import getpass
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "  typed-token ")
    assert cli_main(["board-login", "--server", "http://x:1", "--team", "Alpha"]) == 0
    assert sub.load_config()["token"] == "typed-token"
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "")
    assert cli_main(["board-login", "--server", "http://x:1", "--team", "Alpha"]) == 1
