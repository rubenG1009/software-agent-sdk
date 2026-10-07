# Deferred init (warm-pool dormant mode)

A warm-pool agent server can boot *dormant*: with `OH_DEFERRED_INIT` set, the
lifespan starts the stateless services (VS Code, tool preload, telemetry on the
base config) and marks `/ready` ready, but never enters the conversation, event
or bash services. Until `POST /api/init` delivers the per-user runtime config,
every `/api/*` route (except `/api/init`) answers 503, while `/alive`,
`/health` and `/ready` stay 200 so an orchestrator can place the pod. `GET
/api/init` reports the dormant/initializing/ready state without a key; `POST
/api/init` is gated by `X-Init-API-Key` (the dormant `secret_key`, open when
the pod has none) and, in one shot, applies env, rebuilds telemetry, enters a
conversation/registry/bash service built from the merged config, swaps them
onto `app.state`, recomputes the root path and the VS Code token, and emits
`server_started`. A failed init rolls back to dormant and records the error so
the orchestrator can retry; a second init is a 400; on a
non-deferred server both routes 404. The dormant gate is attached to the `/api`
router only, so the `/sockets/bash-events` WebSocket is **not** behind it — a
security hole this family reproduces.

Source: `openhands-agent-server/openhands/agent_server/init_router.py`, `openhands-agent-server/openhands/agent_server/api.py`, `openhands-agent-server/openhands/agent_server/config.py`, `openhands-agent-server/openhands/agent_server/sockets.py`, `openhands-agent-server/openhands/agent_server/dependencies.py`

Launch: `--no-auth --deferred-init`

Routes: `GET /api/init`, `POST /api/init`

## Sub-features

- `F03.dormant-boot`: a deferred server boots healthy, answers `/alive` and `/ready` 200, and reports `{"state":"dormant","error":null}` on `GET /api/init`.
- `F03.dormant-gates-api`: every `/api/*` route except `/api/init` returns 503 while dormant (reads, mutations and the separately mounted workspace file routes), with the 5xx-rewritten body (`detail` = `Internal Server Error`, `exception` carries the reason).
- `F03.init-key-auth`: `POST /api/init` requires `X-Init-API-Key` equal to the dormant `secret_key`; a missing or wrong key is 401, checked before the body is validated, and leaves the state dormant.
- `F03.init-validation`: an unknown field or an out-of-range value is a 422 (`extra_forbidden` / constraint) and the state stays dormant.
- `F03.init-redacts-secret-input`: a 422 whose echoed input carries a secret-bearing key (`Authorization` header) redacts it to `<redacted>` and the raw value appears nowhere in the response.
- `F03.init-redacts-mistyped-secret`: a 422 caused by a wrongly typed secret field (`session_api_keys` as a string, `secret_key` as a list) must not echo the secret value (reproduces a real leak; see Gotchas).
- `F03.dormant-ws-bash-bypass`: while dormant, the `/sockets/bash-events` WebSocket must not run commands — the dormant gate should cover it (reproduces a real bypass; see Gotchas).
- `F03.init-failure-rollback`: an init that fails mid-build returns 500, rolls the state back to `dormant` with the gate still closed, and records the error on `GET /api/init` so it can be retried.
- `F03.init-success`: a valid `POST /api/init` flips the server to `ready`, and new conversations are stored under the delivered `conversations_path`.
- `F03.init-enforces-session-keys`: after init, `/api/*` rejects a missing or wrong key with 401 and accepts the delivered session key with 200, on a pod that booted without keys.
- `F03.init-applies-env`: `env` entries delivered at init reach `os.environ` and therefore the bash subprocesses, and the delivered `bash_events_dir` receives the events.
- `F03.init-keys-gate-bash-socket`: after init, `/sockets/bash-events` closes with 4001 for a client without the delivered key and runs commands for one with it.
- `F03.init-web-url-root-path`: a delivered `web_url` with a path becomes the root path: prefixed URLs serve and the OpenAPI document advertises the prefix.
- `F03.init-second-call-400`: a second `POST /api/init` after `ready` is rejected with 400 and the state is unchanged.
- `F03.init-open-without-secret`: a pod booted with neither a secret key nor session keys accepts `POST /api/init` without `X-Init-API-Key`; afterwards the first delivered session key is the init key (a keyless retry is 401, a retry with it is 400).
- `F03.init-state-not-persisted`: the init state lives in memory only, so after a restart a deferred pod is dormant again (delivered keys gone) and must be re-initialized.
- `F03.auth-before-gate`: when the dormant config already has session keys, a missing key is 401 *before* the 503 dormant gate.
- `F03.not-deferred-404`: on a non-deferred server both `/api/init` routes return 404, and `POST` still authenticates the init key before the 404.

