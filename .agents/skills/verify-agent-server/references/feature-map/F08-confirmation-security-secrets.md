# Confirmation policy, security analyzer and conversation secrets

The runtime safety and credential knobs of a live conversation. An agent's
host decides when actions need a human's approval (`confirmation_policy`:
`NeverConfirm`, `AlwaysConfirm`, `ConfirmRisky` with a risk threshold),
which analyzer rates each action's risk (`security_analyzer`, or none), and
answers a parked action with accept or reject
(`events/respond_to_confirmation`). It also hands the conversation named
secrets at runtime (`secrets`): a terminal command that mentions a secret's
name gets it as an environment variable, its value is masked as
`<secret-hidden>` in observations and in what the model sees, and it is
encrypted at rest. Start-time `confirmation_policy`, `security_analyzer` and
`secrets` fields of `POST /api/conversations` belong to the lifecycle family;
`POST .../run` (how the Python SDK accepts) belongs to the run family.

Source: `openhands-agent-server/openhands/agent_server/conversation_router.py`, `openhands-agent-server/openhands/agent_server/event_router.py`, `openhands-agent-server/openhands/agent_server/event_service.py`, `openhands-agent-server/openhands/agent_server/models.py`, `openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py`, `openhands-sdk/openhands/sdk/conversation/secret_registry.py`, `openhands-sdk/openhands/sdk/conversation/state.py`, `openhands-sdk/openhands/sdk/security/`, `openhands-sdk/openhands/sdk/secret/secrets.py`, `openhands-sdk/openhands/sdk/agent/agent.py`, `openhands-tools/openhands/tools/terminal/impl.py`

Needs: `llm`, `tmux`

Launch: `--env TMUX_TMPDIR=/tmp/qa-f08-tmux`

Routes: `POST /api/conversations/{conversation_id}/events/respond_to_confirmation`,
`POST /api/conversations/{conversation_id}/secrets`,
`POST /api/conversations/{conversation_id}/confirmation_policy`,
`POST /api/conversations/{conversation_id}/security_analyzer`

## Sub-features

- `F08.policy-set`: `POST .../confirmation_policy` switches between `AlwaysConfirm`, `ConfirmRisky` (with `threshold` and `confirm_unknown`) and `NeverConfirm`; GET, `base_state.json` and a `confirmation_policy` state update on the events socket reflect each change at once.
- `F08.policy-errors`: an unknown policy kind, a `threshold` of `UNKNOWN` or an unknown level, and a missing or empty `policy` are 422; an unknown conversation is 404; no key is 401; the stored policy is unchanged.
- `F08.always-confirm-wait`: after a runtime switch to `AlwaysConfirm`, the agent's next terminal action parks the conversation in `waiting_for_confirmation` (pushed on the socket) with the `ActionEvent` recorded, no observation, and the command not run.
- `F08.confirm-accept`: `accept: true` runs the pending command (observation and file on disk) and the run continues to `finished`.
- `F08.confirm-reject`: `accept: false` records one `UserRejectObservation` with the given reason (REST and socket) and returns to `idle` without running the command; a second reject is a no-op, and a later accept only resumes the agent.
- `F08.confirm-errors`: a missing or non-boolean `accept` and a malformed id are 422; an unknown conversation is 404; no key is 401.
- `F08.confirm-capacity`: with the server's run capacity full, accept is 429 and leaves the action pending and unrun; reject still works; accept on a running conversation is a 200 no-op.
- `F08.confirm-real`: DeepSeek flash under `AlwaysConfirm` stops before its terminal command and finishes the task once its actions are accepted.
- `F08.analyzer-set-clear`: `POST .../security_analyzer` sets `PatternSecurityAnalyzer` or `LLMSecurityAnalyzer` and clears it with `null`; GET, `base_state.json` and the socket reflect each change.
- `F08.analyzer-errors`: a missing `security_analyzer` field and an unknown kind are 422; an unknown conversation is 404; no key is 401; the stored analyzer is unchanged.
- `F08.confirm-risky`: under `ConfirmRisky` with `PatternSecurityAnalyzer`, a low-risk command runs unasked and `rm -rf` waits for confirmation; once the analyzer is cleared, an unrated command waits too.
- `F08.secrets-update`: `POST .../secrets` accepts plain strings, `{"value": ...}` and `StaticSecret` objects (200); once the state is saved, GET lists the names with masked values and `base_state.json` holds them encrypted, never in plaintext.
- `F08.secrets-visible`: a secret posted at runtime is listed by GET right away, without waiting for another state change.
- `F08.secrets-errors`: a missing or non-object `secrets`, an unknown secret kind and a `LookupSecret` without `url` are 422; an unknown conversation is 404; no key is 401; nothing is stored.
- `F08.secrets-bad-value`: a number or `null` as a secret value is refused with 422, not a 500.
- `F08.secrets-terminal`: a terminal command that names a runtime secret receives its value, while the observation and the next request to the model show `<secret-hidden>` and the plaintext is stored nowhere.
- `F08.secrets-override`: a runtime secret replaces a start-time secret of the same name for the next command.
- `F08.secrets-profile-scope`: for a conversation launched from an Agent Profile with `secret_refs`, names outside the list are silently dropped (200).
- `F08.secrets-restart`: a runtime secret that reached `base_state.json` is still injected into commands after a server restart.
- `F08.secrets-unsaved-restart`: a runtime secret survives a restart even when nothing else changed in the conversation after it was posted.
- `F08.secrets-override-restart`: a runtime override of a start-time secret still wins after a restart.
- `F08.policy-restart`: a confirmation policy set at runtime is still in force after a restart: GET reports it and the next action waits for confirmation.
- `F08.analyzer-restart`: a security analyzer set at runtime is still set after a restart.

## How to get to it (agent POV)

- REST: `POST /api/conversations/{conversation_id}/confirmation_policy`
  (body `SetConfirmationPolicyRequest`: `{"policy": {"kind": "AlwaysConfirm"}}`,
  `{"kind": "NeverConfirm"}` or `{"kind": "ConfirmRisky", "threshold": "LOW|MEDIUM|HIGH", "confirm_unknown": true}`),
  `POST .../security_analyzer` (`{"security_analyzer": {"kind": "PatternSecurityAnalyzer"}}`
  or `null`; other kinds: `LLMSecurityAnalyzer`, `PolicyRailSecurityAnalyzer`,
  `EnsembleSecurityAnalyzer`, `ToolShieldLLMSecurityAnalyzer`, `GraySwanAnalyzer`),
  `POST .../secrets` (`{"secrets": {"NAME": "value" | {"value": "..."} | {"kind": "StaticSecret", "value": "..."} | {"kind": "LookupSecret", "url": "...", "headers": {}}}}`),
  and `POST .../events/respond_to_confirmation` (`{"accept": true}` or
  `{"accept": false, "reason": "..."}`). All four answer `{"success": true}`.
