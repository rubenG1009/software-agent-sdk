# Session WebSocket protocol

The session socket is the newer, resumable conversation stream. A client
connects to one conversation, authenticates with a first frame, and receives
JSON envelopes discriminated by `type`. A `sync` frame always comes first and
announces the replay range. Persisted events then arrive as `durable` frames
whose `seq` is the event's index in the on-disk log, so a client can store the
last `seq` and reconnect with `?after_seq=<seq>` without gaps or duplicates.
Unpersisted state snapshots arrive as `transient` frames with no `seq`. While
a streaming LLM answers, `item_started`, `delta` and `item_aborted` progress
frames show the typing. Problems with the socket itself come back as `error`
frames. The client sends the same `Message` JSON as on the legacy events
socket, and every message it sends starts a run. Admission is bounded by
bytes: an oversized frame or a stalled reader gets close code 1013 instead of
blocking the publisher, and the client recovers by reconnecting with its
cursor.

Source: `openhands-agent-server/openhands/agent_server/session_socket.py`, `openhands-agent-server/openhands/agent_server/session_protocol.py`, `openhands-agent-server/openhands/agent_server/sockets.py`, `openhands-agent-server/openhands/agent_server/pub_sub.py`, `openhands-agent-server/openhands/agent_server/event_service.py`, `openhands-sdk/openhands/sdk/agent/stream_context.py`

Needs: `llm`

Routes: `WS /sockets/session/{conversation_id}`

## Sub-features

- `F07.sync-first`: the first server frame is `{"type": "sync"}`; `from_seq` echoes `after_seq` (absent when live-only) and `through_seq` is the last on-disk `seq` (absent for an empty log).
- `F07.snapshot-transient`: every connection gets one `transient` frame with a `full_state` `ConversationStateUpdateEvent` and no `seq`, after `sync` (and after the replay when one ran); it is never persisted.
- `F07.full-replay`: `after_seq=-1` replays every persisted event as `durable` frames with `seq` 0..`through_seq`, in order, once each, with the same ids REST returns.
- `F07.seq-on-disk`: a durable frame's `seq` is the event's on-disk index, the `NNNNN` in `events/event-NNNNN-<event id>.json`.
- `F07.resume-cursor`: `after_seq=k` replays exactly the events with `seq > k`; `after_seq=through_seq` replays nothing.
- `F07.live-durable`: on a live-only connection, an event appended later (a REST message with `run: false`) arrives as a `durable` frame with the next `seq`.
- `F07.live-order`: live `durable` frames on one connection arrive in ascending `seq` order.
- `F07.send-message`: a `Message` JSON sent on the socket is persisted as a user `MessageEvent` (echoed as a `durable` frame) and runs the agent to `finished`.
- `F07.error-frame`: JSON that is not a valid `Message` gets an `error` frame (`code` `ValidationError`); the connection stays open and nothing is persisted.
- `F07.error-non-json`: a text frame that is not JSON gets an `error` frame with `code` `JSONDecodeError`, and a binary frame gets an `error` frame too; the connection stays open.
- `F07.reject-non-user`: a `Message` whose `role` is not `user` gets an `error` frame (`Only user messages are allowed to be sent to the agent.`) and is not persisted.
- `F07.auth-frame-ignored`: a redundant `{"type": "auth", ...}` frame after authentication is ignored: no `error` frame, nothing persisted.
- `F07.auth`: a first-frame key opens the socket; a wrong key or a message sent before authenticating closes it with 4001 (nothing persisted); a wrong deprecated query key fails the handshake with HTTP 403.
- `F07.unknown-conversation`: a well-formed id that names no conversation closes with 4004 `Conversation not found` after authentication.
- `F07.bad-handshake`: a conversation id that is not a UUID, or an `after_seq` that is not an integer, fails the handshake with HTTP 403.
- `F07.restart-resume`: `seq` survives a server restart: reconnecting with the same cursor replays the same event ids at the same `seq` values.
- `F07.progress-frames`: with `llm.stream` on, a run streams `item_started`, then `delta` frames (`order` 0, 1, ...), and each item is retired by exactly one `durable` frame whose `event.id` equals `item_id` (or by `item_aborted`).
- `F07.progress-not-replayed`: reconnecting with `after_seq=-1` after a streamed run replays the durable message but no `item_started`, `delta` or `item_aborted` frame.
- `F07.frame-too-large`: replaying an event over 4 MiB closes the socket with 1013 `frame_too_large`; the event stays readable over REST and a cursor past it replays the rest.
- `F07.slow-consumer`: a client that stops reading while more than the 16 MiB write budget queues up is closed with 1013 `slow_consumer`, and the conversation keeps serving other sockets.
- `F07.subscriber-limit`: the event fan-out admits at most 50 subscribers per conversation; extra sockets close with 1013 `Too many connections for this conversation`, and closing sockets frees their slots.
- `F07.deleted-close`: deleting a conversation closes the session sockets attached to it.

## How to get to it (agent POV)

