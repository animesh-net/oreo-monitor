# Oreo Monitor

Checks the oreo-cloud Raspberry Pi and the oreo-ai app it runs from outside, every hour, as a GitHub Actions workflow, and sends an ntfy alert to my phone when something is down.

Part of the Oreo stack: [oreo-ai](https://github.com/animesh-net/oreo-ai) · [oreo-code](https://github.com/animesh-net/oreo-code) · [oreo-cloud](https://github.com/animesh-net/oreo-cloud) · [oreo-monitor](https://github.com/animesh-net/oreo-monitor)

## Architecture

- Each run joins the tailnet as a temporary `tag:ci` device and checks, stopping at the first failure: Tailscale ping, SSH, the Pi's heartbeat, Immich through Caddy, oreo-ai through Caddy.
- Alerts (**Oreo Cloud NEEDS ATTENTION** / **Oreo Cloud OK**) go out after two failing runs in a row; nothing during the router's daily restart, 05:55 to 06:15.
- From 00:30 to 06:45, while the Pi is powered off for the night, runs check nothing and keep the saved state; `OREO_QUIET_WINDOW` (`HH:MM-HH:MM`, empty for none) changes it.
- The up/down state lives in the Actions cache, and all server details are GitHub secrets, so nothing private is in this public repo.

| Path | What it is |
| --- | --- |
| `.github/workflows/monitor.yml` | Hourly schedule and manual run |
| `scripts/monitor.py` | The checks and ntfy alerts |
| `.github/workflows/ci.yml` | Pre-commit hooks and tests on PRs |
| `scripts/check_commit_msg.py` | Commit message and PR title rules |
| `scripts/clean_pr_body.py` | Strips AI footers from PR bodies |
| `tests/` | pytest tests |

## Run it

- A Tailscale tailnet with the Pi on it
- An ntfy topic (the same as the Pi's)

1. In the Tailscale access controls, add `"tagOwners": { "tag:ci": ["autogroup:admin"] }` and this entry to `"grants"`:

   ```json
   { "src": ["tag:ci"], "dst": ["<pi-tailscale-ip>"], "ip": ["tcp:22", "tcp:8787", "tcp:443"] }
   ```

2. Under Settings, then Trust credentials, add an OAuth credential with **Auth Keys: Write** and tag `tag:ci` (its secret starts with `tskey-client-`).
3. Add these repository secrets under Settings, then Secrets and variables, then Actions:

   | Setting | Default | What it is |
   | --- | --- | --- |
   | `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET` | none | From step 2 |
   | `OREO_HOST` | none | The Pi's Tailscale IP (`tailscale ip -4`) |
   | `OREO_HEARTBEAT_TOKEN` | none | Same as in the Pi's `.env` |
   | `OREO_NTFY_URL` | none | The ntfy topic; `OREO_NTFY_TOKEN` only if it is protected |
   | `OREO_SITE_URL` | unset | Optional: `https://cloud.animesh.org.in/api/server/ping` |
   | `OREO_AI_URL` | unset | Optional: `https://ai.animesh.org.in/health` |

4. Under Actions, open **Monitor** and choose **Run workflow**; a green run means every check passed.

GitHub turns off schedules after 60 days without commits; merging Dependabot's weekly PRs keeps it running.

## Develop

`pip install pre-commit pytest && pre-commit install && pytest`. Repo rules are in `CLAUDE.md`.

## License

Copyright © 2026 Animesh Singh. Released under the [MIT License](LICENSE).
