# Run, pause, interrupt and status transitions

How an agent or its host drives the agent loop of an existing conversation:
start it on pending input (`/run`, which returns at once and runs in the
background), stop it at the next step boundary (`/pause`) or cancel the
in-flight model call (`/interrupt`), and follow `execution_status` through
`idle`, `running`, `paused`, `finished` and `error` on the conversation, the
status filters and the events socket. It also covers what a consumer sees at
the edges: a second run while one is active (409), the server's run capacity
(429), unknown ids, and conversations that were running when the server
stopped gracefully or was killed.

Source: `openhands-agent-server/openhands/agent_server/conversation_router.py`, `openhands-agent-server/openhands/agent_server/conversation_service.py`, `openhands-agent-server/openhands/agent_server/event_service.py`, `openhands-agent-server/openhands/agent_server/api.py`, `openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py`, `openhands-sdk/openhands/sdk/conversation/state.py`

Needs: `llm`

Launch: `--config-json '{"max_concurrent_runs": 1}'`

Routes: `POST /api/conversations/{conversation_id}/run`,
`POST /api/conversations/{conversation_id}/pause`,
`POST /api/conversations/{conversation_id}/interrupt`

## Sub-features

- `F05.run-queued`: a message appended with `run: false` leaves the conversation `idle`; `POST /run` returns 200 at once and the agent runs on DeepSeek flash through `running` to `finished`, both transitions pushed on the events socket.
- `F05.run-finished-noop`: `POST /run` on a `finished` conversation without new input returns 200, stays `finished` and adds no events (no model call).
- `F05.run-new-input`: a new user message moves a `finished` conversation back to `idle`, and `POST /run` runs it to `finished` again.
- `F05.pause-idle`: pausing an idle conversation returns 200, reports `paused` on GET, the status search and count and the events socket, and persists one `PauseEvent`.
- `F05.pause-repeat`: pausing a `paused` conversation again returns 200 and adds no second `PauseEvent`.
- `F05.run-resume-paused`: `POST /run` resumes a `paused` conversation through `running` to `finished`.
- `F05.interrupt-idle`: interrupt with nothing running falls back to pause: `paused`, one `PauseEvent`, no `InterruptEvent`.
- `F05.run-error`: a run whose model provider is unreachable ends in `error` with a `ConversationErrorEvent` and is listed by `status=error`.
- `F05.pause-terminal`: pause and interrupt on a `finished` or `error` conversation return 200 and change neither the status nor the event log.
- `F05.run-error-responsive`: a run that fails does not stall the server: other requests keep answering while the error is handled.
- `F05.unknown-id-run`: `POST /run` on an unknown id returns 404.
- `F05.unknown-id-pause`: `POST /pause` and `POST /interrupt` on an unknown id return the documented 404.
- `F05.control-errors`: all three routes answer 401 without or with a wrong session key and 422 for a malformed id, and the conversation is untouched.
- `F05.run-conflict`: `POST /run` while a run is active returns 409 `Conversation already running...`, and the active run keeps going without a second model call.
- `F05.pause-running`: pause during a long model call returns 200 at once; the events socket, status search and event log say `paused`, and `/run` stays 409 while the step is still in flight.
- `F05.pause-running-get`: after a pause during a long model call, `GET /api/conversations/{id}` and `base_state.json` report `paused` like every other view.
- `F05.pause-running-release`: interrupting a paused conversation whose step is still in flight cancels it (`InterruptEvent`), GET catches up to `paused`, and the run slot is free again.
- `F05.interrupt-running`: interrupt cancels a hanging model call within 5 s: 200, `paused`, an `InterruptEvent` and no `PauseEvent`, pushed on the events socket.
- `F05.run-after-interrupt`: after an interrupt, `POST /run` is accepted at once and the resumed run reaches `finished`.
- `F05.run-capacity`: with `max_concurrent_runs` 1, `POST /run` on a second conversation returns 429 while the first holds the slot, leaves it `idle`, and succeeds once the first is interrupted.
- `F05.restart-running-graceful`: a conversation running at a graceful restart comes back `paused`, with a `PauseEvent` and an `InterruptEvent`.
- `F05.restart-keeps-status`: `finished`, `paused` and `error` statuses survive a restart unchanged.
- `F05.restart-hard-running`: a conversation running when the server is SIGKILLed comes back `error` on the next start, and `/run` resumes it.

## How to get to it (agent POV)