## How to get to it (agent POV)

- Config / launch: `OH_DEFERRED_INIT=1` (`Config.deferred_init`) puts the server
  in dormant mode; `control-agent-server launch --new --deferred-init` sets it.
  A warm-pool pod normally also boots without session keys (they arrive in the
  init body), which `--no-auth` models; `--no-secret-key` additionally drops
  `OH_SECRET_KEY` (the open-init case).
- REST: `GET /api/init` (unauthenticated status poll for orchestrators) and
  `POST /api/init` (authenticated with the `X-Init-API-Key` header, whose value
  is the dormant `secret_key` = `OH_SECRET_KEY`, else the first boot session
  key, else nothing and the route is open). The init body overrides a narrow
  set of `Config` fields: `session_api_keys`, `secret_key`,
  `conversations_path`, `bash_events_dir`, `conversation_worktree_root`,
  `webhooks`, `web_url`, `allow_cors_origins`, `max_concurrent_runs`, `env`,
  `telemetry`. The recipes deliver `session_api_keys`, `conversations_path`,
  `bash_events_dir`, `web_url` and `env`, and read each one back.
- REST (gated): every other `/api/*` route answers 503 while dormant; the recipe
  probes `/api/settings`, `/api/conversations/search`,
  `/api/bash/bash_events/search`, `POST /api/bash/execute_bash_command` and the
  workspace file route `/api/conversations/{id}/workspace` (mounted on its own
  router, 503 because no conversation service exists yet).
- WebSocket: `/sockets/bash-events` is mounted outside the `/api` dormant gate,
  so it is reachable while the pod is dormant; the recipes drive it to
  reproduce the bypass and, after init, to show the delivered keys gate it.
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
  creates the user workspace dirs the success bullet delivers. (`api --auth
  init` would send the same header, but it sends nothing on a `--no-auth` run;
  see Gotchas.)
  ```sh
  SK="$(cat "$AGENT_SERVER_VERIFY_RUN/private/secret_key")"
  test -n "$SK"
  mkdir -p "$AGENT_SERVER_VERIFY_RUN/fixtures/conv" "$AGENT_SERVER_VERIFY_RUN/fixtures/bash" "$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f03-workspace"
  ```
- Bullets run top to bottom on this one run. The dormant-state bullets come
  first; `F03.init-success` is the one-way transition to `ready`; the
  open-init bullet uses its own second server; the last three bullets each
  `restart` the run (resetting it to dormant, then adding a boot key, then
  turning deferred mode off) and say so.

- **Dormant boot (`F03.dormant-boot`).** A deferred pod is up, ready to place, and reports dormant.
  ```sh
  control-agent-server api GET /alive --auth none --expect 200 --check status eq ok
  control-agent-server api GET /ready --auth none --expect 200 --check status eq ready
  control-agent-server api GET /api/init --auth none --expect 200 \
    --check state eq dormant --check error missing --save F03.dormant-boot/status
  control-agent-server logs --grep 'Server started in deferred-init mode' --expect-min 1
  control-agent-server api GET /openapi.json --auth none --max-chars 200 --check servers missing
  ```
  `/ready` is 200 although the conversation service is not entered, `GET
  /api/init` is `{"state":"dormant","error":null}`, and the log carries
  `Server started in deferred-init mode; awaiting POST /api/init` (wrapped
  over two lines by the log formatter, hence the shorter pattern). The OpenAPI
  document has no `servers` yet (the before view for
  `F03.init-web-url-root-path`).
- **Dormant gate (`F03.dormant-gates-api`).** Every `/api/*` route but `/api/init` is 503 while dormant.
  ```sh
  control-agent-server api GET /api/settings --auth none --expect 503 \
    --check detail eq 'Internal Server Error' \
    --check exception contains "deferred-init state 'dormant'" --save F03.dormant-gates-api/settings
  control-agent-server api GET /api/conversations/search --auth none --expect 503 --check detail eq 'Internal Server Error'
  control-agent-server api GET /api/bash/bash_events/search --auth none --expect 503 --check exception contains 'call POST /api/init first'
  control-agent-server api POST /api/bash/execute_bash_command --auth none --json '{"command":"true"}' --expect 503 \
    --check exception contains 'call POST /api/init first'
  control-agent-server api GET /api/conversations/00000000-0000-0000-0000-0000000000f3/workspace --auth none --expect 503 \
    --check exception contains 'Conversation service is not available'
  ```
  All five answer 503. The real 503 detail is rewritten by the 5xx handler, so
  assert on the status and on `exception`, which still carries the reason. The
  workspace file route is mounted on its own `/api` router without the gate;
  it is 503 only because no conversation service exists before init.
