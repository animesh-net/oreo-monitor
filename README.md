# oreo-monitor

External monitor for the oreo-cloud Raspberry Pi home server.

- A GitHub Actions workflow checks the Pi every 5 minutes, including whether Docker is healthy.
- Alerts go to the owner's phone. Credentials are stored as GitHub secrets, never in this repository.
- Public repository, so the workflow minutes are free. It contains no server details or secrets.

The server's scripts and images live in the private repository `oreo-cloud`.

## Changes

`main` is protected. Every change goes through a pull request and is squash-merged by the owner.