- REST: `POST /api/conversations/{conversation_id}/run` (no body). Returns
  200 `{"success": true}` as soon as the background run is scheduled; 404 for
  an unknown id (or one whose lease another live instance holds); 409
  `Conversation already running. Wait for completion or pause first.`; 429
  `Conversation run limit reached. Retry the request later.`; 409
  `{"detail": "credential_binding_activation_required", "retryable": true}`
  when a required credential binding is missing (credential family); 400 while
  the server shuts down. `/run` also resumes `paused`, `error` and `stuck`
  conversations and approves actions waiting for confirmation.
- REST: `POST /api/conversations/{conversation_id}/pause` and
  `POST /api/conversations/{conversation_id}/interrupt` (no body), 200
  `{"success": true}`. Pause flips `idle` or `running` to `paused` and appends
  a `PauseEvent`; the current step finishes first. Interrupt cancels the
  in-flight async run (`InterruptEvent`, synthetic error observations for
  unfinished actions) and falls back to pause when nothing runs.
- Second views (owned by other families, used here as proof):
  `GET /api/conversations/{conversation_id}` (`execution_status`),
  `GET /api/conversations/search` and `/count` with `status`,
  `GET /api/conversations/{conversation_id}/events/count` with a
  fully-qualified `kind`, `agent_final_response`, and the events socket
  `/sockets/events/{conversation_id}`: `ConversationStateUpdateEvent` frames
  with `key` `execution_status` (plus a `full_state` snapshot on connect and
  after each run), `PauseEvent`, `InterruptEvent`, `ConversationErrorEvent`.
- Other ways to start a run (other families): `initial_message` on create and
  `POST /api/conversations/{conversation_id}/events` with `"run": true`.
- SDK: `RemoteConversation.run(blocking=True, poll_interval, timeout)` posts
  `/run` (a 409 is logged and treated as "already running") and polls until the
  run ends; `RemoteConversation.pause()` and `interrupt()` post the other two
  routes (`openhands-sdk/openhands/sdk/conversation/impl/remote_conversation.py`).
  `LocalConversation.run()/arun()/pause()/interrupt()` implement the
  transitions in-process.
- TypeScript client: `ConversationClient.runConversation`,
  `pauseConversation`, `interruptConversation`
  (`clients/typescript/src/client/conversation-client.ts`) and
  `RemoteConversation.run()` / `pause()`
  (`clients/typescript/src/conversation/remote-conversation.ts`).
- Config: `max_concurrent_runs` (`OH_MAX_CONCURRENT_RUNS`, default 10) caps
  concurrent runs and conversation creation; set with `launch --config-json`.
- Recipes below use REST through `api`, the events socket through `ws start`
  (opened before the action), real DeepSeek flash runs for every happy path,
  `fixture llm-stub` for a model call that hangs (the only way to hold a run
  in `running` on demand) and an unreachable `base_url` for a provider error.

## Driving it with control-agent-server

Preconditions:

- A run launched with this family's `Launch:` flags
  (`launch --new --config-json '{"max_concurrent_runs": 1}'`), `doctor` ok,
  and `$DEEPSEEK_API_KEY` set; the block below saves the DeepSeek profiles.
  With one run slot, every bullet that starts a run must find the slot free,
  so the bullets run strictly in order and each one that holds the slot
  releases it (interrupt) before it ends. `F05.run-capacity` depends on the
  limit of 1.
- No `tmux` or browser: every agent has `tools: []`, which keeps only the
  built-in `finish` and `think` tools.
- The block below creates, in order: an unknown id `$NOPE`, the
  fully-qualified event kinds that `events/count` filters on, an inline agent
  whose provider is unreachable (`$OFFLINE_AGENT`, `127.0.0.1:9`), an
  `llm-stub` that hangs every call for 300 s (`$HANG_AGENT`), a second hanging
  stub that `F05.run-after-interrupt` later rewrites to call `finish`
  (`$RESUME_AGENT`), and all nine conversations, without an initial message
  (an initial message always starts a run, and creating a conversation needs a
  free run slot): `A`, `B`, `C`, `Q` on DeepSeek flash, `E` offline, `P`, `G`,
  `K` on the hanging stub, `R` on the resumable stub. All start `idle`.

