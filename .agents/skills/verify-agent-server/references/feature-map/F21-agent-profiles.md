# Agent profiles

Named, secret-free launch specs a consumer saves once and starts
conversations from. An Agent Profile is either an OpenHands agent that names a
saved LLM profile (`llm_profile_ref`) plus tools, persona, prompt suffix,
skill deny-list, condenser and critic policy, or an ACP agent that names an
ACP backend (`acp_server`); both kinds carry an MCP allow-list
(`mcp_server_refs`) and a secret allow-list (`secret_refs`). Each profile is
one JSON file under `OH_PERSISTENCE_DIR/agent-profiles`, keyed by a renameable
name, with a server-managed stable `id` and a `revision` that every overwrite
bumps. The server keeps a separate active pointer
(`settings.active_agent_profile_id`, set by id and never copied into
`agent_settings`), seeds a `default` profile on the first list, previews a
launch without starting anything (`materialize`), and resolves a profile when
a conversation is started with `agent_profile_id`. The TypeScript
`AgentProfilesClient` and Agent Canvas's profile editor are the consumers.

Source: `openhands-agent-server/openhands/agent_server/agent_profiles_router.py`, `openhands-agent-server/openhands/agent_server/launch.py`, `openhands-agent-server/openhands/agent_server/_secrets_exposure.py`, `openhands-sdk/openhands/sdk/profiles/`, `openhands-sdk/openhands/sdk/launch/`, `clients/typescript/src/client/agent-profiles-client.ts`

Needs: `llm`

Routes: `GET /api/agent-profiles`, `GET /api/agent-profiles/{name}`,
`POST /api/agent-profiles/{name}`, `DELETE /api/agent-profiles/{name}`,
`POST /api/agent-profiles/{name}/rename`,
`POST /api/agent-profiles/{profile_id}/activate`,
`POST /api/agent-profiles/{name}/materialize`

## Sub-features

- `F21.auth-required`: every agent-profile route answers 401 without a valid `X-Session-API-Key`, and nothing is written (not even the lazy seed).
- `F21.lazy-seed`: the first list on an empty store seeds one `default` OpenHands profile (revision 0, `llm_profile_ref` = the active LLM profile), points `active_agent_profile_id` at it, and later lists do not seed again.
- `F21.seed-no-ghost-llm`: on a never-configured server the seeded `default` keeps a soft `llm_profile_ref` `default` without writing a keyless `default` LLM profile (materialize reports it unresolved); once the live LLM has a real key, the next seed mirrors it into a keyed `default` LLM profile.
- `F21.save-create`: `POST /api/agent-profiles/{name}` answers 201 and stores the profile under the path name with a server-minted id (a client `id` and body `name` are ignored) at revision 0; GET, the list summary and the file agree.
- `F21.save-overwrite`: saving an existing name replaces the whole profile (no merge), keeps its `id` and sets `revision` to the previous one plus one, ignoring a client `revision`.
- `F21.acp-kind`: an ACP profile (`agent_kind` `acp`, `acp_server`) saves with its ACP defaults and lists with `llm_profile_ref` null.
- `F21.save-validation`: a missing `llm_profile_ref`, a field of the other kind or an unknown field, an invalid `acp_server` or `agent_kind`, a too-new `schema_version` and a non-object body are 422 with a reason, and nothing is stored.
- `F21.name-rules`: names must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` on every name route and in `new_name`; 64 characters are accepted, 65, a leading dot or dash and a space are 422.
- `F21.not-found`: GET, rename and stored materialize of an unknown name are 404 `Agent profile '<name>' not found`, activate of an unknown id or of a name is 404, and DELETE of an unknown name is 200.
- `F21.activate`: `POST /api/agent-profiles/{profile_id}/activate` sets only `active_agent_profile_id` (`agent_settings_applied` false): the list and settings show the id and `agent_settings` is unchanged.
- `F21.rename`: rename moves the profile to the new name with the same `id` and `revision`, keeps the active pointer, frees the old name (404), answers 200 "unchanged" for the same name and 409 when the target exists.
- `F21.delete`: DELETE removes the profile file; deleting another profile leaves the pointer alone, deleting the active one clears it (and a non-empty store is not reseeded).
- `F21.delete-active-acp-reset`: deleting the active profile while `agent_settings` are ACP resets them to OpenHands defaults and keeps the server's `mcp_config`.
- `F21.materialize-valid`: materializing a stored profile whose references resolve answers `valid` true with `llm_profile_resolved`, `llm_api_key_set`, the resolved MCP keys and skills, the secret allow-list and `resolved_settings` with the key masked (the raw key appears nowhere), and persists nothing.
- `F21.materialize-dangling`: dangling LLM, MCP and meta-profile references and a tool the server cannot run give 200 `valid` false with every problem in `errors`, the dangling names in their fields, and no `resolved_settings`.
- `F21.materialize-draft`: a draft body is previewed under the path name without being saved: an ACP draft reports its credential secret names, `disabled_skills` removes a skill from `resolved_skills`, and an invalid draft or an extra top-level key is 422.
- `F21.limit`: the store holds at most 50 profiles: creating a 51st is 409 and writes nothing, overwriting one at the cap still works.
- `F21.corrupt-file`: a profile file that is not valid JSON is skipped by the list, GET, stored materialize and rename of it are 400 with the parse error, and DELETE still removes it.
- `F21.conversation-start`: a conversation started with `agent_profile_id` runs the profile's LLM profile (not the active one), records `launched_agent_profile` with the id and the revision it launched with, and its stats and events name the profile's model after a run.
- `F21.secret-scope`: a profile's `secret_refs` keep only the allowed names of the secrets a conversation is started with, without an error; a profile without `secret_refs` keeps them all.
- `F21.restart`: profiles, their ids and revisions, and the active pointer survive a restart.
- `F21.store-busy`: while another process holds the profile store lock, a profile request answers 503 `Profile store is busy` after the 30-second lock timeout, and works again once the lock is free.
- `F21.busy-blocks-server`: waiting for the profile store lock must not stall the rest of the server; `/alive` keeps answering promptly.
- `F21.json-suffix-identity`: saving a name that ends in `.json` twice must keep one `id` and bump `revision`, like any other name.

## How to get to it (agent POV)

- REST: `GET /api/agent-profiles` (summaries `{id, name, agent_kind,
  revision, llm_profile_ref, mcp_server_refs}` and
  `active_agent_profile_id`; seeds `default` on an empty store),
  `GET /api/agent-profiles/{name}` (`{name, profile}`),
  `POST /api/agent-profiles/{name}` (the body is the profile; 201 `{name,
  message}` without the id, so read it back with GET),
  `DELETE /api/agent-profiles/{name}`,
  `POST /api/agent-profiles/{name}/rename` (`{"new_name": ...}`),
  `POST /api/agent-profiles/{profile_id}/activate` (the uuid, not the name),
  `POST /api/agent-profiles/{name}/materialize` (no body or `{}` for the
  stored profile, `{"profile": {...}}` for a draft). Every recipe below
  drives these routes directly.
- REST (other families, used here as second views or setup):
  `GET /api/settings` and `PATCH /api/settings` (`active_agent_profile_id`,
  `agent_settings`; F18), `POST /api/conversations` with `agent_profile_id`
  (F04; reached through `conversation start --agent-profile NAME`, which
  resolves the name to the id with the list route), `GET /api/profiles` and
  `POST /api/profiles/{name}/activate` (LLM profiles; F20), and
  `POST`/`DELETE /api/settings/mcp/{settings_key}` (MCP servers; F19).
- WebSocket: profile routes emit no events; a conversation started from a
  profile streams its events on `/sockets/events/{conversation_id}` (F06),
  checked here by replay.
- TypeScript client: `AgentProfilesClient.listAgentProfiles`,
  `getAgentProfile`, `saveAgentProfile`, `deleteAgentProfile`,
  `renameAgentProfile`, `activateAgentProfile(profileId)` and
  `materializeAgentProfile(name, draft?)`; `ConversationManager.agentProfiles`
  exposes the same client.
- SDK: `RemoteConversation.create(workspace, StartConversationRequest(...,
  agent_profile_id=...))` starts from a saved profile;
  `RemoteWorkspace.get_secrets(agent_profile_id=...)` lists the secrets a
  profile may see (F18).
- Agent Canvas: the profile picker and editor (list, save, materialize
  preview, activate); for context only.

## Driving it with control-agent-server

Preconditions:

- A run is live and exported (`launch --new`) and `doctor` is ok. Nothing
  has called `GET /api/agent-profiles` yet (`doctor` does not), so the
  profile store is empty.
- `$DEEPSEEK_API_KEY` is set; the block below saves `deepseek-flash`
  (active) and `deepseek-pro`, and writes one user skill `qa-f21-skill`
  under the run's private `HOME` for the materialize bullets. `jq` and
  `flock` (util-linux) are on `PATH`.
- Bullets share `SEED`, `CODER` and `ACP` (ids read back with GET). The
  ACP reset bullet leaves the MCP server `qa-f21-mcp` for the materialize
  bullets; the draft bullet deletes it.

```sh
control-agent-server llm preset deepseek
control-agent-server state ls 'home/.openhands/agent-profiles/*.json' --expect-count 0
mkdir -p "$AGENT_SERVER_VERIFY_RUN/home/.agents/skills/qa-f21-skill"
printf -- '---\nname: qa-f21-skill\ndescription: QA F21 user skill\n---\nQA_F21_SKILL_BODY\n' \
  > "$AGENT_SERVER_VERIFY_RUN/home/.agents/skills/qa-f21-skill/SKILL.md"
