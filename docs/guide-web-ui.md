# LayaModel: the admin web UI

One page, `/admin/`, for tokens and CPU threads. It is the same for every way of running the service (Docker on the
same device, Docker on a deployment device, no Docker). Only the address differs:

| Run | Address |
|---|---|
| Docker or `run.bat` on this PC | `http://127.0.0.1:9120/admin/` |
| Docker on the deployment box | `http://<box-ip>:9120/admin/` |

If `LAYA_PORT` is changed, use that port.

## Before you open it
The page needs the admin password: the value of `LAYA_ADMIN_PASSWORD`.
- Docker: set it in `.env` next to `docker-compose.yml`, then `docker compose up -d`.
- No Docker: set it in the environment before starting the service (`run.bat` / `uvicorn`); the service reads the
  real environment, not `.env`.
- Empty password = no auth at all and the page answers `Admin password required (set LAYA_ADMIN_PASSWORD)`. Set
  one to use the page.

## Sign in
Type the admin password and press **Load**. A wrong password shows `Wrong admin password`. The password is held in
the page only: reload the tab and sign in again.

## Tokens
Each calling project gets its own token, so one can be revoked without touching the others.
- **Create:** type a project name (up to 64 characters) and press **Create token**. The token appears once as
  `Copy now, it is not shown again: ...`. Copy it before you do anything else.
- **Use:** the caller sends it in the `X-Internal-Token` header on every call except `/health`. Citadel: set it as
  `LAYA_TOKEN` in `apps/garrison/.env`, then `docker compose up -d` in Citadel (`restart` does not reload `env_file`).
- **List:** the table shows project name and creation time. Token values are not shown again.
- **Revoke:** press **Revoke** on the row and confirm. The caller gets `401 Invalid token` from then on. Lost
  token = revoke it and create a new one.

Tokens live in `tokens.json` (`LAYA_TOKENS_FILE`). In Docker that is the `tokens` volume at `/data`, so they survive
`docker compose down` and rebuilds. Without Docker it is `tokens.json` in the folder the service starts from. Tokens
are enforced only while `LAYA_ADMIN_PASSWORD` is set.

## Torch CPU threads
Field **Torch CPU threads**, then **Apply**.
- Sets how many CPU threads torch uses for each prediction. In a container with a CPU quota torch still counts the
  host's cores, and more threads than the quota makes each prediction several times slower. Start near the number
  of cores the container may use.
- Range 1 to 256. The field shows the value in use now.
- The change applies at once to the replica that answers the click and is saved to `settings.json` next to
  `tokens.json`. Other replicas pick it up when they restart: `docker compose restart laya`.
- The saved value beats `LAYA_TORCH_THREADS` from `.env`. Remove `settings.json` from the `/data` volume to go back
  to the `.env` value.
- `GET /health` reports the value in use as `torch_threads`.

## Replicas (read-only)
The line **Replicas: N** shows `LAYA_REPLICAS`. The page cannot change it; each replica loads its own copy of the
models, so it multiplies RAM. To change it, set `LAYA_REPLICAS` in `.env`, then:
```bash
docker compose up -d --build
docker compose restart laya_lb
```
`Replicas: unknown` means the variable is not set, which is normal without Docker.

## Problems
| Symptom | Fix |
|---|---|
| Page does not load | Service not running, wrong port, or blocked by a firewall. Test `/health`. |
| `Wrong admin password` | Password differs from `LAYA_ADMIN_PASSWORD` in the running container. Recreate it after editing `.env`. |
| `Admin password required (set LAYA_ADMIN_PASSWORD)` | The password is empty. Set it and restart. |
| Token lost | Revoke it and create a new one. |
| Thread change gone after restart | Other replicas load the saved value only on restart; check `/health` on each. |
| Page works over plain `http` only | Expected on a LAN. Never expose port 9120 to the internet. |
