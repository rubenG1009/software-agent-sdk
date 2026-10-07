# Conversation lifecycle and catalog

How an agent or its host creates conversations and finds them again: start a
conversation from the saved settings, a stored Agent Profile or an inline
agent (optionally with a client-chosen id, a parent, a git worktree,
start-time secrets and observability headers), read one, several or a page of
them, count them by status, rename and retag them, read the agent's final
answer, and delete them while keeping the workspace. The catalog survives a
server restart. Running, pausing and run capacity (429) live in the run family;
the events socket and event search live in the events family.

Source: `openhands-agent-server/openhands/agent_server/conversation_router.py`, `openhands-agent-server/openhands/agent_server/conversation_service.py`, `openhands-agent-server/openhands/agent_server/models.py`, `openhands-agent-server/openhands/agent_server/launch.py`, `openhands-sdk/openhands/sdk/conversation/request.py`, `openhands-sdk/openhands/sdk/conversation/response_utils.py`, `openhands-sdk/openhands/sdk/conversation/types.py`

Needs: `llm`, `git`

Routes: `GET /api/conversations/search`, `GET /api/conversations/count`,
`GET /api/conversations/{conversation_id}`,
`GET /api/conversations/{conversation_id}/agent_final_response`,
`GET /api/conversations`, `POST /api/conversations`,
`DELETE /api/conversations/{conversation_id}`,
`PATCH /api/conversations/{conversation_id}`

## Sub-features

- `F04.create-settings`: a create from the saved settings (`agent_settings` plus `secrets_encrypted`, the Agent Canvas path) returns 201 `idle`, adds one to the count, and persists the agent only in `base_state.json`, never in `meta.json`.
- `F04.create-inline-agent`: an inline `agent` without `kind` is accepted as `Agent`; the API key is never echoed back.
- `F04.create-agent-profile`: `agent_profile_id` resolves a stored Agent Profile and its LLM profile and records `launched_agent_profile`.
- `F04.create-validation`: a missing agent source, two agent sources, a missing workspace, a bad tag key, `max_iterations` 0 and invalid `agent_settings` are 422; an unknown `agent_profile_id` is 404; a profile with a dangling LLM reference is 422 `unresolved_profile_references`; no key is 401; nothing is created.
- `F04.create-idempotent`: re-posting an existing client `conversation_id` returns 200 with the same conversation, creates nothing and does not resend the initial message.
- `F04.create-parent`: `parent_conversation_id` links a child that the parent lists in `sub_conversation_ids`; an unknown parent, a different workspace and a self-parent are 422.
- `F04.create-worktree`: `worktree: true` inside a git repository moves the conversation into its own worktree on branch `openhands/<id>`.
- `F04.create-observability`: the `X-OpenHands-Observability-*` headers are validated (422 for non-object metadata) and stored in `meta.json`.
- `F04.create-secrets`: start-time `StaticSecret` values appear masked in the create response and are encrypted at rest.
- `F04.create-secrets-get`: a start-time secret is listed by `GET /api/conversations/{id}` right after the create.
- `F04.create-secrets-plain`: a plain-string secret value in the create body is accepted or rejected with 422, never a 500.
- `F04.run-real`: an initial message runs on DeepSeek flash to `finished`; the events socket replays the run, the final response is non-empty and autotitle names the conversation.
- `F04.final-response`: `agent_final_response` is empty before the agent answers, carries the exact `finish` message afterwards, and is 404 for an unknown id.
- `F04.get`: `GET /api/conversations/{id}` returns `runtime_info`, trims skills unless `include_skills=true`, accepts the 32-hex id form, and answers 404, 422 and 401.
- `F04.batch-get`: `GET /api/conversations?ids=..` returns a list aligned with the ids, `null` for unknown ones, and 422 without or with malformed ids.
- `F04.batch-get-limit`: 100 ids in one batch are refused with a client error, not a 500.
- `F04.search-page`: `limit` and `next_page_id` page newest first by default; `sort_order=CREATED_AT` reverses it; bad limits and sort orders are 422.
- `F04.search-filter`: `status` filters search and count consistently; an unknown status is 422.
- `F04.count`: `GET /api/conversations/count` equals the number of conversations search lists.
- `F04.patch-title`: PATCH `title` is stripped, stored in `meta.json`, bumps `updated_at` and moves the conversation to the top of `UPDATED_AT_DESC`.
- `F04.patch-tags`: PATCH `tags` replaces the whole map in `meta.json` and `base_state.json` and pushes a `tags` state update on the events socket.
- `F04.patch-errors`: an empty or 201-character title and a bad tag key are 422; an unknown id is 200 `{"success": false}`; no key is 401; the stored values are untouched.
- `F04.patch-whitespace-title`: a whitespace-only title is rejected instead of erasing the stored title.
- `F04.delete`: DELETE stops a running conversation (`PauseEvent`, `InterruptEvent`), removes its state, keeps the workspace and worktree, orphans children, and later reads are 404 (socket close 4004); a repeat or unknown id is 400.
- `F04.restart-persist`: after a restart the catalog, statuses, titles, tags, final responses and event replay are unchanged, and deleted conversations stay deleted.

## How to get to it (agent POV)

