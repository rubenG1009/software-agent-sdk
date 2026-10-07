# Agent Server feature map

This directory is the maintained source for verifying the agent-facing
behavior of the OpenHands Agent Server: every REST route and WebSocket, and
the behaviors around them (persistence, webhooks, auth, consumers). Read this
index before driving the server, then use the matching family file as the
recipe.

Maintenance baseline: `8ba966d1d3af49f08e04349c055009e1614b48d6` (first pass, 2026-10-07).

The map has **8 sub-features**.

## Baseline preconditions

- `make build` (or `uv sync --dev`) has run in the repository root.
- `control-agent-server` is on `PATH`:
  `export PATH="$PWD/.agents/skills/verify-agent-server/scripts:$PATH"`.
- A run of this checkout is live and exported:
  `export AGENT_SERVER_VERIFY_RUN=$(control-agent-server launch --new --print-run)`.
- `control-agent-server doctor` reports `ok: true`.
- Model-backed recipes: `$DEEPSEEK_API_KEY` is set and
  `control-agent-server llm preset deepseek` has run (deepseek-flash active).
- Never drive a server that this verification run did not launch or attach.

## Driving conventions

- Start every family from the baseline unless its `Preconditions:` say
  otherwise; run its bullets top to bottom in one shell.
- Capture per-run values into shell variables (`--print-id`, `--field`,
  `--print-path`); never paste ids from an earlier run.
- Treat every command as literal. Keep quoted JSON and flags unchanged.
- Prefix fixtures and names with `qa-` or `QA_`; restore shared state (active
  profile, settings) after a mutation unless a later bullet needs it.
- Assert status codes, stored values, files, event kinds and tool
  observations, never the model's wording.

## Proof and skip reporting

- A mutation is proven by a read-only second view: a GET, a WebSocket frame,
  a file on disk, or a webhook delivery.
- Save the exchange that proves each sub-feature with `--save <ID>/<name>` and
  cite it in `evidence add`.
- Report an unreachable path with the attempted command and the unmet
  precondition (`blocked`), never as a pass through a different entry point.

## Family entry contract

Each family file starts with an H1 title, one paragraph describing the
agent-visible behavior, a `Source:` line and a `Routes:` line (see
[mapping.md](../mapping.md#3-write-each-entry)). It then uses exactly four H2
sections in this order: `Sub-features`, `How to get to it (agent POV)`,
`Driving it with control-agent-server` (starting with `Preconditions:`), and
`Gotchas`.

How to write and prove new entries: [../mapping.md](../mapping.md). How to keep
them honest: [../maintenance.md](../maintenance.md).

## Families

| ID | Family | What it covers | Entry points | Needs | Sub-features |
|---|---|---|---|---|---|
| F01 | [Server status, info and contract](F01-server-status.md) | liveness, health, readiness, server info and its `/` alias, uptime and idle time, OpenAPI document | `GET /alive`, `/health`, `/ready`, `/server_info`, `/`, `/openapi.json` | baseline | 8 |

## Not mapped

Routes deliberately left without an owner, with the reason:

- `GET /docs`, `GET /redoc`, `GET /docs/oauth2-redirect`: FastAPI's generated
  documentation pages, not part of the agent-facing contract (`/openapi.json`
  is mapped in F01).
