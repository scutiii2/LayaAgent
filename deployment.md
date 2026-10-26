# Deploying LayaModel

LayaModel is one HTTP service (port 9120) that owns the Laya models. It runs as `laya` replicas behind an nginx
load balancer, `laya_lb`. Callers use `http://<host>:9120`; they never reach a replica directly.

There are two ways to run it. Pick one: both use host port 9120.

| | Standalone | Inside the Citadel stack |
|---|---|---|
| Where | this folder's `docker-compose.yml` | `Citadel/docker-compose.yml` |
| Compose project | `laya` | `citadel` |
| Network | its own `laya` net, plus the external `citadel_core` | Citadel's `core` |
| Start | `docker compose up -d --build` here | `docker compose up -d --build` in `Citadel/` |

## Requirements

- Docker with Compose v2.
- RAM for the models **per replica** (each replica loads its own copy), so `LAYA_REPLICAS` multiplies memory use.
- Network access on the first start to download the weights (see Offline).
- CPU only. The Dockerfile installs the CPU build of torch and fails the build if a CUDA or ROCm build is found.

## Settings

| Variable | Default | Effect |
|---|---|---|
| `LAYA_REPLICAS` | `1` | Number of `laya` containers. Read by Compose, not the service. |
| `LAYA_PORT` | `9120` | Host port `laya_lb` publishes. Inside the containers the service always listens on 9120. |
| `LAYA_TOKEN` | empty | When set, every call except `/health` must send it as `X-Internal-Token`. Callers set the same value (Garrison: `LAYA_TOKEN` in `apps/garrison/.env`). |
| `LAYA_WARM` | `1` | Load both models at start. Compose sets it; with `0` the first request pays the load time. |
| `LAYA_OFFLINE` | unset | `1` uses only already-downloaded weights. Neither compose file passes it: add it under `environment:` of `laya` to use it. |

Put the variables in a `.env` next to the compose file that runs the stack (this folder, or `Citadel/`).

## Standalone

Citadel's network must exist first if Garrison should reach the service, so start the Citadel stack once, or drop
`citadel` from `laya_lb`'s networks and the `citadel` network block in `docker-compose.yml` if you do not need Garrison.

```bash
docker compose up -d --build
```

Without Docker: `run.bat` (creates `.venv_laya` on first run, listens on `127.0.0.1:9120`).

## Inside the Citadel stack

The Citadel compose builds this folder through `build: ../LayaModel`, so `LayaModel/` must sit next to `Citadel/`
(`Python/LayaModel` and `Python/Citadel`). Services `laya` and `laya_lb` join the `core` network; Garrison reaches the
service at `http://laya_lb:9120` (its `LAYA_SERVICE_URL`, set by Compose).

```bash
cd ../Citadel
docker compose up -d --build laya laya_lb
```

The `laya_lb` published port is bound to `127.0.0.1` there, so only the host can call it.

## First start

1. The build installs torch and the service. The image has no weights.
2. Each replica downloads the weights into the `models` volume (`laya_models` in Citadel) the first time. Replicas
   share the volume, so later starts and extra replicas reuse the download.
3. `laya_lb` starts only after a replica passes its health check. The check allows 120 s (`start_period`) before
   failures count, so a slow first download can leave the stack `unhealthy`; run `docker compose ps` and wait, or
   raise `start_period`.

## Check it works

```bash
curl http://127.0.0.1:9120/health
```

Expect `{"status": "ok", "models": {...}}` with both models `true` once warmed. `/health` needs no token.

```bash
curl -X POST http://127.0.0.1:9120/v1/validate -H "Content-Type: application/json" -H "X-Internal-Token: <token>" -d "{\"questions\": []}"
```

A 422 means the service is up and checking requests (an empty question set is invalid). Omit the token header when
`LAYA_TOKEN` is empty.

## Scaling

```bash
LAYA_REPLICAS=3 docker compose up -d --build
docker compose restart laya_lb
```

The restart is required: nginx resolves the replica addresses once at start, so it does not see new or removed
replicas until it restarts. `least_conn` balances; a request that errors or times out on one replica is retried once
on another (safe because `/v1/ask` is a pure function of its body).

## Update

```bash
docker compose up -d --build
docker compose restart laya_lb
```

Rebuilding replaces the replicas, so restart `laya_lb` afterwards. The weights volume survives rebuilds.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `laya_lb` never starts | No replica is healthy yet (first download, or out of memory). Check `docker compose logs laya`. |
| Replicas restart in a loop | Out of RAM for the models. Lower `LAYA_REPLICAS`. |
| Garrison: "Laya is not configured: set LAYA_SERVICE_URL" | `LAYA_SERVICE_URL` is empty (running outside Compose and not set). |
| Garrison: "could not be reached" | Service not started, or not on Garrison's network (`core` / `citadel_core`). |
| 401 "Invalid token" from every call but `/health` | `LAYA_TOKEN` differs between the service and the caller. |
| `bind: address already in use` on 9120 | Standalone and Citadel stacks both running. Stop one. |
| nginx 502 after scaling | `laya_lb` not restarted after the replica count changed. |
| Offline start fails to load a model | `LAYA_OFFLINE=1` but the weights are not in the `models` volume yet. |