- REST: `POST /api/conversations` (body `StartConversationRequest`: `workspace`,
  exactly one of `agent_settings`, `agent_profile_id` or `agent`, and optional
  `conversation_id`, `parent_conversation_id`, `initial_message`, `worktree`,
  `secrets`, `secrets_encrypted`, `tags`, `max_iterations`, `autotitle`,
  `title_llm_profile`, `confirmation_policy`, `plugins`, `client_tools`, ...;
  query `include_skills`; headers `X-OpenHands-Observability-Span-Name`,
  `-Tags`, `-Metadata`, `-Parent-Span-Context`). 201 for a new conversation,
  200 for an existing `conversation_id`.
- REST reads: `GET /api/conversations/{conversation_id}`,
  `GET /api/conversations?ids=..&ids=..` (fewer than 100),
  `GET /api/conversations/search` (`page_id`, `limit` 1..100, `status`,
  `sort_order`, `include_skills`), `GET /api/conversations/count` (`status`),
  `GET /api/conversations/{conversation_id}/agent_final_response`.
- REST writes: `PATCH /api/conversations/{conversation_id}` (`title`, `tags`),
  `DELETE /api/conversations/{conversation_id}`.
- WebSocket (owned by the events family, used here as a second view):
  `/sockets/events/{conversation_id}` replays the initial message and run,
  pushes `ConversationStateUpdateEvent` key `tags` on PATCH, `PauseEvent` and
  `InterruptEvent` when a running conversation is deleted, and closes with 4004
  for a deleted id.
- SDK: `RemoteConversation(agent=..., workspace=RemoteWorkspace(...))` posts
  the create (and re-attaches with `conversation_id`), reads state with
  `GET /api/conversations/{id}`, `set_title()` sends the PATCH, and `close()`
  with `delete_on_close=True` sends the DELETE
  (`openhands-sdk/openhands/sdk/conversation/impl/remote_conversation.py`).
- TypeScript client (`clients/typescript/src/client/conversation-client.ts`):
  `createConversation` (retries once with the same `conversation_id` when the
  server advertises `idempotent_conversation_create_v1`),
  `searchConversations`, `countConversations`, `getConversations`,
  `getConversation`, `getAgentFinalResponse`, `updateConversation`,
  `deleteConversation`; `ConversationManager` wraps them
  (`getAllConversations` pages through search).
- Agent Canvas (context only): the new-conversation flow reads
  `GET /api/settings` with `X-Expose-Secrets: encrypted` and posts
  `agent_settings` with `secrets_encrypted: true` (what
  `conversation start` does); the sidebar uses search, count, title and tags;
  rename and delete use PATCH and DELETE.
- Recipes below use REST through `api`, the CLI's `conversation start` (the
  Agent Canvas create path), and the events socket through `ws`. Batch gets with
  more than one id go through a small `urllib` helper run by `exec`, because
  `api --query` sends one value per key.

## Driving it with control-agent-server

Preconditions:

- A baseline run is live and exported (`launch --new`), `doctor` is ok, and
  `$DEEPSEEK_API_KEY` is set; the block below saves the DeepSeek profiles.
- `git` is installed (worktree fixture). No `tmux` or browser is needed: every
  agent here has `tools: []` (`--tools none`), which keeps only the built-in
  `finish` and `think` tools.
- The block below creates, in order: the workspace `$W`, an unknown id
  `$NOPE`, an offline inline agent `$OFFLINE_AGENT` (unreachable `base_url`,
  never contacted because those conversations never run, with one inline
  skill), an `llm-stub` that always calls `finish` with `QA_F04_DONE`
  (`$STUB_AGENT`), an `llm-stub` that hangs (`$HANG_AGENT`, for deleting a
  running conversation), a git repository `$REPO`, and the batch helper
  `$F/qa-f04-batch.py` (repeated `ids` query keys; prints `QA_BATCH_OK` when
  the status and the aligned ids match).

```sh
control-agent-server llm preset deepseek
F="$AGENT_SERVER_VERIFY_RUN/fixtures"
W="$F/qa-f04-ws"
mkdir -p "$W"
NOPE=$(python3 -c 'import uuid; print(uuid.uuid4())')
OFFLINE_AGENT='{"llm": {"model": "openai/qa-offline", "api_key": "qa-offline-key", "base_url": "http://127.0.0.1:9/v1", "num_retries": 0}, "tools": [], "agent_context": {"skills": [{"name": "qa-f04-skill", "content": "Answer briefly."}]}}'
STUB=$(control-agent-server fixture llm-stub --name qa-f04-stub --step 'tool:finish:{"message":"QA_F04_DONE"}' --print-path)
STUB_AGENT="{\"llm\": {\"model\": \"openai/qa-stub\", \"api_key\": \"qa-stub-key\", \"base_url\": \"$STUB/v1\", \"num_retries\": 0}, \"tools\": []}"
HANG=$(control-agent-server fixture llm-stub --name qa-f04-hang --step hang:300 --print-path)
HANG_AGENT="{\"llm\": {\"model\": \"openai/qa-stub\", \"api_key\": \"qa-stub-key\", \"base_url\": \"$HANG/v1\", \"num_retries\": 0}, \"tools\": []}"
REPO=$(control-agent-server fixture git-repo --name qa-f04-repo --print-path)
cat > "$F/qa-f04-batch.py" <<'EOF'
"""GET /api/conversations with repeated ids; prints QA_BATCH_OK on a match."""
import json, os, sys, urllib.error, urllib.parse, urllib.request

ids, statuses = sys.argv[1].split(","), {int(s) for s in sys.argv[2].split(",")}
want = sys.argv[3].split(",") if len(sys.argv) > 3 else None
query = urllib.parse.urlencode([("ids", i) for i in ids])
request = urllib.request.Request(
    f"{os.environ['AGENT_SERVER_URL']}/api/conversations?{query}",
    headers={"X-Session-API-Key": os.environ["SESSION_API_KEY"]},
)
try:
    with urllib.request.urlopen(request, timeout=60) as response:
        status, body = response.status, json.loads(response.read())
except urllib.error.HTTPError as error:
    status, body = error.code, json.loads(error.read() or b"null")
got = [item and item["id"] for item in body] if isinstance(body, list) else body
print(json.dumps({"sent": len(ids), "status": status, "body": got})[:1500])
ok = status in statuses and (want is None or got == [None if w == "null" else w for w in want])
print("QA_BATCH_OK" if ok else "QA_BATCH_MISMATCH")
sys.exit(0 if ok else 1)
EOF
```