- Second views: `GET /api/conversations/{id}` (`execution_status`,
  `confirmation_policy`, `security_analyzer`, `secret_registry.secret_sources`
  with masked values), the event history (`ActionEvent`, `ObservationEvent`,
  `UserRejectObservation`, `ConversationStateUpdateEvent` keys
  `execution_status`, `confirmation_policy`, `security_analyzer`), and the
  conversation's `base_state.json` on disk.
- WebSocket (owned by the events family): `/sockets/events/{conversation_id}`
  pushes the state updates above and the `UserRejectObservation` live.
- Start-time fields of `POST /api/conversations` (`confirmation_policy`,
  `security_analyzer`, `secrets`) are stored in `meta.json` and re-applied on
  every reload; the runtime routes here change only the live state.
- SDK (`openhands-sdk/openhands/sdk/conversation/impl/remote_conversation.py`):
  `RemoteConversation.set_confirmation_policy()`, `set_security_analyzer()`,
  `update_secrets()` (serializes `SecretSource` objects, calls callables), and
  `reject_pending_actions(reason)` (`accept: false`). The SDK accepts by
  calling `run()` (`POST .../run`); `respond_to_confirmation` with
  `accept: true` does the same thing server-side.
- TypeScript client: `ConversationClient.setConfirmationPolicy`,
  `setSecurityAnalyzer`, `updateSecrets`, `respondToConfirmation`
  (`clients/typescript/src/client/conversation-client.ts`) and
  `RemoteConversation.setConfirmationPolicy`, `setSecurityAnalyzer`,
  `updateSecrets` (always sends `StaticSecret` objects) and
  `sendConfirmationResponse(accept, reason)`
  (`clients/typescript/src/conversation/remote-conversation.ts`).
- Agent Canvas (context only): the confirmation-mode toggle and the
  approve/reject buttons on a pending action call these routes.