- WebSocket: `/sockets/session/{conversation_id}` with the query parameter
  `after_seq` (omit it for live-only, `-1` for the full history, `k` to resume
  after `seq` k). Authentication is shared with the other sockets: a first
  frame `{"type": "auth", "session_api_key": K}`, or the deprecated
  `session_api_key` query parameter or `X-Session-API-Key` header (F02 owns
  the auth matrix). Every recipe here drives the socket directly with
  the CLI's `ws listen` and `ws start`, or with a small `websockets` or
  raw-socket program under `exec` when the CLI cannot send the frame
  (non-JSON text, binary frames, a reader that stalls, 55 sockets at once).
- Client to server: a `Message` JSON object
  (`{"role": "user", "content": [{"type": "text", "text": "..."}]}`). Extra
  fields are ignored, `run` included: every message runs the agent
  (`EventService.send_message(message, run=True)`).
- Server to client: `sync`, `durable`, `transient`, `item_started`, `delta`,
  `item_aborted`, `error` (`session_protocol.py`). Frames are serialized with
  `exclude_none`, so absent optional fields are missing, not `null`.
- SDK and TypeScript client: neither consumes this socket yet;
  `RemoteConversation` and the TypeScript client use `/sockets/events/{id}`
  (F06 and its socket family). Only `tests/agent_server/test_session_socket.py`
  and `tests/agent_server/test_agent_server_wsproto.py` reference it.
- REST second views used here: `POST /api/conversations/{id}/events`
  (append a message without running), `GET .../events/search` and
  `GET .../events/count` (what was persisted), `GET`/`DELETE
  /api/conversations/{id}`, and `PATCH /api/settings`
  (`agent_settings_diff.llm.stream`, which new conversations inherit).

## Driving it with control-agent-server

Preconditions:

- A baseline run is live and exported (`launch --new`), and `doctor` is ok.
  `$DEEPSEEK_API_KEY` is set (two bullets run deepseek-flash).
- `EMPTY` is a conversation with no events. `CID` is a conversation with
  exactly five persisted events, created without a model call: two user
  messages appended with `run: false` give `SystemPromptEvent` (seq 0),
  `MessageEvent` QA_F07_ONE (1), `last_user_message_id` update (2),
  `MessageEvent` QA_F07_TWO (3) and `last_user_message_id` update (4).
  `E0`..`E4` are their ids from REST. The bullets up to `F07.live-durable`
  rely on `CID` having exactly those five events, so they persist nothing.
  Both conversations use `--tools none --no-autotitle`, so no title subscriber
  or tool runtime is involved.
  ```sh
  control-agent-server llm preset deepseek
  EMPTY=$(control-agent-server conversation start --tools none --no-autotitle --print-id)
  CID=$(control-agent-server conversation start --tools none --no-autotitle --print-id)
  control-agent-server api POST "/api/conversations/$CID/events" --json '{"role":"user","content":[{"type":"text","text":"QA_F07_ONE"}],"run":false}' --expect 200
  control-agent-server api POST "/api/conversations/$CID/events" --json '{"role":"user","content":[{"type":"text","text":"QA_F07_TWO"}],"run":false}' --expect 200
  control-agent-server api GET "/api/conversations/$CID/events/count" --expect 200 --check . eq 5
  E0=$(control-agent-server api GET "/api/conversations/$CID/events/search" --query limit=100 --field items.0.id)
  E1=$(control-agent-server api GET "/api/conversations/$CID/events/search" --query limit=100 --field items.1.id)
  E2=$(control-agent-server api GET "/api/conversations/$CID/events/search" --query limit=100 --field items.2.id)
  E3=$(control-agent-server api GET "/api/conversations/$CID/events/search" --query limit=100 --field items.3.id)
  E4=$(control-agent-server api GET "/api/conversations/$CID/events/search" --query limit=100 --field items.4.id)
  ```
- Captures are saved under names that end in the conversation id, so the
  `state cat evidence/...` checks read the file this replay wrote even on a
  run that replayed the family before.

- **Sync comes first (`F07.sync-first`).** Read only the first frame of a
  live-only connection, on an empty and on a non-empty conversation.
  ```sh
  control-agent-server ws listen "/sockets/session/$EMPTY" --count 1 --save "F07.sync-first/empty-$EMPTY"
  control-agent-server state cat "evidence/F07.sync-first/empty-$EMPTY.json" \
    --check frames.0.frame.type eq sync --check frames.0.frame.through_seq missing --check frames.0.frame.from_seq missing
  control-agent-server ws listen "/sockets/session/$CID" --count 1 --save "F07.sync-first/live-$CID"
  control-agent-server state cat "evidence/F07.sync-first/live-$CID.json" \
    --check frames.0.frame.type eq sync --check frames.0.frame.through_seq eq 4 --check frames.0.frame.from_seq missing
  ```
  The empty conversation's first frame is exactly `{"type": "sync"}`; `CID`'s
  is `{"type": "sync", "through_seq": 4}`.