- **Create from the saved settings (`F04.create-settings`).** The Agent Canvas
  path: `agent_settings` from `GET /api/settings` (encrypted) and no prompt.
  ```sh
  N1=$(control-agent-server api GET /api/conversations/count --field .)
  CID=$(control-agent-server conversation start --tools none --no-autotitle --tag qa=f04 --workspace "$W" --save F04.create-settings/start --print-id)
  control-agent-server api GET "/api/conversations/$CID" --expect 200 --check execution_status eq idle \
    --check agent.kind eq Agent --check agent.llm.model eq deepseek/deepseek-flash --check agent.tools len-eq 0 \
    --check agent.llm.api_key ne "$DEEPSEEK_API_KEY" --check tags.qa eq f04 --check title missing \
    --check workspace.working_dir eq "$W" --save F04.create-settings/get
  control-agent-server api GET /api/conversations/count --check . eq $((N1 + 1))
  control-agent-server state cat "server/workspace/conversations/${CID//-/}/meta.json" --max-chars 200 \
    --check agent missing --check secrets_encrypted eq true --check autotitle eq false --check tags.qa eq f04
  control-agent-server state cat "server/workspace/conversations/${CID//-/}/base_state.json" --max-chars 200 \
    --check agent.llm.model eq deepseek/deepseek-flash --check execution_status eq idle
  ```
  The create is 201 and `idle`, the count grows by one, `meta.json` has no
  `agent` and `base_state.json` holds it.
- **Inline agent (`F04.create-inline-agent`).** An `agent` payload without
  `kind`.
  ```sh
  IID=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $OFFLINE_AGENT, \"autotitle\": false}" \
    --expect 201 --check agent.kind eq Agent --check agent.llm.model eq openai/qa-offline \
    --check agent.llm.api_key ne qa-offline-key --check execution_status eq idle \
    --check launched_agent_profile missing --save F04.create-inline-agent/start --field id)
  control-agent-server api GET "/api/conversations/$IID" --expect 200 --check agent.kind eq Agent \
    --check agent.llm.base_url eq http://127.0.0.1:9/v1 --check agent.llm.api_key ne qa-offline-key
  ```
  Both views say `kind` `Agent`; the API key comes back as `null`.
