# Deferred init (warm-pool dormant mode)

A warm-pool agent server can boot *dormant*: with `OH_DEFERRED_INIT` set, the
lifespan starts the stateless services (VS Code, tool preload, telemetry on the
base config) and marks `/ready` ready, but never enters the conversation, event
or bash services. Until `POST /api/init` delivers the per-user runtime config,
every `/api/*` route (except `/api/init`) answers 503, while `/alive`,
`/health` and `/ready` stay 200 so an orchestrator can place the pod. `GET
/api/init` reports the dormant/initializing/ready state without a key; `POST
/api/init` is gated by `X-Init-API-Key` (the dormant `secret_key`) and, in one
shot, applies env, rebuilds telemetry, enters a conversation/registry/bash
service built from the merged config, swaps them onto `app.state`, recomputes
the root path and the VS Code token, and emits `server_started`. A failed init
rolls back to dormant and records the error so the orchestrator can retry; a
second init after `ready` is a 400; on a non-deferred server both routes 404.
The dormant gate is attached to the `/api` router only, so the
`/sockets/bash-events` WebSocket is **not** behind it — a security hole this
family reproduces.

Source: `openhands-agent-server/openhands/agent_server/init_router.py`, `openhands-agent-server/openhands/agent_server/api.py`, `openhands-agent-server/openhands/agent_server/config.py`, `openhands-agent-server/openhands/agent_server/sockets.py`

Launch: `--no-auth --deferred-init`

Routes: `GET /api/init`, `POST /api/init`

## Sub-features

- `F03.dormant-boot`: a deferred server boots healthy, answers `/ready` 200, and reports `{"state":"dormant","error":null}` on `GET /api/init`.
- `F03.dormant-gates-api`: every `/api/*` route except `/api/init` returns 503 while dormant, with the 5xx-rewritten body (`detail` = `Internal Server Error`, `exception` carries the dormant message).
- `F03.init-key-auth`: `POST /api/init` requires `X-Init-API-Key` equal to the dormant `secret_key`; a missing or wrong key is 401 and leaves the state dormant.
- `F03.init-validation`: an unknown field or an out-of-range value is a 422 (`extra_forbidden` / constraint) and the state stays dormant.
- `F03.init-redacts-secret-input`: a 422 whose echoed input carries a secret-bearing key (`Authorization` header) redacts it to `<redacted>` and never returns the raw value.
- `F03.dormant-ws-bash-bypass`: while dormant, the `/sockets/bash-events` WebSocket must not run commands — the dormant gate should cover it (reproduces a real bypass; see Gotchas).
- `F03.init-failure-rollback`: an init that fails mid-build returns 500, rolls the state back to `dormant`, and records the error on `GET /api/init` so it can be retried.
- `F03.init-success`: a valid `POST /api/init` flips the server to `ready`, and a pod that booted without keys now enforces the session keys delivered in the body.
- `F03.init-enforces-session-keys`: after init, `/api/*` rejects a missing key with 401 and accepts the delivered session key with 200.
- `F03.init-applies-env`: `env` entries delivered at init reach `os.environ` and therefore the bash subprocesses, and the delivered `bash_events_dir` receives the events.
- `F03.init-second-call-400`: a second `POST /api/init` after `ready` is rejected with 400 and the state is unchanged.
- `F03.init-state-not-persisted`: the init state lives in memory only, so after a restart a deferred pod is dormant again and must be re-initialized.
- `F03.auth-before-gate`: when the dormant config already has session keys, a missing key is 401 *before* the 503 dormant gate.
- `F03.not-deferred-404`: on a non-deferred server both `/api/init` routes return 404, and `POST` still authenticates the init key before the 404.

## How to get to it (agent POV)

- Config / launch: `OH_DEFERRED_INIT=1` (`Config.deferred_init`) puts the server
  in dormant mode; `control-agent-server launch --new --deferred-init` sets it.
  A warm-pool pod normally also boots without session keys (they arrive in the
  init body), which `--no-auth` models.
- REST: `GET /api/init` (unauthenticated status poll for orchestrators) and
  `POST /api/init` (authenticated with the `X-Init-API-Key` header, whose value
  is the dormant `secret_key` = `OH_SECRET_KEY`). The init body overrides a
  narrow set of `Config` fields: `session_api_keys`, `secret_key`,
  `conversations_path`, `bash_events_dir`, `conversation_worktree_root`,
  `webhooks`, `web_url`, `allow_cors_origins`, `max_concurrent_runs`, `env`,
  `telemetry`.