```sh
control-agent-server llm preset deepseek
NOPE=$(python3 -c 'import uuid; print(uuid.uuid4())')
PAUSE_KIND=openhands.sdk.event.user_action.PauseEvent
INTERRUPT_KIND=openhands.sdk.event.user_action.InterruptEvent
ERROR_KIND=openhands.sdk.event.conversation_error.ConversationErrorEvent
ACTION_KIND=openhands.sdk.event.llm_convertible.action.ActionEvent
OFFLINE_AGENT='{"llm": {"model": "openai/qa-offline", "api_key": "qa-offline-key", "base_url": "http://127.0.0.1:9/v1", "num_retries": 0}, "tools": []}'
HANG=$(control-agent-server fixture llm-stub --name qa-f05-hang --step hang:300 --print-path)
HANG_AGENT="{\"llm\": {\"model\": \"openai/qa-stub\", \"api_key\": \"qa-stub-key\", \"base_url\": \"$HANG/v1\", \"num_retries\": 0}, \"tools\": []}"
RESUME=$(control-agent-server fixture llm-stub --name qa-f05-resume --step hang:300 --print-path)
RESUME_AGENT="{\"llm\": {\"model\": \"openai/qa-stub\", \"api_key\": \"qa-stub-key\", \"base_url\": \"$RESUME/v1\", \"num_retries\": 0}, \"tools\": []}"
A=$(control-agent-server conversation start --tools none --no-autotitle --print-id)
B=$(control-agent-server conversation start --tools none --no-autotitle --print-id)
C=$(control-agent-server conversation start --tools none --no-autotitle --print-id)
Q=$(control-agent-server conversation start --tools none --no-autotitle --print-id)
E=$(control-agent-server conversation start --body-json "{\"agent\": $OFFLINE_AGENT}" --no-autotitle --print-id)
P=$(control-agent-server conversation start --body-json "{\"agent\": $HANG_AGENT}" --no-autotitle --print-id)
G=$(control-agent-server conversation start --body-json "{\"agent\": $HANG_AGENT}" --no-autotitle --print-id)
K=$(control-agent-server conversation start --body-json "{\"agent\": $HANG_AGENT}" --no-autotitle --print-id)
R=$(control-agent-server conversation start --body-json "{\"agent\": $RESUME_AGENT}" --no-autotitle --print-id)
control-agent-server api GET /api/conversations/count --query status=idle --check . eq 9
```

- **Run queued input on a real model (`F05.run-queued`).** Append a message
  without running, then start the loop with `/run` while the events socket
  listens.
  ```sh
  control-agent-server conversation send "$A" --text 'Reply with the single word ok, then finish.' --no-run
  control-agent-server api GET "/api/conversations/$A" --check execution_status eq idle
  control-agent-server ws start "/sockets/events/$A" --name f05-a-run --duration 300
  control-agent-server api POST "/api/conversations/$A/run" --expect 200 --check success eq true --save F05.run-queued/run
  control-agent-server conversation wait "$A" --until finished --timeout 180
  control-agent-server api GET "/api/conversations/$A" --check execution_status eq finished --save F05.run-queued/after
  control-agent-server api GET "/api/conversations/$A/events/count" --query kind=$ACTION_KIND --check . ge 1
  control-agent-server ws stop f05-a-run --contains '"key": "execution_status", "value": "running"' --save F05.run-queued/frames
  control-agent-server ws read f05-a-run --contains '"key": "execution_status", "value": "finished"'
  ```
  The status stays `idle` after the append, `/run` answers 200
  `{"success": true}` within milliseconds, the wait reports the transitions
  `running`, `finished`, the agent emitted at least one action (its `finish`
  call), and the socket pushed `execution_status` `running` and then
  `finished`.
- **Run with nothing to do (`F05.run-finished-noop`).** The proof is an
  absence, so the bullet gives the background run a fixed 3 s window.
  ```sh
  N=$(control-agent-server api GET "/api/conversations/$A/events/count" --field .)
  control-agent-server api POST "/api/conversations/$A/run" --expect 200 --check success eq true --save F05.run-finished-noop/run
  sleep 3
  control-agent-server api GET "/api/conversations/$A/events/count" --check . eq "$N" --save F05.run-finished-noop/count
  control-agent-server api GET "/api/conversations/$A" --check execution_status eq finished
  ```
  `/run` returns 200, the event count is unchanged and the status is still
  `finished`: a finished conversation without new input exits the loop before
  calling the model.
- **New input after finishing (`F05.run-new-input`).** A user message resets
  `finished` to `idle`; `/run` picks it up.
  ```sh
  control-agent-server conversation send "$A" --text 'Reply with the single word again, then finish.' --no-run
  control-agent-server api GET "/api/conversations/$A" --check execution_status eq idle --save F05.run-new-input/idle
  control-agent-server api POST "/api/conversations/$A/run" --expect 200 --check success eq true
  control-agent-server conversation wait "$A" --until finished --timeout 180
  control-agent-server api GET "/api/conversations/$A/events/count" --query kind=$ACTION_KIND --check . ge 2 --save F05.run-new-input/actions
  ```
  The status reads `idle` after the append and `finished` after the second
  run, which added at least one more action.