- **Stored Agent Profile (`F04.create-agent-profile`).** An Agent Profile that
  references the saved `deepseek-flash` LLM profile.
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f04-agent --json '{"llm_profile_ref": "deepseek-flash", "tools": []}' --expect 201
  PID=$(control-agent-server api GET /api/agent-profiles/qa-f04-agent --field profile.id)
  AID=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent_profile_id\": \"$PID\", \"autotitle\": false}" \
    --expect 201 --check launched_agent_profile.agent_profile_id eq "$PID" \
    --check agent.llm.model eq deepseek/deepseek-flash --check agent.tools len-eq 0 \
    --save F04.create-agent-profile/start --field id)
  control-agent-server api GET "/api/conversations/$AID" --check launched_agent_profile.agent_profile_id eq "$PID" \
    --check launched_agent_profile.revision exists --check agent.llm.model eq deepseek/deepseek-flash
  ```
  The conversation records the profile id and runs the profile's model.
- **Create validation (`F04.create-validation`).** Every bad request is
  refused and nothing is created.
  ```sh
  N2=$(control-agent-server api GET /api/conversations/count --field .)
  control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}}" \
    --expect 422 --check detail.0.msg contains 'must be provided' --save F04.create-validation/no-agent-source
  control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent_profile_id\": \"$PID\", \"agent_settings\": {}}" \
    --expect 422 --check detail.0.msg contains 'mutually exclusive'
  control-agent-server api POST /api/conversations --json "{\"agent\": $OFFLINE_AGENT}" --expect 422 --check detail.0.loc contains workspace
  control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $OFFLINE_AGENT, \"tags\": {\"Bad-Key\": \"x\"}}" \
    --expect 422 --check detail.0.msg contains 'lowercase alphanumeric'
  control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $OFFLINE_AGENT, \"max_iterations\": 0}" --expect 422
  control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent_settings\": {\"agent_kind\": \"nope\"}}" --expect 422
  control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent_profile_id\": \"$NOPE\"}" \
    --expect 404 --check detail contains 'not found'
  control-agent-server api POST /api/agent-profiles/qa-f04-dangling --json '{"llm_profile_ref": "qa-f04-missing", "tools": []}' --expect 201
  DANGLING=$(control-agent-server api GET /api/agent-profiles/qa-f04-dangling --field profile.id)
  control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent_profile_id\": \"$DANGLING\"}" \
    --expect 422 --check detail.code eq unresolved_profile_references \
    --check detail.dangling_llm_profile_ref eq qa-f04-missing --save F04.create-validation/dangling-profile
  control-agent-server api DELETE /api/agent-profiles/qa-f04-dangling --expect 200
  control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $OFFLINE_AGENT}" --auth none --expect 401
  control-agent-server api GET /api/conversations/count --check . eq "$N2"
  ```
  All statuses match and the count is unchanged.
- **Idempotent create with a client id (`F04.create-idempotent`).** The same
  body twice, with an initial message that the stub answers with `finish`.
  ```sh
  QID=$(python3 -c 'import uuid; print(uuid.uuid4())')
  QBODY="{\"conversation_id\": \"$QID\", \"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $STUB_AGENT, \"autotitle\": false, \"initial_message\": {\"role\": \"user\", \"content\": [{\"type\": \"text\", \"text\": \"Finish now.\"}]}}"
  N3=$(control-agent-server api GET /api/conversations/count --field .)
  control-agent-server api POST /api/conversations --json "$QBODY" --expect 201 --check id eq "$QID" --save F04.create-idempotent/first
  control-agent-server conversation wait "$QID" --until finished --timeout 60
  control-agent-server api POST /api/conversations --json "$QBODY" --expect 200 --check id eq "$QID" \
    --check execution_status eq finished --save F04.create-idempotent/second
  control-agent-server api GET /api/conversations/count --check . eq $((N3 + 1))
  control-agent-server api GET "/api/conversations/$QID/events/count" --query source=user --check . eq 1
  ```
  The second POST is 200 with the finished conversation, the count grew once,
  and there is still exactly one user event.
- **Parent and child (`F04.create-parent`).** Links within one workspace.
  ```sh
  CHILD=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $OFFLINE_AGENT, \"autotitle\": false, \"parent_conversation_id\": \"$IID\"}" \
    --expect 201 --check parent_conversation_id eq "$IID" --field id)
  control-agent-server api GET "/api/conversations/$IID" --check sub_conversation_ids contains "$CHILD" --save F04.create-parent/parent
  control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W/other\"}, \"agent\": $OFFLINE_AGENT, \"parent_conversation_id\": \"$IID\"}" \
    --expect 422 --check detail contains 'different workspace'
  control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $OFFLINE_AGENT, \"parent_conversation_id\": \"$NOPE\"}" \
    --expect 422 --check detail contains 'not found'
  control-agent-server api POST /api/conversations --json "{\"conversation_id\": \"$NOPE\", \"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $OFFLINE_AGENT, \"parent_conversation_id\": \"$NOPE\"}" \
    --expect 422 --check detail contains 'own parent'
  ```
  The parent lists the child; the three invalid links are 422 with a reason.
- **Git worktree (`F04.create-worktree`).** `worktree: true` on a repository.
  ```sh
  WT=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$REPO\"}, \"agent\": $OFFLINE_AGENT, \"autotitle\": false, \"worktree\": true}" \
    --expect 201 --check workspace.working_dir ne "$REPO" --field id)
  control-agent-server api GET "/api/conversations/$WT" \
    --check workspace.working_dir eq "$AGENT_SERVER_VERIFY_RUN/worktrees/$WT/qa-f04-repo" --save F04.create-worktree/get
  test -n "$(git -C "$REPO" branch --list "openhands/$WT")"
  git -C "$REPO" worktree list | grep -q "$AGENT_SERVER_VERIFY_RUN/worktrees/$WT/qa-f04-repo"
  test "$(git -C "$AGENT_SERVER_VERIFY_RUN/worktrees/$WT/qa-f04-repo" rev-parse HEAD)" = "$(git -C "$REPO" rev-parse HEAD)"
  ```
  The conversation works in `<worktree root>/<id>/qa-f04-repo` on branch
  `openhands/<id>`, checked out at the repository's HEAD.
- **Observability headers (`F04.create-observability`).** Header metadata must
  be a JSON object.
  ```sh
  control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $OFFLINE_AGENT}" \
    --header 'X-OpenHands-Observability-Metadata: nope' --expect 422 --check detail contains 'must be a JSON object'
  OID=$(control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $OFFLINE_AGENT, \"autotitle\": false}" \
    --header 'X-OpenHands-Observability-Metadata: {"team": "qa"}' --header 'X-OpenHands-Observability-Tags: qa-f04, nightly' \
    --header 'X-OpenHands-Observability-Span-Name: qa-f04-span' --expect 201 --field id)
  control-agent-server state cat "server/workspace/conversations/${OID//-/}/meta.json" --max-chars 200 \
    --check observability_metadata.team eq qa --check observability_tags len-eq 2 \
    --check observability_tags contains qa-f04 --check observability_span_name eq qa-f04-span
  ```
  Non-JSON metadata is 422; valid headers land in `meta.json` (they are not
  part of `ConversationInfo`).
- **Start-time secrets (`F04.create-secrets`).** A `StaticSecret` in the
  create body.
  ```sh
  SECID=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $OFFLINE_AGENT, \"autotitle\": false, \"secrets\": {\"QA_F04_TOKEN\": {\"kind\": \"StaticSecret\", \"value\": \"qa-f04-secret-value\"}}}" \
    --expect 201 --check secret_registry.secret_sources.QA_F04_TOKEN.kind eq StaticSecret \
    --check secret_registry.secret_sources.QA_F04_TOKEN.value ne qa-f04-secret-value --save F04.create-secrets/start --field id)
  control-agent-server state cat "server/workspace/conversations/${SECID//-/}/meta.json" --max-chars 200 \
    --check secrets.QA_F04_TOKEN.kind eq StaticSecret --not-contains qa-f04-secret-value
  control-agent-server state cat "server/workspace/conversations/${SECID//-/}/base_state.json" --max-chars 200 --not-contains qa-f04-secret-value
  ```
  The response lists the secret with its value masked; on disk it is
  encrypted.
- **Start-time secret visible to GET (`F04.create-secrets-get`), known bug.**
  Read the conversation created in the previous bullet.
  ```sh
  control-agent-server api GET "/api/conversations/$SECID" --expect 200 \
    --check secret_registry.secret_sources.QA_F04_TOKEN.kind eq StaticSecret --save F04.create-secrets-get/get
  ```
  Expected: the GET lists `QA_F04_TOKEN` like the create response did. Today
  it returns `{"secret_sources": {}}`: start-time secrets are applied to the
  live state in place without an autosave, and GET reads the
  `base_state.json` snapshot. The secret appears after the next state save (a
  tags PATCH, a message), so the runtime itself still has it.
- **Plain-string secret value (`F04.create-secrets-plain`), known bug.**
  `POST .../secrets` accepts `{"NAME": "value"}`; the create body should either
  accept it too or refuse it with 422.
  ```sh
  control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $OFFLINE_AGENT, \"autotitle\": false, \"secrets\": {\"QA_F04_PLAIN\": \"qa-f04-plain-value\"}}" \
    --expect 201,422 --save F04.create-secrets-plain/start
  ```
  Today the server answers 500 `"exception": "'str' object has no attribute
  'pop'"`: `DiscriminatedUnionMixin` calls `.pop("kind")` on the string, an
  `AttributeError` that escapes request validation.