- REST (gated): every other `/api/*` route answers 503 while dormant; the recipe
  probes `/api/settings`, `/api/conversations/search` and
  `/api/bash/bash_events/search`.
- WebSocket (bug surface): `/sockets/bash-events` is mounted outside the `/api`
  dormant gate, so it is reachable while the pod is dormant; the recipe drives it
  to reproduce the bypass.
- SDK / TypeScript client: no consumer method calls `/api/init`; only the
  generated TypeScript types describe it
  (`clients/typescript/src/generated/agent-server-schema.ts`). The caller is a
  warm-pool orchestrator.

## Driving it with control-agent-server

Preconditions:

- A fresh warm-pool run, launched dormant and without boot session keys, is
  live and exported: `control-agent-server launch --new --no-auth
  --deferred-init`. `doctor` is ok (a deferred run's `doctor` uses `/alive`,
  since `/ready` is 200 even while dormant). No LLM profile is needed.
- The following `sh` block runs first: it reads the run's dormant
  `secret_key` (the bootstrap `X-Init-API-Key`, never printed) into `$SK` and
  creates the user workspace dirs the success bullet delivers.
  ```sh
  SK="$(cat "$AGENT_SERVER_VERIFY_RUN/private/secret_key")"
  test -n "$SK"
  mkdir -p "$AGENT_SERVER_VERIFY_RUN/fixtures/conv" "$AGENT_SERVER_VERIFY_RUN/fixtures/bash"
  ```
- Bullets run top to bottom on this one run. The dormant-state bullets come
  first; `F03.init-success` is the one-way transition to `ready`; the last
  three bullets each `restart` the run (resetting it to dormant, then adding a
  boot key, then turning deferred mode off) and say so.

- **Dormant boot (`F03.dormant-boot`).** A deferred pod is up, ready to place, and reports dormant.
  ```sh
  control-agent-server api GET /ready --auth none --expect 200 --check status eq ready
  control-agent-server api GET /api/init --auth none --expect 200 \
    --check state eq dormant --check error missing --save F03.dormant-boot/status
  control-agent-server logs --grep 'deferred-init mode' | grep -q 'deferred-init mode'
  ```
  `/ready` is 200 although the conversation service is not entered, `GET
  /api/init` is `{"state":"dormant","error":null}`, and the log carries
  `Server started in deferred-init mode; awaiting POST /api/init`.
- **Dormant gate (`F03.dormant-gates-api`).** Every `/api/*` route but `/api/init` is 503 while dormant.
  ```sh
  control-agent-server api GET /api/settings --auth none --expect 503 \
    --check detail eq 'Internal Server Error' \
    --check exception contains "deferred-init state 'dormant'" --save F03.dormant-gates-api/settings
  control-agent-server api GET /api/conversations/search --auth none --expect 503 --check detail eq 'Internal Server Error'
  control-agent-server api GET /api/bash/bash_events/search --auth none --expect 503 --check exception contains 'call POST /api/init first'
  ```
  All three answer 503. The real 503 detail is rewritten by the 5xx handler, so
  assert on the status and on `exception`, which still carries the dormant
  message.
- **Init key auth (`F03.init-key-auth`).** The bootstrap key is required; a bad one is 401 and the state is unchanged.
  ```sh
  control-agent-server api POST /api/init --auth none --json '{}' --expect 401 --save F03.init-key-auth/no-header
  control-agent-server api POST /api/init --auth none --header 'X-Init-API-Key: qa-wrong-key' --json '{}' --expect 401
  control-agent-server api GET /api/init --auth none --check state eq dormant
  ```
  Both posts are 401 (the key is checked before the body and before any 404),
  and `GET /api/init` is still dormant.
- **Init validation (`F03.init-validation`).** Unknown fields and out-of-range values are 422; the state stays dormant.
  ```sh
  control-agent-server api POST /api/init --auth none --header "X-Init-API-Key: $SK" \
    --json '{"bogus":1}' --expect 422 --check 'detail.0.type' eq extra_forbidden --save F03.init-validation/unknown-field
  control-agent-server api POST /api/init --auth none --header "X-Init-API-Key: $SK" \
    --json '{"max_concurrent_runs":0}' --expect 422 --check 'detail.0.type' eq greater_than_equal
  control-agent-server api GET /api/init --auth none --check state eq dormant
  ```
  `InitRequest` is `extra="forbid"`, so `bogus` is `extra_forbidden`;
  `max_concurrent_runs` has `ge=1`, so `0` fails the bound. Neither touches the
  state.