```

- **No key, no access (`F21.auth-required`).** Every route without a key
  (one with a wrong key), before anything was seeded.
  ```sh
  control-agent-server api GET /api/agent-profiles --auth none --expect 401 --save F21.auth-required/list
  control-agent-server api GET /api/agent-profiles/qa-f21-coder --auth bad --expect 401
  control-agent-server api POST /api/agent-profiles/qa-f21-coder --auth none --json '{"llm_profile_ref": "deepseek-flash"}' --expect 401
  control-agent-server api DELETE /api/agent-profiles/qa-f21-coder --auth none --expect 401
  control-agent-server api POST /api/agent-profiles/qa-f21-coder/rename --auth none --json '{"new_name": "qa-f21-x"}' --expect 401
  control-agent-server api POST /api/agent-profiles/00000000-0000-4000-8000-000000000000/activate --auth none --expect 401
  control-agent-server api POST /api/agent-profiles/qa-f21-coder/materialize --auth none --json '{}' --expect 401
  control-agent-server state ls 'home/.openhands/agent-profiles/*.json' --expect-count 0
  control-agent-server api GET /api/settings --check active_agent_profile_id missing
  ```
  All seven answer 401; no profile file exists and no pointer is set, so
  the refused list did not seed.
- **Lazy seed (`F21.lazy-seed`).** The first authenticated list.
  ```sh
  SEED=$(control-agent-server api GET /api/agent-profiles --expect 200 --check profiles len-eq 1 \
    --check profiles.0.name eq default --check profiles.0.agent_kind eq openhands --check profiles.0.revision eq 0 \
    --check profiles.0.llm_profile_ref eq deepseek-flash --save F21.lazy-seed/first-list --field active_agent_profile_id)
  control-agent-server api GET /api/agent-profiles/default --check profile.id eq "$SEED" \
    --check profile.llm_profile_ref eq deepseek-flash --check profile.mcp_server_refs missing --check profile.disabled_skills len-eq 0
  control-agent-server api GET /api/settings --check active_agent_profile_id eq "$SEED" --check active_profile eq deepseek-flash
  control-agent-server state cat home/.openhands/agent-profiles/default.json --check id eq "$SEED" --check name eq default
  control-agent-server api GET /api/agent-profiles --check profiles len-eq 1 --check active_agent_profile_id eq "$SEED" --save F21.lazy-seed/second-list
  ```
  One `default` profile appears, referencing the active LLM profile
  `deepseek-flash`, and the pointer names its id in the list, in settings
  and in the file; the second list returns the same single profile.
- **No ghost LLM profile (`F21.seed-no-ghost-llm`).** A second server that
  never had an LLM configured, then the same server with a real key.
  ```sh
  B=$(control-agent-server launch --new --name f21-seed --print-run)
  trap 'control-agent-server stop --run "$B" >/dev/null' EXIT
  control-agent-server api GET /api/agent-profiles --run "$B" --expect 200 --check profiles len-eq 1 \
    --check profiles.0.name eq default --check profiles.0.llm_profile_ref eq default --save F21.seed-no-ghost-llm/keyless-seed
  control-agent-server api GET /api/profiles --run "$B" --check profiles len-eq 0 --check active_profile missing
  control-agent-server state ls 'home/.openhands/profiles/*.json' --run "$B" --expect-count 0
  control-agent-server api POST /api/agent-profiles/default/materialize --run "$B" --json '{}' --expect 200 \
    --check valid eq false --check llm_profile_resolved eq false --check errors contains "LLM profile 'default' not found"
  control-agent-server api PATCH /api/settings --run "$B" \
    --json '{"agent_settings_diff": {"llm": {"model": "openai/qa-f21-model", "api_key": "qa-f21-fake-key"}}}' \
    --expect 200 --check llm_api_key_is_set eq true
  control-agent-server api DELETE /api/agent-profiles/default --run "$B" --expect 200
  control-agent-server api GET /api/settings --run "$B" --check active_agent_profile_id missing
  control-agent-server api GET /api/agent-profiles --run "$B" --check profiles len-eq 1 --check profiles.0.llm_profile_ref eq default \
    --check active_agent_profile_id exists
  control-agent-server api GET /api/profiles --run "$B" --check profiles len-eq 1 --check profiles.0.name eq default \
    --check profiles.0.model eq openai/qa-f21-model --check profiles.0.api_key_set eq true --save F21.seed-no-ghost-llm/mirrored
  control-agent-server api POST /api/agent-profiles/default/materialize --run "$B" --json '{}' --expect 200 \
    --check llm_profile_resolved eq true --check llm_api_key_set eq true
  ```
  The keyless seed writes no LLM profile and materialize calls its
  reference unresolved. After the live LLM gets a key, deleting the active
  `default` empties the store and clears the pointer, so the next list
  seeds again and this time mirrors the LLM into a keyed `default` LLM
  profile that the agent profile resolves. Server B is stopped on exit.
- **Create (`F21.save-create`).** A body that also carries a client `id`
  and a different `name`.
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f21-coder --expect 201 \
    --json '{"name": "qa-f21-body-name", "id": "11111111-1111-4111-8111-111111111111", "llm_profile_ref": "deepseek-pro", "tools": [], "mcp_server_refs": [], "system_message_suffix": "QA F21 suffix"}' \
    --check name eq qa-f21-coder --check message eq "Agent profile 'qa-f21-coder' saved" --save F21.save-create/save
  CODER=$(control-agent-server api GET /api/agent-profiles/qa-f21-coder --expect 200 \
    --check name eq qa-f21-coder --check profile.name eq qa-f21-coder --check profile.id ne 11111111-1111-4111-8111-111111111111 \
    --check profile.revision eq 0 --check profile.schema_version eq 3 --check profile.agent_kind eq openhands \
    --check profile.llm_profile_ref eq deepseek-pro --check profile.tools len-eq 0 --check profile.mcp_server_refs len-eq 0 \
    --check profile.system_message_suffix eq 'QA F21 suffix' --check profile.agent eq CodeActAgent \
    --save F21.save-create/get --field profile.id)
  control-agent-server api GET /api/agent-profiles/qa-f21-body-name --expect 404
  control-agent-server api GET /api/agent-profiles --field profiles \
    | jq -e --arg id "$CODER" 'map(select(.name == "qa-f21-coder" and .id == $id and .revision == 0 and .llm_profile_ref == "deepseek-pro")) | length == 1'
  control-agent-server state cat home/.openhands/agent-profiles/qa-f21-coder.json --check id eq "$CODER" --check name eq qa-f21-coder
  ```
  The response carries no id; GET shows a fresh server-minted id at
  revision 0 under the path name, the body name stores nothing, and the
  list summary and the file agree.