- **A real run (`F04.run-real`).** DeepSeek flash answers a one-line prompt;
  autotitle is on.
  ```sh
  RID=$(control-agent-server conversation start --tools none --workspace "$W/qa-real" \
    --prompt 'Reply with the single word: pong' --wait --until finished --timeout 300 --save F04.run-real/start --print-id)
  control-agent-server api GET "/api/conversations/$RID" --check execution_status eq finished \
    --check agent.llm.model eq deepseek/deepseek-flash --check stats.usage_to_metrics.default.model_name exists --save F04.run-real/get
  control-agent-server ws listen "/sockets/events/$RID" --query resend_mode=all --until key=execution_status --until value=finished \
    --duration 20 --save F04.run-real/replay
  control-agent-server conversation events "$RID" --kinds MessageEvent --contains 'single word: pong' --expect-kind MessageEvent
  control-agent-server api GET "/api/conversations/$RID/events/count" --query source=user --check . eq 1
  control-agent-server api GET "/api/conversations/$RID/agent_final_response" --expect 200 --check response matches '\S' --save F04.run-real/final-response
  for _ in $(seq 60); do control-agent-server api GET "/api/conversations/$RID" --check title exists >/dev/null && break; sleep 1; done
  control-agent-server api GET "/api/conversations/$RID" --check title exists --save F04.run-real/title
  ```
  The run finishes, the replay ends with `execution_status` `finished`, the
  prompt is recorded once as the user's `MessageEvent`, the final response is
  non-empty (a `finish` message or a plain reply, whichever the model chose)
  and a title appears (a second LLM call that emits no event, hence the bounded
  poll).
- **Final response (`F04.final-response`).** Empty before the agent answers,
  then exactly the stub's `finish` message.
  ```sh
  FID=$(control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $STUB_AGENT, \"autotitle\": false}" --expect 201 --field id)
  control-agent-server api GET "/api/conversations/$FID/agent_final_response" --expect 200 --check response eq '' --save F04.final-response/empty
  control-agent-server conversation send "$FID" --text 'Finish now.' --wait --until finished --timeout 60
  control-agent-server api GET "/api/conversations/$FID/agent_final_response" --expect 200 --check response eq QA_F04_DONE --save F04.final-response/finish
  control-agent-server conversation events "$FID" --kinds ActionEvent --contains FinishAction --expect-kind ActionEvent
  control-agent-server api GET "/api/conversations/$FID" --check execution_status eq finished --check title missing
  control-agent-server api GET "/api/conversations/$NOPE/agent_final_response" --expect 404
  control-agent-server api GET "/api/conversations/$FID/agent_final_response" --auth none --expect 401
  ```
  `{"response": ""}`, then `{"response": "QA_F04_DONE"}`; `autotitle: false`
  kept the title empty; unknown ids are 404.
- **Read one conversation (`F04.get`).** Skills trimming, id forms and errors.
  ```sh
  control-agent-server api GET "/api/conversations/$IID" --expect 200 --check id eq "$IID" \
    --check runtime_info.runtime_status eq available --check runtime_info.can_resume eq true \
    --check agent.agent_context.skills len-eq 0 --check sub_conversation_ids contains "$CHILD" --save F04.get/default
  control-agent-server api GET "/api/conversations/$IID" --query include_skills=true \
    --check agent.agent_context.skills len-eq 1 --check agent.agent_context.skills.0.name eq qa-f04-skill --save F04.get/include-skills
  IHEX=${IID//-/}
  control-agent-server api GET "/api/conversations/$IHEX" --expect 200 --check id eq "$IID"
  control-agent-server api GET "/api/conversations/$NOPE" --expect 404 --save F04.get/unknown
  control-agent-server api GET /api/conversations/not-a-uuid --expect 422
  control-agent-server api GET "/api/conversations/$IID" --auth none --expect 401
  ```
  The default response trims the inline skill; `include_skills=true` returns
  it. The 32-hex form resolves to the dashed id.