- **Input redaction (`F03.init-redacts-secret-input`).** A 422 echo redacts secret-bearing keys.
  ```sh
  control-agent-server api POST /api/init --auth none --header "X-Init-API-Key: $SK" \
    --json '{"webhooks":[{"headers":{"Authorization":"Bearer QA-SENTINEL-7788"}}]}' \
    --expect 422 --check 'detail.0.input.headers.Authorization' eq '<redacted>' \
    --check 'detail.0.input.headers.Authorization' ne 'Bearer QA-SENTINEL-7788' --save F03.init-redacts-secret-input/redacted
  control-agent-server api GET /api/init --auth none --check state eq dormant
  ```
  The webhook is missing its required `base_url`, so the 422 echoes the webhook
  object as `input`; the validation handler runs it through `sanitize_dict`, so
  the `Authorization` value comes back `<redacted>` and the sentinel never
  appears.
- **Dormant gate bypass on the bash WebSocket (`F03.dormant-ws-bash-bypass`), known bug.** While dormant, `/api/bash/*` is 503, but `/sockets/bash-events` accepts an unauthenticated connection and runs the command anyway. The correct behavior asserted here is that the command never executes; it currently does, so this is an expected failure until the socket is brought behind the dormant gate.
  ```sh
  control-agent-server api GET /api/init --auth none --check state eq dormant
  control-agent-server api POST /api/bash/execute_bash_command --auth none --json '{"command":"true"}' --expect 503
  PROBE="$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f03-ws-bypass.txt"
  rm -f "$PROBE"
  control-agent-server ws listen /sockets/bash-events --auth none \
    --send "{\"command\": \"echo bypassed-while-dormant > $PROBE\"}" --duration 5 --save F03.dormant-ws-bash-bypass/bypass
  test ! -f "$PROBE"
  ```
  `GET /api/init` is still dormant and the REST bash route is 503, yet the
  socket runs the command and writes the file, so `test ! -f` fails: the
  unauthenticated pre-init execution is the bug.
- **Failure rollback (`F03.init-failure-rollback`).** A failing init returns 500 and returns to dormant with the error recorded.
  ```sh
  control-agent-server api POST /api/init --auth none --header "X-Init-API-Key: $SK" \
    --json '{"conversations_path":"/proc/oh-cannot-create-f03"}' --expect 500 --save F03.init-failure-rollback/failure
  control-agent-server api GET /api/init --auth none --check state eq dormant --check error contains FileNotFoundError
  ```
  The unwritable path makes the conversation service fail to enter; the handler
  rolls the state back to `dormant` and stores the exception string under
  `error`, so an orchestrator can retry. (The successful retry is the next
  bullet.)
- **Successful init (`F03.init-success`).** A valid body flips the pod to `ready`.
  ```sh
  BODY="$(python3 -c "import json,os;r=os.environ['AGENT_SERVER_VERIFY_RUN'];print(json.dumps({'session_api_keys':['qa-user-key'],'conversations_path':r+'/fixtures/conv','bash_events_dir':r+'/fixtures/bash','env':{'PROBE_VAR':'qa-hello'}}))")"
  control-agent-server api POST /api/init --auth none --header "X-Init-API-Key: $SK" \
    --json "$BODY" --expect 200 --check state eq ready --save F03.init-success/ready
  control-agent-server api GET /api/init --auth none --check state eq ready
  ```
  The post returns `{"state":"ready","error":null}` and the status poll agrees.
- **Delivered keys are enforced (`F03.init-enforces-session-keys`).** The pod booted without keys; init added them.
  ```sh
  control-agent-server api GET /api/settings --auth none --expect 401 --save F03.init-enforces-session-keys/no-key
  control-agent-server api GET /api/settings --auth none --header 'X-Session-API-Key: qa-user-key' --expect 200
  ```
  `/api/settings` without a key is now 401 (it was 503 while dormant and would
  have been open on this no-auth pod before init); the delivered `qa-user-key`
  is accepted.
- **Init env reaches bash (`F03.init-applies-env`).** `env` entries are set before the services boot, so subprocesses see them, and the delivered `bash_events_dir` is used.
  ```sh
  control-agent-server api POST /api/bash/execute_bash_command --auth none --header 'X-Session-API-Key: qa-user-key' \
    --json '{"command":"echo PROBE=$PROBE_VAR"}' --expect 200 --check stdout contains 'PROBE=qa-hello' --save F03.init-applies-env/env
  test -n "$(ls -A "$AGENT_SERVER_VERIFY_RUN/fixtures/bash")"
  ```
  The command prints `PROBE=qa-hello` (the init-delivered env), and the
  delivered bash-events directory now holds the command and output events.
