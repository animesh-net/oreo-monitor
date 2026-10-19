"""One outside check of the oreo-cloud Pi, run by .github/workflows/monitor.yml every 5 minutes.

The checks go in order and stop at the first one that fails, so the alert says where the
problem is: the Pi on Tailscale, then SSH, then the heartbeat (Docker and the checks inside
it), then Immich through Caddy.

An alert goes out only when a problem is seen twice in a row, so one missed run does not
page anyone, and not during the router's daily restart. One message says when it is fixed.
Logs are public in this repository, so they name only the stage, never the details.

Configuration (repository secrets, passed as environment variables):
  OREO_HOST             the Pi's Tailscale name or address
  OREO_HEARTBEAT_TOKEN  the same token as in the Pi's .env
  OREO_NTFY_URL         ntfy topic for alerts (OREO_NTFY_TOKEN if it is protected)
  OREO_SITE_URL         optional, e.g. Immich's /api/server/ping address
"""

import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Asia/Kolkata")
QUIET_WINDOW = (time(5, 55), time(6, 15))  # the router restarts itself at 06:00
REMINDER = timedelta(hours=6)
HEARTBEAT_PORT = 8787


@dataclass(frozen=True)
class Result:
    ok: bool
    stage: str
    message: str


@dataclass(frozen=True)
class Probes:
    tailscale_ping: Callable[[str], bool]
    tcp_open: Callable[[str, int], bool]
    http_get: Callable[[str, str | None], tuple[int | None, dict | None]]


def probe(host: str, token: str, site_url: str | None, p: Probes) -> Result:
    if not p.tailscale_ping(host):
        return Result(
            False,
            "tailnet",
            "The Pi does not answer on Tailscale. It is off, has lost its network, "
            "or Tailscale on it has stopped.",
        )
    if not p.tcp_open(host, 22):
        return Result(
            False,
            "ssh",
            "The Pi is on Tailscale but SSH does not answer. The system may be hung; "
            "it may need a power cycle.",
        )
    status, body = p.http_get(f"http://{host}:{HEARTBEAT_PORT}/heartbeat", token)
    if status is None:
        return Result(
            False,
            "docker",
            "The Pi is up but its heartbeat does not answer, so Docker or the oreo "
            "container is down. This needs you: connect over Tailscale with SSH, run "
            "sudo systemctl restart docker, then docker compose up -d in oreo-cloud.",
        )
    if status == 401:
        return Result(
            False,
            "token",
            "The heartbeat rejected the token. OREO_HEARTBEAT_TOKEN differs between the "
            "Pi's .env and this repository's secrets.",
        )
    if status == 503:
        failing = [
            f"{check['name']}: {check['detail']}"
            for check in (body or {}).get("checks", [])
            if not check.get("ok")
        ]
        return Result(False, "checks", "The Pi reports problems:\n" + "\n".join(failing))
    if status != 200:
        return Result(False, "heartbeat", f"The heartbeat answered HTTP {status}.")
    if site_url:
        site_status, _ = p.http_get(site_url, None)
        if site_status is None or site_status >= 500:
            return Result(
                False,
                "site",
                "The Pi is healthy but Immich does not answer through Caddy.",
            )
    return Result(True, "up", "All checks pass.")


def _clock(moment: datetime) -> str:
    return moment.astimezone(ZONE).strftime("%H:%M")


def in_quiet_window(moment: datetime) -> bool:
    start, end = QUIET_WINDOW
    return start <= moment.astimezone(ZONE).time() < end


def decide(state: dict, result: Result, now: datetime) -> tuple[dict, tuple[str, str] | None]:
    """The next state and, when one is due, a (title, message) to send."""
    status = state.get("status", "up")
    since = datetime.fromisoformat(state["since"]) if state.get("since") else now

    if result.ok:
        if status == "down":
            minutes = max(1, round((now - since).total_seconds() / 60))
            unit = "minute" if minutes == 1 else "minutes"
            return {"status": "up"}, (
                "Oreo Cloud OK",
                f"✅ The Pi passes every outside check again after about {minutes} {unit} "
                f"(problem from {_clock(since)}, fixed at {_clock(now)}).",
            )
        return {"status": "up"}, None

    if status == "up" or (status == "suspect" and in_quiet_window(now)):
        # First failure, or still inside the router restart: wait for the next run.
        return {"status": "suspect", "since": since.isoformat(), "stage": result.stage}, None

    last_alert = datetime.fromisoformat(state["alerted"]) if state.get("alerted") else None
    due = (
        status == "suspect"
        or state.get("stage") != result.stage
        or (last_alert is not None and now - last_alert >= REMINDER)
    )
    new = {
        "status": "down",
        "since": since.isoformat(),
        "stage": result.stage,
        "alerted": (now if due else last_alert or now).isoformat(),
    }
    if not due:
        return new, None
    return new, ("Oreo Cloud NEEDS ATTENTION", f"⚠️ {result.message}\n(since {_clock(since)})")


def _tailscale_ping(host: str) -> bool:
    command = ["sudo", "tailscale", "ping", "--c=3", "--timeout=5s", host]
    return subprocess.run(command, capture_output=True, check=False).returncode == 0


def _tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=10):
            return True
    except OSError:
        return False


def _http_get(url: str, token: str | None) -> tuple[int | None, dict | None]:
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    except (urllib.error.URLError, OSError):
        return None, None
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, None


def _send(title: str, message: str) -> None:
    headers = {"Title": title, "Tags": "white_check_mark" if "OK" in title else "warning"}
    if "OK" not in title:
        headers["Priority"] = "high"
    if os.environ.get("OREO_NTFY_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['OREO_NTFY_TOKEN']}"
    request = urllib.request.Request(
        os.environ["OREO_NTFY_URL"], data=message.encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()


def main() -> int:
    if os.environ.get("TAILSCALE_JOINED") != "success":
        # The runner could not join the tailnet: a monitor problem, not a Pi problem.
        print("Could not join the tailnet; the Pi was not checked.")
        return 1
    state_file = Path(os.environ.get("STATE_FILE", "monitor-state.json"))
    try:
        state = json.loads(state_file.read_text())
    except (FileNotFoundError, ValueError):
        state = {}
    result = probe(
        os.environ["OREO_HOST"],
        os.environ["OREO_HEARTBEAT_TOKEN"],
        os.environ.get("OREO_SITE_URL") or None,
        Probes(_tailscale_ping, _tcp_open, _http_get),
    )
    new_state, notification = decide(state, result, datetime.now(UTC))
    if notification:
        _send(*notification)  # if this fails the run fails and the state is not saved
    state_file.write_text(json.dumps(new_state))
    print(f"Result: {new_state['status']} ({result.stage})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