- **Batch get (`F04.batch-get`).** Results are aligned with the ids.
  ```sh
  control-agent-server api GET /api/conversations --query ids="$IID" --expect 200 --check . len-eq 1 \
    --check 0.id eq "$IID" --check 0.runtime_info.runtime_status eq available --check 0.agent.agent_context.skills len-eq 0 --save F04.batch-get/one
  control-agent-server api GET /api/conversations --query ids="$IID" --query include_skills=true --check 0.agent.agent_context.skills len-eq 1
  control-agent-server exec --expect-output QA_BATCH_OK --save F04.batch-get/aligned -- python3 "$F/qa-f04-batch.py" "$IID,$NOPE,$FID" 200 "$IID,null,$FID"
  IDS99=$(python3 -c 'import uuid; print(",".join(str(uuid.uuid4()) for _ in range(99)))')
  control-agent-server exec --expect-output QA_BATCH_OK -- python3 "$F/qa-f04-batch.py" "$IDS99" 200
  control-agent-server api GET /api/conversations --expect 422 --check detail.0.loc contains ids
  control-agent-server api GET /api/conversations --query ids=not-a-uuid --expect 422
  control-agent-server api GET /api/conversations --query ids="$IID" --auth none --expect 401
  ```
  Three ids return `[IID, null, FID]`; 99 unknown ids return 99 nulls; missing
  or malformed ids are 422.
- **100 ids in one batch (`F04.batch-get-limit`), known bug.** The router
  limits a batch to 99 ids.
  ```sh
  IDS100=$(python3 -c 'import uuid; print(",".join(str(uuid.uuid4()) for _ in range(100)))')
  control-agent-server exec --expect-output QA_BATCH_OK --save F04.batch-get-limit/hundred -- python3 "$F/qa-f04-batch.py" "$IDS100" 400,422
  ```
  Expected: a 4xx that names the limit. Today it is 500 with an empty
  `exception`: the limit is a bare `assert len(ids) < 100` in
  `batch_get_conversations` (and disappears under `python -O`).
- **Search pages (`F04.search-page`).** Two new conversations make the newest
  two deterministic.
  ```sh
  S1=$(control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $OFFLINE_AGENT, \"autotitle\": false}" --expect 201 --field id)
  S2=$(control-agent-server api POST /api/conversations --json "{\"workspace\": {\"working_dir\": \"$W\"}, \"agent\": $OFFLINE_AGENT, \"autotitle\": false}" --expect 201 --field id)
  control-agent-server api GET /api/conversations/search --query limit=1 --expect 200 --check items len-eq 1 \
    --check items.0.id eq "$S2" --check items.0.runtime_info.runtime_status eq available \
    --check next_page_id eq "${S1//-/}" --save F04.search-page/first
  control-agent-server api GET /api/conversations/search --query limit=1 --query page_id="${S1//-/}" --check items.0.id eq "$S1" --save F04.search-page/second
  control-agent-server api GET /api/conversations/search --query sort_order=CREATED_AT --query limit=100 --check items.-1.id eq "$S2" --check next_page_id missing
  control-agent-server api GET /api/conversations/search --query limit=0 --expect 422
  control-agent-server api GET /api/conversations/search --query limit=101 --expect 422
  control-agent-server api GET /api/conversations/search --query sort_order=bogus --expect 422
  control-agent-server api GET /api/conversations/search --auth none --expect 401
  ```
  The first page holds `S2` and points at `S1` (32-hex); that page starts with
  `S1`; ascending order ends with `S2`.
- **Status filter (`F04.search-filter`).** Finished and idle conversations
  from the bullets above.
  ```sh
  control-agent-server api GET /api/conversations/search --query status=finished --check items contains "$FID" \
    --check items contains "$QID" --check items not-contains "$IID" --check items.0.execution_status eq finished --save F04.search-filter/finished
  NF=$(control-agent-server api GET /api/conversations/count --query status=finished --field .)
  control-agent-server api GET /api/conversations/search --query status=finished --query limit=100 --check items len-eq "$NF"
  control-agent-server api GET /api/conversations/search --query status=idle --check items contains "$IID" --check items not-contains "$FID"
  control-agent-server api GET /api/conversations/search --query status=bogus --expect 422
  control-agent-server api GET /api/conversations/count --query status=bogus --expect 422
  ```
  The finished page holds the stub and DeepSeek conversations only, and its
  size equals `count?status=finished`.
- **Count (`F04.count`).** The total agrees with search.
  ```sh
  N=$(control-agent-server api GET /api/conversations/count --expect 200 --field .)
  control-agent-server api GET /api/conversations/search --query limit=100 --check items len-eq "$N" --save F04.count/search-all
  control-agent-server api GET /api/conversations/count --auth none --expect 401
  ```
  Count grows on create (first bullets) and shrinks on delete (Delete bullet).
- **Rename (`F04.patch-title`).** The SDK's `set_title()` request.
  ```sh
  U0=$(control-agent-server api GET "/api/conversations/$CID" --field updated_at)
  control-agent-server api PATCH "/api/conversations/$CID" --json '{"title": "  QA F04 title  "}' --expect 200 --check success eq true --save F04.patch-title/patch
  control-agent-server api GET "/api/conversations/$CID" --check title eq 'QA F04 title' --check updated_at ne "$U0" --check tags.qa eq f04 --save F04.patch-title/get
  control-agent-server state cat "server/workspace/conversations/${CID//-/}/meta.json" --max-chars 200 --check title eq 'QA F04 title'
  control-agent-server api GET /api/conversations/search --query sort_order=UPDATED_AT_DESC --query limit=1 --check items.0.id eq "$CID"
  ```
  The title is stripped and stored, tags are untouched, and the conversation
  is now the most recently updated.