- **Second init is 400 (`F03.init-second-call-400`).** Init is one-shot.
  ```sh
  control-agent-server api POST /api/init --auth none --header "X-Init-API-Key: $SK" \
    --json '{}' --expect 400 --check detail contains 'already in state: ready' --save F03.init-second-call-400/already-ready
  control-agent-server api GET /api/init --auth none --check state eq ready
  ```
  The second post is 400 and the state is unchanged (`secret_key` was not
  overridden, so `$SK` still authenticates).
- **Init state is not persisted (`F03.init-state-not-persisted`).** This bullet restarts the run; a deferred pod comes back dormant.
  ```sh
  control-agent-server restart
  control-agent-server api GET /api/init --auth none --check state eq dormant --check error missing --save F03.init-state-not-persisted/after-restart
  control-agent-server api GET /api/settings --auth none --expect 503
  ```
  The transition lives only in memory, so a re-launched warm pod is dormant
  again and must be re-initialized.
- **Auth precedes the gate (`F03.auth-before-gate`).** This bullet restarts the run with a boot session key, still deferred.
  ```sh
  control-agent-server restart --env OH_SESSION_API_KEYS_0=qa-boot-key
  control-agent-server api GET /api/settings --auth none --expect 401 --save F03.auth-before-gate/no-key
  control-agent-server api GET /api/settings --auth none --header 'X-Session-API-Key: qa-boot-key' --expect 503
  ```
  When the dormant config has session keys, `check_session_api_key` runs before
  `require_initialized`: a missing key is 401, and only a valid key reaches the
  503 dormant gate.
- **Not deferred is 404 (`F03.not-deferred-404`).** This bullet restarts the run with deferred mode off.
  ```sh
  control-agent-server restart --config-json '{"deferred_init": false}'
  control-agent-server api GET /api/init --auth none --expect 404 --check detail contains 'deferred_init=True' --save F03.not-deferred-404/get
  control-agent-server api POST /api/init --auth none --json '{}' --expect 401
  control-agent-server api POST /api/init --auth none --header "X-Init-API-Key: $SK" --json '{}' --expect 404
  control-agent-server api GET /api/settings --auth none --header 'X-Session-API-Key: qa-boot-key' --expect 200
  ```
  With no `InitService` on `app.state`, `GET /api/init` is 404; `POST` still
  checks the init key first (401 without it, 404 with it), and the rest of the
  API serves normally.

## Gotchas

- `/ready` is 200 while dormant (the pod is placeable), so a readiness probe is
  not an init check — poll `GET /api/init` for the real state. `doctor` on a
  deferred run uses `/alive` for the same reason.
- The dormant 503's `detail` is rewritten to `Internal Server Error` by the 5xx
  exception handler; the dormant message survives only in `exception`. Key on
  the status code, not the `detail` text.
- The bootstrap `X-Init-API-Key` is the dormant `secret_key`, which defaults to
  the first session key when `OH_SECRET_KEY` is unset and is **open to anyone**
  when neither is set. `control-agent-server launch` always sets `OH_SECRET_KEY`
  (even under `--no-auth`), so this run's `POST /api/init` is always
  key-protected; the open case needs a pod booted with no secret and no keys.
- Init is one-shot and in-memory: it does not persist across a restart
  (`F03.init-state-not-persisted`), and a second call after `ready` is 400. If
  the init body sets `secret_key`, or if the dormant config had none and
  session keys are delivered, the bootstrap key changes and a retry with the old
  key is 401 instead of 400.
- `OH_DEFERRED_INIT` must be `1`/`true` (case-insensitive); `yes` parses as
  False.
- Security: `/sockets/bash-events` is mounted outside the `/api` dormant gate
  and, on a warm-pool pod with no boot session keys, accepts unauthenticated
  connections and executes bash before `/api/init`
  (`F03.dormant-ws-bash-bypass`). The REST bash routes are correctly 503. The
  WebSocket list is at `control-agent-server map routes --module sockets`.
- Known caveats this family does not assert (separate from the bypass): the
  settings/secrets store singletons capture the cipher at import from the
  dormant config, so an init-delivered `secret_key` does not reach them;
  `allow_cors_origins` delivered at init does not change the already-installed
  CORS middleware; and `web_url` is applied unconditionally despite its
  "only when not already set" description.