- **Pause an idle conversation (`F05.pause-idle`).** `B` has pending input and
  has never run.
  ```sh
  control-agent-server conversation send "$B" --text 'Reply with the single word ok, then finish.' --no-run
  control-agent-server ws start "/sockets/events/$B" --name f05-b-pause --duration 300
  control-agent-server api POST "/api/conversations/$B/pause" --expect 200 --check success eq true --save F05.pause-idle/pause
  control-agent-server api GET "/api/conversations/$B" --check execution_status eq paused --save F05.pause-idle/get
  control-agent-server api GET "/api/conversations/$B/events/count" --query kind=$PAUSE_KIND --check . eq 1
  control-agent-server api GET /api/conversations/search --query status=paused --check items contains "$B"
  control-agent-server api GET /api/conversations/count --query status=paused --check . eq 1
  control-agent-server ws stop f05-b-pause --contains '"key": "execution_status", "value": "paused"' --save F05.pause-idle/frames
  control-agent-server ws read f05-b-pause --expect-kind PauseEvent
  ```
  Every view agrees on `paused`: GET, `search`/`count` with `status=paused`,
  one persisted `PauseEvent`, and the socket's `execution_status` frame and
  `PauseEvent` frame.
- **Pause twice (`F05.pause-repeat`).**
  ```sh
  control-agent-server api POST "/api/conversations/$B/pause" --expect 200 --check success eq true --save F05.pause-repeat/pause
  control-agent-server api GET "/api/conversations/$B/events/count" --query kind=$PAUSE_KIND --check . eq 1
  control-agent-server api GET "/api/conversations/$B" --check execution_status eq paused
  ```
  The second pause is accepted and changes nothing: still one `PauseEvent`.
- **Resume a paused conversation (`F05.run-resume-paused`).**
  ```sh
  control-agent-server ws start "/sockets/events/$B" --name f05-b-resume --duration 300
  control-agent-server api POST "/api/conversations/$B/run" --expect 200 --check success eq true --save F05.run-resume-paused/run
  control-agent-server conversation wait "$B" --until finished --timeout 180
  control-agent-server api GET "/api/conversations/$B/events/count" --query kind=$ACTION_KIND --check . ge 1 --save F05.run-resume-paused/actions
  control-agent-server ws stop f05-b-resume --contains '"key": "execution_status", "value": "running"' --save F05.run-resume-paused/frames
  control-agent-server ws read f05-b-resume --contains '"key": "execution_status", "value": "finished"'
  ```
  The paused conversation runs its pending message on DeepSeek flash: the
  socket shows `running` then `finished`.
- **Interrupt with nothing running (`F05.interrupt-idle`).** `C` is idle and
  has no input.
  ```sh
  control-agent-server api POST "/api/conversations/$C/interrupt" --expect 200 --check success eq true --save F05.interrupt-idle/interrupt
  control-agent-server api GET "/api/conversations/$C" --check execution_status eq paused
  control-agent-server api GET "/api/conversations/$C/events/count" --query kind=$PAUSE_KIND --check . eq 1
  control-agent-server api GET "/api/conversations/$C/events/count" --query kind=$INTERRUPT_KIND --check . eq 0 --save F05.interrupt-idle/interrupt-events
  ```
  The interrupt falls back to pause: `paused`, one `PauseEvent`, no
  `InterruptEvent`.
- **A run that fails (`F05.run-error`).** `E`'s provider is unreachable
  (connection refused, no retries).
  ```sh
  control-agent-server conversation send "$E" --text 'hi' --no-run
  control-agent-server api POST "/api/conversations/$E/run" --expect 200 --check success eq true --save F05.run-error/run
  control-agent-server conversation wait "$E" --until error --timeout 120
  control-agent-server api GET "/api/conversations/$E/events/count" --query kind=$ERROR_KIND --check . eq 1
  control-agent-server api GET "/api/conversations/$E/events/search" --query kind=$ERROR_KIND \
    --check items.0.code exists --check items.0.detail exists --save F05.run-error/error-event
  control-agent-server api GET /api/conversations/search --query status=error --check items contains "$E"
  ```
  `/run` still answers 200 (the failure happens in the background); the
  status becomes `error`, one `ConversationErrorEvent` carries a `code`
  (`LLMServiceUnavailableError` here) and a `detail`, and `status=error`
  lists `E`.
- **Pause and interrupt a terminal conversation (`F05.pause-terminal`).**
  ```sh
  for CID in "$A" "$E"; do
    S=$(control-agent-server api GET "/api/conversations/$CID" --field execution_status)
    N=$(control-agent-server api GET "/api/conversations/$CID/events/count" --field .)
    control-agent-server api POST "/api/conversations/$CID/pause" --expect 200 --check success eq true --save F05.pause-terminal/pause
    control-agent-server api POST "/api/conversations/$CID/interrupt" --expect 200 --check success eq true --save F05.pause-terminal/interrupt
    control-agent-server api GET "/api/conversations/$CID" --check execution_status eq "$S"
    control-agent-server api GET "/api/conversations/$CID/events/count" --check . eq "$N"
  done
  ```
  Both calls are accepted on the `finished` and the `error` conversation, and
  neither the status nor the event count moves.
