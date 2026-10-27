# LayaModel

The one place Laya (the `laya` package, torch and the model weights) is installed. Projects send it
typed questions over HTTP instead of loading the models themselves.

## API

| Call | Purpose |
|---|---|
| `POST /v1/ask` | `{"strategy", "text", "questions", "max_len", "min_confidence", "thresholds", "prune_ratio", "pair_ratio", "trace"}` → `{"strategy", "answers", "uncertain", "calls"}`. Callers pick a strategy, never a model. |
| `GET /v1/strategies` | The strategy names and the default (`auto`). |
| `POST /v1/validate` | `{"questions"}` → `{"ok": true}`, or 422 with what is wrong. The one definition of a valid question set (types, `criteria` shapes, 2 to 10 options, 1 to 8 questions); `/v1/ask` applies it too. Callers check their questions here instead of keeping a copy of the rules. |
| `POST /v1/combine` | `{"voters", "options", "prune_ratio", "pair_ratio"}` → the voters over `options` (renormalised), their `average`, the `kept` options and, with two voters or more, the pairwise `final` comparison. For a caller that adds its own voter (Garrison's cloud fallback, Jev) to the local models. |
| `GET /health` | `{"status": "ok", "models": {name: loaded}}`. No token needed. |

When `LAYA_TOKEN` is set, send it as `X-Internal-Token`. Errors: 422 bad request or question, 413 text longer
than the window, 502 no model could answer, 500 anything else. A 413 or 502 body is
`{"detail": {"message", "calls"}}`, so the caller can still log the model calls that were made.

`calls` lists each model call of a request (`model`, `input_tokens`, `duration_ms`, `ok`) for usage logs.
`trace: true` adds `rounds`, and for a choice question the service could not settle it also returns `options` and
`voters` (each model's latest answer), which is what `/v1/combine` continues from.

### Strategies

| Strategy | What it does | Cost |
|---|---|---|
| `english-only` | Laya English alone. | 1 call |
| `typed-only` | Laya typed-decisions alone. | 1 call |
| `english-then-typed` | English; if unsure, typed; if still unsettled, drop clearly worse options and ask again (up to 3 rounds); last, compare both models' confidence-weighted values (`also_check` / `unknown`). Today's local flow without Jev. | 1-2+ calls |
| `typed-then-english` | The same, typed first. | 1-2+ calls |
| `most-confident` | Both answer; the more confident wins; disagreement is reported. | 2 calls |
| `average` | Both answer; probabilities (choice) or values (score, noul) are averaged. | 2 calls |
| `consensus` | Both answer; certain only when they agree and both meet their threshold, else `unknown` with `candidates`. | 2 calls |
| `auto` (default) | `english-then-typed`, except noul questions skip English (its yes/no label bug). | 1-2+ calls |

Thresholds (answer confidence at or above): 2 options English 0.90 / typed 0.80; 3+ options 0.75 / 0.55.
A request's `min_confidence` replaces all of them; `thresholds` (`{"2": {"laya-english": 0.9}, "3+": {...}}`)
replaces single ones. `prune_ratio` (0.25; 0 never drops options) and `pair_ratio` (0.5) tune the narrowing and the
pairwise comparison. Answers carry the pick, `answer_confidence`, `uncertain`,
`answered_by`; `trace: true` adds `rounds`. No strategy calls a cloud model.

## Run

Local: `run.bat` (port 9120). Docker, with a load balancer:

```bash
docker compose up -d --build
```

`laya` runs `LAYA_REPLICAS` copies (default 1) behind an nginx (`laya_lb`, `least_conn`, one retry on
error/timeout). Each replica keeps its own models in RAM; downloaded weights are shared in the `models`
volume. After changing the replica count, run `docker compose restart laya_lb`. Full guide (standalone vs the
Citadel stack, first start, scaling, troubleshooting): [deployment.md](deployment.md).

## Settings

`LAYA_HOST` (127.0.0.1), `LAYA_PORT` (9120), `LAYA_ADMIN_PASSWORD` (unlocks `/admin/`; falls back to `LAYA_TOKEN`), `LAYA_TOKEN`, `LAYA_WARM` (1 loads both models at start), `LAYA_TORCH_THREADS` (cap on torch CPU threads; `/health` reports the value in use),
`LAYA_OFFLINE` (1 uses only already downloaded weights).

## Consumers

Every project reaches the service the same way: `POST /v1/ask` with a strategy.

- **Garrison** (`apps/garrison/src/llm/laya_agent.py`, class `LAYAAgent`): set `LAYA_SERVICE_URL` and `LAYA_TOKEN`.
  Its triage flow asks for a strategy per question type and adds Jev for what the service could not settle,
  using `/v1/combine`, and checks questions with `/v1/validate`. Garrison loads no Laya model and keeps no copy of
  the question rules.
- **Armory** keeps its `LAYA_URL`: it asks Garrison's triage agent, which asks this service.
- Not yet moved: `ascension`, `chess`, `sortie` and `ClaudeRouters` still carry their own copy of Laya.

Not a git repository yet; run `git init` here before committing.