- **State snapshot (`F07.snapshot-transient`).** The second frame of a
  live-only connection.
  ```sh
  control-agent-server ws listen "/sockets/session/$CID" --count 2 --save "F07.snapshot-transient/live-$CID"
  control-agent-server state cat "evidence/F07.snapshot-transient/live-$CID.json" \
    --check frames.1.frame.type eq transient --check frames.1.frame.seq missing \
    --check frames.1.frame.event.kind eq ConversationStateUpdateEvent \
    --check frames.1.frame.event.key eq full_state --check frames.1.frame.event.value.id eq "$CID"
  control-agent-server api GET "/api/conversations/$CID/events/count" --check . eq 5
  ```
  The snapshot is a `transient` frame without `seq` whose event is a
  `full_state` update of this conversation, and the event count is still 5:
  the snapshot is not persisted.
- **Full replay (`F07.full-replay`).** Connect with `after_seq=-1`.
  ```sh
  control-agent-server ws listen "/sockets/session/$CID" --query after_seq=-1 --duration 3 --save "F07.full-replay/all-$CID"
  control-agent-server state cat "evidence/F07.full-replay/all-$CID.json" --check frames len-eq 7 \
    --check frames.0.frame.from_seq eq -1 --check frames.0.frame.through_seq eq 4 \
    --check frames.1.frame.type eq durable --check frames.1.frame.seq eq 0 --check frames.1.frame.event.id eq "$E0" \
    --check frames.2.frame.seq eq 1 --check frames.2.frame.event.id eq "$E1" \
    --check frames.3.frame.seq eq 2 --check frames.3.frame.event.id eq "$E2" \
    --check frames.4.frame.seq eq 3 --check frames.4.frame.event.id eq "$E3" \
    --check frames.5.frame.seq eq 4 --check frames.5.frame.event.id eq "$E4" \
    --check frames.6.frame.type eq transient
  ```
  Exactly seven frames: `sync {from_seq: -1, through_seq: 4}`, five durable
  frames with `seq` 0 to 4 carrying the REST ids in REST order, then the
  snapshot.
- **Seq is the on-disk index (`F07.seq-on-disk`).** Read the event files by
  the name the `seq` predicts.
  ```sh
  control-agent-server state cat "server/workspace/conversations/${CID//-/}/events/event-00001-$E1.json" --check id eq "$E1" --contains QA_F07_ONE
  control-agent-server state cat "server/workspace/conversations/${CID//-/}/events/event-00003-$E3.json" --check id eq "$E3" --contains QA_F07_TWO
  ```
  Both files exist under the predicted names and hold the two messages.
- **Resume from a cursor (`F07.resume-cursor`).** Reconnect after `seq` 2,
  then after the last `seq`.
  ```sh
  control-agent-server ws listen "/sockets/session/$CID" --query after_seq=2 --duration 3 --save "F07.resume-cursor/after2-$CID"
  control-agent-server state cat "evidence/F07.resume-cursor/after2-$CID.json" --check frames len-eq 4 \
    --check frames.0.frame.from_seq eq 2 --check frames.1.frame.seq eq 3 --check frames.1.frame.event.id eq "$E3" \
    --check frames.2.frame.seq eq 4 --check frames.3.frame.type eq transient
  control-agent-server ws listen "/sockets/session/$CID" --query after_seq=4 --duration 3 --save "F07.resume-cursor/after4-$CID"
  control-agent-server state cat "evidence/F07.resume-cursor/after4-$CID.json" --check frames len-eq 2 \
    --check frames.0.frame.from_seq eq 4 --check frames.0.frame.through_seq eq 4 --check frames.1.frame.type eq transient
  ```
  `after_seq=2` replays `seq` 3 and 4 only; `after_seq=4` replays nothing and
  goes straight to the snapshot.
- **Invalid message (`F07.error-frame`).** Send two JSON frames that are not
  a `Message`.
  ```sh
  control-agent-server ws listen "/sockets/session/$CID" --send '{"content":"QA_F07_BAD"}' --send '[1, 2]' \
    --count 4 --duration 10 --expect-open --save "F07.error-frame/invalid-$CID"
  control-agent-server state cat "evidence/F07.error-frame/invalid-$CID.json" --check frames len-eq 6 \
    --check frames.4.frame.type eq error --check frames.4.frame.code eq ValidationError --check frames.4.frame.detail contains role \
    --check frames.5.frame.type eq error --check frames.5.frame.code eq ValidationError
  control-agent-server api GET "/api/conversations/$CID/events/count" --check . eq 5
  ```
  After `sync` and the snapshot come two `error` frames (`ValidationError`,
  the first naming the missing `role`); the socket is still open and nothing
  was persisted.