- **Responsive while a run fails (`F05.run-error-responsive`), known bug.**
  Re-run `E` and probe `/alive` twice right away; normally each probe (CLI
  start included) takes well under a second.
  ```sh
  control-agent-server api POST "/api/conversations/$E/run" --expect 200
  T0=$(date +%s%N)
  control-agent-server api GET /alive --auth none --expect 200 --timeout 60
  control-agent-server api GET /alive --auth none --expect 200 --timeout 60 --save F05.run-error-responsive/alive
  MS=$(( ($(date +%s%N) - T0) / 1000000 ))
  control-agent-server conversation wait "$E" --until error --timeout 60
  echo "two /alive probes took ${MS} ms"
  test "$MS" -lt 3000
  ```
  Expected: both probes answer in about 100 ms of server time. Today the first
  one waits about 5 s: `_run_and_publish` logs the run failure with
  `logger.exception` on the event loop (`event_service.py`, "Error during
  conversation run"), and the default console handler renders a rich
  traceback of about 1,000 lines synchronously, blocking every request,
  socket and run on the server meanwhile. With `LOG_JSON=true` (the Docker
  images' setting) the probes answer in about 80 ms.
- **Run an unknown id (`F05.unknown-id-run`).**
  ```sh
  control-agent-server api POST "/api/conversations/$NOPE/run" --expect 404 --check detail eq 'Not Found' --save F05.unknown-id-run/run
  ```
  404 `{"detail": "Not Found"}`.
- **Pause or interrupt an unknown id (`F05.unknown-id-pause`), known bug.**
  Both routes declare 404 "Item not found" (and no 400) in the OpenAPI
  document, like `/run` and `GET /api/conversations/{id}`.
  ```sh
  control-agent-server api GET /openapi.json --auth none --max-chars 200 \
    --check 'paths./api/conversations/{conversation_id}/pause.post.responses.404' exists \
    --check 'paths./api/conversations/{conversation_id}/interrupt.post.responses.404' exists
  control-agent-server api POST "/api/conversations/$NOPE/pause" --expect 404 --save F05.unknown-id-pause/pause
  control-agent-server api POST "/api/conversations/$NOPE/interrupt" --expect 404 --save F05.unknown-id-pause/interrupt
  ```
  Expected: 404 for both. Today both return 400 `{"detail": "Bad Request"}`
  (the handlers raise 400 when the service finds no conversation), so a
  consumer cannot tell a missing conversation from a bad request, and the
  status differs from `/run` for the same id.
- **Auth and malformed ids (`F05.control-errors`).**
  ```sh
  control-agent-server api POST "/api/conversations/$A/run" --auth none --expect 401 --check detail eq Unauthorized --save F05.control-errors/run-no-key
  control-agent-server api POST "/api/conversations/$A/pause" --auth none --expect 401 --save F05.control-errors/pause-no-key
  control-agent-server api POST "/api/conversations/$A/interrupt" --auth none --expect 401 --save F05.control-errors/interrupt-no-key
  control-agent-server api POST "/api/conversations/$A/run" --auth bad --expect 401
  control-agent-server api POST "/api/conversations/$A/pause" --auth bad --expect 401
  control-agent-server api POST "/api/conversations/$A/interrupt" --auth bad --expect 401
  control-agent-server api POST /api/conversations/not-a-uuid/run --expect 422 --check detail.0.loc contains conversation_id --save F05.control-errors/run-malformed
  control-agent-server api POST /api/conversations/not-a-uuid/pause --expect 422 --check detail.0.loc contains conversation_id
  control-agent-server api POST /api/conversations/not-a-uuid/interrupt --expect 422 --check detail.0.loc contains conversation_id
  control-agent-server api GET "/api/conversations/$A" --check execution_status eq finished
  control-agent-server api GET "/api/conversations/$A/events/count" --query kind=$PAUSE_KIND --check . eq 0
  ```
  Each route rejects a missing and a wrong key with 401 and a malformed path
  id with 422 naming `conversation_id`; `A` is still `finished`.
- **Run while running (`F05.run-conflict`).** `P`'s model call hangs, so the
  run stays `running`.
  ```sh
  control-agent-server conversation send "$P" --text 'hi' --no-run
  control-agent-server api POST "/api/conversations/$P/run" --expect 200 --check success eq true
  control-agent-server conversation wait "$P" --until running --timeout 60
  control-agent-server sink read --name qa-f05-hang --expect-min 1
  control-agent-server api POST "/api/conversations/$P/run" --expect 409 \
    --check detail eq 'Conversation already running. Wait for completion or pause first.' --save F05.run-conflict/run-409
  control-agent-server api GET "/api/conversations/$P" --check execution_status eq running
  control-agent-server api GET /api/conversations/count --query status=running --check . eq 1
  ```
  The second `/run` is refused with 409 and that exact detail; `P` is still
  the one running conversation and the stub saw the single model call.
- **Pause during a long model call (`F05.pause-running`).**
  ```sh
  control-agent-server ws start "/sockets/events/$P" --name f05-p-pause --duration 300
  T0=$(date +%s%N)
  control-agent-server api POST "/api/conversations/$P/pause" --expect 200 --check success eq true --timeout 60 --save F05.pause-running/pause
  MS=$(( ($(date +%s%N) - T0) / 1000000 ))
  test "$MS" -lt 3000
  control-agent-server api GET "/api/conversations/$P/events/count" --query kind=$PAUSE_KIND --check . eq 1
  control-agent-server api GET /api/conversations/search --query status=paused --check items contains "$P" --save F05.pause-running/search
  control-agent-server ws stop f05-p-pause --contains '"key": "execution_status", "value": "paused"' --save F05.pause-running/frames
  control-agent-server ws read f05-p-pause --expect-kind PauseEvent
  control-agent-server api POST "/api/conversations/$P/run" --expect 409 --save F05.pause-running/run-409
  ```
  The pause answers at once (the run loop releases the state lock for network
  waits), one `PauseEvent` is persisted, `status=paused` lists `P` and the
  socket pushes `paused` and the `PauseEvent`. The model call is still in
  flight, so `/run` is still 409 even though the status is `paused`.
- **GET after a mid-call pause (`F05.pause-running-get`), known bug.** Read
  the same conversation through its detail route and its state file.
  ```sh
  control-agent-server api GET "/api/conversations/$P" --check execution_status eq paused --save F05.pause-running-get/get
  control-agent-server state cat "server/workspace/conversations/$(echo "$P" | tr -d -)/base_state.json" --check execution_status eq paused
  ```
  Expected: `paused`, like the socket, the event log and the status search.
  Today both still say `running` until the model call returns (here 300 s) or
  is interrupted: the pause runs inside the run loop's open state block
  (`ConversationState._save_depth` stays 1 while `arun()` releases only the
  lock for the network wait), so the autosave of `base_state.json` is deferred
  to the end of the step, and `GET /api/conversations/{id}` answers from that
  file. A consumer that pauses and polls GET (as `conversation wait` and SDK
  pollers do) keeps seeing `running`; a crash in that window restores the
  conversation as `error` instead of `paused`.
- **Release a paused step with interrupt (`F05.pause-running-release`).**
  ```sh
  control-agent-server ws start "/sockets/events/$P" --name f05-p-release --duration 300
  T0=$(date +%s%N)
  control-agent-server api POST "/api/conversations/$P/interrupt" --expect 200 --check success eq true --timeout 60 --save F05.pause-running-release/interrupt
  MS=$(( ($(date +%s%N) - T0) / 1000000 ))
  test "$MS" -lt 5000
  control-agent-server api GET "/api/conversations/$P" --check execution_status eq paused --save F05.pause-running-release/get
  control-agent-server api GET "/api/conversations/$P/events/count" --query kind=$INTERRUPT_KIND --check . eq 1
  control-agent-server api GET /api/conversations/count --query status=running --check . eq 0
  control-agent-server ws stop f05-p-release --expect-kind InterruptEvent --save F05.pause-running-release/frames
  ```
  The interrupt cancels the hanging call within 5 s, appends an
  `InterruptEvent` (also on the socket), GET now reads `paused`, nothing is
  running and the single run slot is free for the next bullet.
- **Interrupt a running conversation (`F05.interrupt-running`).** `R`'s model
  call hangs until its stub is rewritten.
  ```sh
  control-agent-server conversation send "$R" --text 'hi' --no-run
  control-agent-server ws start "/sockets/events/$R" --name f05-r-interrupt --duration 300
  control-agent-server api POST "/api/conversations/$R/run" --expect 200 --check success eq true
  control-agent-server conversation wait "$R" --until running --timeout 60
  control-agent-server sink read --name qa-f05-resume --expect-min 1
  T0=$(date +%s%N)
  control-agent-server api POST "/api/conversations/$R/interrupt" --expect 200 --check success eq true --timeout 60 --save F05.interrupt-running/interrupt
  MS=$(( ($(date +%s%N) - T0) / 1000000 ))
  test "$MS" -lt 5000
  control-agent-server api GET "/api/conversations/$R" --check execution_status eq paused --save F05.interrupt-running/get
  control-agent-server api GET "/api/conversations/$R/events/count" --query kind=$INTERRUPT_KIND --check . eq 1
  control-agent-server api GET "/api/conversations/$R/events/count" --query kind=$PAUSE_KIND --check . eq 0
  control-agent-server ws stop f05-r-interrupt --expect-kind InterruptEvent --save F05.interrupt-running/frames
  control-agent-server ws read f05-r-interrupt --contains '"key": "execution_status", "value": "paused"'
  ```
  The interrupt returns within 5 s although the model call would hang for
  300 s; GET reads `paused`, the log has one `InterruptEvent` and no
  `PauseEvent`, and the socket pushed both the `InterruptEvent` and the
  `paused` transition.
- **Resume after an interrupt (`F05.run-after-interrupt`).** The provider now
  answers with a `finish` call (an exact tool call a real model cannot be
  made to produce on demand).
  ```sh
  control-agent-server fixture llm-stub --name qa-f05-resume --step 'tool:finish:{"message":"QA_F05_RESUMED"}'
  control-agent-server api POST "/api/conversations/$R/run" --expect 200 --check success eq true --save F05.run-after-interrupt/run
  control-agent-server conversation wait "$R" --until finished --timeout 60
  control-agent-server api GET "/api/conversations/$R/agent_final_response" --check response eq QA_F05_RESUMED --save F05.run-after-interrupt/final
  control-agent-server sink read --name qa-f05-resume --expect-min 2
  ```
  `/run` is accepted at once (no lingering 409), the resumed run calls the
  model again and ends `finished` with the stub's `finish` message.
- **Run capacity (`F05.run-capacity`).** One slot: `G` holds it on a hanging
  call while `Q` asks to run.
  ```sh
  control-agent-server conversation send "$Q" --text 'Reply with the single word ok, then finish.' --no-run
  control-agent-server conversation send "$G" --text 'hi' --no-run
  control-agent-server api POST "/api/conversations/$G/run" --expect 200 --check success eq true
  control-agent-server conversation wait "$G" --until running --timeout 60
  control-agent-server api POST "/api/conversations/$Q/run" --expect 429 \
    --check detail eq 'Conversation run limit reached. Retry the request later.' --save F05.run-capacity/run-429
  control-agent-server api GET "/api/conversations/$Q" --check execution_status eq idle --check last_user_message_id exists
  control-agent-server api GET /api/conversations/count --query status=running --check . eq 1
  control-agent-server api POST "/api/conversations/$G/interrupt" --expect 200 --check success eq true
  control-agent-server api POST "/api/conversations/$Q/run" --expect 200 --check success eq true --save F05.run-capacity/run-after-release
  control-agent-server conversation wait "$Q" --until finished --timeout 180
  ```
  `Q`'s run is refused with 429 while `G` runs, its queued message stays and
  it stays `idle`; after `G` is interrupted the same `/run` is accepted and
  `Q` finishes on DeepSeek flash.
- **Graceful restart while running (`F05.restart-running-graceful`).**
  ```sh
  control-agent-server conversation send "$K" --text 'hi' --no-run
  control-agent-server api POST "/api/conversations/$K/run" --expect 200 --check success eq true
  control-agent-server conversation wait "$K" --until running --timeout 60
  control-agent-server restart
  control-agent-server api GET "/api/conversations/$K" --check execution_status eq paused --save F05.restart-running-graceful/get
  control-agent-server api GET "/api/conversations/$K/events/count" --query kind=$PAUSE_KIND --check . eq 1
  control-agent-server api GET "/api/conversations/$K/events/count" --query kind=$INTERRUPT_KIND --check . eq 1
  control-agent-server doctor
  ```
  Shutdown pauses the running conversation and cancels its step, so `K`
  comes back `paused` with one `PauseEvent` and one `InterruptEvent`, and the
  restarted server is healthy.
- **Statuses survive the restart (`F05.restart-keeps-status`).** Read-only
  checks after the previous bullet's restart.
  ```sh
  for CID in "$A" "$B" "$Q" "$R"; do
    control-agent-server api GET "/api/conversations/$CID" --check execution_status eq finished
  done
  for CID in "$C" "$P" "$G"; do
    control-agent-server api GET "/api/conversations/$CID" --check execution_status eq paused
  done
  control-agent-server api GET "/api/conversations/$E" --check execution_status eq error --save F05.restart-keeps-status/error
  control-agent-server api GET /api/conversations/count --query status=paused --check . eq 4 --save F05.restart-keeps-status/paused-count
  control-agent-server api GET /api/conversations/count --query status=running --check . eq 0
  ```
  Four conversations are `finished`, four `paused` (`C`, `P`, `G`, `K`), `E`
  is still `error` and nothing is `running`.
- **Crash while running (`F05.restart-hard-running`).** SIGKILL leaves
  `running` on disk.
  ```sh
  control-agent-server api POST "/api/conversations/$K/run" --expect 200 --check success eq true
  control-agent-server conversation wait "$K" --until running --timeout 60
  control-agent-server state cat "server/workspace/conversations/$(echo "$K" | tr -d -)/base_state.json" --check execution_status eq running
  control-agent-server restart --hard
  control-agent-server api GET "/api/conversations/$K" --check execution_status eq error --save F05.restart-hard-running/get
  control-agent-server conversation events "$K" --kinds ConversationStateUpdateEvent --key execution_status --contains '"error"' --save F05.restart-hard-running/status-events
  control-agent-server api GET /api/conversations/count --query status=running --check . eq 0
  control-agent-server api POST "/api/conversations/$K/run" --expect 200 --check success eq true --save F05.restart-hard-running/rerun
  control-agent-server conversation wait "$K" --until running --timeout 60
  control-agent-server api POST "/api/conversations/$K/interrupt" --expect 200 --check success eq true
  control-agent-server api GET "/api/conversations/$K" --check execution_status eq paused
  control-agent-server doctor
  ```
  The killed server left `running` in `base_state.json`; the next start takes
  over the dead owner's lease, marks `K` `error` (a persisted
  `execution_status` update), nothing is `running`, and `/run` resumes `K`
  (interrupted again to free the slot).

## Gotchas

- `initial_message` on create always starts a run, whatever its `run` field
  says (see F04), and `conversation start --no-run` therefore still runs. To
  stage pending input, create without a prompt and append with
  `conversation send --no-run` (`POST .../events` with `"run": false`).
- Creating a conversation takes a run slot too (the create path is admitted
  like a run, by design: `tests/agent_server/test_run_admission.py`). With
  `max_concurrent_runs` 1 and a run in progress, `POST /api/conversations`
  itself returns 429, so create every conversation a recipe needs before the
  first run holds the slot.
- `GET /api/conversations/{id}` composes its answer from the autosaved
  `base_state.json`, while the events socket, the status filters of search
  and count, and the event log come from memory. They differ while a step is
  in flight and something changed the state mid-step
  (`F05.pause-running-get`).
- Pause does not stop a model call that is in progress: the status flips to
  `paused` at once, but the step finishes first, and until then `/run`
  answers 409 "Wait for completion or pause first" although the conversation
  is paused. `/interrupt` cancels the call (and is the way out); it waits at
  most 5 s for the run task, and if the task has not ended by then `/run`
  stays 409 until it does.
- `/run` returns before anything happens; observe the outcome with
  `conversation wait`, the events socket or the event log. A provider failure
  is a 200 from `/run` followed by `error` and a `ConversationErrorEvent`.
- `events/count` and `events/search` filter `kind` by the fully-qualified
  class path (`openhands.sdk.event.user_action.PauseEvent`), not the short
  `kind` value the events carry (F06).
- Every state change is also persisted as a `ConversationStateUpdateEvent`,
  so count specific kinds instead of total events, except to prove that
  nothing happened (`F05.run-finished-noop`).
- Graceful shutdown pauses and cancels running conversations (`PauseEvent`
  then `InterruptEvent`); SIGKILL leaves `running` on disk, and the next start
  turns it into `error` and appends an `AgentErrorEvent` for an unfinished
  tool call, if any. A lease held by a dead process on the same host is taken
  over immediately; a lease from another host must expire first
  (`OH_LEASE_TTL_SECONDS`, default 45), and until then `/run` answers 404.
- The 5 s stall in `F05.run-error-responsive` depends on logging: it happens
  with the default console logging (`launch` does not set `LOG_JSON`) and not
  with `LOG_JSON=true`. Every failed run also delays the socket's error frames
  by the same amount.
- `/run` on a conversation waiting for confirmation approves the pending
  actions; pause, interrupt, pause and resume of `/goal` loops, conversation
  webhooks on pause and interrupt, and credential bindings are covered by
  their own families.
- SDK and TypeScript `RemoteConversation.run()` post the same `/run`; the
  SDK accepts a 409 as "already running" and waits for that run to end
  instead of failing, so the 409 recipes here are the only place that status
  is visible.