- **Init key auth (`F03.init-key-auth`).** The bootstrap key is required, before the body is looked at; a bad one is 401 and the state is unchanged.
  ```sh
  control-agent-server api POST /api/init --auth none --json '{}' --expect 401 --save F03.init-key-auth/no-header
  control-agent-server api POST /api/init --auth none --header 'X-Init-API-Key: qa-wrong-key' --json '{}' --expect 401
  control-agent-server api POST /api/init --auth none --header 'X-Init-API-Key: qa-wrong-key' --json '{"bogus":1}' --expect 401
  control-agent-server api GET /api/init --auth none --check state eq dormant
  ```
  All three posts are 401; the third carries a body that the right key turns
  into a 422 (next bullet), so the key is checked first. `GET /api/init` is
  still dormant. The right key's 200 is `F03.init-success`.
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
  RAW_REDACTED="$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f03-422-redacted.json"
  control-agent-server api POST /api/init --auth none --header "X-Init-API-Key: $SK" \
    --json '{"webhooks":[{"headers":{"Authorization":"Bearer QA-SENTINEL-7788"}}]}' \
    --expect 422 --check 'detail.0.loc.3' eq base_url --check 'detail.0.input.headers.Authorization' eq '<redacted>' \
    --raw-out "$RAW_REDACTED" --save F03.init-redacts-secret-input/redacted
  test -s "$RAW_REDACTED"
  if grep -q 'QA-SENTINEL-7788' "$RAW_REDACTED"; then exit 1; fi
  control-agent-server api GET /api/init --auth none --check state eq dormant
  ```
  The webhook is missing its required `base_url`, so the 422 echoes the webhook
  object as `input`; the validation handler runs it through `sanitize_dict`, so
  the `Authorization` value comes back `<redacted>` and the sentinel is nowhere
  in the raw response bytes.
- **Mistyped secrets are echoed (`F03.init-redacts-mistyped-secret`), known bug.** A wrongly typed secret field comes back raw in the 422. The correct behavior asserted here is that neither sentinel appears in the response; today both do, so this is an expected failure.
  ```sh
  RAW_MISTYPED="$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f03-422-mistyped.json"
  control-agent-server api POST /api/init --auth none --header "X-Init-API-Key: $SK" \
    --json '{"session_api_keys":"QA-SENTINEL-SESS-4411","secret_key":["QA-SENTINEL-SECRET-4422"]}' \
    --expect 422 --check detail len-eq 2 --check 'detail.0.loc.1' eq session_api_keys --check 'detail.1.loc.1' eq secret_key \
    --raw-out "$RAW_MISTYPED" --save F03.init-redacts-mistyped-secret/echo
  test -s "$RAW_MISTYPED"
  if grep -q 'QA-SENTINEL-S' "$RAW_MISTYPED"; then exit 1; fi
  ```
  Both errors are about the secret fields, yet their `input` is the bare value
  (`"QA-SENTINEL-SESS-4411"`, `["QA-SENTINEL-SECRET-4422"]`): `sanitize_dict`
  redacts by dict key, and a wrongly typed value reaches it without its key,
  so the `grep` finds the sentinels.
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
  socket answers with `BashCommand` and `BashOutput` (`exit_code` 0) frames and
  writes the file, so `test ! -f` fails: the unauthenticated pre-init execution
  is the bug. `ws listen` succeeds whether the socket is refused, closed or
  open, so only the file decides; the same frame running after init
  (`F03.init-keys-gate-bash-socket`) is the positive control.
- **Failure rollback (`F03.init-failure-rollback`).** A failing init returns 500 and returns to dormant with the error recorded.
  ```sh
  control-agent-server api POST /api/init --auth none --header "X-Init-API-Key: $SK" \
    --json '{"conversations_path":"/proc/oh-cannot-create-f03"}' --expect 500 \
    --check exception contains oh-cannot-create-f03 --save F03.init-failure-rollback/failure
  control-agent-server api GET /api/init --auth none --check state eq dormant --check error contains oh-cannot-create-f03
  control-agent-server api GET /api/settings --auth none --expect 503
  ```
  The unwritable path makes the conversation service fail to enter; the handler
  rolls the state back to `dormant`, keeps the gate closed, and stores
  `<ExceptionType>: <message>` under `error` (on Linux
  `FileNotFoundError: [Errno 2] ... '/proc/oh-cannot-create-f03'`), so an
  orchestrator can retry. The successful retry is the next bullet.
- **Successful init (`F03.init-success`).** A valid body flips the pod to `ready`; conversations land in the delivered directory.
  ```sh
  BODY="$(python3 -c "import json,os;r=os.environ['AGENT_SERVER_VERIFY_RUN'];print(json.dumps({'session_api_keys':['qa-user-key'],'conversations_path':r+'/fixtures/conv','bash_events_dir':r+'/fixtures/bash','web_url':'http://qa-f03.invalid/rt/qa-f03','env':{'PROBE_VAR':'qa-hello'}}))")"
  control-agent-server api POST /api/init --auth none --header "X-Init-API-Key: $SK" \
    --json "$BODY" --expect 200 --check state eq ready --check error missing --save F03.init-success/post
  control-agent-server api GET /api/init --auth none --check state eq ready --check error missing --save F03.init-success/ready
  CONV_BODY="$(python3 -c "import json,os;print(json.dumps({'agent_settings':{'agent_kind':'openhands','llm':{'model':'openai/qa-placeholder','api_key':'qa-placeholder','base_url':'http://127.0.0.1:9/v1','num_retries':0},'tools':[]},'workspace':{'kind':'LocalWorkspace','working_dir':os.environ['AGENT_SERVER_VERIFY_RUN']+'/fixtures/qa-f03-workspace'},'autotitle':False}))")"
  F03_CID=$(control-agent-server api POST /api/conversations --auth none --header 'X-Session-API-Key: qa-user-key' --json "$CONV_BODY" --expect 2xx --field id)
  control-agent-server api GET "/api/conversations/$F03_CID" --auth none --header 'X-Session-API-Key: qa-user-key' --expect 200 --check id eq "$F03_CID"
  test -d "$AGENT_SERVER_VERIFY_RUN/fixtures/conv/$(echo "$F03_CID" | tr -d -)"
  ```
  The post returns `{"state":"ready","error":null}` and the status poll
  agrees. A conversation created with the delivered key (a placeholder model
  that is never called) is stored under the delivered `conversations_path`, as
  `<id without dashes>/`.
- **Delivered keys are enforced (`F03.init-enforces-session-keys`).** The pod booted without keys; init added them.
  ```sh
  control-agent-server api GET /api/settings --auth none --expect 401 --save F03.init-enforces-session-keys/no-key
  control-agent-server api GET /api/settings --auth none --header 'X-Session-API-Key: qa-wrong-key' --expect 401
  control-agent-server api GET /api/settings --auth none --header 'X-Session-API-Key: qa-user-key' --expect 200
  ```
  `/api/settings` without a key or with a wrong one is now 401 (it was 503
  while dormant and would have been open on this no-auth pod before init); the
  delivered `qa-user-key` is accepted.
- **Init env reaches bash (`F03.init-applies-env`).** `env` entries are set before the services boot, so subprocesses see them, and the delivered `bash_events_dir` is used.
  ```sh
  control-agent-server api POST /api/bash/execute_bash_command --auth none --header 'X-Session-API-Key: qa-user-key' \
    --json '{"command":"echo PROBE=$PROBE_VAR"}' --expect 200 --check stdout contains 'PROBE=qa-hello' --save F03.init-applies-env/env
  test -n "$(ls -A "$AGENT_SERVER_VERIFY_RUN/fixtures/bash")"
  ```
  The command prints `PROBE=qa-hello` (the init-delivered env), and the
  delivered bash-events directory now holds the command and output events.
- **Delivered keys gate the bash socket (`F03.init-keys-gate-bash-socket`).** After init the socket authenticates with the delivered keys.
  ```sh
  SOCK_PROBE="$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f03-ws-after-init.txt"
  rm -f "$SOCK_PROBE"
  control-agent-server ws listen /sockets/bash-events --auth none \
    --send "{\"command\": \"echo no-key > $SOCK_PROBE\"}" --duration 5 --expect-close 4001 --save F03.init-keys-gate-bash-socket/no-key
  test ! -f "$SOCK_PROBE"
  control-agent-server ws listen /sockets/bash-events --auth key --key qa-user-key \
    --send "{\"command\": \"echo with-key > $SOCK_PROBE\"}" --until-kind BashOutput --until exit_code=0 --duration 20 \
    --expect-kind BashCommand --save F03.init-keys-gate-bash-socket/with-key
  grep -qx with-key "$SOCK_PROBE"
  ```
  Without a key the command frame is taken as a failed first-frame auth and
  the socket closes with 4001 before anything runs; with `qa-user-key` the
  same kind of frame produces `BashCommand` and `BashOutput` (`exit_code` 0)
  and writes the file. This is also the positive control for
  `F03.dormant-ws-bash-bypass`: the frame and probe mechanism detect an
  execution.
- **Delivered web URL sets the root path (`F03.init-web-url-root-path`).** The init body carried `web_url` `http://qa-f03.invalid/rt/qa-f03`.
  ```sh
  PREFIX=/rt/qa-f03
  control-agent-server api GET "$PREFIX/alive" --auth none --expect 200 --check status eq ok --save F03.init-web-url-root-path/prefixed-alive
  control-agent-server api GET "$PREFIX/api/settings" --auth none --header 'X-Session-API-Key: qa-user-key' --expect 200
  OTHER_PREFIX=/rt/qa-other
  control-agent-server api GET "$OTHER_PREFIX/alive" --auth none --expect 404
  control-agent-server api GET /openapi.json --auth none --max-chars 200 --check servers.0.url eq /rt/qa-f03
  control-agent-server api GET /alive --auth none --expect 200
  ```
  Only the URL's path matters (the host is never contacted): `/rt/qa-f03/...`
  serves the app, another prefix is 404, unprefixed paths keep working, and
  the OpenAPI document now lists `servers: [{"url": "/rt/qa-f03"}]` (it had no
  `servers` while dormant). The prefixed paths go through `$PREFIX` because
  `map check` validates literal paths against the unprefixed route table.