- **Retag (`F04.patch-tags`).** Tags replace the whole map; the socket sees it
  live.
  ```sh
  control-agent-server ws start "/sockets/events/$CID" --name qa-f04-tags --duration 120
  control-agent-server api PATCH "/api/conversations/$CID" --json '{"tags": {"env": "qa", "run": "one"}}' --check success eq true
  control-agent-server api PATCH "/api/conversations/$CID" --json '{"tags": {"env": "prod"}}' --check success eq true --save F04.patch-tags/replace
  control-agent-server api GET "/api/conversations/$CID" --check tags.env eq prod --check tags.run missing --check tags.qa missing \
    --check title eq 'QA F04 title' --save F04.patch-tags/get
  control-agent-server state cat "server/workspace/conversations/${CID//-/}/base_state.json" --max-chars 200 --check tags.env eq prod --check tags.run missing
  control-agent-server state cat "server/workspace/conversations/${CID//-/}/meta.json" --max-chars 200 --check tags.env eq prod
  control-agent-server ws stop qa-f04-tags --kinds ConversationStateUpdateEvent --save F04.patch-tags/live
  grep -q '"key": "tags", "value": {"env": "prod"}' "$AGENT_SERVER_VERIFY_RUN/captures/qa-f04-tags.jsonl"
  control-agent-server ws listen "/sockets/events/$CID" --query resend_mode=all --until key=tags --until value.env=prod --duration 15
  ```
  Only `env=prod` remains, in both files; the live capture and the replay both
  carry the `tags` state update.
- **PATCH errors (`F04.patch-errors`).** Nothing changes on a refused update.
  ```sh
  control-agent-server api PATCH "/api/conversations/$CID" --json '{"title": ""}' --expect 422
  LONG=$(python3 -c 'print("x" * 201)')
  control-agent-server api PATCH "/api/conversations/$CID" --json "{\"title\": \"$LONG\"}" --expect 422
  control-agent-server api PATCH "/api/conversations/$CID" --json '{"tags": {"Bad-Key": "x"}}' --expect 422
  control-agent-server api PATCH "/api/conversations/$NOPE" --json '{"title": "QA nobody"}' --expect 200 --check success eq false --save F04.patch-errors/unknown
  control-agent-server api PATCH /api/conversations/not-a-uuid --json '{"title": "QA"}' --expect 422
  control-agent-server api PATCH "/api/conversations/$CID" --json '{"title": "QA"}' --auth none --expect 401
  control-agent-server api GET "/api/conversations/$CID" --check title eq 'QA F04 title' --check tags.env eq prod
  ```
  The unknown id is 200 `{"success": false}` (not the 404 the OpenAPI
  document lists); the stored title and tags are unchanged.
- **Whitespace-only title (`F04.patch-whitespace-title`), known bug.** On the
  child conversation, so the bug cannot leak into later bullets.
  ```sh
  control-agent-server api PATCH "/api/conversations/$CHILD" --json '{"title": "QA F04 child"}' --check success eq true
  control-agent-server api PATCH "/api/conversations/$CHILD" --json '{"title": "   "}' --expect 422 --save F04.patch-whitespace-title/patch
  control-agent-server api GET "/api/conversations/$CHILD" --check title eq 'QA F04 child'
  ```
  Expected: 422 (like an empty title) and the title kept. Today `min_length=1`
  accepts `"   "`, the service stores `title.strip()`, and the title becomes
  `""` (which also stops autotitle).
- **Delete (`F04.delete`).** A running conversation (the hanging stub) with a
  child and a file in its workspace, plus the worktree conversation.
  ```sh
  mkdir -p "$W/qa-del" && echo keep > "$W/qa-del/qa-f04-keep.txt"
  DEL=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W/qa-del\"}, \"agent\": $HANG_AGENT, \"autotitle\": false, \"initial_message\": {\"role\": \"user\", \"content\": [{\"type\": \"text\", \"text\": \"Wait.\"}]}}" \
    --expect 201 --field id)
  DELCHILD=$(control-agent-server api POST /api/conversations \
    --json "{\"workspace\": {\"working_dir\": \"$W/qa-del\"}, \"agent\": $OFFLINE_AGENT, \"autotitle\": false, \"parent_conversation_id\": \"$DEL\"}" --expect 201 --field id)
  control-agent-server conversation wait "$DEL" --until running --timeout 30
  N4=$(control-agent-server api GET /api/conversations/count --field .)
  control-agent-server ws start "/sockets/events/$DEL" --name qa-f04-delete --duration 60
  control-agent-server api DELETE "/api/conversations/$DEL" --expect 200 --check success eq true --timeout 30 --save F04.delete/delete
  control-agent-server ws stop qa-f04-delete --expect-kind InterruptEvent --save F04.delete/live
  control-agent-server api GET "/api/conversations/$DEL" --expect 404 --save F04.delete/get-after
  control-agent-server api GET "/api/conversations/$DEL/agent_final_response" --expect 404
  control-agent-server api GET /api/conversations --query ids="$DEL" --check 0 eq null
  control-agent-server api GET /api/conversations/count --check . eq $((N4 - 1))
  control-agent-server ws listen "/sockets/events/$DEL" --expect-close 4004 --duration 5
  test ! -e "$AGENT_SERVER_VERIFY_RUN/server/workspace/conversations/${DEL//-/}"
  test -f "$W/qa-del/qa-f04-keep.txt"
  control-agent-server api GET "/api/conversations/$DELCHILD" --check parent_conversation_id eq "$DEL"
  control-agent-server api DELETE "/api/conversations/$DEL" --expect 400
  control-agent-server api DELETE "/api/conversations/$NOPE" --expect 400
  control-agent-server api DELETE /api/conversations/not-a-uuid --expect 422
  control-agent-server api DELETE "/api/conversations/$DELCHILD" --auth none --expect 401
  control-agent-server api DELETE "/api/conversations/$WT" --expect 200 --check success eq true
  test -d "$AGENT_SERVER_VERIFY_RUN/worktrees/$WT/qa-f04-repo"
  test -n "$(git -C "$REPO" branch --list "openhands/$WT")"
  ```
  The running conversation is paused and interrupted, then gone from every
  read view and from disk; the workspace file, the child (with a dangling
  `parent_conversation_id`), the worktree and its branch remain. A second
  delete and an unknown id are 400 (the OpenAPI document lists 404).
