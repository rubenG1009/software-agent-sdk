# Server status, info and contract

Probes and metadata every consumer reads before anything else: liveness,
health and readiness for orchestrators, `/server_info` (and its `/` alias) for
versions, build identity, usable tools, capability flags and idle time, and the
OpenAPI document that clients generate types from. All of them answer without
a session key, even when authentication is on.

Source: `openhands-agent-server/openhands/agent_server/server_details_router.py`, `openhands-agent-server/openhands/agent_server/api.py`, `openhands-agent-server/openhands/agent_server/openapi.py`

Routes: `GET /alive`, `GET /health`, `GET /ready`, `GET /server_info`, `GET /`,
`GET /openapi.json`

## Sub-features

- `F01.alive`: `GET /alive` returns 200 `{"status": "ok"}` without a session key.
- `F01.health`: `GET /health` returns 200 `{"status": "ok"}` without a session key.
- `F01.ready`: `GET /ready` returns 200 `{"status": "ready"}` once startup finished, without a session key.
- `F01.server-info`: `GET /server_info` reports package versions, `build_git_sha` equal to the served checkout, usable tools and capability flags, without a session key.
- `F01.root-info`: `GET /` returns the same server info document as `/server_info`.
- `F01.uptime-restart`: `uptime` grows while the process lives and starts again from zero after a restart.
- `F01.idle-time`: `idle_time` grows while nothing happens and resets when a file operation runs.
- `F01.openapi`: `GET /openapi.json` serves the OpenAPI document with the conversation routes and without the WebSockets.

## How to get to it (agent POV)

- REST: `GET /alive`, `GET /health`, `GET /ready` (Kubernetes-style probes; the
  launcher and `doctor` use them), `GET /server_info` and `GET /`.
- REST: `GET /openapi.json`; `/docs` and `/redoc` render it for humans (not
  mapped).
- SDK: `RemoteWorkspace` health checks and the Docker/API workspaces poll
  `/alive` and `/ready` before using a server; Agent Canvas reads
  `/server_info` to gate features on `capabilities` and versions.
- TypeScript client: the generated schema in `clients/typescript/src/generated/`
  is built from the OpenAPI document of the pinned server release.

## Driving it with control-agent-server

Preconditions:

- A baseline run is live and exported (`launch --new`), `doctor` is ok. No
  LLM profile is needed.
- Commands run from the repository root, so `git rev-parse HEAD` names the
  served checkout.

- **Liveness (`F01.alive`).** Probe without a key.
  ```sh
  control-agent-server api GET /alive --auth none --expect 200 --check status eq ok --save F01.alive/alive
  ```
  The status is `200` and the body is `{"status": "ok"}` although no key was
  sent.
- **Health (`F01.health`).** Probe without a key.
  ```sh
  control-agent-server api GET /health --auth none --expect 200 --check status eq ok --save F01.health/health
  ```
  The status is `200` and the body is `{"status": "ok"}`.
- **Readiness (`F01.ready`).** Probe without a key after startup.
  ```sh
  control-agent-server api GET /ready --auth none --expect 200 --check status eq ready --save F01.ready/ready
  ```
  The body is `{"status": "ready"}`.
- **Server info (`F01.server-info`).** Read build identity and capabilities
  without a key.
  ```sh
  control-agent-server api GET /server_info --auth none --expect 200 \
    --check build_git_sha eq "$(git rev-parse HEAD)" \
    --check capabilities contains idempotent_conversation_create_v1 \
    --check capabilities contains tool_catalog_v1 \
    --check usable_tools contains terminal \
    --check conversation_runtime eq local \
    --check sdk_version exists --save F01.server-info/info
  ```
  Every check passes; the saved body also has `version`, `tools_version` and
  `workspace_version`.
- **Root alias (`F01.root-info`).** `/` serves the same document.
  ```sh
  VERSION=$(control-agent-server api GET /server_info --auth none --field version)
  control-agent-server api GET / --auth none --expect 200 --check version eq "$VERSION" \
    --check build_git_sha eq "$(git rev-parse HEAD)" --save F01.root-info/root
  ```
  Both checks pass.
- **Uptime across a restart (`F01.uptime-restart`).** The server's own clock
  is under test, so this bullet sleeps.
  ```sh
  sleep 3
  U1=$(control-agent-server api GET /server_info --auth none --field uptime)
  control-agent-server restart
  control-agent-server api GET /server_info --auth none --check uptime lt "$U1" --save F01.uptime-restart/after-restart
  control-agent-server doctor
  ```
  `U1` is at least `3.0`; after the restart `uptime` is smaller and `doctor`
  is ok again.
- **Idle time (`F01.idle-time`).** Status probes are not activity; a file
  operation is.
  ```sh
  sleep 3
  I1=$(control-agent-server api GET /server_info --auth none --field idle_time)
  control-agent-server api GET /server_info --auth none --check idle_time ge 3
  control-agent-server api POST /api/file/create_directory --query path=/tmp/qa-f01-idle --expect 200
  control-agent-server api GET /server_info --auth none --check idle_time lt "$I1" --save F01.idle-time/after-mkdir
  ```
  `idle_time` is at least `3.0` although probes ran in between, and drops
  after the directory is created.
- **OpenAPI document (`F01.openapi`).** The contract clients generate from.
  ```sh
  control-agent-server api GET /openapi.json --auth none --expect 200 --max-chars 200 \
    --check 'paths./api/conversations.post.operationId' matches start_conversation \
    --check 'paths./api/conversations/{conversation_id}/pause' exists \
    --check 'paths./sockets/events/{conversation_id}' missing --save F01.openapi/openapi
  ```
  All checks pass. WebSockets are not part of the OpenAPI document;
  `control-agent-server map routes --module sockets` lists them.

## Gotchas

- `/ready` returns 503 `{"status": "initializing"}` until startup finished (tool
  preload, VS Code); `launch` waits for it, so a 503 on a launched run means
  something is wrong. In deferred-init mode `/ready` stays 503 until
  `POST /api/init` (see the deferred init family).
- `idle_time` only resets on agent activity and on file uploads, downloads,
  directory creation and archives, not on every request; orchestrators use it
  to reap idle sandboxes.
- `build_git_sha` and `build_git_ref` come from `OPENHANDS_BUILD_GIT_SHA` and
  `OPENHANDS_BUILD_GIT_REF`; `launch` sets them from the checkout. A server
  started another way reports `unknown`, which is why `doctor` compares the
  SHA only for launched runs.
- `uptime` and `idle_time` are serialized as floats (`12.0`); compare them
  with `--check ... lt`, not with the shell's integer `test`.
- Dotted `--check` and `--field` paths may contain slashes and braces
  (`paths./api/conversations.post`), because only dots separate segments.