- **Non-JSON and binary frames (`F07.error-non-json`).** The CLI's `--send`
  only takes JSON, so a short `websockets` program sends the raw frames.
  ```sh
  mkdir -p "$AGENT_SERVER_VERIFY_RUN/fixtures"
  cat > "$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f07-raw-frames.py" <<'EOF'
  import json, os, sys
  from websockets.sync.client import connect

  url = os.environ["AGENT_SERVER_URL"].replace("http", "ws", 1) + "/sockets/session/" + sys.argv[1]
  with connect(url) as ws:
      ws.send(json.dumps({"type": "auth", "session_api_key": os.environ["SESSION_API_KEY"]}))
      ws.send("QA_F07 this is not JSON")
      ws.send(b"QA_F07 binary frame")
      ws.send("{}")
      frames = [json.loads(ws.recv(timeout=10)) for _ in range(5)]
  types = [f["type"] for f in frames]
  codes = [f.get("code") for f in frames if f["type"] == "error"]
  print("types", types, "codes", codes)
  assert types == ["sync", "transient", "error", "error", "error"], types
  assert codes[0] == "JSONDecodeError" and codes[2] == "ValidationError", codes
  print("QA_OK")
  EOF
  control-agent-server exec --expect-output QA_OK --save "F07.error-non-json/raw-$CID" -- .venv/bin/python "$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f07-raw-frames.py" "$CID"
  control-agent-server api GET "/api/conversations/$CID/events/count" --check . eq 5
  ```
  Three `error` frames in order: `JSONDecodeError` for the text, one for the
  binary frame (today `KeyError` `'text'`), and `ValidationError` for `{}`,
  which also proves the socket survived the first two.
- **Non-user role (`F07.reject-non-user`).** Send an `assistant` message.
  ```sh
  control-agent-server ws listen "/sockets/session/$CID" --send '{"role":"assistant","content":[{"type":"text","text":"QA_F07_ROLE"}]}' \
    --count 3 --duration 10 --expect-open --save "F07.reject-non-user/assistant-$CID"
  control-agent-server state cat "evidence/F07.reject-non-user/assistant-$CID.json" \
    --check frames.3.frame.type eq error --check frames.3.frame.detail contains 'Only user messages are allowed'
  control-agent-server api GET "/api/conversations/$CID/events/count" --check . eq 5
  ```
  An `error` frame (code `AssertionError` today) and no new event; the agent
  does not run.
- **Redundant auth frame (`F07.auth-frame-ignored`).** Authenticate with the
  header, then also send an auth frame, as a client that does both would.
  ```sh
  control-agent-server ws listen "/sockets/session/$CID" --auth header --send '{"type":"auth","session_api_key":"qa-redundant"}' \
    --duration 3 --expect-open --save "F07.auth-frame-ignored/redundant-$CID"
  control-agent-server state cat "evidence/F07.auth-frame-ignored/redundant-$CID.json" --check frames len-eq 3 --check summary.kinds.error missing
  control-agent-server api GET "/api/conversations/$CID/events/count" --check . eq 5
  ```
  Only `sync` and the snapshot arrive: no `error` frame, no new event. The key
  inside a redundant frame is not checked again.
- **Authentication (`F07.auth`).** The session-socket view of F02's matrix.
  ```sh
  control-agent-server ws listen "/sockets/session/$CID" --count 1 --expect-open --save "F07.auth/first-frame-$CID"
  control-agent-server ws listen "/sockets/session/$CID" --auth bad --expect-close 4001 --save "F07.auth/bad-key-$CID"
  control-agent-server ws listen "/sockets/session/$CID" --auth none --send '{"role":"user","content":[{"type":"text","text":"QA_F07_NOAUTH"}]}' --expect-close 4001
  control-agent-server ws listen "/sockets/session/$CID" --auth none --query session_api_key=qa-wrong-key --duration 3 | grep -qF '"http_status": 403'
  control-agent-server api GET "/api/conversations/$CID/events/count" --check . eq 5
  ```
  The run's key opens the socket (`sync` arrives); a wrong key and a message
  sent instead of an auth frame both close with 4001 `Authentication failed`,
  and the unauthenticated message is not persisted; a wrong key in the
  deprecated query parameter is refused at the handshake (HTTP 403, no close
  code).
- **Unknown conversation (`F07.unknown-conversation`).** A valid UUID that
  names nothing.
  ```sh
  control-agent-server ws listen /sockets/session/00000000-0000-4000-8000-0000000000f7 --query after_seq=-1 --expect-close 4004 --save F07.unknown-conversation/unknown
  ```
  Close code 4004, reason `Conversation not found`, after a successful auth
  frame.
- **Malformed handshake (`F07.bad-handshake`).** Path and query validation
  run before the socket is accepted.
  ```sh
  control-agent-server ws listen /sockets/session/qa-not-a-uuid --duration 3 | grep -qF '"http_status": 403'
  control-agent-server ws listen "/sockets/session/$CID" --query after_seq=qa --duration 3 | grep -qF '"http_status": 403'
  ```
  Both are HTTP 403 handshake rejections, not close codes.