- **Overwrite (`F21.save-overwrite`).** Save the same name again with a
  different body and a client `revision`.
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f21-coder --expect 201 \
    --json '{"llm_profile_ref": "deepseek-pro", "tools": [], "mcp_server_refs": [], "persona": "QA F21 persona", "revision": 41}'
  control-agent-server api GET /api/agent-profiles/qa-f21-coder --check profile.id eq "$CODER" --check profile.revision eq 1 \
    --check profile.persona eq 'QA F21 persona' --check profile.system_message_suffix missing --save F21.save-overwrite/get
  ```
  The id is unchanged, the revision is 1 (not 41), and the suffix of the
  first save is gone: an overwrite replaces the whole profile.
- **ACP profile (`F21.acp-kind`).**
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f21-acp --expect 201 \
    --json '{"agent_kind": "acp", "acp_server": "codex", "acp_model": "gpt-5.5", "secret_refs": ["OPENAI_API_KEY"]}'
  ACP=$(control-agent-server api GET /api/agent-profiles/qa-f21-acp --check profile.agent_kind eq acp \
    --check profile.acp_server eq codex --check profile.acp_model eq gpt-5.5 --check profile.acp_prompt_timeout eq 1800 \
    --check profile.acp_startup_timeout eq 90 --check profile.llm_profile_ref missing --check profile.secret_refs contains OPENAI_API_KEY \
    --check profile.revision eq 0 --save F21.acp-kind/get --field profile.id)
  control-agent-server api GET /api/agent-profiles --field profiles \
    | jq -e --arg id "$ACP" 'map(select(.id == $id and .agent_kind == "acp" and .llm_profile_ref == null)) | length == 1'
  ```
  The ACP profile stores its backend and the default timeouts (1800 s
  prompt, 90 s startup) and has no LLM reference in GET or in the list.