- **Restart (`F04.restart-persist`).** A graceful restart of the same run.
  ```sh
  N5=$(control-agent-server api GET /api/conversations/count --field .)
  control-agent-server restart
  control-agent-server api GET /api/conversations/count --check . eq "$N5"
  control-agent-server api GET "/api/conversations/$RID" --check execution_status eq finished --check title exists --save F04.restart-persist/real-run
  control-agent-server api GET "/api/conversations/$RID/agent_final_response" --check response matches '\S'
  control-agent-server api GET "/api/conversations/$FID/agent_final_response" --check response eq QA_F04_DONE --save F04.restart-persist/final-response
  control-agent-server api GET "/api/conversations/$CID" --check title eq 'QA F04 title' --check tags.env eq prod --check execution_status eq idle
  control-agent-server api GET "/api/conversations/$IID" --check sub_conversation_ids contains "$CHILD"
  control-agent-server api GET /api/conversations/search --query status=finished --check items contains "$FID" --check items contains "$RID" --check items contains "$QID"
  control-agent-server api GET "/api/conversations/$DEL" --expect 404
  control-agent-server ws listen "/sockets/events/$FID" --query resend_mode=all --until-kind ActionEvent --duration 15 --save F04.restart-persist/replay
  ```
  Everything reads back the same, the deleted conversation stays 404, and the
  finished conversation's events replay up to its `finish` action.

## Gotchas

- A create with `initial_message` always starts a run (`initial_message.run`
  is ignored), and the create response is composed right after the run is
  scheduled, so it may still say `idle`. Wait with `conversation wait`. To
  create without running, omit `initial_message`.
- `GET`, `search` and the batch get read the autosaved `base_state.json`
  snapshot (plus `meta.json`), not live memory. Changes applied in place
  without an autosave (start-time secrets, `POST .../secrets`) stay invisible
  until the next state save: see `F04.create-secrets-get`.
- Secrets never come back: `agent.llm.api_key` is `null` in REST responses
  (the masked value is re-parsed as "no secret") and `**********` in the
  socket's `full_state` frame. Assert with `ne`, never by printing a key.
- `next_page_id` is the 32-hex form of the next item's id, while items carry
  dashed ids. An unknown `page_id` silently restarts at the first page instead
  of failing.
- `count` counts catalog records (`meta.json`); search skips records whose
  `base_state.json` is missing, so the two can differ on a damaged store.
- `agent.agent_context.skills` is trimmed to `[]` on every route unless
  `include_skills=true`; the stored agent keeps them.
- Unknown ids: GET and `agent_final_response` are 404, PATCH is 200
  `{"success": false}` and DELETE is 400, although the OpenAPI document lists
  404 for PATCH and DELETE (the router tests lock the current codes).
- `GET /api/conversations` takes fewer than 100 ids (see
  `F04.batch-get-limit`). `api --query` sends one value per key and drops a
  `?query` written into PATH, so batches of several ids go through the
  `exec` helper in `Preconditions:`.
- PATCH `tags` replaces the whole map; PATCH `title` alone leaves tags alone.
  A set title stops autotitle. PATCH, DELETE and `agent_final_response` load
  (hydrate) a cold conversation, which claims its `owner_lease.json`; GET,
  search, count and the batch get do not.
- Autotitle is a separate background LLM call after the first user message; it
  emits no event, so poll `title` (bounded) after the run.
- `parent_conversation_id` needs the same `working_dir` as the parent. DELETE
  does not cascade: children keep a dangling `parent_conversation_id`, and a
  worktree and its `openhands/<id>` branch stay behind.
- Saved LLM profiles cannot be named in `agent_settings`; start from one with
  `agent_profile_id` (an Agent Profile whose `llm_profile_ref` names it), as
  in `F04.create-agent-profile`.
- Default tools (`tools: null`) need `tmux` for the terminal and Chromium for
  the browser; `"tools": []` (`--tools none`) keeps `finish` and `think` only.
  Give stub and offline agents `"num_retries": 0`, or an LLM error retries for
  minutes.
- A relative `working_dir` is resolved against the server's working directory
  (the run's `server/`), not the caller's.
- `conversation start --title` does not set a title (the start request has no
  title field); rename with PATCH.
- A create reserves one `max_concurrent_runs` slot while it initializes, so a
  full server answers 429 even for a create without a prompt (driven in the
  run family).