- **Live durable frame (`F07.live-durable`).** Capture a live-only socket in
  the background, then append a message over REST without running.
  ```sh
  control-agent-server ws start "/sockets/session/$CID" --name "live-$CID" --settle 2
  control-agent-server api POST "/api/conversations/$CID/events" --json '{"role":"user","content":[{"type":"text","text":"QA_F07_LIVE"}],"run":false}' --expect 200
  L5=$(control-agent-server api GET "/api/conversations/$CID/events/search" --query limit=100 --field items.5.id)
  control-agent-server conversation events "$CID" --kinds MessageEvent --contains QA_F07_LIVE --expect-kind MessageEvent
  control-agent-server ws stop "live-$CID" --kinds durable --contains "\"seq\": 5, \"event\": {\"id\": \"$L5\"" --save "F07.live-durable/live-$CID"
  control-agent-server state cat "evidence/F07.live-durable/live-$CID.json" --check frames len-eq 4 \
    --check frames.0.frame.through_seq eq 4 --check frames.1.frame.type eq transient
  ```
  After `sync` (`through_seq` 4) and the snapshot, two durable frames arrive:
  the message as `seq` 5, with the id REST lists at index 5, and its
  `last_user_message_id` update as `seq` 6.
- **Live frames in seq order (`F07.live-order`), known bug.** Durable frames
  on one connection should arrive in `seq` order, like the replay. A user
  message is published after the `last_user_message_id` update it causes,
  because `LocalConversation`'s persist callback appends the message, sets
  `last_user_message_id` (which appends and publishes the update at once),
  and only then lets the message reach the publish callback. A client that
  stores the highest `seq` it saw and drops between the two frames resumes
  past the message and loses it.
  ```sh
  ORD=$(control-agent-server conversation start --tools none --no-autotitle --print-id)
  control-agent-server ws start "/sockets/session/$ORD" --name "order-$ORD" --settle 2
  control-agent-server api POST "/api/conversations/$ORD/events" --json '{"role":"user","content":[{"type":"text","text":"QA_F07_ORDER"}],"run":false}' --expect 200
  control-agent-server conversation events "$ORD" --kinds MessageEvent --contains QA_F07_ORDER --expect-kind MessageEvent
  control-agent-server ws stop "order-$ORD" --kinds durable --contains QA_F07_ORDER --save "F07.live-order/order-$ORD"
  control-agent-server state cat "evidence/F07.live-order/order-$ORD.json" --check frames len-eq 5 \
    --check frames.2.frame.seq eq 0 --check frames.3.frame.seq eq 1 --check frames.4.frame.seq eq 2
  ```
  Expected `seq` 0, 1, 2; today the frames arrive as 0, 2, 1 (the
  `last_user_message_id` update, then the message), on every user message,
  whether it came over REST or over the socket.
- **Send a message on the socket (`F07.send-message`).** A tiny deepseek-flash
  run; the message is sent by the background capture as it connects.
  ```sh
  control-agent-server ws start "/sockets/session/$CID" --name "send-$CID" --settle 2 \
    --send '{"role":"user","content":[{"type":"text","text":"QA_F07_WS Reply with the single word: ok"}]}'
  control-agent-server conversation wait "$CID" --until finished --timeout 180
  control-agent-server ws stop "send-$CID" --kinds durable --contains QA_F07_WS --save "F07.send-message/send-$CID"
  control-agent-server ws read "send-$CID" --kinds durable --contains '"value": "finished"'
  control-agent-server conversation events "$CID" --kinds MessageEvent --contains QA_F07_WS --expect-kind MessageEvent
  control-agent-server api GET "/api/conversations/$CID" --check execution_status eq finished
  ```
  The socket echoes the user message as a durable frame and later the
  durable `execution_status: finished` update; REST lists the message and
  reports `finished`. No `run` field was needed.
- **Cursor survives a restart (`F07.restart-resume`).** Restart the server,
  then resume from the same cursor.
  ```sh
  T=$(control-agent-server api GET "/api/conversations/$CID/events/count" --field .)
  control-agent-server restart
  control-agent-server ws listen "/sockets/session/$CID" --query after_seq=2 --duration 3 --save "F07.restart-resume/after2-$CID"
  control-agent-server state cat "evidence/F07.restart-resume/after2-$CID.json" --check frames len-eq "$((T - 1))" \
    --check frames.0.frame.through_seq eq "$((T - 1))" \
    --check frames.1.frame.seq eq 3 --check frames.1.frame.event.id eq "$E3" \
    --check frames.2.frame.seq eq 4 --check frames.2.frame.event.id eq "$E4"
  ```
  After the restart `through_seq` is still the last index before it, and
  `seq` 3 and 4 still carry `E3` and `E4`: `sync`, `T - 3` durable frames and
  the snapshot.