- **Save validation (`F21.save-validation`).** Bad bodies under one name.
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f21-bad --json '{}' --expect 422 \
    --check detail.0.loc contains llm_profile_ref --check detail.0.type eq missing --save F21.save-validation/missing-ref
  control-agent-server api POST /api/agent-profiles/qa-f21-bad --json '{"agent_kind": "acp", "llm_profile_ref": "deepseek-flash"}' \
    --expect 422 --check detail.0.type eq extra_forbidden --check detail.0.loc contains llm_profile_ref
  control-agent-server api POST /api/agent-profiles/qa-f21-bad --json '{"llm_profile_ref": "deepseek-flash", "acp_server": "codex"}' \
    --expect 422 --check detail.0.type eq extra_forbidden --check detail.0.loc contains acp_server
  control-agent-server api POST /api/agent-profiles/qa-f21-bad --json '{"llm_profile_ref": "deepseek-flash", "qa_unknown": 1}' \
    --expect 422 --check detail.0.loc contains qa_unknown
  control-agent-server api POST /api/agent-profiles/qa-f21-bad --json '{"agent_kind": "acp", "acp_server": "qa-nope"}' \
    --expect 422 --check detail.0.type eq literal_error --check detail.0.msg contains claude-code
  control-agent-server api POST /api/agent-profiles/qa-f21-bad --json '{"agent_kind": "qa-nope"}' --expect 422 --check detail.0.type eq union_tag_invalid
  control-agent-server api POST /api/agent-profiles/qa-f21-bad --json '{"llm_profile_ref": "deepseek-flash", "tool_concurrency_limit": 0}' --expect 422
  control-agent-server api POST /api/agent-profiles/qa-f21-bad --json '{"llm_profile_ref": "deepseek-flash", "schema_version": 99}' \
    --expect 422 --check detail eq 'Invalid agent profile'
  control-agent-server api POST /api/agent-profiles/qa-f21-bad --json '["qa"]' --expect 422 --check detail.0.type eq dict_type
  control-agent-server api GET /api/agent-profiles/qa-f21-bad --expect 404
  control-agent-server state ls 'home/.openhands/agent-profiles/qa-f21-bad*' --expect-count 0
  ```
  Each is 422 with `loc`, `type` and `msg` (the schema-version failure
  gives only `Invalid agent profile`), and no `qa-f21-bad` file exists.
- **Name rules (`F21.name-rules`).** The boundary and the bad shapes, on
  every route that takes a name.
  ```sh
  L64=qa-f21-$(printf 'n%.0s' $(seq 1 57))
  test ${#L64} -eq 64
  control-agent-server api POST "/api/agent-profiles/$L64" --json '{"llm_profile_ref": "deepseek-flash"}' --expect 201
  control-agent-server api GET "/api/agent-profiles/$L64" --check profile.name eq "$L64"
  control-agent-server api DELETE "/api/agent-profiles/$L64" --expect 200
  control-agent-server api POST "/api/agent-profiles/${L64}n" --json '{"llm_profile_ref": "deepseek-flash"}' --expect 422 \
    --check detail.0.type eq string_too_long --save F21.name-rules/too-long
  control-agent-server api POST /api/agent-profiles/.qa-f21 --json '{"llm_profile_ref": "deepseek-flash"}' --expect 422 \
    --check detail.0.type eq string_pattern_mismatch --save F21.name-rules/leading-dot
  control-agent-server api POST /api/agent-profiles/-qa-f21 --json '{"llm_profile_ref": "deepseek-flash"}' --expect 422
  control-agent-server api POST '/api/agent-profiles/qa%20f21' --json '{"llm_profile_ref": "deepseek-flash"}' --expect 422
  control-agent-server api GET /api/agent-profiles/.qa-f21 --expect 422
  control-agent-server api DELETE /api/agent-profiles/.qa-f21 --expect 422
  control-agent-server api POST /api/agent-profiles/.qa-f21/materialize --json '{}' --expect 422
  control-agent-server api POST /api/agent-profiles/.qa-f21/rename --json '{"new_name": "qa-f21-ok"}' --expect 422
  control-agent-server api POST /api/agent-profiles/qa-f21-coder/rename --json '{"new_name": ".qa-f21"}' --expect 422 \
    --check detail.0.loc contains new_name
  control-agent-server api POST /api/agent-profiles/qa-f21-coder/rename --json '{}' --expect 422 --check detail.0.type eq missing
  control-agent-server api GET /api/agent-profiles/qa-f21-coder --check profile.id eq "$CODER"
  control-agent-server state ls 'home/.openhands/agent-profiles/qa-f21-n*' --expect-count 0
  ```
  The 64-character name round-trips; 65 characters, a leading dot or dash
  and a space are 422 on save, GET, DELETE, materialize and rename, as is a
  bad or missing `new_name`, and `qa-f21-coder` is untouched.
- **Unknown names and ids (`F21.not-found`).**
  ```sh
  control-agent-server api GET /api/agent-profiles/qa-f21-nope --expect 404 \
    --check detail eq "Agent profile 'qa-f21-nope' not found" --save F21.not-found/get
  control-agent-server api POST /api/agent-profiles/qa-f21-nope/rename --json '{"new_name": "qa-f21-nope2"}' --expect 404 \
    --check detail eq "Agent profile 'qa-f21-nope' not found"
  control-agent-server api POST /api/agent-profiles/qa-f21-nope/materialize --expect 404
  control-agent-server api POST /api/agent-profiles/qa-f21-nope/materialize --json '{}' --expect 404
  control-agent-server api POST /api/agent-profiles/00000000-0000-4000-8000-000000000000/activate --expect 404 \
    --check detail eq "Agent profile with id '00000000-0000-4000-8000-000000000000' not found"
  control-agent-server api POST /api/agent-profiles/qa-f21-coder/activate --expect 404 \
    --check detail eq "Agent profile with id 'qa-f21-coder' not found" --save F21.not-found/activate-by-name
  control-agent-server api DELETE /api/agent-profiles/qa-f21-nope --expect 200 \
    --check message eq "Agent profile 'qa-f21-nope' deleted" --save F21.not-found/delete
  control-agent-server api GET /api/agent-profiles/qa-f21-nope2 --expect 404
  control-agent-server api GET /api/settings --check active_agent_profile_id eq "$SEED"
  ```
  Unknown names are 404 on GET, rename and materialize (with or without an
  empty body); activate is keyed on the id, so a name is 404 too. DELETE is
  idempotent and the pointer is untouched.
- **Activate by id (`F21.activate`).** Point at `qa-f21-coder`, whose LLM
  (`deepseek-pro`), tools and persona differ from the live settings.
  ```sh
  BEFORE=$(control-agent-server api GET /api/settings --field agent_settings | jq -S -c .)
  control-agent-server api POST "/api/agent-profiles/$CODER/activate" --expect 200 --check id eq "$CODER" \
    --check agent_settings_applied eq false --save F21.activate/activate
  control-agent-server api GET /api/agent-profiles --check active_agent_profile_id eq "$CODER"
  control-agent-server api GET /api/settings --check active_agent_profile_id eq "$CODER" --check active_profile eq deepseek-flash \
    --check agent_settings.llm.model eq deepseek/deepseek-flash --save F21.activate/settings
  AFTER=$(control-agent-server api GET /api/settings --field agent_settings | jq -S -c .)
  test "$BEFORE" = "$AFTER"
  ```
  The pointer moves in both views while `agent_settings` (still
  `deepseek-flash`) is identical before and after.
- **Rename (`F21.rename`).** Rename the active profile, then the edge cases.
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f21-coder/rename --json '{"new_name": "qa-f21-coder2"}' --expect 200 \
    --check name eq qa-f21-coder2 --check message eq "Agent profile 'qa-f21-coder' renamed to 'qa-f21-coder2'" --save F21.rename/rename
  control-agent-server api GET /api/agent-profiles/qa-f21-coder2 --check profile.id eq "$CODER" --check profile.name eq qa-f21-coder2 \
    --check profile.revision eq 1 --save F21.rename/get
  control-agent-server api GET /api/agent-profiles/qa-f21-coder --expect 404
  control-agent-server api GET /api/agent-profiles --check active_agent_profile_id eq "$CODER"
  control-agent-server state cat home/.openhands/agent-profiles/qa-f21-coder2.json --check name eq qa-f21-coder2 --check id eq "$CODER"
  control-agent-server state ls 'home/.openhands/agent-profiles/qa-f21-coder.json' --expect-count 0
  control-agent-server api POST /api/agent-profiles/qa-f21-coder2/rename --json '{"new_name": "qa-f21-coder2"}' --expect 200 \
    --check message eq "Agent profile 'qa-f21-coder2' unchanged (same name)"
  control-agent-server api POST /api/agent-profiles/qa-f21-coder2/rename --json '{"new_name": "qa-f21-acp"}' --expect 409 \
    --check detail eq "Agent profile 'qa-f21-acp' already exists" --save F21.rename/conflict
  control-agent-server api GET /api/agent-profiles/qa-f21-acp --check profile.id eq "$ACP"
  control-agent-server api POST /api/agent-profiles/qa-f21-coder2/rename --json '{"new_name": "qa-f21-coder"}' --expect 200
  control-agent-server api GET /api/agent-profiles/qa-f21-coder --check profile.id eq "$CODER"
  ```
  The id and revision move with the file (whose `name` field is
  rewritten), the pointer still names the id, the old name is free, the
  same-name rename is a no-op, and a taken name is 409 with both profiles
  intact. The profile is renamed back for later bullets.
- **Delete (`F21.delete`).** A profile that is not active, then one that is.
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f21-tmp --json '{"llm_profile_ref": "deepseek-flash"}' --expect 201
  control-agent-server api DELETE /api/agent-profiles/qa-f21-tmp --expect 200 --check message eq "Agent profile 'qa-f21-tmp' deleted" \
    --save F21.delete/delete
  control-agent-server api GET /api/agent-profiles/qa-f21-tmp --expect 404
  control-agent-server state ls 'home/.openhands/agent-profiles/qa-f21-tmp.json' --expect-count 0
  control-agent-server api GET /api/settings --check active_agent_profile_id eq "$CODER"
  control-agent-server api POST /api/agent-profiles/qa-f21-doomed --json '{"llm_profile_ref": "deepseek-flash"}' --expect 201
  DOOMED=$(control-agent-server api GET /api/agent-profiles/qa-f21-doomed --field profile.id)
  control-agent-server api POST "/api/agent-profiles/$DOOMED/activate" --expect 200
  control-agent-server api DELETE /api/agent-profiles/qa-f21-doomed --expect 200
  control-agent-server api GET /api/agent-profiles --check active_agent_profile_id missing --save F21.delete/list-after-active \
    --field profiles | jq -e 'map(.name) | (index("qa-f21-doomed") == null) and (map(select(. == "default")) | length == 1)'
  control-agent-server api GET /api/settings --check active_agent_profile_id missing --check agent_settings.agent_kind eq openhands \
    --check agent_settings.llm.model eq deepseek/deepseek-flash
  control-agent-server api POST "/api/agent-profiles/$CODER/activate" --expect 200
  ```
  The inactive delete removes the file and keeps the pointer; deleting the
  active profile clears the pointer in both views, leaves OpenHands
  settings alone, and does not reseed (the store is not empty). The pointer
  goes back to `qa-f21-coder`.
- **Active ACP reset (`F21.delete-active-acp-reset`).** Live settings on
  ACP with one MCP server, then the active profile is deleted.
  ```sh
  control-agent-server api PATCH /api/settings --json '{"agent_settings_diff": {"agent_kind": "acp", "acp_server": "codex"}}' \
    --expect 200 --check agent_settings.agent_kind eq acp
  control-agent-server api POST /api/settings/mcp/qa-f21-mcp --expect 201 \
    --json '{"transport": "http", "url": "https://example.invalid/mcp", "description": "QA F21"}'
  control-agent-server api POST /api/agent-profiles/qa-f21-acp-active --json '{"agent_kind": "acp", "acp_server": "codex"}' --expect 201
  ACTIVE_ACP=$(control-agent-server api GET /api/agent-profiles/qa-f21-acp-active --field profile.id)
  control-agent-server api POST "/api/agent-profiles/$ACTIVE_ACP/activate" --expect 200
  control-agent-server api GET /api/settings --check active_agent_profile_id eq "$ACTIVE_ACP" --check agent_settings.agent_kind eq acp \
    --check agent_settings.mcp_config.qa-f21-mcp exists
  control-agent-server api DELETE /api/agent-profiles/qa-f21-acp-active --expect 200
  control-agent-server api GET /api/settings --check active_agent_profile_id missing --check agent_settings.agent_kind eq openhands \
    --check agent_settings.acp_server missing --check agent_settings.mcp_config.qa-f21-mcp.url eq https://example.invalid/mcp \
    --save F21.delete-active-acp-reset/settings
  control-agent-server api POST /api/profiles/deepseek-flash/activate --expect 200
  control-agent-server api POST "/api/agent-profiles/$CODER/activate" --expect 200
  control-agent-server api GET /api/settings --check agent_settings.llm.model eq deepseek/deepseek-flash \
    --check llm_api_key_is_set eq true --check active_agent_profile_id eq "$CODER"
  ```
  After the delete the pointer is clear and `agent_settings` are fresh
  OpenHands defaults that still hold `qa-f21-mcp`. Re-activating the
  `deepseek-flash` LLM profile and `qa-f21-coder` restores the run.
- **Materialize a resolvable profile (`F21.materialize-valid`).** A stored
  profile that names the active LLM profile, `qa-f21-mcp` and a secret.
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f21-preview --expect 201 \
    --json '{"llm_profile_ref": "deepseek-flash", "tools": [], "mcp_server_refs": ["qa-f21-mcp"], "secret_refs": ["QA_F21_ALLOWED"], "system_message_suffix": "QA F21 suffix"}'
  N_CONV=$(control-agent-server api GET /api/conversations/count --field .)
  control-agent-server api POST /api/agent-profiles/qa-f21-preview/materialize --expect 200 --quiet \
    --check agent_kind eq openhands --check valid eq true --check errors len-eq 0 --check llm_profile_ref eq deepseek-flash \
    --check llm_profile_resolved eq true --check llm_api_key_set eq true --check resolved_mcp_config_keys contains qa-f21-mcp \
    --check dangling_mcp_server_refs len-eq 0 --check resolved_skills contains qa-f21-skill --check secret_refs contains QA_F21_ALLOWED \
    --check resolved_settings.llm.model eq deepseek/deepseek-flash --check resolved_settings.llm.api_key eq '**********' \
    --check resolved_settings.tools len-eq 0 --check resolved_settings.mcp_config.qa-f21-mcp.url eq https://example.invalid/mcp \
    --check resolved_settings.agent_context.system_message_suffix eq 'QA F21 suffix' --save F21.materialize-valid/stored
  RAW="$AGENT_SERVER_VERIFY_RUN/private/qa-f21-materialize.json"
  control-agent-server api POST /api/agent-profiles/qa-f21-preview/materialize --expect 200 --quiet --raw-out "$RAW"
  grep -q deepseek/deepseek-flash "$RAW"
  if grep -qF "$DEEPSEEK_API_KEY" "$RAW"; then exit 1; fi
  rm -f "$RAW"
  control-agent-server api GET /api/agent-profiles/qa-f21-preview --check profile.revision eq 0
  control-agent-server api GET /api/conversations/count --check . eq "$N_CONV"
  control-agent-server api GET /api/settings --check active_agent_profile_id eq "$CODER"
  ```
  The preview resolves everything, lists `qa-f21-skill` among the skills,
  masks the key in `resolved_settings`, and the raw body (kept in the
  run's private directory and removed) never contains the key. The
  profile's revision, the conversation count and the pointer are
  unchanged.
- **Dangling references (`F21.materialize-dangling`).** Saving does not
  check references; materialize reports them.
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f21-dangling --expect 201 \
    --json '{"llm_profile_ref": "qa-f21-missing", "tools": [], "mcp_server_refs": ["qa-f21-mcp", "qa-f21-nomcp"], "enable_classify_and_switch_llm_tool": true, "meta_profile_ref": "qa-f21-nometa"}'
  control-agent-server api POST /api/agent-profiles/qa-f21-dangling/materialize --expect 200 --check valid eq false \
    --check errors contains "LLM profile 'qa-f21-missing' not found" --check errors contains 'MCP server(s) not configured: qa-f21-nomcp' \
    --check errors contains "Meta-profile 'qa-f21-nometa' not found" --check llm_profile_resolved eq false \
    --check dangling_mcp_server_refs len-eq 1 --check dangling_mcp_server_refs contains qa-f21-nomcp \
    --check resolved_mcp_config_keys contains qa-f21-mcp --check dangling_meta_profile_ref eq qa-f21-nometa \
    --check resolved_settings missing --save F21.materialize-dangling/stored
  control-agent-server api POST /api/agent-profiles/qa-f21-dangling/materialize --expect 200 \
    --json '{"profile": {"llm_profile_ref": "deepseek-flash", "tools": [{"name": "qa_no_such_tool"}], "mcp_server_refs": []}}' \
    --check valid eq false --check unusable_tools contains qa_no_such_tool \
    --check errors contains 'Tool(s) this server cannot run: qa_no_such_tool' --check resolved_settings missing --save F21.materialize-dangling/tool
  control-agent-server api DELETE /api/agent-profiles/qa-f21-dangling --expect 200
  ```
  Both are 200 with `valid` false: the three missing references are listed
  together (the existing `qa-f21-mcp` still resolves), and an unknown tool
  is reported as unusable.
- **Draft preview (`F21.materialize-draft`).** Drafts are never saved.
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f21-draft/materialize --expect 200 \
    --json '{"profile": {"name": "qa-f21-other", "agent_kind": "acp", "acp_server": "claude-code"}}' \
    --check agent_kind eq acp --check valid eq true --check acp_api_key_secret_name eq ANTHROPIC_API_KEY \
    --check acp_base_url_secret_name eq ANTHROPIC_BASE_URL --check llm_profile_ref missing \
    --check resolved_settings.acp_server eq claude-code --save F21.materialize-draft/acp
  control-agent-server api GET /api/agent-profiles/qa-f21-draft --expect 404
  control-agent-server api GET /api/agent-profiles/qa-f21-other --expect 404
  control-agent-server api POST /api/agent-profiles/qa-f21-acp/materialize --expect 200 \
    --check acp_api_key_secret_name eq OPENAI_API_KEY --check acp_file_secret_names contains CODEX_AUTH_JSON
  control-agent-server api POST /api/agent-profiles/qa-f21-preview/materialize --expect 200 --quiet \
    --json '{"profile": {"llm_profile_ref": "deepseek-flash", "tools": [], "mcp_server_refs": [], "disabled_skills": ["qa-f21-skill"]}}' \
    --check valid eq true --check disabled_skills contains qa-f21-skill --check resolved_skills not-contains qa-f21-skill \
    --check resolved_skills len-ge 1 --check resolved_mcp_config_keys len-eq 0 --save F21.materialize-draft/disabled-skill
  control-agent-server api GET /api/agent-profiles/qa-f21-preview --check profile.disabled_skills len-eq 0 \
    --check profile.mcp_server_refs contains qa-f21-mcp --check profile.revision eq 0
  control-agent-server api POST /api/agent-profiles/qa-f21-draft/materialize --json '{"profile": "qa"}' --expect 422 \
    --check detail.0.msg contains 'profile must be an object'
  control-agent-server api POST /api/agent-profiles/qa-f21-draft/materialize --expect 422 \
    --json '{"profile": {"agent_kind": "acp", "llm_profile_ref": "deepseek-flash"}}' --check detail.0.type eq extra_forbidden
  control-agent-server api POST /api/agent-profiles/qa-f21-draft/materialize --json '{"qa_extra": 1}' --expect 422 \
    --check detail.0.type eq extra_forbidden --save F21.materialize-draft/extra-key
  control-agent-server api DELETE /api/settings/mcp/qa-f21-mcp --expect 200
  ```
  The ACP drafts report the provider's credential secret names (Claude
  Code: `ANTHROPIC_API_KEY`; the stored Codex profile: `OPENAI_API_KEY` or
  the `CODEX_AUTH_JSON` file) and nothing is stored under either name. A
  draft over the stored `qa-f21-preview` drops `qa-f21-skill` from the
  skills (the stored preview listed it) while the stored profile stays as
  it was. A non-object draft, a cross-kind field and an unknown top-level
  key are 422. The MCP server is removed.
- **At most 50 (`F21.limit`).** Fill the store to the cap. About fifty API
  calls each way, so the bullet takes about a minute.
  ```sh
  N=$(control-agent-server api GET /api/agent-profiles --field profiles | jq length)
  test "$N" -lt 50
  for i in $(seq "$N" 49); do
    control-agent-server api POST "/api/agent-profiles/qa-f21-fill-$i" --json '{"llm_profile_ref": "deepseek-flash"}' --expect 201 --quiet >/dev/null
  done
  control-agent-server api GET /api/agent-profiles --check profiles len-eq 50 --quiet
  control-agent-server api POST /api/agent-profiles/qa-f21-over --json '{"llm_profile_ref": "deepseek-flash"}' --expect 409 \
    --check detail eq 'Agent profile limit reached (50). Delete a profile before saving a new one.' --save F21.limit/over
  control-agent-server api GET /api/agent-profiles/qa-f21-over --expect 404
  control-agent-server state ls 'home/.openhands/agent-profiles/qa-f21-over.json' --expect-count 0
  control-agent-server api POST /api/agent-profiles/qa-f21-fill-49 --json '{"llm_profile_ref": "deepseek-pro"}' --expect 201
  control-agent-server api GET /api/agent-profiles/qa-f21-fill-49 --check profile.revision eq 1 --check profile.llm_profile_ref eq deepseek-pro
  for i in $(seq "$N" 49); do
    control-agent-server api DELETE "/api/agent-profiles/qa-f21-fill-$i" --expect 200 --quiet >/dev/null
  done
  control-agent-server api GET /api/agent-profiles --check profiles len-eq "$N" --quiet
  ```
  The 51st create is 409 and leaves no file, while an overwrite at the cap
  is 201; the fillers are deleted again.
- **Corrupt file (`F21.corrupt-file`).** A file in the store that is not
  JSON (written directly, as a crash or a bad edit would leave it).
  ```sh
  printf '{not json' > "$AGENT_SERVER_VERIFY_RUN/home/.openhands/agent-profiles/qa-f21-corrupt.json"
  control-agent-server api GET /api/agent-profiles --expect 200 --field profiles \
    | jq -e 'map(.name) | (index("qa-f21-corrupt") == null) and (index("qa-f21-coder") != null)'
  control-agent-server api GET /api/agent-profiles/qa-f21-corrupt --expect 400 \
    --check detail contains 'Failed to load profile' --save F21.corrupt-file/get
  control-agent-server api POST /api/agent-profiles/qa-f21-corrupt/materialize --json '{}' --expect 400 --check detail contains 'Failed to load profile'
  control-agent-server api POST /api/agent-profiles/qa-f21-corrupt/rename --json '{"new_name": "qa-f21-corrupt2"}' --expect 400
  control-agent-server api DELETE /api/agent-profiles/qa-f21-corrupt --expect 200
  control-agent-server state ls 'home/.openhands/agent-profiles/qa-f21-corrupt*' --expect-count 0
  ```
  The list skips the file and still answers; reading, previewing or
  renaming it is 400 with the JSON error; DELETE removes it.
- **Start a conversation from a profile (`F21.conversation-start`).** One
  tiny DeepSeek run on a profile that names `deepseek-pro`, while
  `deepseek-flash` stays the active LLM.
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f21-runner --json '{"llm_profile_ref": "deepseek-pro", "tools": [], "mcp_server_refs": []}' --expect 201
  RUNNER=$(control-agent-server api GET /api/agent-profiles/qa-f21-runner --field profile.id)
  control-agent-server api GET /api/settings --check active_profile eq deepseek-flash --check agent_settings.llm.model eq deepseek/deepseek-flash
  RCID=$(control-agent-server conversation start --agent-profile qa-f21-runner --no-autotitle --prompt 'Reply with exactly: ok' \
    --wait --until finished,error,stuck --timeout 240 --print-id --save F21.conversation-start/start)
  control-agent-server api GET "/api/conversations/$RCID" --quiet --check execution_status eq finished \
    --check launched_agent_profile.agent_profile_id eq "$RUNNER" --check launched_agent_profile.revision eq 0 \
    --check agent.llm.model eq deepseek/deepseek-v4-pro --check stats.usage_to_metrics.default.model_name eq deepseek/deepseek-v4-pro \
    --check stats.usage_to_metrics.default.accumulated_token_usage.prompt_tokens gt 0 --save F21.conversation-start/get
  control-agent-server conversation events "$RCID" --key stats --contains deepseek/deepseek-v4-pro --expect-min 1
  control-agent-server ws listen "/sockets/events/$RCID" --query resend_mode=all --expect-kind SystemPromptEvent \
    --expect-kind MessageEvent --duration 5 --save F21.conversation-start/ws-replay
  control-agent-server api POST /api/agent-profiles/qa-f21-runner --json '{"llm_profile_ref": "deepseek-flash", "tools": [], "mcp_server_refs": []}' --expect 201
  control-agent-server api GET /api/agent-profiles/qa-f21-runner --check profile.revision eq 1 --check profile.id eq "$RUNNER"
  control-agent-server api GET "/api/conversations/$RCID" --quiet --check launched_agent_profile.revision eq 0 \
    --check agent.llm.model eq deepseek/deepseek-v4-pro
  ```
  The conversation finishes on `deepseek/deepseek-v4-pro` (the profile's
  LLM, not the active `deepseek-flash`): the agent, the stats, the `stats`
  state event and the WebSocket replay agree, and `launched_agent_profile`
  names the profile id at revision 0. Editing the profile afterwards bumps
  its revision but not the conversation's record or model.
- **Secret scope (`F21.secret-scope`).** The same two start-time secrets on
  a scoped and an unscoped profile; neither conversation runs.
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f21-scoped --expect 201 \
    --json '{"llm_profile_ref": "deepseek-flash", "tools": [], "mcp_server_refs": [], "secret_refs": ["QA_F21_ALLOWED"]}'
  SCID=$(control-agent-server conversation start --agent-profile qa-f21-scoped --no-autotitle \
    --secret QA_F21_ALLOWED=qa-f21-allowed-value --secret QA_F21_OTHER=qa-f21-other-value --print-id)
  UCID=$(control-agent-server conversation start --agent-profile qa-f21-runner --no-autotitle \
    --secret QA_F21_ALLOWED=qa-f21-allowed-value --secret QA_F21_OTHER=qa-f21-other-value --print-id)
  control-agent-server api PATCH "/api/conversations/$SCID" --json '{"tags": {"qa": "f21-scope"}}' --expect 200 --quiet
  control-agent-server api PATCH "/api/conversations/$UCID" --json '{"tags": {"qa": "f21-scope"}}' --expect 200 --quiet
  control-agent-server api GET "/api/conversations/$SCID" --quiet --check launched_agent_profile.secret_refs len-eq 1 \
    --check launched_agent_profile.secret_refs contains QA_F21_ALLOWED \
    --check secret_registry.secret_sources.QA_F21_ALLOWED.kind eq StaticSecret \
    --check secret_registry.secret_sources.QA_F21_OTHER missing --save F21.secret-scope/scoped
  control-agent-server api GET "/api/conversations/$UCID" --quiet --check launched_agent_profile.secret_refs missing \
    --check secret_registry.secret_sources.QA_F21_ALLOWED.kind eq StaticSecret \
    --check secret_registry.secret_sources.QA_F21_OTHER.kind eq StaticSecret --save F21.secret-scope/unscoped
  control-agent-server state grep qa-f21-other-value --glob 'server/**/*' --expect-none
  ```
  Both creates succeed. After a tag edit saves each conversation's state,
  the scoped one records the allow-list and keeps only `QA_F21_ALLOWED`,
  while the unscoped one keeps both, so the filter comes from
  `secret_refs`. No plaintext secret value is stored.
- **Restart (`F21.restart`).**
  ```sh
  control-agent-server restart
  control-agent-server api GET /api/agent-profiles --check active_agent_profile_id eq "$CODER" --save F21.restart/list
  control-agent-server api GET /api/agent-profiles/qa-f21-coder --check profile.id eq "$CODER" --check profile.revision eq 1 \
    --check profile.persona eq 'QA F21 persona'
  control-agent-server api GET /api/agent-profiles/qa-f21-acp --check profile.id eq "$ACP" --check profile.agent_kind eq acp
  control-agent-server api GET /api/agent-profiles/default --check profile.id eq "$SEED"
  control-agent-server api GET /api/settings --check active_agent_profile_id eq "$CODER"
  control-agent-server doctor
  ```
  Every profile keeps its id and revision and the pointer still names
  `qa-f21-coder`; `doctor` is ok after the restart.
- **Store busy (`F21.store-busy`).** The bullet's own shell takes the
  store's file lock (`flock` on file descriptor 9, opened on the lock file
  the server uses), as another process sharing the persistence directory
  would.
  ```sh
  LOCK="$AGENT_SERVER_VERIFY_RUN/home/.openhands/agent-profiles/.agent-profiles.lock"
  exec 9>>"$LOCK"
  flock -w 5 9
  T0=$SECONDS
  control-agent-server api GET /api/agent-profiles/qa-f21-coder --timeout 90 --expect 503 \
    --check exception contains 'Profile store is busy' --save F21.store-busy/busy
  test $((SECONDS - T0)) -ge 25
  test $((SECONDS - T0)) -le 45
  flock -u 9
  control-agent-server api GET /api/agent-profiles/qa-f21-coder --expect 200 --check profile.id eq "$CODER"
  ```
  The request waits out the 30-second lock timeout and answers 503 (the
  5xx body is `{"detail": "Internal Server Error", "exception": "503:
  Profile store is busy. Please retry."}`); once the lock is released the
  same GET is 200. The lock also goes away when the bullet's shell exits.