- **Second init is 400 (`F03.init-second-call-400`).** Init is one-shot.
  ```sh
  control-agent-server api POST /api/init --auth none --header "X-Init-API-Key: $SK" \
    --json '{}' --expect 400 --check detail contains 'already in state: ready' --save F03.init-second-call-400/already-ready
  control-agent-server api GET /api/init --auth none --check state eq ready
  ```
  The second post is 400 and the state is unchanged (`secret_key` was not
  overridden, so `$SK` still authenticates).
- **Open init without a secret (`F03.init-open-without-secret`).** A second, keyless and secretless dormant server, stopped at the end of the bullet.
  ```sh
  OPEN=$(control-agent-server launch --new --no-auth --no-secret-key --deferred-init --name f03-open --print-run)
  trap 'control-agent-server stop --run "$OPEN" >/dev/null' EXIT
  control-agent-server api GET /api/init --run "$OPEN" --auth none --expect 200 --check state eq dormant
  control-agent-server api POST /api/init --run "$OPEN" --auth none --json '{"session_api_keys":["qa-open-key"]}' \
    --expect 200 --check state eq ready --save F03.init-open-without-secret/open
  control-agent-server api GET /api/settings --run "$OPEN" --auth none --expect 401
  control-agent-server api GET /api/settings --run "$OPEN" --auth none --header 'X-Session-API-Key: qa-open-key' --expect 200
  control-agent-server api POST /api/init --run "$OPEN" --auth none --json '{}' --expect 401
  control-agent-server api POST /api/init --run "$OPEN" --auth none --header 'X-Init-API-Key: qa-open-key' --json '{}' \
    --expect 400 --check detail contains 'already in state: ready' --save F03.init-open-without-secret/retry
  control-agent-server stop --run "$OPEN"
  ```
  With no `secret_key` (`check_init_api_key`: "No key configured → endpoint is
  open. Acceptable for dev."), the first post needs no header and applies the
  delivered key. Because the dormant config had no secret, the merged config's
  `secret_key` falls back to `qa-open-key`, so a keyless retry is now 401 and a
  retry with `qa-open-key` reaches the one-shot 400.
- **Init state is not persisted (`F03.init-state-not-persisted`).** This bullet restarts the run; a deferred pod comes back dormant.
  ```sh
  control-agent-server restart
  control-agent-server api GET /api/init --auth none --check state eq dormant --check error missing --save F03.init-state-not-persisted/after-restart
  control-agent-server api GET /api/settings --auth none --expect 503
  ```
  The transition lives only in memory, so a re-launched warm pod is dormant
  again and must be re-initialized; the keyless request is 503, not 401, so the
  delivered `qa-user-key` is gone too.
- **Auth precedes the gate (`F03.auth-before-gate`).** This bullet restarts the run with a boot session key, still deferred.
  ```sh
  control-agent-server restart --env OH_SESSION_API_KEYS_0=qa-boot-key
  control-agent-server api GET /api/settings --auth none --expect 401 --save F03.auth-before-gate/no-key
  control-agent-server api GET /api/settings --auth none --header 'X-Session-API-Key: qa-boot-key' --expect 503
  ```
  When the dormant config has session keys, `check_session_api_key` runs before
  `require_initialized`: a missing key is 401, and only a valid key reaches the
  503 dormant gate.
- **Not deferred is 404 (`F03.not-deferred-404`).** This bullet restarts the run with deferred mode off (the boot key from the previous bullet stays).
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
  exception handler; the reason survives only in `exception`. Key on the status
  code, not the `detail` text. The same handler puts the init failure's
  exception string (paths included) in the 500 body.
- The bootstrap `X-Init-API-Key` is the dormant `secret_key`, which defaults to
  the first session key when `OH_SECRET_KEY` is unset and is **open to anyone**
  when neither is set (`F03.init-open-without-secret`). `control-agent-server
  launch` sets `OH_SECRET_KEY` unless `--no-secret-key` is given, so the main
  run's `POST /api/init` is key-protected.
- Harness: `api --auth init` reads `<run>/private/secret_key`, but on a
  `--no-auth` run it sends no header at all (the auth helper returns early when
  the run has no session key), so these recipes pass `--header
  "X-Init-API-Key: $SK"` explicitly. `doctor`'s dormant detection reads a
  `status` field that `GET /api/init` does not have (`state`), so it treats a
  deferred run as dormant even after init.
- Init is one-shot and in-memory: it does not persist across a restart
  (`F03.init-state-not-persisted`), and a second call is 400 (`already in
  state: ready`; a call that lands while another is still building gets
  `already in state: initializing`, which init is too fast to show on demand). If
  the init body sets `secret_key`, or if the dormant config had none and
  session keys are delivered, the bootstrap key changes and a retry with the old
  key is 401 instead of 400.
- A failed init rolls back only the state: `env` entries it applied stay in
  `os.environ` (observed: a variable sent only in a failed attempt is visible
  to bash after the successful retry), and the bash service it entered before
  failing is not exited. `InitRequest.env` documents the `os.environ.update`,
  not a rollback; resend the full env on retry.
- `OH_DEFERRED_INIT` must be `1`/`true` (case-insensitive); `yes` parses as
  False.
- Security: `/sockets/bash-events` is mounted outside the `/api` dormant gate
  and, on a warm-pool pod with no boot session keys, accepts unauthenticated
  connections and executes bash before `/api/init`
  (`F03.dormant-ws-bash-bypass`), with the import-time bash service and the
  dormant `bash_events_dir`. The REST bash routes are correctly 503. With a
  boot session key the socket rejects a keyless client (4001) but still runs
  commands for a key holder while every `/api/*` route is 503 (observed live;
  not asserted). Real exposure needs the pod to be reachable: without a boot key
  and without `--host` the server binds `127.0.0.1`, and binding `0.0.0.0`
  logs an unauthenticated-bind warning. The WebSocket list is at
  `control-agent-server map routes --module sockets`; the conversation sockets
  close for unknown ids while dormant.
- The 422 sanitizer redacts by key (`Authorization`, `api_key`, ...), so a
  secret field sent with the wrong type is echoed raw
  (`F03.init-redacts-mistyped-secret`). Low severity: the caller gets back its
  own input, but orchestrators and proxies log error bodies, and
  `session_api_keys` as a bare string is an easy mistake. The sanitizer is
  shared by every route's 422.
- Known caveats this family does not assert: the settings/secrets store
  singletons capture the cipher at import from the dormant config, so an
  init-delivered `secret_key` does not reach them; `allow_cors_origins`
  delivered at init does not change the already-installed CORS middleware;
  `web_url` is applied unconditionally despite its "only when not already set"
  description; and init-delivered `telemetry` and the deferred
  `server_started` event belong to the telemetry family (F32).