- Recipes below use REST through `api`, the socket through `ws start`/`ws stop`,
  scripted terminal actions from `fixture llm-stub` (one stub per scenario,
  because a stub's step counter never resets), and DeepSeek flash for the
  real-model confirmation path.

## Driving it with control-agent-server

Preconditions:

- A run launched with this family's `Launch:` flag (`--env
  TMUX_TMPDIR=/tmp/qa-f08-tmux`), `doctor` ok, `$DEEPSEEK_API_KEY` set; the
  block below saves the DeepSeek profiles. The flag keeps tmux socket paths
  under the 107-byte Unix socket limit (see Gotchas).
- `tmux` is installed: every scripted agent here has the `terminal` tool and
  nothing else (plus the built-in `finish` and `think`).
- The block below creates, in order: the workspace root `$W` with one folder
  per scenario (the `qa-f08-victim` folders are what `rm -rf` must not
  delete), an unknown id `$NOPE`, an offline inline agent `$OFFLINE_AGENT`
  (never run), and one scripted `llm-stub` agent per scenario. Each stub
  answers its conversation's model calls in order and repeats its last step:
  `$ACCEPT_AGENT` (write `qa-f08-accepted.txt`, finish), `$REJECT_AGENT`
  (`rm -rf qa-f08-victim`, finish), `$RISKY_AGENT` (a low-risk `echo`,
  `rm -rf qa-f08-victim`, an `echo`, finish), `$SECRET_AGENT` (write
  `$QA_F08_TOKEN` to a file and echo it, finish, twice), `$ROTATE_AGENT`
  (write `$QA_F08_ROT` to a file, finish, twice) and `$POLICY_AGENT` (write
  `qa-f08-policy.txt`, finish).

```sh
control-agent-server llm preset deepseek
W="$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f08"
mkdir -p "$W/knobs" "$W/accept" "$W/reject/qa-f08-victim" "$W/risky/qa-f08-victim" "$W/secret" "$W/rotate" \
  "$W/scoped" "$W/real" "$W/policy" "$W/analyzer"
NOPE=$(python3 -c 'import uuid; print(uuid.uuid4())')
OFFLINE_AGENT='{"llm": {"model": "openai/qa-offline", "api_key": "qa-offline-key", "base_url": "http://127.0.0.1:9/v1", "num_retries": 0}, "tools": []}'
MSG='{"role": "user", "content": [{"type": "text", "text": "Run the command."}]}'
stub_agent() {
  printf '{"llm": {"model": "openai/qa-stub", "api_key": "qa-stub-key", "base_url": "%s/v1", "num_retries": 0}, "tools": [{"name": "terminal"}]}' \
    "$(control-agent-server fixture llm-stub --name "$@" --print-path)"
}
FINISH='tool:finish:{"message":"QA_F08_DONE"}'
ACCEPT_AGENT=$(stub_agent qa-f08-accept --step 'tool:terminal:{"command":"echo qa-accepted > qa-f08-accepted.txt"}' --step "$FINISH")
REJECT_AGENT=$(stub_agent qa-f08-reject --step 'tool:terminal:{"command":"rm -rf qa-f08-victim"}' --step "$FINISH")
RISKY_AGENT=$(stub_agent qa-f08-risky --step 'tool:terminal:{"command":"echo qa-low > qa-f08-low.txt"}' \
  --step 'tool:terminal:{"command":"rm -rf qa-f08-victim"}' --step 'tool:terminal:{"command":"echo qa-unrated > qa-f08-unrated.txt"}' --step "$FINISH")
SECRET_STEP='tool:terminal:{"command":"printf %s \"$QA_F08_TOKEN\" > qa-f08-token.txt; echo \"token=$QA_F08_TOKEN\""}'
SECRET_AGENT=$(stub_agent qa-f08-secret --step "$SECRET_STEP" --step "$FINISH" --step "$SECRET_STEP" --step "$FINISH")
ROTATE_STEP='tool:terminal:{"command":"printf %s \"$QA_F08_ROT\" > qa-f08-rot.txt"}'
ROTATE_AGENT=$(stub_agent qa-f08-rotate --step "$ROTATE_STEP" --step "$FINISH" --step "$ROTATE_STEP" --step "$FINISH")
POLICY_AGENT=$(stub_agent qa-f08-policy --step 'tool:terminal:{"command":"echo qa-policy > qa-f08-policy.txt"}' --step "$FINISH")
REJECT_KIND=openhands.sdk.event.llm_convertible.observation.UserRejectObservation
OBSERVATION_KIND=openhands.sdk.event.llm_convertible.observation.ObservationEvent
```

- **Set the confirmation policy (`F08.policy-set`).** An idle conversation
  starts with `NeverConfirm`; a socket capture records each change.
  ```sh
  KID=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W/knobs\"}, \"agent\": $OFFLINE_AGENT, \"autotitle\": false}" \
    --expect 201 --check confirmation_policy.kind eq NeverConfirm --check security_analyzer eq null --field id)
  control-agent-server ws start "/sockets/events/$KID" --name qa-f08-policy --duration 120
  control-agent-server api POST "/api/conversations/$KID/confirmation_policy" --json '{"policy": {"kind": "AlwaysConfirm"}}' \
    --expect 200 --check success eq true --save F08.policy-set/always
  control-agent-server api GET "/api/conversations/$KID" --check confirmation_policy.kind eq AlwaysConfirm
  control-agent-server state cat "server/workspace/conversations/${KID//-/}/base_state.json" --max-chars 200 \
    --check confirmation_policy.kind eq AlwaysConfirm
  control-agent-server api POST "/api/conversations/$KID/confirmation_policy" \
    --json '{"policy": {"kind": "ConfirmRisky", "threshold": "MEDIUM", "confirm_unknown": false}}' --expect 200
  control-agent-server api GET "/api/conversations/$KID" --check confirmation_policy.kind eq ConfirmRisky \
    --check confirmation_policy.threshold eq MEDIUM --check confirmation_policy.confirm_unknown eq false --save F08.policy-set/risky
  control-agent-server api POST "/api/conversations/$KID/confirmation_policy" --json '{"policy": {"kind": "NeverConfirm"}}' --expect 200
  control-agent-server api GET "/api/conversations/$KID" --check confirmation_policy.kind eq NeverConfirm
  control-agent-server ws stop qa-f08-policy --kinds ConversationStateUpdateEvent --contains '"threshold": "MEDIUM"' --save F08.policy-set/socket
  control-agent-server conversation events "$KID" --key confirmation_policy --contains ConfirmRisky
  ```
  Each POST is 200 `{"success": true}`, the next GET and `base_state.json`
  show the new policy (`ConfirmRisky` keeps `threshold` `MEDIUM` and
  `confirm_unknown` `false`), and the socket pushed a `confirmation_policy`
  state update for each change.
- **Policy errors (`F08.policy-errors`).** Bad bodies, an unknown id, no key.
  ```sh
  control-agent-server api POST "/api/conversations/$KID/confirmation_policy" --json '{"policy": {"kind": "SometimesConfirm"}}' \
    --expect 422 --check detail.0.msg contains 'Unknown kind' --save F08.policy-errors/unknown-kind
  control-agent-server api POST "/api/conversations/$KID/confirmation_policy" --json '{"policy": {"kind": "ConfirmRisky", "threshold": "UNKNOWN"}}' \
    --expect 422 --check detail.0.msg contains 'cannot be UNKNOWN'
  control-agent-server api POST "/api/conversations/$KID/confirmation_policy" --json '{"policy": {"kind": "ConfirmRisky", "threshold": "EXTREME"}}' \
    --expect 422 --check detail.0.loc contains threshold
  control-agent-server api POST "/api/conversations/$KID/confirmation_policy" --json '{}' --expect 422 --check detail.0.loc contains policy
  control-agent-server api POST "/api/conversations/$KID/confirmation_policy" --json '{"policy": {}}' --expect 422
  control-agent-server api POST "/api/conversations/$NOPE/confirmation_policy" --json '{"policy": {"kind": "AlwaysConfirm"}}' --expect 404
  control-agent-server api POST "/api/conversations/$KID/confirmation_policy" --json '{"policy": {"kind": "AlwaysConfirm"}}' --auth none --expect 401
  control-agent-server api GET "/api/conversations/$KID" --check confirmation_policy.kind eq NeverConfirm
  ```
  Every status matches and the policy is still `NeverConfirm`.
- **Wait for confirmation (`F08.always-confirm-wait`).** A runtime switch to
  `AlwaysConfirm`, then a message; the socket is captured from before the
  message.
  ```sh
  AID=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W/accept\"}, \"agent\": $ACCEPT_AGENT, \"autotitle\": false}" --expect 201 --field id)
  control-agent-server api POST "/api/conversations/$AID/confirmation_policy" --json '{"policy": {"kind": "AlwaysConfirm"}}' --expect 200
  control-agent-server ws start "/sockets/events/$AID" --name qa-f08-wait --duration 120
  control-agent-server conversation send "$AID" --text 'Run the command.' --wait --until waiting_for_confirmation --timeout 120
  control-agent-server api GET "/api/conversations/$AID" --check execution_status eq waiting_for_confirmation \
    --check confirmation_policy.kind eq AlwaysConfirm --save F08.always-confirm-wait/waiting
  control-agent-server conversation events "$AID" --kinds ActionEvent --contains qa-f08-accepted.txt
  control-agent-server api GET "/api/conversations/$AID/events/count" --query kind="$OBSERVATION_KIND" --check . eq 0
  test ! -e "$W/accept/qa-f08-accepted.txt"
  control-agent-server ws stop qa-f08-wait --kinds ConversationStateUpdateEvent --contains waiting_for_confirmation --save F08.always-confirm-wait/socket
  ```
  The conversation waits with the terminal `ActionEvent` recorded, no
  observation and no file; the socket pushed `execution_status`
  `waiting_for_confirmation`.
- **Accept (`F08.confirm-accept`).** Approve the pending command.
  ```sh
  control-agent-server api POST "/api/conversations/$AID/events/respond_to_confirmation" --json '{"accept": true}' \
    --expect 200 --check success eq true --save F08.confirm-accept/accept
  control-agent-server conversation wait "$AID" --until finished --timeout 120
  test "$(cat "$W/accept/qa-f08-accepted.txt")" = qa-accepted
  control-agent-server conversation events "$AID" --kinds ObservationEvent --contains qa-f08-accepted.txt
  control-agent-server api GET "/api/conversations/$AID/agent_final_response" --check response eq QA_F08_DONE --save F08.confirm-accept/final
  ```
  The command ran (the file holds `qa-accepted`, the terminal observation is
  recorded) and the agent finished with the stub's `finish` message.
- **Reject (`F08.confirm-reject`).** A conversation created with
  `AlwaysConfirm` in the start body proposes `rm -rf qa-f08-victim`.
  ```sh
  RJ=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W/reject\"}, \"agent\": $REJECT_AGENT, \"autotitle\": false, \"confirmation_policy\": {\"kind\": \"AlwaysConfirm\"}, \"initial_message\": $MSG}" \
    --expect 201 --field id)
  control-agent-server conversation wait "$RJ" --until waiting_for_confirmation --timeout 120
  control-agent-server ws start "/sockets/events/$RJ" --name qa-f08-reject --duration 120
  control-agent-server api POST "/api/conversations/$RJ/events/respond_to_confirmation" \
    --json '{"accept": false, "reason": "QA_F08 rejected"}' --expect 200 --save F08.confirm-reject/reject
  control-agent-server conversation wait "$RJ" --until idle --timeout 60
  test -d "$W/reject/qa-f08-victim"
  control-agent-server api GET "/api/conversations/$RJ/events/search" --query kind="$REJECT_KIND" \
    --check items len-eq 1 --check items.0.rejection_reason eq 'QA_F08 rejected' --check items.0.tool_name eq terminal \
    --save F08.confirm-reject/observation
  control-agent-server ws stop qa-f08-reject --kinds UserRejectObservation --contains 'QA_F08 rejected' --save F08.confirm-reject/socket
  control-agent-server api POST "/api/conversations/$RJ/events/respond_to_confirmation" --json '{"accept": false, "reason": "again"}' --expect 200
  control-agent-server api GET "/api/conversations/$RJ/events/count" --query kind="$REJECT_KIND" --check . eq 1
  control-agent-server api POST "/api/conversations/$RJ/events/respond_to_confirmation" --json '{"accept": true}' --expect 200
  control-agent-server conversation wait "$RJ" --until finished --timeout 120
  control-agent-server api GET "/api/conversations/$RJ/agent_final_response" --check response eq QA_F08_DONE
  test -d "$W/reject/qa-f08-victim"
  ```
  The reject is 200, the conversation goes back to `idle`, one
  `UserRejectObservation` carries the reason (also pushed on the socket) and
  the victim folder survives. A second reject finds nothing pending and adds
  nothing. The later accept has nothing pending either, so it just runs the
  agent, which finishes; the rejected command never runs.
- **Confirmation errors (`F08.confirm-errors`).** Bad bodies, ids and auth.
  ```sh
  control-agent-server api POST "/api/conversations/$RJ/events/respond_to_confirmation" --json '{}' \
    --expect 422 --check detail.0.loc contains accept --save F08.confirm-errors/missing-accept
  control-agent-server api POST "/api/conversations/$RJ/events/respond_to_confirmation" --json '{"accept": "maybe"}' --expect 422
  control-agent-server api POST /api/conversations/not-a-uuid/events/respond_to_confirmation --json '{"accept": false}' --expect 422
  control-agent-server api POST "/api/conversations/$NOPE/events/respond_to_confirmation" --json '{"accept": false}' \
    --expect 404 --check detail contains 'Conversation not found'
  control-agent-server api POST "/api/conversations/$RJ/events/respond_to_confirmation" --json '{"accept": false}' --auth none --expect 401
  ```
  All statuses match.
- **Accept with the run capacity full (`F08.confirm-capacity`).** A second
  server limited to one concurrent run: conversation `X` waits for
  confirmation (a parked conversation holds no run slot), a conversation on
  a hanging stub takes the only slot, then `X` is accepted.
  ```sh
  B=$(control-agent-server launch --new --name f08-cap --print-run --config-json '{"max_concurrent_runs": 1}' --env TMUX_TMPDIR=/tmp/qa-f08-tmux)
  trap 'control-agent-server stop --run "$B" >/dev/null' EXIT
  CAP_STUB=$(control-agent-server fixture llm-stub --run "$B" --name qa-f08-cap \
    --step 'tool:terminal:{"command":"echo qa-cap > qa-f08-cap.txt"}' --step "$FINISH" --print-path)
  HANG_STUB=$(control-agent-server fixture llm-stub --run "$B" --name qa-f08-hang --step hang:300 --print-path)
  mkdir -p "$W/cap" "$W/hang"
  X=$(control-agent-server api POST /api/conversations --run "$B" \
    --json "{\"workspace\": {\"working_dir\": \"$W/cap\"}, \"agent\": {\"llm\": {\"model\": \"openai/qa-stub\", \"api_key\": \"qa-stub-key\", \"base_url\": \"$CAP_STUB/v1\", \"num_retries\": 0}, \"tools\": [{\"name\": \"terminal\"}]}, \"autotitle\": false, \"confirmation_policy\": {\"kind\": \"AlwaysConfirm\"}, \"initial_message\": $MSG}" \
    --expect 201 --field id)
  control-agent-server conversation wait "$X" --run "$B" --until waiting_for_confirmation --timeout 120
  Y=$(control-agent-server api POST /api/conversations --run "$B" \
    --json "{\"workspace\": {\"working_dir\": \"$W/hang\"}, \"agent\": {\"llm\": {\"model\": \"openai/qa-stub\", \"api_key\": \"qa-stub-key\", \"base_url\": \"$HANG_STUB/v1\", \"num_retries\": 0}, \"tools\": []}, \"autotitle\": false, \"initial_message\": $MSG}" \
    --expect 201 --field id)
  control-agent-server conversation wait "$Y" --run "$B" --until running --timeout 60
  control-agent-server api POST "/api/conversations/$X/events/respond_to_confirmation" --run "$B" --json '{"accept": true}' \
    --expect 429 --check detail contains 'run limit' --save F08.confirm-capacity/accept-429
  control-agent-server api GET "/api/conversations/$X" --run "$B" --check execution_status eq waiting_for_confirmation
  test ! -e "$W/cap/qa-f08-cap.txt"
  control-agent-server api POST "/api/conversations/$X/events/respond_to_confirmation" --run "$B" --json '{"accept": false}' --expect 200
  control-agent-server conversation wait "$X" --run "$B" --until idle --timeout 60
  control-agent-server api POST "/api/conversations/$Y/events/respond_to_confirmation" --run "$B" --json '{"accept": true}' \
    --expect 200 --save F08.confirm-capacity/accept-running
  control-agent-server api GET "/api/conversations/$Y" --run "$B" --check execution_status eq running
  test ! -e "$W/cap/qa-f08-cap.txt"
  ```
  The accept is 429 `Conversation run limit reached` and `X` keeps waiting
  with its command unrun; the reject needs no slot and succeeds; an accept
  on the running conversation is a 200 no-op. The trap stops the second
  server.
- **A real model asks first (`F08.confirm-real`).** DeepSeek flash with the
  terminal tool and `AlwaysConfirm`; every action it proposes is accepted
  until it finishes.
  ```sh
  REAL=$(control-agent-server conversation start --tools terminal --no-autotitle --confirmation-policy always --workspace "$W/real" \
    --prompt 'Use the terminal tool to run exactly this one command, then finish: echo qa-f08-real > qa-f08-real.txt' \
    --wait --until waiting_for_confirmation --timeout 300 --save F08.confirm-real/start --print-id)
  test ! -e "$W/real/qa-f08-real.txt"
  control-agent-server conversation events "$REAL" --kinds ActionEvent --contains qa-f08-real
  for _ in 1 2 3 4 5 6 7 8; do
    STATUS=$(control-agent-server api GET "/api/conversations/$REAL" --field execution_status)
    if [ "$STATUS" = finished ]; then break; fi
    if [ "$STATUS" = waiting_for_confirmation ]; then
      control-agent-server api POST "/api/conversations/$REAL/events/respond_to_confirmation" --json '{"accept": true}' --expect 200 --field success
    fi
    control-agent-server conversation wait "$REAL" --until waiting_for_confirmation,finished,error --timeout 300
  done
  control-agent-server api GET "/api/conversations/$REAL" --check execution_status eq finished --save F08.confirm-real/finished
  test "$(cat "$W/real/qa-f08-real.txt")" = qa-f08-real
  ```
  The model's first terminal action waits and has not run; after the accepts
  the file holds `qa-f08-real` and the conversation is `finished`. The loop
  tolerates a model that adds a check command (each is accepted) and a
  status read that is still `waiting_for_confirmation` right after an accept
  (a repeated accept is a no-op).
- **Set and clear the analyzer (`F08.analyzer-set-clear`).** On the idle
  conversation from the first bullet.
  ```sh
  control-agent-server ws start "/sockets/events/$KID" --name qa-f08-analyzer --duration 120
  control-agent-server api POST "/api/conversations/$KID/security_analyzer" --json '{"security_analyzer": {"kind": "PatternSecurityAnalyzer"}}' \
    --expect 200 --check success eq true --save F08.analyzer-set-clear/pattern
  control-agent-server api GET "/api/conversations/$KID" --check security_analyzer.kind eq PatternSecurityAnalyzer \
    --check security_analyzer.high_patterns len-ge 1
  control-agent-server state cat "server/workspace/conversations/${KID//-/}/base_state.json" --max-chars 200 \
    --check security_analyzer.kind eq PatternSecurityAnalyzer
  control-agent-server api POST "/api/conversations/$KID/security_analyzer" --json '{"security_analyzer": {"kind": "LLMSecurityAnalyzer"}}' --expect 200
  control-agent-server api GET "/api/conversations/$KID" --check security_analyzer.kind eq LLMSecurityAnalyzer
  control-agent-server api POST "/api/conversations/$KID/security_analyzer" --json '{"security_analyzer": null}' --expect 200
  control-agent-server api GET "/api/conversations/$KID" --check security_analyzer eq null --save F08.analyzer-set-clear/cleared
  control-agent-server ws stop qa-f08-analyzer --kinds ConversationStateUpdateEvent --contains LLMSecurityAnalyzer --save F08.analyzer-set-clear/socket
  ```
  GET and `base_state.json` follow each change (`PatternSecurityAnalyzer`
  comes back with its default pattern lists), the clear leaves `null`, and
  the socket pushed `security_analyzer` state updates.
- **Analyzer errors (`F08.analyzer-errors`).** The field is required even to
  clear it.
  ```sh
  control-agent-server api POST "/api/conversations/$KID/security_analyzer" --json '{}' \
    --expect 422 --check detail.0.loc contains security_analyzer --save F08.analyzer-errors/missing
  control-agent-server api POST "/api/conversations/$KID/security_analyzer" --json '{"security_analyzer": {"kind": "NopeAnalyzer"}}' \
    --expect 422 --check detail.0.msg contains 'Unknown kind'
  control-agent-server api POST "/api/conversations/$NOPE/security_analyzer" --json '{"security_analyzer": null}' --expect 404
  control-agent-server api POST "/api/conversations/$KID/security_analyzer" --json '{"security_analyzer": null}' --auth none --expect 401
  control-agent-server api GET "/api/conversations/$KID" --check security_analyzer eq null
  ```
  All statuses match and the analyzer is still `null`.
- **Risk-based confirmation (`F08.confirm-risky`).** `ConfirmRisky` (default
  threshold `HIGH`, `confirm_unknown` true) with `PatternSecurityAnalyzer`
  set at runtime; the stub proposes `echo`, then `rm -rf qa-f08-victim`, then
  another `echo`.
  ```sh
  RK=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W/risky\"}, \"agent\": $RISKY_AGENT, \"autotitle\": false}" --expect 201 --field id)
  control-agent-server api POST "/api/conversations/$RK/confirmation_policy" --json '{"policy": {"kind": "ConfirmRisky"}}' --expect 200
  control-agent-server api GET "/api/conversations/$RK" --check confirmation_policy.threshold eq HIGH --check confirmation_policy.confirm_unknown eq true
  control-agent-server api POST "/api/conversations/$RK/security_analyzer" --json '{"security_analyzer": {"kind": "PatternSecurityAnalyzer"}}' --expect 200
  control-agent-server conversation send "$RK" --text 'Run the commands.' --wait --until waiting_for_confirmation --timeout 120
  test "$(cat "$W/risky/qa-f08-low.txt")" = qa-low
  test -d "$W/risky/qa-f08-victim"
  control-agent-server conversation events "$RK" --kinds ActionEvent --show 1 --contains 'rm -rf' --save F08.confirm-risky/held
  control-agent-server api POST "/api/conversations/$RK/events/respond_to_confirmation" --json '{"accept": false, "reason": "QA_F08 high risk"}' --expect 200
  control-agent-server api POST "/api/conversations/$RK/security_analyzer" --json '{"security_analyzer": null}' --expect 200
  control-agent-server api POST "/api/conversations/$RK/events/respond_to_confirmation" --json '{"accept": true}' --expect 200
  control-agent-server conversation wait "$RK" --until waiting_for_confirmation --timeout 120
  test ! -e "$W/risky/qa-f08-unrated.txt"
  control-agent-server api POST "/api/conversations/$RK/events/respond_to_confirmation" --json '{"accept": true}' --expect 200
  control-agent-server conversation wait "$RK" --until finished --timeout 120
  test "$(cat "$W/risky/qa-f08-unrated.txt")" = qa-unrated
  test -d "$W/risky/qa-f08-victim"
  ```
  The low-risk `echo` ran without asking, `rm -rf` (rated `HIGH` by the
  pattern analyzer) waited and was rejected, so the victim folder survives.
  With the analyzer cleared, the next `echo` is unrated (`UNKNOWN`) and
  `confirm_unknown` makes it wait; accepting it lets the agent finish.
- **Update secrets (`F08.secrets-update`).** The three accepted value forms,
  on the idle conversation `$KID`. A tags PATCH forces a state save first
  (see the next bullet for why).
  ```sh
  control-agent-server api POST "/api/conversations/$KID/secrets" \
    --json '{"secrets": {"QA_F08_PLAIN": "qa-f08-plain-value", "QA_F08_DICT": {"value": "qa-f08-dict-value"}, "QA_F08_STATIC": {"kind": "StaticSecret", "value": "qa-f08-static-value", "description": "qa static"}}}' \
    --expect 200 --check success eq true --save F08.secrets-update/post
  control-agent-server api PATCH "/api/conversations/$KID" --json '{"tags": {"qa": "f08-save"}}' --expect 200 --check success eq true
  control-agent-server api GET "/api/conversations/$KID" --expect 200 \
    --check secret_registry.secret_sources.QA_F08_PLAIN.kind eq StaticSecret \
    --check secret_registry.secret_sources.QA_F08_PLAIN.value ne qa-f08-plain-value \
    --check secret_registry.secret_sources.QA_F08_DICT.kind eq StaticSecret \
    --check secret_registry.secret_sources.QA_F08_STATIC.description eq 'qa static' \
    --check secret_registry.secret_sources.QA_F08_STATIC.value ne qa-f08-static-value --save F08.secrets-update/get
  control-agent-server state cat "server/workspace/conversations/${KID//-/}/base_state.json" --max-chars 200 \
    --check secret_registry.secret_sources.QA_F08_PLAIN.value exists --not-contains qa-f08-plain-value
  control-agent-server state grep qa-f08-dict-value --glob 'server/**/*' --expect-none
  control-agent-server state grep qa-f08-static-value --glob 'server/**/*' --expect-none
  ```
  The POST is 200; after the save GET lists all three names as
  `StaticSecret` with `value` `null` (masked) and the description kept, and
  `base_state.json` holds cipher text, never the plaintext.
- **Runtime secret visible to GET (`F08.secrets-visible`), known bug.** Post
  one more secret and read the conversation right away.
  ```sh
  control-agent-server api POST "/api/conversations/$KID/secrets" --json '{"secrets": {"QA_F08_FRESH": "qa-f08-fresh-value"}}' --expect 200
  control-agent-server api GET "/api/conversations/$KID" --check secret_registry.secret_sources.QA_F08_FRESH.kind eq StaticSecret \
    --save F08.secrets-visible/get
  ```
  Expected: GET lists `QA_F08_FRESH`. Today it does not:
  `LocalConversation.update_secrets` mutates
  `state.secret_registry.secret_sources` in place, the state only autosaves
  on attribute assignment, and GET reads the `base_state.json` snapshot. The
  name appears after the next state change (a PATCH, a message, a policy
  change); until then the live registry has it but no reader can see it, and
  a restart loses it (`F08.secrets-unsaved-restart`).
- **Secret errors (`F08.secrets-errors`).** Bad bodies, an unknown id, no key.
  ```sh
  control-agent-server api POST "/api/conversations/$KID/secrets" --json '{}' --expect 422 --check detail.0.loc contains secrets \
    --save F08.secrets-errors/missing
  control-agent-server api POST "/api/conversations/$KID/secrets" --json '{"secrets": "qa"}' --expect 422 --check detail.0.type eq dict_type
  control-agent-server api POST "/api/conversations/$KID/secrets" --json '{"secrets": {"QA_F08_BAD": {"kind": "NopeSecret", "value": "x"}}}' \
    --expect 422 --check detail.0.msg contains 'Unknown kind'
  control-agent-server api POST "/api/conversations/$KID/secrets" --json '{"secrets": {"QA_F08_LOOKUP": {"kind": "LookupSecret"}}}' \
    --expect 422 --check detail.0.loc contains url
  control-agent-server api POST "/api/conversations/$NOPE/secrets" --json '{"secrets": {"QA_F08_X": "qa-x"}}' --expect 404
  control-agent-server api POST "/api/conversations/$KID/secrets" --json '{"secrets": {"QA_F08_X": "qa-x"}}' --auth none --expect 401
  control-agent-server api PATCH "/api/conversations/$KID" --json '{"tags": {"qa": "f08-errors"}}' --expect 200
  control-agent-server api GET "/api/conversations/$KID" --check secret_registry.secret_sources.QA_F08_BAD missing \
    --check secret_registry.secret_sources.QA_F08_LOOKUP missing --check secret_registry.secret_sources.QA_F08_X missing \
    --check secret_registry.secret_sources.QA_F08_PLAIN exists
  ```
  Every status matches and, after a save, none of the refused names is
  stored while the earlier secrets remain.
- **Non-string secret value (`F08.secrets-bad-value`), known bug.** A number
  (or `null`) where a value belongs.
  ```sh
  control-agent-server api POST "/api/conversations/$KID/secrets" --json '{"secrets": {"QA_F08_NUMBER": 5}}' \
    --expect 422 --save F08.secrets-bad-value/number
  control-agent-server api POST "/api/conversations/$KID/secrets" --json '{"secrets": {"QA_F08_NULL": null}}' --expect 422
  ```
  Expected: 422 like any other invalid body. Today both are 500
  `"exception": "'int' object has no attribute 'pop'"` (`'NoneType'` for
  `null`): `UpdateSecretsRequest.convert_string_secrets` passes non-string,
  non-dict values through, and `DiscriminatedUnionMixin` calls `.pop("kind")`
  on them, an `AttributeError` that escapes request validation. Same root
  cause as `F04.create-secrets-plain`.
- **Secrets in the terminal (`F08.secrets-terminal`).** The stub's command
  writes `$QA_F08_TOKEN` to a file and echoes it.
  ```sh
  SID=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W/secret\"}, \"agent\": $SECRET_AGENT, \"autotitle\": false}" --expect 201 --field id)
  control-agent-server api POST "/api/conversations/$SID/secrets" --json '{"secrets": {"QA_F08_TOKEN": "qa-f08-token-value"}}' \
    --expect 200 --save F08.secrets-terminal/post
  control-agent-server conversation send "$SID" --text 'Run the command.' --wait --until finished --timeout 120
  test "$(cat "$W/secret/qa-f08-token.txt")" = qa-f08-token-value
  control-agent-server conversation events "$SID" --kinds ObservationEvent --contains 'token=<secret-hidden>' \
    --save F08.secrets-terminal/observation
  control-agent-server sink read --name qa-f08-secret --contains 'token=<secret-hidden>' --expect-min 1
  ! grep -q qa-f08-token-value "$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f08-secret.jsonl"
  control-agent-server state grep qa-f08-token-value --glob 'server/**/*' --expect-none
  control-agent-server api GET "/api/conversations/$SID" --check secret_registry.secret_sources.QA_F08_TOKEN.kind eq StaticSecret
  ```
  The file holds the real value, so the command got it as an environment
  variable; the observation reads `token=<secret-hidden>`, the model's next
  request carries the masked text and never the value, and no server file
  holds the plaintext. The run saved the state, so GET lists the name.
- **Override a start-time secret (`F08.secrets-override`).** A conversation
  created with `QA_F08_ROT` = `qa-f08-rot-old`, then a runtime POST of a new
  value.
  ```sh
  ROT=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W/rotate\"}, \"agent\": $ROTATE_AGENT, \"autotitle\": false, \"secrets\": {\"QA_F08_ROT\": {\"kind\": \"StaticSecret\", \"value\": \"qa-f08-rot-old\"}}}" \
    --expect 201 --field id)
  control-agent-server api POST "/api/conversations/$ROT/secrets" --json '{"secrets": {"QA_F08_ROT": "qa-f08-rot-new"}}' \
    --expect 200 --save F08.secrets-override/post
  control-agent-server conversation send "$ROT" --text 'Run the command.' --wait --until finished --timeout 120
  test "$(cat "$W/rotate/qa-f08-rot.txt")" = qa-f08-rot-new
  rm "$W/rotate/qa-f08-rot.txt"
  ```
  The command wrote `qa-f08-rot-new`: the runtime value replaced the
  start-time one in the live registry.
- **Agent Profile secret scope (`F08.secrets-profile-scope`).** An Agent
  Profile that allows only `QA_F08_ALLOWED`.
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f08-scoped \
    --json '{"llm_profile_ref": "deepseek-flash", "tools": [], "secret_refs": ["QA_F08_ALLOWED"]}' --expect 201
  SCOPED_PROFILE=$(control-agent-server api GET /api/agent-profiles/qa-f08-scoped --field profile.id)
  PSC=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W/scoped\"}, \"agent_profile_id\": \"$SCOPED_PROFILE\", \"autotitle\": false}" \
    --expect 201 --check launched_agent_profile.secret_refs contains QA_F08_ALLOWED --field id)
  control-agent-server api POST "/api/conversations/$PSC/secrets" \
    --json '{"secrets": {"QA_F08_ALLOWED": "qa-f08-allowed-value", "QA_F08_OTHER": "qa-f08-other-value"}}' --expect 200 --check success eq true
  control-agent-server api PATCH "/api/conversations/$PSC" --json '{"tags": {"qa": "f08-scope"}}' --expect 200
  control-agent-server api GET "/api/conversations/$PSC" --check secret_registry.secret_sources.QA_F08_ALLOWED.kind eq StaticSecret \
    --check secret_registry.secret_sources.QA_F08_OTHER missing --save F08.secrets-profile-scope/get
  control-agent-server api DELETE /api/agent-profiles/qa-f08-scoped --expect 200
  ```
  The POST is 200 for both names, but only `QA_F08_ALLOWED` is stored: the
  launched profile's `secret_refs` filter runtime secrets without an error.