- **Lock wait stalls the server (`F21.busy-blocks-server`), known bug.**
  The handlers are `async` but take the store's file lock synchronously, so
  the event loop waits with them.
  ```sh
  control-agent-server api GET /alive --auth none --expect 200 --expect-max-ms 2000
  LOCK="$AGENT_SERVER_VERIFY_RUN/home/.openhands/agent-profiles/.agent-profiles.lock"
  exec 9>>"$LOCK"
  flock -w 5 9
  (exec 9>&- >/dev/null 2>&1; control-agent-server api GET /api/agent-profiles/qa-f21-coder --timeout 90 --quiet) &
  sleep 2
  control-agent-server api GET /alive --auth none --expect 200 --timeout 60 --expect-max-ms 2000 --save F21.busy-blocks-server/alive
  flock -u 9
  wait
  ```
  Correct behavior: `/alive` answers within two seconds while the profile
  request waits for the lock (the bare `sleep 2` only lets that request
  reach the server). Today `/alive`, like every other route and socket,
  hangs until the 30-second lock wait ends, so orchestrator probes fail
  while any other process holds the lock. The background request does not
  inherit the lock, so the server recovers as soon as the shell exits.
- **`.json` names lose their identity (`F21.json-suffix-identity`), known bug.**
  The store strips a trailing `.json` from the file name but keeps it in the
  profile's `name`.
  ```sh
  control-agent-server api POST /api/agent-profiles/qa-f21-suffix.json --json '{"llm_profile_ref": "deepseek-flash"}' --expect 201
  J1=$(control-agent-server api GET /api/agent-profiles/qa-f21-suffix.json --check profile.revision eq 0 --field profile.id)
  control-agent-server api POST /api/agent-profiles/qa-f21-suffix.json --json '{"llm_profile_ref": "deepseek-pro"}' --expect 201
  control-agent-server api GET /api/agent-profiles/qa-f21-suffix.json --check profile.llm_profile_ref eq deepseek-pro \
    --check profile.id eq "$J1" --check profile.revision eq 1 --save F21.json-suffix-identity/after-overwrite
  ```
  Correct behavior: the overwrite keeps `J1` and moves to revision 1 (or
  the name is refused). Today the file is `qa-f21-suffix.json`, the list
  shows it as `qa-f21-suffix` (which GET also serves), and the identity
  lookup by the full name misses, so every save mints a new id at revision
  0: an active pointer on the old id dangles, and deleting the profile does
  not clear it.

