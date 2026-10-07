# Server settings, settings schemas and the secrets store

The server keeps one settings document and one named-secrets store per
persistence directory, and every consumer reads them before it builds an agent.
`GET /api/settings` returns the agent settings (LLM, MCP, condenser, tools),
the conversation settings (`max_iterations`, confirmation, security analyzer),
the active LLM, agent and meta-profile pointers and the opaque
frontend-owned `misc_settings`, with secrets redacted unless the caller asks
for them with `X-Expose-Secrets: plaintext` or `encrypted`. `PATCH
/api/settings` takes sparse diffs. Two schema routes describe the agent and
conversation settings forms. The secrets store is a flat name-to-value map:
the list never shows values, `GET /api/settings/secrets/{name}` returns the
raw value as `text/plain` (the target of the SDK's `LookupSecret` URLs), and
`PUT` upserts. Both files are Fernet-encrypted at rest with the server's
cipher (`OH_SECRET_KEY`, falling back to the session key) and survive
restarts. Settings changes emit no WebSocket events.

Source: `openhands-agent-server/openhands/agent_server/settings_router.py`, `openhands-agent-server/openhands/agent_server/_secrets_exposure.py`, `openhands-agent-server/openhands/agent_server/persistence/models.py`, `openhands-agent-server/openhands/agent_server/persistence/store.py`, `openhands-sdk/openhands/sdk/settings/api_models.py`, `openhands-sdk/openhands/sdk/settings/model.py`, `openhands-sdk/openhands/sdk/utils/pydantic_secrets.py`, `openhands-sdk/openhands/sdk/utils/cipher.py`, `openhands-sdk/openhands/sdk/workspace/remote/base.py`

Routes: `GET /api/settings/agent-schema`, `GET /api/settings/conversation-schema`,
`GET /api/settings`, `PATCH /api/settings`, `GET /api/settings/secrets`,
`GET /api/settings/secrets/{name}`, `PUT /api/settings/secrets`,
`DELETE /api/settings/secrets/{name}`

## Sub-features

- `F18.get-defaults`: on a fresh persistence directory `GET /api/settings` returns OpenHands defaults (no API key, `llm_api_key_is_set: false`, every pointer null, empty `misc_settings`) without creating `settings.json`.
- `F18.agent-schema`: `GET /api/settings/agent-schema` returns the `AgentSettings` form schema with shared, `openhands` and `acp` sections, secret fields flagged, and every OpenHands field key present in `agent_settings`.
- `F18.conversation-schema`: `GET /api/settings/conversation-schema` returns the `ConversationSettings` schema whose three field keys and defaults match `conversation_settings` on a fresh server.
- `F18.auth-required`: with a session key configured, every settings and secrets route answers 401 to a missing or wrong `X-Session-API-Key`, whatever `X-Expose-Secrets` says.
- `F18.patch-llm`: a PATCH of `agent_settings_diff.llm` stores the model and key, flips `llm_api_key_is_set`, creates `settings.json`, and answers redacted even when `X-Expose-Secrets: plaintext` is sent.
- `F18.expose-modes`: GET redacts secrets as `**********` by default, returns the raw value with `plaintext`, a Fernet token with `encrypted` (and the legacy `true`), and 400 for any other value.
- `F18.roundtrip`: posting back the encrypted token keeps the real key; posting back the redacted placeholder clears it.
- `F18.agent-diff-merge`: an `agent_settings_diff` merges sparsely (siblings such as the key survive) and a `null` unsets a field (RFC 7386).
- `F18.conversation-diff`: a `conversation_settings_diff` updates only the named fields; a top-level `null` or an out-of-range value is 422 and changes nothing.
- `F18.misc-settings-merge`: `misc_settings_diff` deep-merges nested objects, replaces lists, removes a nested key on `null`, and stores a top-level `null` as `null`.
- `F18.patch-validation`: an empty or unknown-keys-only PATCH is 400, an invalid value is 422 `Settings validation failed` without echoing the posted secret, malformed pointers are 422, and nothing is stored.
- `F18.active-profile-pointer`: PATCH `active_profile` applies that LLM profile to `agent_settings.llm`, an unknown profile is 404, an explicit `llm` diff wins over the profile, and `null` clears only the pointer.
- `F18.agent-kind-switch`: switching `agent_kind` to `acp` rebuilds from a fresh ACP base (no `llm`, no key); switching back gives fresh OpenHands defaults.
- `F18.secret-put-list-get`: `PUT /api/settings/secrets` answers `{name, description}`, the list shows names and descriptions but never values, GET by name returns the raw value as `text/plain`, and a second PUT overwrites value and description.
- `F18.secret-delete`: DELETE answers `{"deleted": true}`; afterwards GET and a second DELETE are 404 `Secret not found` and the list omits the name.
- `F18.secret-name-validation`: names that do not match `^[a-zA-Z][a-zA-Z0-9_]{0,63}$` are 422 on GET, PUT and DELETE (64 characters are accepted, 65 are not); a PUT without `value` is 422; an unknown valid name is 404.
- `F18.encrypted-at-rest`: `settings.json` and `secrets.json` hold Fernet tokens, never the raw values, with mode `0600`.
- `F18.secret-scope-agent-profile`: `?agent_profile_id=` limits the list to that agent profile's `secret_refs` (`[]` lists nothing, no `secret_refs` lists everything); an unknown id is 404 `Agent profile not found`.
- `F18.sdk-remote-workspace`: the SDK's `RemoteWorkspace.get_secrets()` returns `LookupSecret`s whose URLs resolve to the stored values, and `get_llm()` returns the stored model and key.
- `F18.persist-restart`: settings (plaintext key, model, conversation settings) and secrets read back unchanged after a restart with the same cipher key.
- `F18.corrupted-files`: with an unparsable `settings.json`, GET silently returns defaults and PATCH is 409 without touching the file; with an unparsable `secrets.json` the list is empty, GET by name 404, PUT and DELETE 500; restoring the files restores the values.
- `F18.no-cipher`: without any cipher key, `X-Expose-Secrets: encrypted` is 503, `plaintext` still works, both files store plaintext, and the secrets routes are open without a key.
- `F18.secret-empty-value`: a PUT whose value is empty or the redaction placeholder must not leave a listed but unreadable secret or wipe an existing value.
- `F18.dangling-pointers`: PATCH must refuse an `active_agent_profile_id` or `active_meta_profile` that names nothing, as the dedicated activate routes do (404).
- `F18.secret-key-rotation`: after a restart with a new cipher key, a write must not destroy values stored under the old key, so rotating back recovers them.
- `F18.empty-secret-key`: an empty `OH_SECRET_KEY` must count as no key (with no session key, `encrypted` is 503), not as a cipher keyed by the empty string that anyone can decrypt.

## How to get to it (agent POV)

- REST: `GET /api/settings` (optional `X-Expose-Secrets: plaintext | encrypted`;
  `true` is a legacy alias of `encrypted`), `PATCH /api/settings` with any of
  `agent_settings_diff`, `conversation_settings_diff`, `misc_settings_diff`,
  `active_profile`, `active_agent_profile_id`, `active_meta_profile`;
  `GET /api/settings/agent-schema` and `GET /api/settings/conversation-schema`.
- REST: `GET /api/settings/secrets` (optional `agent_profile_id`),
  `PUT /api/settings/secrets` `{"name", "value", "description"?}`,
  `GET /api/settings/secrets/{name}` (raw `text/plain`),
  `DELETE /api/settings/secrets/{name}`.
- Neighbours used as arrange steps and second views, owned by other families:
  `POST/DELETE /api/profiles/{name}` and `GET /api/profiles` (LLM profiles),
  `POST/GET/DELETE /api/agent-profiles/{name}` (agent profiles). The MCP
  sub-routes `/api/settings/mcp/{settings_key}` belong to the MCP settings
  family; `/api/settings` while dormant is in the deferred-init family (F03).
- SDK: `RemoteWorkspace.get_llm()` and `get_mcp_config()` read
  `GET /api/settings` with `X-Expose-Secrets: plaintext`;
  `RemoteWorkspace.get_secrets(names=None, agent_profile_id=None)` lists names
  and returns `LookupSecret(url=<host>/api/settings/secrets/<name>)`, which the
  server or the client resolves later; `clone_repos` reads one value through
  `_get_secret_value` (`openhands-sdk/openhands/sdk/workspace/remote/base.py`).
  Recipe `F18.sdk-remote-workspace` exercises this lane through
  `control-agent-server exec`.
- TypeScript client: `SettingsClient.getAgentSchema()`,
  `getConversationSchema()`, `getSettings({exposeSecrets})`,
  `updateSettings(request)`, `listSecrets({agentProfileId})`,
  `upsertSecret(request)`, `getSecret(name)`, `deleteSecret(name)`
  (`clients/typescript/src/client/settings-client.ts`).
- Configuration: `OH_PERSISTENCE_DIR` holds `settings.json` and `secrets.json`
  (else `~/.openhands`; launched runs use `<run>/home/.openhands`);
  `OH_SECRET_KEY` is the cipher, else the first session key; with neither,
  secrets are stored in plaintext (`launch --no-auth --no-secret-key`).
  `OH_SESSION_API_KEYS_*` gates every route.
- Agent Canvas: the settings pages render forms from the two schemas and PATCH
  diffs; the secrets page lists, upserts and deletes (context only).

## Driving it with control-agent-server

Preconditions:

- A fresh run (`launch --new`, default flags) whose persistence directory has
  no `settings.json` yet: do not run `llm preset` first, `F18.get-defaults`
  checks the untouched defaults. No model is needed. `jq` is on `PATH`.
- The block below creates the fixture directory, the fake values the bullets
  store (`QA_F18_LLM_KEY` for the LLM key, `QA_F18_SECRET` for a named
  secret; both exported so `state grep --env-value` can search for them) and
  `sdk_probe.py`, a small SDK program that drives `RemoteWorkspace` against
  the run (`F18.sdk-remote-workspace`).
- Bullets mutate settings in order and restore what they change; the last
  four are known bugs and are self-contained. `F18.persist-restart` and
  `F18.secret-key-rotation` restart the run; `F18.no-cipher` and
  `F18.empty-secret-key` launch a second run of their own (`*-f18-nocipher`,
  `*-f18-emptykey`) and stop it, so their `--save` evidence lands in that
  run's `evidence/` directory.

  ```sh
  F18="$AGENT_SERVER_VERIFY_RUN/fixtures/qa-f18"
  mkdir -p "$F18"
  export QA_F18_LLM_KEY=qa-f18-llm-key-5b1e7d
  export QA_F18_SECRET=qa-f18-secret-value-3d9a
  cat > "$F18/sdk_probe.py" <<'EOF'
  import os

  from openhands.sdk.workspace import RemoteWorkspace

  ws = RemoteWorkspace(
      host=os.environ["AGENT_SERVER_URL"],
      api_key=os.environ["SESSION_API_KEY"],
      working_dir="/tmp",
  )
  secrets = ws.get_secrets()
  token = secrets["QA_F18_TOKEN"]
  assert token.url == f"{ws.host}/api/settings/secrets/QA_F18_TOKEN", token.url
  assert token.description == "qa f18 token", token.description
  assert token.get_value() == os.environ["QA_F18_SECRET"], "LookupSecret value differs"
  assert set(ws.get_secrets(names=["QA_F18_TOKEN"])) == {"QA_F18_TOKEN"}
  llm = ws.get_llm()
  assert llm.model == "openai/qa-f18-model", llm.model
  assert llm.api_key is not None
  assert llm.api_key.get_secret_value() == os.environ["QA_F18_LLM_KEY"], "LLM key differs"
  print("QA_F18_SDK_OK", sorted(secrets))
  EOF
  ```

- **Fresh defaults (`F18.get-defaults`).** Read settings before anything
  wrote them.
  ```sh
  control-agent-server api GET /api/settings --expect 200 --raw-out "$F18/settings-defaults.json" \
    --check agent_settings.agent_kind eq openhands --check agent_settings.llm.api_key missing \
    --check llm_api_key_is_set eq false --check active_profile missing --check active_agent_profile_id missing \
    --check active_meta_profile missing --check misc_settings len-eq 0 \
    --check conversation_settings.max_iterations eq 500 --save F18.get-defaults/get
  DEFAULT_MODEL=$(control-agent-server api GET /api/settings --field agent_settings.llm.model)
  test ! -e "$AGENT_SERVER_VERIFY_RUN/home/.openhands/settings.json"
  ```
  Every check passes, `DEFAULT_MODEL` is the SDK's default model, and the
  read did not create `settings.json`.
- **Agent settings schema (`F18.agent-schema`).** Read the form schema and
  compare its field keys with the settings document.
  ```sh
  control-agent-server api GET /api/settings/agent-schema --expect 200 --raw-out "$F18/agent-schema.json" \
    --check model_name eq AgentSettings --check sections len-ge 5 --max-chars 300 --save F18.agent-schema/schema
  jq -e '[.sections[].variant] | (index("openhands") != null) and (index("acp") != null) and (index(null) != null)' "$F18/agent-schema.json"
  jq -e '[.sections[].fields[] | select(.secret == true) | .key] | (index("llm.api_key") != null) and (index("verification.critic_api_key") != null) and (index("llm.model") == null)' "$F18/agent-schema.json"
  jq -e --slurpfile s "$F18/settings-defaults.json" 'def haspath(p): if (p|length) == 1 then has(p[0]) else (.[p[0]] // {}) | haspath(p[1:]) end; [.sections[] | select(.variant != "acp") | .fields[].key | split(".") as $p | ($s[0].agent_settings | haspath($p))] | all' "$F18/agent-schema.json"
  ```
  Sections carry `variant` `null` (shared `general`), `openhands` (`llm`,
  `condenser`, `verification`, ...) and `acp`; `llm.api_key` and the other
  credentials are flagged `secret`, `llm.model` is not; every non-ACP field
  key (`llm.model`, `condenser.max_size`, ...) exists in the default
  `agent_settings`.
- **Conversation settings schema (`F18.conversation-schema`).** Compare the
  schema with the defaults read in `F18.get-defaults`.
  ```sh
  control-agent-server api GET /api/settings/conversation-schema --expect 200 --raw-out "$F18/conversation-schema.json" \
    --check model_name eq ConversationSettings --save F18.conversation-schema/schema
  jq -e --slurpfile s "$F18/settings-defaults.json" '[.sections[].fields[] | .key as $k | .default == $s[0].conversation_settings[$k]] | (all and length == 3)' "$F18/conversation-schema.json"
  jq -e '[.sections[].fields[].key] | sort == ["confirmation_mode", "max_iterations", "security_analyzer"]' "$F18/conversation-schema.json"
  ```
  The schema has exactly `max_iterations`, `confirmation_mode` and
  `security_analyzer`, and each default (`500`, `false`, `llm`) equals the
  value in `conversation_settings`.
- **Key required (`F18.auth-required`).** Every route without a key, with a
  wrong key, and with `X-Expose-Secrets: plaintext` but no key.
  ```sh
  control-agent-server api GET /api/settings --auth none --expect 401 --check detail eq Unauthorized --save F18.auth-required/settings-no-key
  control-agent-server api GET /api/settings --auth bad --header 'X-Expose-Secrets: plaintext' --expect 401 --save F18.auth-required/plaintext-wrong-key
  control-agent-server api GET /api/settings/agent-schema --auth none --expect 401
  control-agent-server api GET /api/settings/conversation-schema --auth none --expect 401
  control-agent-server api PATCH /api/settings --auth none --json '{"misc_settings_diff": {"qa_f18_noauth": 1}}' --expect 401
  control-agent-server api GET /api/settings/secrets --auth none --expect 401
  control-agent-server api GET /api/settings/secrets/QA_F18_TOKEN --auth bad --expect 401 --save F18.auth-required/secret-wrong-key
  control-agent-server api PUT /api/settings/secrets --auth none --json '{"name": "QA_F18_NOAUTH", "value": "qa-f18-noauth"}' --expect 401
  control-agent-server api DELETE /api/settings/secrets/QA_F18_TOKEN --auth none --expect 401
  control-agent-server api GET /api/settings --check misc_settings len-eq 0
  control-agent-server api GET /api/settings/secrets --check secrets len-eq 0
  ```
  All nine calls are 401 `{"detail": "Unauthorized"}`; the rejected PATCH and
  PUT stored nothing.
- **Set the LLM (`F18.patch-llm`).** PATCH a model and key, asking for
  plaintext in the response, then read it back.
  ```sh
  control-agent-server api PATCH /api/settings --header 'X-Expose-Secrets: plaintext' \
    --json "{\"agent_settings_diff\": {\"llm\": {\"model\": \"openai/qa-f18-model\", \"api_key\": \"$QA_F18_LLM_KEY\"}}}" \
    --expect 200 --check agent_settings.llm.api_key eq '**********' --check agent_settings.llm.model eq openai/qa-f18-model \
    --check llm_api_key_is_set eq true --check . not-contains "$QA_F18_LLM_KEY" --save F18.patch-llm/patch
  control-agent-server api GET /api/settings --expect 200 --check agent_settings.llm.model eq openai/qa-f18-model \
    --check agent_settings.llm.api_key eq '**********' --check llm_api_key_is_set eq true --save F18.patch-llm/get
  test -f "$AGENT_SERVER_VERIFY_RUN/home/.openhands/settings.json"
  ```
  The PATCH response is redacted although plaintext was requested; the GET
  shows the model and `llm_api_key_is_set: true`, and `settings.json` now
  exists.
- **Exposure modes (`F18.expose-modes`).** Read the key four ways.
  ```sh
  control-agent-server api GET /api/settings --check agent_settings.llm.api_key eq '**********' --save F18.expose-modes/redacted
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --check agent_settings.llm.api_key eq "$QA_F18_LLM_KEY" --save F18.expose-modes/plaintext
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: encrypted' --check agent_settings.llm.api_key matches '^gAAAAA' \
    --check . not-contains "$QA_F18_LLM_KEY" --save F18.expose-modes/encrypted
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: true' --check agent_settings.llm.api_key matches '^gAAAAA' --save F18.expose-modes/legacy-true
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: qa-bogus' --expect 400 \
    --check detail contains 'Invalid X-Expose-Secrets header value' --save F18.expose-modes/bogus
  ```
  No header gives `**********`, `plaintext` the stored value, `encrypted` and
  `true` a `gAAAAA...` Fernet token (the CLI prints it as
  `<redacted:encrypted>`), any other value 400.
- **Post back what GET returned (`F18.roundtrip`).** The encrypted token, then
  the redacted placeholder.
  ```sh
  TOKEN=$(control-agent-server api GET /api/settings --header 'X-Expose-Secrets: encrypted' --field agent_settings.llm.api_key)
  control-agent-server api PATCH /api/settings --json "{\"agent_settings_diff\": {\"llm\": {\"api_key\": \"$TOKEN\"}}}" \
    --expect 200 --check llm_api_key_is_set eq true --save F18.roundtrip/encrypted-back
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --check agent_settings.llm.api_key eq "$QA_F18_LLM_KEY"
  control-agent-server api PATCH /api/settings --json '{"agent_settings_diff": {"llm": {"api_key": "**********"}}}' \
    --expect 200 --check llm_api_key_is_set eq false --save F18.roundtrip/redacted-back
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --check agent_settings.llm.api_key missing \
    --check agent_settings.llm.model eq openai/qa-f18-model --save F18.roundtrip/after-redacted
  control-agent-server api PATCH /api/settings --json "{\"agent_settings_diff\": {\"llm\": {\"api_key\": \"$QA_F18_LLM_KEY\"}}}" \
    --expect 200 --check llm_api_key_is_set eq true
  ```
  The server decrypts the posted token, so the plaintext read still returns
  the original key. Posting `**********` clears the key (`api_key` null,
  `llm_api_key_is_set: false`) while the model stays; the last PATCH restores
  the key.
- **Sparse agent diff and unset (`F18.agent-diff-merge`).** Add two LLM fields,
  then remove them with `null`.
  ```sh
  control-agent-server api PATCH /api/settings --json '{"agent_settings_diff": {"llm": {"temperature": 0.3, "base_url": "http://127.0.0.1:9/v1"}}}' \
    --expect 200 --check agent_settings.llm.temperature eq 0.3 --check agent_settings.llm.base_url eq http://127.0.0.1:9/v1 \
    --check agent_settings.llm.model eq openai/qa-f18-model --check llm_api_key_is_set eq true --save F18.agent-diff-merge/sparse
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --check agent_settings.llm.temperature eq 0.3 \
    --check agent_settings.llm.base_url eq http://127.0.0.1:9/v1 --check agent_settings.llm.api_key eq "$QA_F18_LLM_KEY"
  control-agent-server api PATCH /api/settings --json '{"agent_settings_diff": {"llm": {"base_url": null, "temperature": null}}}' \
    --expect 200 --check agent_settings.llm.base_url missing --check agent_settings.llm.temperature missing \
    --check llm_api_key_is_set eq true --save F18.agent-diff-merge/unset
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --check agent_settings.llm.api_key eq "$QA_F18_LLM_KEY" \
    --check agent_settings.llm.model eq openai/qa-f18-model --check agent_settings.llm.base_url missing
  ```
  The sparse diff keeps `model` and the key; `null` resets `base_url` and
  `temperature` to their defaults (`null`).
- **Conversation settings (`F18.conversation-diff`).** Change two fields, then
  try a top-level `null` and an invalid value.
  ```sh
  control-agent-server api PATCH /api/settings --json '{"conversation_settings_diff": {"max_iterations": 77, "confirmation_mode": true}}' \
    --expect 200 --check conversation_settings.max_iterations eq 77 --check conversation_settings.confirmation_mode eq true \
    --check conversation_settings.security_analyzer eq llm --save F18.conversation-diff/patch
  control-agent-server api PATCH /api/settings --json '{"conversation_settings_diff": {"confirmation_mode": null}}' \
    --expect 422 --check detail eq 'Settings validation failed' --save F18.conversation-diff/top-level-null
  control-agent-server api PATCH /api/settings --json '{"conversation_settings_diff": {"max_iterations": 0}}' --expect 422
  control-agent-server api GET /api/settings --check conversation_settings.max_iterations eq 77 \
    --check conversation_settings.confirmation_mode eq true --save F18.conversation-diff/get
  ```
  The untouched `security_analyzer` keeps `llm`; both rejected PATCHes are 422
  and the GET still shows `77` and `true` (restored in `F18.persist-restart`).
- **Opaque misc settings (`F18.misc-settings-merge`).** Merge twice, then null
  the whole key.
  ```sh
  control-agent-server api PATCH /api/settings --json '{"misc_settings_diff": {"qa_f18": {"theme": "dark", "keep": 1, "tags": ["a", "b"]}}}' \
    --expect 200 --check misc_settings.qa_f18.theme eq dark --check misc_settings.qa_f18.keep eq 1
  control-agent-server api PATCH /api/settings --json '{"misc_settings_diff": {"qa_f18": {"theme": "light", "tags": ["c"], "keep": null}}}' \
    --expect 200 --save F18.misc-settings-merge/merge
  control-agent-server api GET /api/settings --check misc_settings.qa_f18 eq '{"theme": "light", "tags": ["c"]}' --save F18.misc-settings-merge/get
  control-agent-server api PATCH /api/settings --json '{"misc_settings_diff": {"qa_f18": null}}' --expect 200 \
    --check misc_settings eq '{"qa_f18": null}' --save F18.misc-settings-merge/top-level-null
  control-agent-server api GET /api/settings --check misc_settings eq '{"qa_f18": null}'
  ```
  The nested `theme` is replaced, the list `["a", "b"]` becomes `["c"]`, the
  nested `null` removes `keep`. A top-level `null` is stored as `null`: a
  client cannot delete a top-level `misc_settings` key.
- **Rejected PATCH bodies (`F18.patch-validation`).** Empty, typo-only, a bad
  type next to a secret, and malformed pointers.
  ```sh
  control-agent-server api PATCH /api/settings --json '{}' --expect 400 --check detail contains 'At least one of' --save F18.patch-validation/empty
  control-agent-server api PATCH /api/settings --json '{"qa_typo": 1}' --expect 400 --save F18.patch-validation/unknown-key
  control-agent-server api PATCH /api/settings --json '{"agent_settings_diff": {"llm": {"temperature": "hot", "api_key": "qa-f18-leak-probe"}}}' \
    --expect 422 --check detail eq 'Settings validation failed' --check . not-contains qa-f18-leak-probe --save F18.patch-validation/bad-type
  control-agent-server api PATCH /api/settings --json '{"agent_settings_diff": "qa-not-an-object"}' --expect 422
  control-agent-server api PATCH /api/settings --json '{"active_profile": "bad name!"}' --expect 422 --save F18.patch-validation/bad-profile-name
  control-agent-server api PATCH /api/settings --json '{"active_agent_profile_id": "not-a-uuid"}' --expect 422
  control-agent-server api PATCH /api/settings --json '{"active_meta_profile": "bad/name"}' --expect 422
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --check agent_settings.llm.api_key eq "$QA_F18_LLM_KEY" \
    --check agent_settings.llm.temperature missing --check active_profile missing --check active_agent_profile_id missing --check active_meta_profile missing
  ```
  `{}` and a body of unknown keys are 400 `At least one of ...`; the bad
  type is 422 with the generic detail and no trace of the posted key; the
  pointer patterns are enforced (422). The final GET shows nothing changed.
- **Active LLM profile pointer (`F18.active-profile-pointer`).** Save an LLM
  profile (arrange), point settings at it, then at a missing one, then clear.
  ```sh
  control-agent-server api POST /api/profiles/qa-f18-llm --json '{"llm": {"model": "openai/qa-f18-profile-model", "api_key": "qa-f18-profile-key-91c2"}}' --expect 201
  control-agent-server api PATCH /api/settings --json '{"active_profile": "qa-f18-llm"}' --expect 200 --check active_profile eq qa-f18-llm \
    --check agent_settings.llm.model eq openai/qa-f18-profile-model --check llm_api_key_is_set eq true --save F18.active-profile-pointer/activate
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --check agent_settings.llm.api_key eq qa-f18-profile-key-91c2
  control-agent-server api GET /api/profiles --check active_profile eq qa-f18-llm --save F18.active-profile-pointer/profiles
  control-agent-server api PATCH /api/settings --json '{"active_profile": "qa-f18-nope"}' --expect 404 \
    --check detail eq "Profile 'qa-f18-nope' not found" --save F18.active-profile-pointer/unknown
  control-agent-server api GET /api/settings --check active_profile eq qa-f18-llm
  control-agent-server api PATCH /api/settings --json '{"active_profile": "qa-f18-llm", "agent_settings_diff": {"llm": {"model": "openai/qa-f18-explicit"}}}' \
    --expect 200 --check agent_settings.llm.model eq openai/qa-f18-explicit
  control-agent-server api PATCH /api/settings --json '{"active_profile": null}' --expect 200 --check active_profile missing \
    --check agent_settings.llm.model eq openai/qa-f18-explicit --save F18.active-profile-pointer/clear
  control-agent-server api GET /api/settings --check active_profile missing --check agent_settings.llm.model eq openai/qa-f18-explicit
  control-agent-server api GET /api/profiles --check active_profile missing --check profiles len-eq 1
  control-agent-server api PATCH /api/settings --json "{\"agent_settings_diff\": {\"llm\": {\"model\": \"openai/qa-f18-model\", \"api_key\": \"$QA_F18_LLM_KEY\"}}}" --expect 200
  control-agent-server api DELETE /api/profiles/qa-f18-llm --expect 200
  control-agent-server api GET /api/profiles --check active_profile missing --check profiles len-eq 0
  ```
  The pointer copies the profile's model and key into `agent_settings.llm`
  and `GET /api/profiles` agrees; the unknown name is 404 and leaves the
  pointer; an explicit `llm` diff in the same PATCH wins; `null` clears the
  pointer (both GETs agree, the profile itself stays) and keeps the LLM. The
  LLM and profile list are restored.
- **Agent kind switch (`F18.agent-kind-switch`).** To ACP and back.
  ```sh
  control-agent-server api PATCH /api/settings --json '{"agent_settings_diff": {"agent_kind": "acp", "acp_server": "claude-code"}}' \
    --expect 200 --check agent_settings.agent_kind eq acp --check agent_settings.acp_server eq claude-code \
    --check agent_settings.llm missing --check llm_api_key_is_set eq false --save F18.agent-kind-switch/to-acp
  control-agent-server api GET /api/settings --check agent_settings.agent_kind eq acp --check conversation_settings.max_iterations eq 77
  control-agent-server api PATCH /api/settings --json '{"agent_settings_diff": {"agent_kind": "openhands"}}' --expect 200 \
    --check agent_settings.agent_kind eq openhands --check agent_settings.llm.model eq "$DEFAULT_MODEL" \
    --check llm_api_key_is_set eq false --save F18.agent-kind-switch/back
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --check agent_settings.llm.api_key missing
  control-agent-server api PATCH /api/settings --json "{\"agent_settings_diff\": {\"llm\": {\"model\": \"openai/qa-f18-model\", \"api_key\": \"$QA_F18_LLM_KEY\"}}}" \
    --expect 200 --check llm_api_key_is_set eq true
  ```
  ACP settings have no `llm`, so the key is gone; switching back starts from
  fresh OpenHands defaults (the default model, no key), not from the old LLM.
  Conversation settings are untouched. The last PATCH restores the LLM.
- **Upsert, list and read a secret (`F18.secret-put-list-get`).** Create,
  list, read, overwrite, restore.
  ```sh
  control-agent-server api GET /api/settings/secrets --expect 200 --check secrets len-eq 0
  control-agent-server api PUT /api/settings/secrets --json "{\"name\": \"QA_F18_TOKEN\", \"value\": \"$QA_F18_SECRET\", \"description\": \"qa f18 token\"}" \
    --expect 200 --check name eq QA_F18_TOKEN --check description eq 'qa f18 token' --check value missing --save F18.secret-put-list-get/put
  control-agent-server api GET /api/settings/secrets --expect 200 --check secrets len-eq 1 --check secrets.0.name eq QA_F18_TOKEN \
    --check secrets.0.description eq 'qa f18 token' --check . not-contains "$QA_F18_SECRET" --save F18.secret-put-list-get/list
  control-agent-server api GET /api/settings/secrets/QA_F18_TOKEN --expect 200 --check . eq "$QA_F18_SECRET" \
    --check-header content-type contains text/plain --save F18.secret-put-list-get/get
  control-agent-server api PUT /api/settings/secrets --json '{"name": "QA_F18_TOKEN", "value": "qa-f18-secret-v2"}' --expect 200 --check description missing
  control-agent-server api GET /api/settings/secrets/QA_F18_TOKEN --expect 200 --check . eq qa-f18-secret-v2 --save F18.secret-put-list-get/get-overwritten
  control-agent-server api GET /api/settings/secrets --check secrets len-eq 1 --check secrets.0.description missing
  control-agent-server api PUT /api/settings/secrets --json "{\"name\": \"QA_F18_TOKEN\", \"value\": \"$QA_F18_SECRET\", \"description\": \"qa f18 token\"}" --expect 200
  ```
  PUT answers 200 with `{name, description}` and no value; the list has the
  name and description only; GET by name answers `text/plain` with the raw
  value. The second PUT replaces the value and, since it has no description,
  clears it. The last PUT restores both for later bullets.
- **Delete a secret (`F18.secret-delete`).** Create a throwaway secret, delete
  it twice.
  ```sh
  control-agent-server api PUT /api/settings/secrets --json '{"name": "QA_F18_DOOMED", "value": "qa-f18-doomed-value"}' --expect 200
  control-agent-server api DELETE /api/settings/secrets/QA_F18_DOOMED --expect 200 --check deleted eq true --save F18.secret-delete/delete
  control-agent-server api GET /api/settings/secrets/QA_F18_DOOMED --expect 404 --check detail eq 'Secret not found' --save F18.secret-delete/get-after
  control-agent-server api DELETE /api/settings/secrets/QA_F18_DOOMED --expect 404 --check detail eq 'Secret not found' --save F18.secret-delete/delete-again
  control-agent-server api GET /api/settings/secrets --check secrets len-eq 1 --check secrets not-contains QA_F18_DOOMED
  ```
  `{"deleted": true}`, then 404 `Secret not found` for both the read and the
  repeated delete; only `QA_F18_TOKEN` is listed.
- **Secret names (`F18.secret-name-validation`).** Invalid names on every
  route, a missing value, an unknown valid name.
  ```sh
  control-agent-server api GET /api/settings/secrets/1bad --expect 422 --check detail contains 'Invalid secret name format' --save F18.secret-name-validation/get
  control-agent-server api GET /api/settings/secrets/bad-name --expect 422
  control-agent-server api DELETE /api/settings/secrets/bad-name --expect 422 --save F18.secret-name-validation/delete
  control-agent-server api PUT /api/settings/secrets --json '{"name": "1bad", "value": "qa-f18-x"}' --expect 422 --save F18.secret-name-validation/put
  control-agent-server api PUT /api/settings/secrets --json "{\"name\": \"A$(printf 'a%.0s' $(seq 64))\", \"value\": \"qa-f18-x\"}" --expect 422
  LONG64="A$(printf 'a%.0s' $(seq 63))"
  control-agent-server api PUT /api/settings/secrets --json "{\"name\": \"$LONG64\", \"value\": \"qa-f18-x\"}" --expect 200 --check name eq "$LONG64"
  control-agent-server api GET "/api/settings/secrets/$LONG64" --expect 200 --check . eq qa-f18-x
  control-agent-server api DELETE "/api/settings/secrets/$LONG64" --expect 200 --check deleted eq true
  control-agent-server api PUT /api/settings/secrets --json '{"name": "QA_F18_NOVALUE"}' --expect 422 --save F18.secret-name-validation/no-value
  control-agent-server api GET /api/settings/secrets/QA_F18_UNKNOWN --expect 404 --check detail eq 'Secret not found'
  control-agent-server api GET /api/settings/secrets --check secrets len-eq 1
  ```
  Names starting with a digit, containing `-` or longer than 64 characters are
  422 `Invalid secret name format ...` (the docstrings say 400; the code says
  422), while a 64-character name is stored, read and deleted; a body without
  `value` is a request-validation 422; an unknown valid name is 404. Only
  `QA_F18_TOKEN` remains.
- **Encrypted at rest (`F18.encrypted-at-rest`).** Inspect both files.
  ```sh
  control-agent-server state cat home/.openhands/settings.json --check agent_settings.llm.api_key matches '^gAAAAA' \
    --check schema_version exists --not-contains "$QA_F18_LLM_KEY" --mode 600
  control-agent-server state cat home/.openhands/secrets.json --check custom_secrets.QA_F18_TOKEN.secret matches '^gAAAAA' \
    --check custom_secrets.QA_F18_TOKEN.description eq 'qa f18 token' --not-contains "$QA_F18_SECRET" --mode 600
  control-agent-server state grep openai/qa-f18-model --glob 'home/**/*'
  control-agent-server state grep QA_F18_TOKEN --glob 'home/**/*'
  control-agent-server state grep --env-value QA_F18_LLM_KEY --glob 'home/**/*' --expect-none
  control-agent-server state grep --env-value QA_F18_SECRET --glob 'home/**/*' --expect-none
  ```
  Both secret fields are `gAAAAA...` tokens and both files are `0600`. The
  glob does reach both files (the model and the secret's name are stored in
  clear and found), yet neither raw value appears anywhere under the run's
  `HOME`.
- **Secrets scoped by an agent profile (`F18.secret-scope-agent-profile`).**
  Add a second secret and two agent profiles (arrange) with different
  `secret_refs`.
  ```sh
  control-agent-server api PUT /api/settings/secrets --json '{"name": "QA_F18_OTHER", "value": "qa-f18-other-value"}' --expect 200
  control-agent-server api POST /api/agent-profiles/qa-f18-scoped --json '{"llm_profile_ref": "qa-f18-llm", "secret_refs": ["QA_F18_TOKEN"]}' --expect 201
  control-agent-server api POST /api/agent-profiles/qa-f18-none --json '{"llm_profile_ref": "qa-f18-llm", "secret_refs": []}' --expect 201
  control-agent-server api POST /api/agent-profiles/qa-f18-all --json '{"llm_profile_ref": "qa-f18-llm"}' --expect 201
  SCOPED=$(control-agent-server api GET /api/agent-profiles/qa-f18-scoped --field profile.id)
  NONE=$(control-agent-server api GET /api/agent-profiles/qa-f18-none --field profile.id)
  ALL=$(control-agent-server api GET /api/agent-profiles/qa-f18-all --check profile.secret_refs missing --field profile.id)
  control-agent-server api GET /api/settings/secrets --query "agent_profile_id=$SCOPED" --expect 200 --check secrets len-eq 1 \
    --check secrets.0.name eq QA_F18_TOKEN --save F18.secret-scope-agent-profile/scoped
  control-agent-server api GET /api/settings/secrets --query "agent_profile_id=$NONE" --expect 200 --check secrets len-eq 0 --save F18.secret-scope-agent-profile/none
  control-agent-server api GET /api/settings/secrets --query "agent_profile_id=$ALL" --expect 200 --check secrets len-eq 2 --save F18.secret-scope-agent-profile/all
  control-agent-server api GET /api/settings/secrets --expect 200 --check secrets len-eq 2
  control-agent-server api GET /api/settings/secrets --query agent_profile_id=00000000-0000-4000-8000-0000000000f1 --expect 404 \
    --check detail eq 'Agent profile not found' --save F18.secret-scope-agent-profile/unknown
  control-agent-server api DELETE /api/agent-profiles/qa-f18-scoped --expect 200
  control-agent-server api DELETE /api/agent-profiles/qa-f18-none --expect 200
  control-agent-server api DELETE /api/agent-profiles/qa-f18-all --expect 200
  control-agent-server api DELETE /api/settings/secrets/QA_F18_OTHER --expect 200
  control-agent-server api GET /api/settings --check active_agent_profile_id missing
  ```
  `secret_refs: ["QA_F18_TOKEN"]` lists only that secret, `[]` lists none,
  a profile without `secret_refs` (null, "all") and no filter both list two;
  an unknown id is 404. The profiles and the second secret are removed and no
  agent profile became active.
- **SDK consumer (`F18.sdk-remote-workspace`).** `RemoteWorkspace` lists the
  secrets as `LookupSecret`s, resolves one, and builds the LLM from settings.
  ```sh
  control-agent-server exec --env QA_F18_SECRET="$QA_F18_SECRET" --env QA_F18_LLM_KEY="$QA_F18_LLM_KEY" --env OPENHANDS_SUPPRESS_BANNER=1 \
    --expect-output QA_F18_SDK_OK --save F18.sdk-remote-workspace/probe -- .venv/bin/python "$F18/sdk_probe.py"
  ```
  The program prints `QA_F18_SDK_OK ['QA_F18_TOKEN']`: the `LookupSecret` URL
  is `<server>/api/settings/secrets/QA_F18_TOKEN`, it resolves over HTTP to
  the stored value, and `get_llm()` returns `openai/qa-f18-model` with the
  stored key (read with `X-Expose-Secrets: plaintext`).
- **Persistence across a restart (`F18.persist-restart`).** Restart with the
  same cipher key, read everything back, then restore the conversation
  settings.
  ```sh
  control-agent-server restart
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --expect 200 \
    --check agent_settings.llm.model eq openai/qa-f18-model --check agent_settings.llm.api_key eq "$QA_F18_LLM_KEY" \
    --check conversation_settings.max_iterations eq 77 --check conversation_settings.confirmation_mode eq true \
    --check misc_settings eq '{"qa_f18": null}' --save F18.persist-restart/settings
  control-agent-server api GET /api/settings/secrets/QA_F18_TOKEN --expect 200 --check . eq "$QA_F18_SECRET" --save F18.persist-restart/secret
  control-agent-server api GET /api/settings/secrets --check secrets len-eq 1 --check secrets.0.description eq 'qa f18 token'
  control-agent-server api PATCH /api/settings --json '{"conversation_settings_diff": {"max_iterations": 500, "confirmation_mode": false}}' \
    --expect 200 --check conversation_settings.max_iterations eq 500 --check conversation_settings.confirmation_mode eq false
  ```
  Every value written before the restart reads back unchanged.
- **Corrupted files (`F18.corrupted-files`).** Back up both files, overwrite
  them with broken JSON, drive every route, restore.
  ```sh
  P="$AGENT_SERVER_VERIFY_RUN/home/.openhands"
  cp "$P/settings.json" "$F18/settings.json.bak"
  cp "$P/secrets.json" "$F18/secrets.json.bak"
  cat > "$P/settings.json" <<'EOF'
  {"qa-f18-corrupt":
  EOF
  cat > "$P/secrets.json" <<'EOF'
  {"custom_secrets": [qa-f18-corrupt
  EOF
  control-agent-server api GET /api/settings --expect 200 --check llm_api_key_is_set eq false \
    --check agent_settings.llm.model eq "$DEFAULT_MODEL" --save F18.corrupted-files/get-settings
  control-agent-server api PATCH /api/settings --json '{"misc_settings_diff": {"qa_f18_probe": 1}}' --expect 409 \
    --check detail eq 'Settings file is corrupted or encrypted with a different key' --save F18.corrupted-files/patch
  control-agent-server state cat home/.openhands/settings.json --contains qa-f18-corrupt
  control-agent-server api GET /api/settings/secrets --expect 200 --check secrets len-eq 0 --save F18.corrupted-files/list-secrets
  control-agent-server api GET /api/settings/secrets/QA_F18_TOKEN --expect 404
  control-agent-server api PUT /api/settings/secrets --json '{"name": "QA_F18_PROBE", "value": "qa-f18-probe"}' --expect 500 \
    --check exception contains 'Secrets file is corrupted or encrypted with a different key' --save F18.corrupted-files/put-secret
  control-agent-server api DELETE /api/settings/secrets/QA_F18_TOKEN --expect 500 --save F18.corrupted-files/delete-secret
  control-agent-server state cat home/.openhands/secrets.json --contains qa-f18-corrupt
  cp "$F18/settings.json.bak" "$P/settings.json"
  cp "$F18/secrets.json.bak" "$P/secrets.json"
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --check agent_settings.llm.api_key eq "$QA_F18_LLM_KEY"
  control-agent-server api GET /api/settings/secrets/QA_F18_TOKEN --expect 200 --check . eq "$QA_F18_SECRET" --save F18.corrupted-files/restored
  ```
  A broken `settings.json` reads as defaults (200, no error), and PATCH
  refuses with 409 instead of overwriting it. A broken `secrets.json` lists
  nothing and hides every value (404); PUT and DELETE refuse with 500 (the
  reason is in `exception`). Neither file was touched, and restoring them
  restores the values without a restart.
- **No cipher (`F18.no-cipher`).** A second run with no `OH_SECRET_KEY` and
  no session key (`launch --no-auth --no-secret-key`), stopped when the
  bullet ends.
  ```sh
  NOCIPHER=$(control-agent-server launch --new --no-auth --no-secret-key --name f18-nocipher --print-run)
  trap 'control-agent-server stop --run "$NOCIPHER" >/dev/null' EXIT
  control-agent-server api PATCH /api/settings --run "$NOCIPHER" --json '{"agent_settings_diff": {"llm": {"api_key": "qa-f18-nocipher-key"}}}' \
    --expect 200 --check llm_api_key_is_set eq true
  control-agent-server api PUT /api/settings/secrets --run "$NOCIPHER" --json '{"name": "QA_F18_NOCIPHER", "value": "qa-f18-nocipher-secret"}' --expect 200
  control-agent-server api GET /api/settings --run "$NOCIPHER" --header 'X-Expose-Secrets: encrypted' --expect 503 \
    --check exception contains 'OH_SECRET_KEY is not configured' --save F18.no-cipher/encrypted
  control-agent-server api GET /api/settings --run "$NOCIPHER" --header 'X-Expose-Secrets: plaintext' --expect 200 \
    --check agent_settings.llm.api_key eq qa-f18-nocipher-key --save F18.no-cipher/plaintext
  control-agent-server api GET /api/settings/secrets/QA_F18_NOCIPHER --run "$NOCIPHER" --auth none --expect 200 \
    --check . eq qa-f18-nocipher-secret --save F18.no-cipher/secret-without-key
  control-agent-server state cat home/.openhands/settings.json --run "$NOCIPHER" --check agent_settings.llm.api_key eq qa-f18-nocipher-key --mode 600
  control-agent-server state cat home/.openhands/secrets.json --run "$NOCIPHER" \
    --check custom_secrets.QA_F18_NOCIPHER.secret eq qa-f18-nocipher-secret --mode 600
  ```
  `encrypted` is 503 (`detail` rewritten to `Internal Server Error`, the
  reason in `exception`), `plaintext` still works, both files hold the raw
  values (still `0600`; the server logs `Saving ... in PLAINTEXT (no cipher
  configured)`), and without session keys anyone can read a secret's value.
- **Empty or placeholder secret value (`F18.secret-empty-value`), known bug.**
  PUT the redaction placeholder over the existing secret (what a form that
  only edits the description sends), then PUT an empty value.
  ```sh
  rc=0
  control-agent-server api PUT /api/settings/secrets --json '{"name": "QA_F18_TOKEN", "value": "**********", "description": "qa f18 edited"}' \
    --expect 200,422 --save F18.secret-empty-value/put-placeholder
  control-agent-server api GET /api/settings/secrets/QA_F18_TOKEN --expect 200 --check . eq "$QA_F18_SECRET" --save F18.secret-empty-value/get-after-placeholder || rc=1
  control-agent-server api PUT /api/settings/secrets --json '{"name": "QA_F18_EMPTY", "value": ""}' --expect 200,422 --save F18.secret-empty-value/put-empty
  if control-agent-server api GET /api/settings/secrets --check secrets contains QA_F18_EMPTY >/dev/null; then
    control-agent-server api GET /api/settings/secrets/QA_F18_EMPTY --expect 200 --save F18.secret-empty-value/get-empty || rc=1
  fi
  control-agent-server api PUT /api/settings/secrets --json "{\"name\": \"QA_F18_TOKEN\", \"value\": \"$QA_F18_SECRET\", \"description\": \"qa f18 token\"}" --expect 200
  control-agent-server api DELETE /api/settings/secrets/QA_F18_EMPTY --expect 200,404
  test "$rc" = 0
  ```
  Expected: the placeholder PUT is refused (422) or keeps the stored value,
  and an empty value is refused or readable. Today both PUTs answer 200:
  `CustomSecret`'s validator turns `""` and `**********` into `null`, so the
  placeholder silently wipes `QA_F18_TOKEN` (GET 404 `Secret not found`) and
  `QA_F18_EMPTY` is listed but every read is 404. The bullet restores the
  secret and deletes the empty one whatever happens.
- **Dangling profile pointers (`F18.dangling-pointers`), known bug.** PATCH
  pointers to an agent profile id and a meta-profile that do not exist.
  ```sh
  rc=0
  control-agent-server api POST /api/agent-profiles/00000000-0000-4000-8000-0000000000f1/activate --expect 404
  control-agent-server api POST /api/meta-profiles/qa-f18-no-router/activate --expect 404
  control-agent-server api PATCH /api/settings --json '{"active_agent_profile_id": "00000000-0000-4000-8000-0000000000f1"}' \
    --expect 404,422 --save F18.dangling-pointers/agent-profile-id || rc=1
  control-agent-server api PATCH /api/settings --json '{"active_meta_profile": "qa-f18-no-router"}' \
    --expect 404,422 --save F18.dangling-pointers/meta-profile || rc=1
  control-agent-server api GET /api/settings --check active_agent_profile_id missing --check active_meta_profile missing \
    --check agent_settings.enable_classify_and_switch_llm_tool eq false --save F18.dangling-pointers/after || rc=1
  control-agent-server api PATCH /api/settings --json '{"active_agent_profile_id": null, "active_meta_profile": null}' --expect 200 \
    --check active_agent_profile_id missing --check active_meta_profile missing --check agent_settings.enable_classify_and_switch_llm_tool eq false
  test "$rc" = 0
  ```
  The dedicated routes refuse both targets with 404. Expected: PATCH refuses
  them too. Today both PATCHes answer 200 and store the pointers (only the
  format is checked); the meta-profile one also turns on
  `enable_classify_and_switch_llm_tool` with no meta-profile behind it, and a
  dangling `active_agent_profile_id` suppresses the lazy default-profile seed
  (`GET /api/agent-profiles` then returns `profiles: []` with that id as
  active). The bullet clears both pointers whatever happens.
- **Cipher key rotation (`F18.secret-key-rotation`), known bug.** Store a
  secret and an LLM key, restart with a new `OH_SECRET_KEY`, write anything,
  then restart with the original key.
  ```sh
  control-agent-server api PUT /api/settings/secrets --json "{\"name\": \"QA_F18_TOKEN\", \"value\": \"$QA_F18_SECRET\"}" --expect 200
  control-agent-server api PATCH /api/settings --json "{\"agent_settings_diff\": {\"llm\": {\"api_key\": \"$QA_F18_LLM_KEY\"}}}" --expect 200 --check llm_api_key_is_set eq true
  control-agent-server restart --rotate-secret-key
  control-agent-server api GET /api/settings/secrets/QA_F18_TOKEN --expect 200,404,409,500 --save F18.secret-key-rotation/read-under-new-key
  control-agent-server api GET /api/settings --expect 200,409,500 --save F18.secret-key-rotation/settings-under-new-key
  control-agent-server api PUT /api/settings/secrets --json '{"name": "QA_F18_ROTATED", "value": "qa-f18-rotated-value"}' --expect 200,409,500 --save F18.secret-key-rotation/put-under-new-key
  control-agent-server api PATCH /api/settings --json '{"misc_settings_diff": {"qa_f18_rotated": true}}' --expect 200,409 --save F18.secret-key-rotation/patch-under-new-key
  rc=0
  control-agent-server state cat home/.openhands/secrets.json --check custom_secrets.QA_F18_TOKEN.secret matches '^gAAAAA' || rc=1
  control-agent-server state cat home/.openhands/settings.json --check agent_settings.llm.api_key matches '^gAAAAA' || rc=1
  control-agent-server restart --restore-secret-key
  control-agent-server api GET /api/settings/secrets/QA_F18_TOKEN --expect 200 --check . eq "$QA_F18_SECRET" --save F18.secret-key-rotation/after-rotating-back || rc=1
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --check agent_settings.llm.api_key eq "$QA_F18_LLM_KEY" \
    --save F18.secret-key-rotation/settings-after-rotating-back || rc=1
  control-agent-server api DELETE /api/settings/secrets/QA_F18_TOKEN --expect 200,404
  control-agent-server api DELETE /api/settings/secrets/QA_F18_ROTATED --expect 200,404
  test "$rc" = 0
  ```
  Under the new key every read degrades silently: the secret is 404 `Secret
  not found`, `llm_api_key_is_set` is `false`, and the log says `Failed to
  decrypt secret value`. Expected: the next write either refuses (the store's
  own "encrypted with a different key" protection: 409 for settings, 500 for
  secrets) or leaves the old ciphertext alone, so the original key reads the
  values again. Today the PUT of an unrelated secret and the misc PATCH both
  answer 200 and rewrite `QA_F18_TOKEN.secret` and `llm.api_key` as `null`,
  so after rotating back both are gone for good. A rotation with no write in
  between is recoverable (`--restore-secret-key` then reads both again).
- **Empty cipher key (`F18.empty-secret-key`), known bug.** A second run with
  no session key and `OH_SECRET_KEY` set to the empty string (what
  `OH_SECRET_KEY=${UNSET_VAR}` produces), stopped when the bullet ends.
  ```sh
  EMPTYKEY=$(control-agent-server launch --new --no-auth --no-secret-key --env OH_SECRET_KEY= --name f18-emptykey --print-run)
  trap 'control-agent-server stop --run "$EMPTYKEY" >/dev/null' EXIT
  control-agent-server api PATCH /api/settings --run "$EMPTYKEY" --json '{"agent_settings_diff": {"llm": {"api_key": "qa-f18-emptykey-key"}}}' --expect 200
  control-agent-server api GET /api/settings --run "$EMPTYKEY" --header 'X-Expose-Secrets: encrypted' --expect 503 \
    --check exception contains 'OH_SECRET_KEY is not configured' --save F18.empty-secret-key/encrypted
  ```
  Expected: an empty key counts as no key, exactly like `F18.no-cipher`
  (`_default_secret_key` already treats an empty session key that way), so
  `encrypted` is 503. Today `Config.cipher` builds `Cipher("")`: `encrypted`
  answers 200 with `gAAAAA...` tokens, `settings.json` holds the same kind of
  token, nothing is logged, and anyone can decrypt both with the public key
  `sha256("")` (`Cipher("").decrypt(token)` returns `qa-f18-emptykey-key`).
  With a session key configured the empty string still wins over the
  session-key fallback. A fix that refuses to start instead would keep this
  bullet failing at `launch`; update the expectation then.

## Gotchas

- Settings and secrets live in `OH_PERSISTENCE_DIR` (launched runs:
  `<run>/home/.openhands/settings.json` and `secrets.json`), not next to the
  conversations. The stores re-read the files on every request, so a heredoc
  edit takes effect without a restart.
- The cipher is `OH_SECRET_KEY`, else the first session key, else none
  (plaintext at rest, `encrypted` 503). Rotating the session key without
  setting `OH_SECRET_KEY` therefore changes the cipher too
  (`F18.secret-key-rotation`), and an empty `OH_SECRET_KEY` is a cipher with
  a public key (`F18.empty-secret-key`). Go back to the run's previous cipher
  with `restart --restore-secret-key`, not `restart --env OH_SECRET_KEY=...`:
  an `--env` override sticks to every later restart and silently turns a
  later `--rotate-secret-key` into a no-op.
- `**********` (and an empty string) posted as a secret means "no secret":
  in a settings PATCH it clears the key, in a secrets PUT it stores `null`.
  Round-trip with `X-Expose-Secrets: encrypted`, which the server decrypts.
- PATCH responses are always redacted, and `conversation_settings` is always
  redacted, whatever `X-Expose-Secrets` says. Any authenticated caller may ask
  for `plaintext`; there is no role split, and without session keys the
  secrets routes are open to anyone.
- `agent_settings_diff` is RFC 7386 (a `null` anywhere unsets);
  `conversation_settings_diff` and `misc_settings_diff` unset only nested
  entries, so a top-level `null` is a 422 for conversation settings and a
  stored `null` in `misc_settings` (a client cannot delete a top-level misc
  key). The `update_settings` docstring ("three diffs deep-merged") and the
  `SettingsUpdateRequest` docstring ("same semantics as
  `agent_settings_diff`") both overstate this.
- Changing `agent_kind` starts from a fresh base of the target variant, so a
  switch to ACP and back drops the LLM and its key.
- A corrupted `settings.json` is indistinguishable from "never configured" on
  GET; only a PATCH (409) reveals it. A corrupted `secrets.json` lists as
  empty; PUT and DELETE answer 500.
- 5xx bodies are rewritten to `{"detail": "Internal Server Error",
  "exception": "<code>: <reason>"}`; assert on the status and `exception`.
- Invalid secret names are 422 (docstrings say 400). The 404 detail is always
  `Secret not found`, also for a stored `null` value.
- `GET /api/agent-profiles` lazily seeds a default agent profile (and may
  write a `default` LLM profile and `active_agent_profile_id`) when none
  exists; this family avoids calling it so `active_agent_profile_id` stays
  null. Use `GET /api/agent-profiles/{name}` to read ids.
- Settings and secrets changes emit no WebSocket events and only affect
  conversations created afterwards; the second view is always another GET,
  the file on disk, or a consumer (`RemoteWorkspace`).
- The CLI prints Fernet tokens as `<redacted:encrypted>`, but `--check` and
  `--field` see the real value, so `TOKEN=$(... --field ...)` round-trips.