- **Restart with runtime knobs (`F08.secrets-restart`).** Arrange the state
  the restart bullets read, restart, and prove a saved runtime secret still
  reaches the terminal.
  ```sh
  PR=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W/policy\"}, \"agent\": $POLICY_AGENT, \"autotitle\": false}" --expect 201 --field id)
  control-agent-server api POST "/api/conversations/$PR/confirmation_policy" --json '{"policy": {"kind": "AlwaysConfirm"}}' --expect 200
  control-agent-server api GET "/api/conversations/$PR" --check confirmation_policy.kind eq AlwaysConfirm
  PA=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W/analyzer\"}, \"agent\": $OFFLINE_AGENT, \"autotitle\": false}" --expect 201 --field id)
  control-agent-server api POST "/api/conversations/$PA/security_analyzer" --json '{"security_analyzer": {"kind": "PatternSecurityAnalyzer"}}' --expect 200
  control-agent-server api GET "/api/conversations/$PA" --check security_analyzer.kind eq PatternSecurityAnalyzer
  control-agent-server api PATCH "/api/conversations/$ROT" --json '{"tags": {"qa": "f08-rotated"}}' --expect 200
  control-agent-server api GET "/api/conversations/$ROT" --check secret_registry.secret_sources.QA_F08_ROT.kind eq StaticSecret
  control-agent-server api POST "/api/conversations/$KID/secrets" --json '{"secrets": {"QA_F08_UNSAVED": "qa-f08-unsaved-value"}}' --expect 200
  rm "$W/secret/qa-f08-token.txt"
  control-agent-server restart
  control-agent-server doctor
  control-agent-server conversation send "$SID" --text 'Run it again.' --wait --until finished --timeout 120
  test "$(cat "$W/secret/qa-f08-token.txt")" = qa-f08-token-value
  control-agent-server api GET "/api/conversations/$SID" --check secret_registry.secret_sources.QA_F08_TOKEN.kind eq StaticSecret \
    --save F08.secrets-restart/after-restart
  ```
  Before the restart `$PR` runs `AlwaysConfirm`, `$PA` has the pattern
  analyzer, `$ROT`'s override is saved, and `$KID` has one secret posted
  with no save after it. After the restart the server is healthy and
  `QA_F08_TOKEN` (saved encrypted with the run's `OH_SECRET_KEY`) is
  injected again.
- **Unsaved secret across a restart (`F08.secrets-unsaved-restart`), known
  bug.** `QA_F08_UNSAVED` was posted to `$KID` right before the restart.
  ```sh
  control-agent-server api PATCH "/api/conversations/$KID" --json '{"tags": {"qa": "f08-after-restart"}}' --expect 200
  control-agent-server api GET "/api/conversations/$KID" --check secret_registry.secret_sources.QA_F08_PLAIN exists \
    --check secret_registry.secret_sources.QA_F08_UNSAVED exists --save F08.secrets-unsaved-restart/get
  ```
  Expected: both names after the restart. Today `QA_F08_PLAIN` (saved by an
  earlier PATCH) is there and `QA_F08_UNSAVED` is gone: the POST never
  reached `base_state.json` (see `F08.secrets-visible`) and runtime secrets
  are not written to `meta.json`, so a restart, an idle eviction (default
  20 minutes) or a sandbox pause right after `POST .../secrets` silently
  drops it.
- **Override across a restart (`F08.secrets-override-restart`), known bug.**
  Run `$ROT`'s command again after the restart.
  ```sh
  control-agent-server conversation send "$ROT" --text 'Run it again.' --wait --until finished --timeout 120
  test "$(cat "$W/rotate/qa-f08-rot.txt")" = qa-f08-rot-new
  ```
  Expected: `qa-f08-rot-new`, as before the restart. Today the file holds
  `qa-f08-rot-old`: `EventService.start` passes the start-time
  `stored.secrets` (from `meta.json`) to `LocalConversation`, which applies
  them over the persisted registry, and `EventService.update_secrets` never
  updates `stored.secrets` (unlike `apply_resume_secrets`). A rotated
  credential silently reverts to the old one after any reload.
- **Policy across a restart (`F08.policy-restart`), known bug.** `$PR` was
  switched to `AlwaysConfirm` at runtime before the restart; send it a
  message now.
  ```sh
  control-agent-server api GET "/api/conversations/$PR" --check confirmation_policy.kind eq AlwaysConfirm
  control-agent-server conversation send "$PR" --text 'Run the command.' --wait --until waiting_for_confirmation,finished --timeout 120
  control-agent-server api GET "/api/conversations/$PR" --check confirmation_policy.kind eq AlwaysConfirm \
    --check execution_status eq waiting_for_confirmation --save F08.policy-restart/after-message
  test ! -e "$W/policy/qa-f08-policy.txt"
  ```
  Expected: the policy is still `AlwaysConfirm` and the command waits.
  Today the first GET (a cold read of `base_state.json`) still says
  `AlwaysConfirm`, but loading the conversation re-applies the start-time
  `NeverConfirm` from `meta.json` (`EventService.start` calls
  `set_confirmation_policy(self.stored.confirmation_policy)`), so the
  command runs unasked, the conversation finishes, and GET then reports
  `NeverConfirm` without any state update event. The same happens after an
  idle eviction (`conversation_idle_ttl_seconds`, default 1200), so a
  confirmation mode switched on at runtime silently turns off.
- **Analyzer across a restart (`F08.analyzer-restart`), known bug.** `$PA`
  got `PatternSecurityAnalyzer` at runtime before the restart; load it.
  ```sh
  control-agent-server api PATCH "/api/conversations/$PA" --json '{"tags": {"qa": "f08-after-restart"}}' --expect 200
  control-agent-server api GET "/api/conversations/$PA" --check security_analyzer.kind eq PatternSecurityAnalyzer \
    --save F08.analyzer-restart/get
  ```
  Expected: the analyzer is still set. Today it is `null`: the reload
  re-applies the start-time analyzer from `meta.json` (none), the same
  mechanism as `F08.policy-restart`.

## Gotchas

- Tmux socket paths: with the default `TMUX_TMPDIR` (`<run>/tmux`) a run
  directory such as `.../20261007-013126-8262-map-f08` makes the socket path
  108 bytes, over the Unix limit, and creating any conversation with the
  `terminal` tool fails with 500 `error connecting to ... (File name too
  long)`. The `Launch:` flag points tmux at `/tmp/qa-f08-tmux` (sockets have
  random names, so concurrent runs do not collide). A bullet that launches a
  second server passes the same `--env`.
- `respond_to_confirmation` with `accept: true` is exactly a run request: it
  needs a run slot (429 when full), it is a no-op on a running conversation,
  and with nothing pending it simply resumes the agent. `accept: false` with
  nothing pending is a 200 no-op. After an accept the status read by GET can
  stay `waiting_for_confirmation` for a moment, because the run starts in the
  background.
- A conversation parked in `waiting_for_confirmation` holds no run slot; the
  agent's run ends at the pending action and a new run starts on accept,
  which executes the pending action without calling the model.
- `ActionEvent.security_risk` is the risk the model declared (here always
  `UNKNOWN`, the stub declares none); the analyzer's rating
  (`PatternSecurityAnalyzer` rated `rm -rf` `HIGH`) is not recorded on the
  event, so clients cannot see why an action was held.
- A single `finish` or `think` action never needs confirmation, even under
  `AlwaysConfirm`; with no analyzer every action is rated `UNKNOWN`, so
  `ConfirmRisky` asks for every action unless `confirm_unknown` is false.
- Secret values come back as `null` in GET (masked) and as cipher text in
  `base_state.json`. Without `OH_SECRET_KEY` and without a session key there
  is no cipher and secrets are dropped on save; `launch` sets both.
- A command receives a secret only when its text mentions the secret's name
  (case-insensitive substring match); masking applies to every registered
  secret's last resolved value, wherever it appears in terminal output.
- Runtime changes made through these four routes live only in
  `base_state.json`; `meta.json` keeps the start-time `confirmation_policy`,
  `security_analyzer` and `secrets` and wins on every reload (restart, idle
  eviction, sandbox pause). See the four restart bullets.
- Unknown conversations answer 404 `{"detail": "Not Found"}` on the
  conversation routes and 404 `Conversation not found: <id>` on
  `respond_to_confirmation` (an events route).
- The event `kind` filter of `events/search` and `events/count` needs the
  fully qualified class path (`$REJECT_KIND`, `$OBSERVATION_KIND`); see
  `F06.search-kind-short`.
