import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "monitor", Path(__file__).parent.parent / "scripts" / "monitor.py"
)
monitor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(monitor)

NOON = datetime(2026, 10, 19, 6, 30, tzinfo=UTC)  # 12:00 in Asia/Kolkata
HEALTHY = {"ok": True, "checks": [{"name": "load", "ok": True, "detail": "0.2"}]}


def probes(ping=True, ssh=True, heartbeat=(200, HEALTHY), site=(200, None)):
    def http_get(url, token):
        return heartbeat if url.endswith("/heartbeat") else site

    return monitor.Probes(lambda host: ping, lambda host, port: ssh, http_get)


def check(**kwargs):
    return monitor.probe("oreo-cloud", "token", "https://cloud.example/ping", probes(**kwargs))


def test_everything_up():
    assert check().ok


def test_stages_are_checked_in_order():
    assert check(ping=False, ssh=False).stage == "tailnet"
    assert check(ssh=False).stage == "ssh"
    assert check(heartbeat=(None, None)).stage == "docker"
    assert check(heartbeat=(401, None)).stage == "token"
    assert check(site=(502, None)).stage == "site"
    assert check(site=(None, None)).stage == "site"


def test_docker_down_says_it_needs_a_manual_restart():
    assert "sudo systemctl restart docker" in check(heartbeat=(None, None)).message


def test_failing_checks_are_listed():
    body = {"ok": False, "checks": [{"name": "disk /", "ok": False, "detail": "95% used"}]}
    result = check(heartbeat=(503, body))
    assert result.stage == "checks"
    assert "disk /: 95% used" in result.message


def test_password_protected_site_counts_as_up():
    assert check(site=(401, None)).ok


DOWN = monitor.Result(False, "docker", "Docker is down")
UP = monitor.Result(True, "up", "All checks pass.")


def run(results, start=NOON, step=5):
    state, sent = {}, []
    for i, result in enumerate(results):
        state, note = monitor.decide(state, result, start + timedelta(minutes=step * i))
        if note:
            sent.append(note)
    return state, sent


def test_one_failed_run_does_not_alert():
    state, sent = run([DOWN, UP])
    assert sent == []
    assert state == {"status": "up"}


def test_two_failed_runs_alert_once_then_recovery_is_reported():
    _, sent = run([DOWN, DOWN, DOWN, DOWN, UP])
    assert [title for title, _ in sent] == ["Oreo Cloud NEEDS ATTENTION", "Oreo Cloud OK"]
    assert "since 12:00" in sent[0][1]
    assert sent[1][1].startswith(
        "✅ The Pi passes every outside check again after about 20 minutes"
    )


def test_a_different_problem_alerts_again():
    other = monitor.Result(False, "tailnet", "Off the tailnet")
    _, sent = run([DOWN, DOWN, other])
    assert len(sent) == 2


def test_reminder_every_six_hours():
    _, sent = run([DOWN] * 80)  # 80 runs, 5 minutes apart: about 6.6 hours
    assert len(sent) == 2


def test_router_restart_window_does_not_alert():
    restart = datetime(2026, 10, 19, 0, 27, tzinfo=UTC)  # 05:57 local
    _, sent = run([DOWN, DOWN, DOWN, UP], start=restart)  # 05:57 to 06:12
    assert sent == []


def test_outage_lasting_past_the_window_alerts_after_it():
    restart = datetime(2026, 10, 19, 0, 30, tzinfo=UTC)  # 06:00 local
    _, sent = run([DOWN] * 6, start=restart)  # until 06:25
    assert [title for title, _ in sent] == ["Oreo Cloud NEEDS ATTENTION"]
    assert "since 06:00" in sent[0][1]


def test_tailnet_join_failure_does_not_check_or_change_state(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TAILSCALE_JOINED", "failure")
    monkeypatch.setenv("STATE_FILE", str(tmp_path / "state.json"))
    assert monitor.main() == 1
    assert not (tmp_path / "state.json").exists()