- **Streaming progress frames (`F07.progress-frames`).** Turn on
  `llm.stream` for one new conversation, restore the setting, then send a
  message on its socket and check the protocol's item rules on the capture.
  ```sh
  control-agent-server api PATCH /api/settings --json '{"agent_settings_diff": {"llm": {"stream": true}}}' --expect 200 --check agent_settings.llm.stream eq true
  SID=$(control-agent-server conversation start --tools none --no-autotitle --print-id)
  control-agent-server api PATCH /api/settings --json '{"agent_settings_diff": {"llm": {"stream": false}}}' --expect 200 --check agent_settings.llm.stream eq false
  control-agent-server ws listen "/sockets/session/$SID" --send '{"role":"user","content":[{"type":"text","text":"Reply with the single word: ok"}]}' \
    --until-kind durable --until event.key=execution_status --until event.value=finished --duration 180 --save "F07.progress-frames/run-$SID"
  ITEM=$(python3 - "$AGENT_SERVER_VERIFY_RUN/evidence/F07.progress-frames/run-$SID.json" <<'EOF'
  import json, sys
  frames = [e["frame"] for e in json.load(open(sys.argv[1]))["frames"] if e["direction"] == "received"]
  started = [(i, f) for i, f in enumerate(frames) if f["type"] == "item_started"]
  assert started, "no item_started frame"
  durable_items = []
  for i, start in started:
      item, attempt = start["item_id"], start["attempt"]
      assert "seq" not in start, start
      mine = [f for f in frames if f["type"] == "delta" and f["item_id"] == item and f["attempt"] == attempt]
      early = [f for f in frames[:i] if f["type"] == "delta" and f["item_id"] == item and f["attempt"] == attempt]
      assert mine and not early, f"deltas of {item} missing or before item_started"
      assert [d["order"] for d in mine] == list(range(len(mine))), "delta order has a gap"
      retired = [f for f in frames[i + 1:] if (f["type"] == "durable" and f["event"]["id"] == item)
                 or (f["type"] == "item_aborted" and f["item_id"] == item)]
      assert len(retired) == 1, f"{item} retired {len(retired)} times"
      if retired[0]["type"] == "durable":
          assert retired[0]["seq"] > start.get("anchor_seq", -1), (retired[0]["seq"], start)
          durable_items.append(item)
  assert durable_items, "no item was retired by a durable frame"
  print(f"{len(started)} item(s); retired by durable: {durable_items}", file=sys.stderr)
  print(durable_items[0])
  EOF
  )
  test -n "$ITEM"
  ```
  At least one `item_started` (no `seq`, an `anchor_seq`), followed by its
  `delta` frames with `order` 0, 1, ..., and exactly one later `durable` frame
  whose `event.id` is the `item_id` (the agent's reply). `ITEM` is that id.
- **Progress is never replayed (`F07.progress-not-replayed`).** Reconnect to
  the streamed conversation with the full history.
  ```sh
  control-agent-server ws listen "/sockets/session/$SID" --query after_seq=-1 --duration 3 --save "F07.progress-not-replayed/replay-$SID"
  control-agent-server state cat "evidence/F07.progress-not-replayed/replay-$SID.json" --contains "$ITEM" \
    --not-contains '"item_started"' --not-contains '"type": "delta"' --not-contains '"item_aborted"'
  ```
  The replay carries the durable reply (its id is `ITEM`) and no progress
  frame of any kind.
- **Oversized event (`F07.frame-too-large`).** Append a 5 MiB message over
  REST, then replay it.
  ```sh
  BIG=$(control-agent-server conversation start --tools none --no-autotitle --print-id)
  mkdir -p "$AGENT_SERVER_VERIFY_RUN/fixtures"
  python3 -c 'import json, sys; json.dump({"role": "user", "content": [{"type": "text", "text": "QA_F07_BIG " + "x" * (5 * 1024 * 1024)}], "run": False}, open(sys.argv[1], "w"))' "$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f07-5mib.json"
  control-agent-server api POST "/api/conversations/$BIG/events" --json-file "$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f07-5mib.json" --expect 200 | tail -c 300
  control-agent-server api GET "/api/conversations/$BIG/events/count" --check . eq 3
  control-agent-server ws listen "/sockets/session/$BIG" --query after_seq=-1 --duration 10 --expect-close 1013 --save "F07.frame-too-large/replay-$BIG"
  control-agent-server state cat "evidence/F07.frame-too-large/replay-$BIG.json" --check summary.close.reason eq frame_too_large \
    --check frames len-eq 2 --check frames.1.frame.seq eq 0
  control-agent-server api GET "/api/conversations/$BIG/events/count" --query body=QA_F07_BIG --check . eq 1
  control-agent-server ws listen "/sockets/session/$BIG" --query after_seq=1 --duration 3 --expect-open --save "F07.frame-too-large/skip-$BIG"
  control-agent-server state cat "evidence/F07.frame-too-large/skip-$BIG.json" --check frames len-eq 3 --check frames.1.frame.seq eq 2
  ```
  The replay delivers `seq` 0 and closes with 1013 `frame_too_large` at the
  5 MiB event; REST still finds it (a body-filtered count of 1; the search
  would print all 5 MiB), and `after_seq=1` skips it and replays `seq` 2.
- **Stalled reader (`F07.slow-consumer`).** Build about 47 MiB of history
  (twelve 3.9 MiB messages, each under the 4 MiB frame cap), then connect
  with `after_seq=-1` from a raw socket with a 64 KiB receive window that
  stops reading for 5 seconds. The CLI always reads, so a stdlib program
  does the handshake and scans what arrives for the close frame.
  ```sh
  SLOW=$(control-agent-server conversation start --tools none --no-autotitle --print-id)
  mkdir -p "$AGENT_SERVER_VERIFY_RUN/fixtures"
  python3 -c 'import json, sys; json.dump({"role": "user", "content": [{"type": "text", "text": "QA_F07_SLOW " + "y" * 4089000}], "run": False}, open(sys.argv[1], "w"))' "$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f07-3m9.json"
  for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
    control-agent-server api POST "/api/conversations/$SLOW/events" --json-file "$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f07-3m9.json" --expect 200 | tail -c 300
  done
  control-agent-server api GET "/api/conversations/$SLOW/events/count" --check . eq 25
  cat > "$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f07-stalled-reader.py" <<'EOF'
  import base64, json, os, socket, sys, time
  from urllib.parse import urlparse

  server = urlparse(os.environ["AGENT_SERVER_URL"])
  cid, pause = sys.argv[1], float(sys.argv[2])
  sock = socket.socket()
  sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)  # before connect: a small window
  sock.connect((server.hostname, server.port))
  key = base64.b64encode(os.urandom(16)).decode()
  sock.sendall(
      f"GET /sockets/session/{cid}?after_seq=-1 HTTP/1.1\r\nHost: {server.netloc}\r\n"
      f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
      "Sec-WebSocket-Version: 13\r\n\r\n".encode()
  )
  head = b""
  while b"\r\n\r\n" not in head:
      head += sock.recv(1)
  assert b" 101 " in head.split(b"\r\n", 1)[0], head
  auth = json.dumps({"type": "auth", "session_api_key": os.environ["SESSION_API_KEY"]}).encode()
  mask = os.urandom(4)
  size = bytes([0x80 | len(auth)]) if len(auth) < 126 else bytes([0xFE]) + len(auth).to_bytes(2, "big")
  sock.sendall(b"\x81" + size + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(auth)))
  time.sleep(pause)  # stop reading while the server replays the history
  close = b"\x88\x0f\x03\xf5slow_consumer"  # close frame: code 1013, reason slow_consumer
  data = bytearray()
  sock.settimeout(20)
  try:
      while chunk := sock.recv(1 << 20):
          data += chunk
          if close in data[-(len(chunk) + len(close)):]:
              break
  except TimeoutError:
      pass
  print("bytes before the close frame:", len(data))
  assert close in data, "no 1013 slow_consumer close frame"
  print("QA_OK close 1013 slow_consumer")
  EOF
  control-agent-server exec --timeout 120 --expect-output 'QA_OK close 1013 slow_consumer' --save "F07.slow-consumer/stalled-$SLOW" -- python3 "$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f07-stalled-reader.py" "$SLOW" 5
  control-agent-server ws listen "/sockets/session/$SLOW" --query after_seq=23 --count 3 --duration 20 --expect-open --save "F07.slow-consumer/resume-$SLOW"
  control-agent-server state cat "evidence/F07.slow-consumer/resume-$SLOW.json" --check frames.0.frame.through_seq eq 24 \
    --check frames.1.frame.seq eq 24 --check frames.2.frame.type eq transient
  ```
  The stalled reader receives some megabytes, then the close frame 1013
  `slow_consumer`. A normal client then resumes from a cursor on the same
  conversation and gets the last event, `seq` 24 (a small state update, so
  the evidence stays small).
- **Subscriber cap (`F07.subscriber-limit`).** Open 55 session sockets to one
  conversation at once from one program, close them, then connect again.
  ```sh
  LIM=$(control-agent-server conversation start --tools none --no-autotitle --print-id)
  mkdir -p "$AGENT_SERVER_VERIFY_RUN/fixtures"
  cat > "$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f07-many-sockets.py" <<'EOF'
  import asyncio, json, os, sys
  from websockets.asyncio.client import connect
  from websockets.exceptions import ConnectionClosed

  url = os.environ["AGENT_SERVER_URL"].replace("http", "ws", 1) + "/sockets/session/" + sys.argv[1]
  count = int(sys.argv[2])
  auth = json.dumps({"type": "auth", "session_api_key": os.environ["SESSION_API_KEY"]})

  async def attach(results, held):
      ws = await connect(url)
      await ws.send(auth)
      try:
          frame = json.loads(await asyncio.wait_for(ws.recv(), 15))
          results.append(("open", frame["type"]))
          held.append(ws)
      except ConnectionClosed as exc:
          results.append(("closed", exc.rcvd.code if exc.rcvd else None, exc.rcvd.reason if exc.rcvd else None))

  async def main():
      results, held = [], []
      await asyncio.gather(*(attach(results, held) for _ in range(count)))
      opened = [r for r in results if r[0] == "open"]
      refused = [r for r in results if r[0] == "closed"]
      print(f"opened={len(opened)} refused={len(refused)} {sorted(set(refused))}")
      assert {r[1] for r in opened} == {"sync"}, opened
      assert 40 <= len(opened) <= 50 and len(opened) + len(refused) == count
      assert set(refused) == {("closed", 1013, "Too many connections for this conversation")}, refused
      for ws in held:
          await ws.close()
      for _ in range(20):  # the server unsubscribes as each close lands
          async with connect(url) as ws:
              await ws.send(auth)
              try:
                  if json.loads(await asyncio.wait_for(ws.recv(), 15))["type"] == "sync":
                      print("QA_OK slot freed")
                      return
              except ConnectionClosed:
                  await asyncio.sleep(0.5)
      raise SystemExit("no slot freed")

  asyncio.run(main())
  EOF
  control-agent-server exec --timeout 120 --expect-output 'QA_OK slot freed' --save "F07.subscriber-limit/many-$LIM" -- .venv/bin/python "$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f07-many-sockets.py" "$LIM" 55
  ```
  Between 40 and 50 sockets get `sync` (49 on a baseline run: the server
  holds one subscription of its own), every other one closes with 1013
  `Too many connections for this conversation`, and once they close a new
  socket is admitted.
- **Deleting closes the socket (`F07.deleted-close`), known bug.** A client
  attached to a conversation that gets deleted should be told. Today the server drops the subscription (`PubSub.close` clears it,
  and `_SessionSubscriber` has no `close` hook) but leaves the socket open
  and silent, so the client waits forever. The `sleep` only orders the
  DELETE after the socket is attached.
  ```sh
  DEL=$(control-agent-server conversation start --tools none --no-autotitle --print-id)
  (sleep 3 && control-agent-server api DELETE "/api/conversations/$DEL" --expect 200) &
  DELPID=$!
  DELWS=$(control-agent-server ws listen "/sockets/session/$DEL" --duration 10 --save "F07.deleted-close/listen-$DEL")
  wait "$DELPID"
  control-agent-server api GET "/api/conversations/$DEL" --expect 404
  grep -qF '"stopped": "closed"' <<<"$DELWS"
  ```
  Expected: the socket is closed by the server shortly after the DELETE.
  Today the listen runs its full 10 seconds (`"stopped": "duration"`) with
  only `sync` and the snapshot, although the DELETE answered 200 and the
  conversation is 404.

## Gotchas

- Neither the SDK nor the TypeScript client uses this socket yet, so a
  regression here breaks no shipped consumer's tests; only these recipes and
  `tests/agent_server/test_session_socket.py` notice.
- The CLI names a frame by its `kind` field before its `type`: session frames
  show up as `sync`, `durable`, `transient`, `error` and `item_started`, but
  a `delta` frame shows up as `text` or `reasoning` (its own `kind` field).
  `--until-kind delta` never matches; check the saved capture instead. Match
  on the envelope with `--until FIELD=VALUE` (`event.key=execution_status`)
  or `--contains` on the frame's JSON (`"seq": 5, "event": {"id": "..."}`,
  key order as the server sends it).