## Gotchas

- `GET /api/agent-profiles` is not read-only on an empty store with no
  pointer: it writes `agent-profiles/default.json` and `settings.json`, and
  mirrors a keyed live LLM into a `default` LLM profile when no LLM profile
  is active. A pointer that names nothing (for example one set through
  `PATCH /api/settings`) suppresses the seed for good. Use other routes for
  read-only probes; `doctor` does.
- The seeded `default` references the active LLM profile, so that LLM
  profile cannot be deleted (409) while the agent profile exists (F20).
- Activate takes the stable uuid; every other route takes the name. The
  save response has no id: read it back with GET.
- Activation never touches `agent_settings`, and a conversation started
  with `agent_profile_id` resolves the profile at start time; the active
  pointer is only a UI selection. `conversation start` without
  `--agent-profile` starts from `agent_settings`, not from the pointer.
- A create keeps a client-supplied `revision` (a body with `"revision": 7`
  starts at 7); only overwrites ignore it. The recipes leave it out of
  creates.
- `PATCH /api/settings` that switches `agent_kind` rebuilds
  `agent_settings` from a fresh base and drops `mcp_config` (F18), so the
  ACP bullet adds `qa-f21-mcp` after the switch; deleting the active
  profile, in contrast, keeps it.
- Materialize discovers user and public skills; the public catalog may be
  cloned from GitHub into `OH_PERSISTENCE_DIR/cache/skills` on first use
  (tolerated when offline). The recipes assert only on the run's own
  `qa-f21-skill` and `len-ge 1`.
- A profile always launches its LLM with streaming on; the meta-profile
  reference is only checked when `enable_classify_and_switch_llm_tool` is
  true.
- Secrets given at conversation start are kept in memory and survive a
  restart, but `GET /api/conversations/{id}` shows an empty
  `secret_registry` until the conversation's state is saved again (a run,
  a tag edit); the secret-scope bullet edits a tag first, as F08 does.
- A profile file that is valid JSON but not a valid profile is listed
  (summaries read raw JSON) yet is 400 on GET. Through other families'
  routes the same profile is a deliberate 500 `Could not load agent
  profile` on `POST /api/conversations`, and an unhandled 500 on
  `GET /api/settings/secrets?agent_profile_id=` (F18), which also answers
  500 instead of 503 while the store is busy: it loads the profile outside
  the store error mapping.
- 5xx responses (the busy 503) carry `detail: "Internal Server Error"` and
  the real message in `exception`; 4xx carry `detail` directly.
- `--check` has no list projection, so recipes that look for a name in the
  list pipe `--field profiles` into `jq -e`.