- A conversation without an initial message has no events at all, so its
  `sync` has no `through_seq`; the first `POST .../events` writes the
  `SystemPromptEvent` (seq 0) before the message. A conversation started with
  `--prompt` always runs, even with `--no-run` (the server ignores
  `initial_message.run`), so fixtures that must not call the model append
  messages with `POST .../events` and `"run": false` instead.
- Messages sent on the socket always run: `Message` ignores unknown fields, so
  `"run": false` in the frame is silently dropped. There is no way to append
  without running over this socket.
- A redundant auth frame is ignored whatever key it carries; only the first
  frame (or the legacy query/header key) is checked.
- `error` frames are about the socket, never persisted, and the connection
  stays open after them. A `role` other than `user` is rejected by an
  `assert` in `LocalConversation.send_message` (code `AssertionError`); under
  `python -O` that check would disappear (see the REST variant in F06).
- The 4 MiB frame cap and the 16 MiB per-connection write budget are marked
  provisional in `session_protocol.py`. An event over 4 MiB can never be
  delivered on this socket: every replay that reaches it closes with 1013,
  so a client must skip it with a cursor and read it over REST.
- Whether a stalled reader trips the 16 MiB budget depends on how much the
  kernel buffers: the server's socket send buffer (`net.ipv4.tcp_wmem` max,
  4 MiB here) plus one frame in flight and one in uvicorn's transport. The
  recipe uses about 47 MiB of history and a 64 KiB client window to stay
  well above that; on a host with much larger send buffers, raise the
  message count. A `websockets` client is a poor stall: it keeps reading
  into its own buffer even with `max_queue=1`.
- Durable frames dropped with a connection (oversize, slow consumer) are not
  lost: reconnect with `after_seq` set to the last `seq` received. Progress
  frames are never replayed, by design.
- The 50-subscriber cap is per conversation and shared with the legacy
  `/sockets/events/{id}` socket and internal subscribers (autotitle,
  webhooks); one slot is already taken on a baseline conversation. The
  stream-progress fan-out has its own cap of 50; when it is full, the socket
  still opens but without typing frames.
- Other close codes the source can send but these recipes do not reach:
  1013 `credential_binding_activation_required` (a conversation waiting on a
  credential binding) and 1011 `subscribe_failed` (the subscribe call
  raised).
- `ws start` waits `--settle` seconds (default 1) for the capture to
  connect; on a loaded machine use `--settle 2` or more before triggering
  the action, or the capture misses it.
- `api` echoes the whole request body in its output, so the multi-megabyte
  POSTs above pipe through `tail -c 300` to keep the map-run transcript
  small; `--max-chars` only trims non-JSON response bodies.
