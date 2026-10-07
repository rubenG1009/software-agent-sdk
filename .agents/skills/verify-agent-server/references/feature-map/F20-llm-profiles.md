# LLM profiles

Named LLM configurations a consumer saves once and switches between: save a
model, key and options under a name, list the saved names with the active
one, read one back (key hidden, encrypted or plaintext on request), check a
draft against the real provider before saving it, make one the active LLM of
the server's settings, rename it (the active pointer and agent-profile
references follow), and delete it (refused while an agent profile still uses
it). Each profile is one JSON file under `OH_PERSISTENCE_DIR/profiles`, with
its key encrypted by the server's cipher, so profiles survive restarts. The
pre-flight `validate` route sends a real one-token completion with the posted
config and answers `valid` true or false; it never reads or writes the store.

Source: `openhands-agent-server/openhands/agent_server/profiles_router.py`, `openhands-agent-server/openhands/agent_server/_secrets_exposure.py`, `openhands-sdk/openhands/sdk/llm/llm_profile_store.py`, `openhands-sdk/openhands/sdk/profiles/profile_refs.py`, `clients/typescript/src/client/profiles-client.ts`

Needs: `llm`

Routes: `GET /api/profiles`, `GET /api/profiles/{name}`,
`POST /api/profiles/{name}`, `POST /api/profiles/{name}/validate`,
`DELETE /api/profiles/{name}`, `POST /api/profiles/{name}/rename`,
`POST /api/profiles/{name}/activate`

## Sub-features

- `F20.auth-required`: every profile route answers 401 without a valid `X-Session-API-Key`, and nothing changes.
- `F20.save`: `POST /api/profiles/{name}` with a DeepSeek model and key answers 201 `Profile '<name>' saved`; the list shows the summary `{name, model, base_url, provider_connection_id, provider_connection_broken, api_key_set: true}` and the active profile, and `GET` by name returns the config.
- `F20.key-encrypted-at-rest`: the profile file `home/.openhands/profiles/<name>.json` is mode `600` with `schema_version` 1 and a Fernet `gAAAAA` token as `api_key`; the plaintext key appears nowhere under the server's home.
- `F20.get-secrets`: `GET /api/profiles/{name}` returns `config.api_key: null` with `api_key_set: true` by default, the raw key with `X-Expose-Secrets: plaintext`, a `gAAAAA` token with `encrypted` (or the legacy `true`), and 400 for any other header value.
- `F20.save-encrypted-roundtrip`: posting back the `gAAAAA` token from an `encrypted` read stores the original key (the server decrypts it before re-encrypting), not the token.
- `F20.save-without-secrets`: `include_secrets: false` stores the placeholder `**********` instead of the key; both the list and `GET` report `api_key_set: false` and plaintext reads return `null`.
- `F20.not-found`: `GET`, `activate` and `rename` of an unknown name answer 404 `Profile '<name>' not found`, also for a same-name rename.
- `F20.name-rules`: names must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`: a leading `-` is 422 on all six named routes, 64 characters are accepted and 65 are 422; a body without `llm` or without `llm.model` is 422 and saves nothing.
- `F20.profile-limit`: with 50 profiles stored, creating another is 409 `Profile limit reached (50)` while overwriting an existing one still answers 201.
- `F20.validate-live`: `validate` with a working DeepSeek flash config answers `{valid: true, error: null}`, also when the key is the `gAAAAA` token from an `encrypted` read; the draft is not saved.
- `F20.validate-rejects`: `validate` answers 200 `valid: false` with a typed error for a model the provider does not serve (`LLMBadRequestError`) and for an invalid DeepSeek key, without echoing the key.
- `F20.validate-bad-key-type`: an invalid DeepSeek key (provider HTTP 401) is reported as `LLMAuthenticationError`, like any other provider's 401.
- `F20.validate-provider-errors`: with retries off, a provider 401 is `valid: false` `LLMAuthenticationError`, a 500 or an unreachable `base_url` is `valid: false` `LLMServiceUnavailableError`, and a 429 or a per-attempt timeout is `valid: true` (transient); the provider receives a system message `Reply with one token.`, a user `ping` and `max_tokens: 1`.
- `F20.validate-unreachable-bounded`: `validate` of a config whose `base_url` refuses connections answers `valid: false` within 30 seconds with the default retry policy.
- `F20.validate-hang-bounded`: `validate` of a config whose provider never answers returns a verdict within 30 seconds with the default timeout and retry policy.
- `F20.activate`: `POST /api/profiles/{name}/activate` answers 200 `llm_applied: true`; `GET /api/settings` then has the profile's LLM (model, key, options) in `agent_settings.llm` and `active_profile` set, the list reports the same `active_profile`, and `settings.json` holds the key encrypted.
- `F20.activate-conversation`: a conversation started from the saved settings after an activation runs on the activated profile's model and options and finishes.
- `F20.activate-acp`: with ACP agent settings, activation only moves the pointer: 200 `llm_applied: false`, `active_profile` set, no `agent_settings.llm`.
- `F20.activate-dangling-provider`: a profile linked to a provider connection that does not exist is saved without its inline key and `base_url`, is listed as `provider_connection_broken: true`, reads fine, and its activation is 422 without moving the active pointer.
- `F20.persist-restart`: profiles, their encrypted keys, options and the active pointer survive a restart with the same secret key.
- `F20.rename`: `POST /api/profiles/{name}/rename` moves the file and keeps the key; the old name is 404, `active_profile` follows the rename in the list and in settings, and agent profiles whose `llm_profile_ref` cited the old name now cite the new one.
- `F20.rename-errors`: renaming onto an existing name is 409 and changes nothing, a same-name rename is 200 `unchanged (same name)`, and an invalid or missing `new_name` is 422.
- `F20.delete-guarded`: deleting a profile that an agent profile references is 409 naming the referrer, and the profile stays.
- `F20.delete`: `DELETE /api/profiles/{name}` removes the file and the list entry and clears `active_profile` in both views, leaves the applied `agent_settings.llm` in place, and answers 200 again for a name that is already gone.
- `F20.secret-key-rotation`: after the server's secret key changes, activating a profile whose stored key can no longer be decrypted is refused instead of silently applying a keyless LLM.

## How to get to it (agent POV)

- REST: `GET /api/profiles`, `GET /api/profiles/{name}` (optional
  `X-Expose-Secrets: plaintext|encrypted`), `POST /api/profiles/{name}`
  (`{"llm": {...LLM fields...}, "include_secrets": true}`),
  `POST /api/profiles/{name}/validate` (`{"llm": {...}}`; the path name is
  only used for logging), `POST /api/profiles/{name}/activate` (no body),
  `POST /api/profiles/{name}/rename` (`{"new_name": "..."}`),
  `DELETE /api/profiles/{name}`. Every recipe below drives these routes.
- Second views used here: `GET /api/settings` (`active_profile`,
  `agent_settings.llm`, `llm_api_key_is_set`; settings family), the profile
  files under `home/.openhands/profiles/` (`state cat`), and
  `GET /api/agent-profiles/{name}` (`llm_profile_ref`; agent profiles family).
  `PATCH /api/settings` with `active_profile` is a second way to activate a
  profile (settings family).
- SDK: `RemoteWorkspace.get_llm(profile_name=...)` reads
  `GET /api/profiles/{name}` with `X-Expose-Secrets: plaintext` and builds an
  `LLM`; without a name it resolves `active_profile` from `GET /api/settings`
  first (`openhands-sdk/openhands/sdk/workspace/remote/base.py`). The SDK's
  local `LLMProfileStore` is the same file format without the server.
- TypeScript client: `ProfilesClient.listProfiles`, `getProfile(name,
  {exposeSecrets})`, `saveProfile`, `validateProfile`, `activateProfile`,
  `renameProfile`, `deleteProfile` (default request timeout 60 s), and the
  same calls on `SettingsClient`.
- Conversations: a conversation started from the saved settings (the Agent
  Canvas path, `conversation start` without agent fields) uses whatever the
  last activation wrote into `agent_settings.llm`
  (`F20.activate-conversation`).
- Agent Canvas (context only): the LLM settings page validates a draft before
  saving it, round-trips keys as `encrypted` tokens, and activates the chosen
  profile.

## Driving it with control-agent-server

Preconditions:

- A baseline run is live and exported (`launch --new`), `doctor` is ok,
  `$DEEPSEEK_API_KEY` is set, and `jq` is on `PATH`. The block below saves the
  DeepSeek preset (`deepseek-flash`, active, and `deepseek-pro`) and an agent
  profile `qa-f20-agent` whose `llm_profile_ref` is `qa-flash`; that reference
  stays soft until `F20.save` creates `qa-flash`, and `F20.rename` and
  `F20.delete-guarded` rely on it.
- Bodies that carry the real key are piped from the shell builtin `printf`
  into `api ... --stdin`, so the key never appears on a command line; the CLI
  redacts it from output and evidence.
- `F20.persist-restart` restarts the run; `F20.secret-key-rotation` restarts
  it with a new secret key and must stay last.

  ```sh
  control-agent-server llm preset deepseek
  control-agent-server api GET /api/profiles --expect 200 --check active_profile eq deepseek-flash --check profiles len-eq 2
  control-agent-server api POST /api/agent-profiles/qa-f20-agent --json '{"llm_profile_ref": "qa-flash"}' --expect 201
  ```

- **Key required (`F20.auth-required`).** Call every route without a key or
  with a wrong one.
  ```sh
  control-agent-server api GET /api/profiles --auth none --expect 401 --check detail eq Unauthorized --save F20.auth-required/list
  control-agent-server api GET /api/profiles/deepseek-flash --auth bad --expect 401
  control-agent-server api POST /api/profiles/qa-noauth --auth none --json '{"llm": {"model": "openai/qa"}}' --expect 401
  control-agent-server api POST /api/profiles/qa-noauth/validate --auth none --json '{"llm": {"model": "openai/qa"}}' --expect 401
  control-agent-server api POST /api/profiles/deepseek-pro/activate --auth none --expect 401
  control-agent-server api POST /api/profiles/deepseek-pro/rename --auth none --json '{"new_name": "qa-noauth"}' --expect 401
  control-agent-server api DELETE /api/profiles/deepseek-pro --auth none --expect 401
  control-agent-server api GET /api/profiles --expect 200 --check active_profile eq deepseek-flash --check profiles len-eq 2 --check profiles contains '"name": "deepseek-pro"'
  ```
  Every call is 401 `{"detail": "Unauthorized"}`; with the key the list still
  holds the two preset profiles and `deepseek-flash` is still active.
- **Save (`F20.save`).** Save the DeepSeek flash model with the real key and
  `num_retries: 0` (the marker later bullets use to tell this profile apart
  from the preset's `deepseek-flash`).
  ```sh
  printf '{"llm": {"model": "deepseek/deepseek-flash", "api_key": "%s", "num_retries": 0}}' "$DEEPSEEK_API_KEY" \
    | control-agent-server api POST /api/profiles/qa-flash --stdin --expect 201 \
      --check name eq qa-flash --check message eq "Profile 'qa-flash' saved" --save F20.save/save
  control-agent-server api GET /api/profiles --expect 200 --check profiles len-eq 3 --check active_profile eq deepseek-flash \
    --check profiles contains '"name": "qa-flash", "model": "deepseek/deepseek-flash", "base_url": null, "provider_connection_id": null, "provider_connection_broken": false, "api_key_set": true' \
    --save F20.save/list
  control-agent-server api GET /api/profiles/qa-flash --expect 200 --check name eq qa-flash \
    --check config.model eq deepseek/deepseek-flash --check config.num_retries eq 0 --check api_key_set eq true
  ```
  The save is 201, the list has three profiles including the `qa-flash`
  summary, and saving did not change the active profile.
- **Encrypted at rest (`F20.key-encrypted-at-rest`).** Read the file the save
  wrote.
  ```sh
  P="$AGENT_SERVER_VERIFY_RUN/home/.openhands/profiles"
  test "$(stat -c %a "$P/qa-flash.json")" = 600
  control-agent-server state cat home/.openhands/profiles/qa-flash.json \
    --check api_key matches '^gAAAAA' --check model eq deepseek/deepseek-flash --check schema_version eq 1
  control-agent-server state grep --env-value DEEPSEEK_API_KEY --glob 'home/**/*' --expect-none
  ```
  The file is `600`, its `api_key` is a Fernet token (printed as
  `<redacted:encrypted>`), and no file under the server's home contains the
  plaintext key (the preset's profiles and `settings.json` included).
- **Reading the key (`F20.get-secrets`).** Read the profile in each exposure
  mode.
  ```sh
  control-agent-server api GET /api/profiles/qa-flash --expect 200 --check config.api_key missing --check api_key_set eq true --save F20.get-secrets/default
  control-agent-server api GET /api/profiles/qa-flash --header 'X-Expose-Secrets: plaintext' --expect 200 \
    --check config.api_key eq "$DEEPSEEK_API_KEY" --save F20.get-secrets/plaintext
  control-agent-server api GET /api/profiles/qa-flash --header 'X-Expose-Secrets: encrypted' --expect 200 \
    --check config.api_key matches '^gAAAAA' --save F20.get-secrets/encrypted
  control-agent-server api GET /api/profiles/qa-flash --header 'X-Expose-Secrets: true' --expect 200 --check config.api_key matches '^gAAAAA'
  control-agent-server api GET /api/profiles/qa-flash --header 'X-Expose-Secrets: yes' --expect 400 \
    --check detail contains 'Invalid X-Expose-Secrets header value' --save F20.get-secrets/invalid-mode
  ```
  Without the header `config.api_key` is `null` and `api_key_set` is `true`;
  `plaintext` returns the DeepSeek key (redacted in the output), `encrypted`
  and the legacy `true` a `gAAAAA` token, and `yes` is 400.
- **Encrypted round trip (`F20.save-encrypted-roundtrip`).** Save a copy whose
  key is the token from an `encrypted` read, as Agent Canvas does.
  ```sh
  ENC=$(control-agent-server api GET /api/profiles/qa-flash --header 'X-Expose-Secrets: encrypted' --field config.api_key)
  control-agent-server api POST /api/profiles/qa-flash-copy \
    --json "{\"llm\": {\"model\": \"deepseek/deepseek-flash\", \"api_key\": \"$ENC\"}}" --expect 201 --save F20.save-encrypted-roundtrip/save
  control-agent-server api GET /api/profiles/qa-flash-copy --header 'X-Expose-Secrets: plaintext' --expect 200 \
    --check config.api_key eq "$DEEPSEEK_API_KEY" --save F20.save-encrypted-roundtrip/plaintext
  control-agent-server state cat home/.openhands/profiles/qa-flash-copy.json --check api_key matches '^gAAAAA'
  control-agent-server api DELETE /api/profiles/qa-flash-copy --expect 200
  ```
  The copy's plaintext key is the DeepSeek key itself, not the token; the
  copy is deleted at the end.
- **Save without secrets (`F20.save-without-secrets`).** Save a profile with
  a key and `include_secrets: false`.
  ```sh
  control-agent-server api POST /api/profiles/qa-nokey \
    --json '{"llm": {"model": "openai/qa-nokey", "api_key": "sk-qa-f20-not-stored"}, "include_secrets": false}' \
    --expect 201 --save F20.save-without-secrets/save
  control-agent-server state cat home/.openhands/profiles/qa-nokey.json --check api_key eq '**********' --not-contains sk-qa-f20-not-stored
  control-agent-server api GET /api/profiles \
    --check profiles contains '"name": "qa-nokey", "model": "openai/qa-nokey", "base_url": null, "provider_connection_id": null, "provider_connection_broken": false, "api_key_set": false' \
    --save F20.save-without-secrets/list
  control-agent-server api GET /api/profiles/qa-nokey --header 'X-Expose-Secrets: plaintext' --expect 200 \
    --check config.api_key missing --check api_key_set eq false
  ```
  The file holds `**********`, never the posted key; the list and `GET` say
  no key is set and a plaintext read returns `null`.
- **Unknown names (`F20.not-found`).** Read, activate and rename a name that
  was never saved.
  ```sh
  control-agent-server api GET /api/profiles/qa-missing --expect 404 --check detail eq "Profile 'qa-missing' not found" --save F20.not-found/get
  control-agent-server api POST /api/profiles/qa-missing/activate --expect 404 --check detail eq "Profile 'qa-missing' not found" --save F20.not-found/activate
  control-agent-server api POST /api/profiles/qa-missing/rename --json '{"new_name": "qa-other"}' --expect 404 --save F20.not-found/rename
  control-agent-server api POST /api/profiles/qa-missing/rename --json '{"new_name": "qa-missing"}' --expect 404
  control-agent-server api GET /api/profiles/qa-other --expect 404
  control-agent-server api GET /api/profiles --check active_profile eq deepseek-flash
  ```
  All are 404 and the active profile is unchanged.
- **Name rules (`F20.name-rules`).** Use a name with a leading `-`, the
  64-character limit, and bodies without `llm` or `model`.
  ```sh
  control-agent-server api GET /api/profiles/-qa-bad --expect 422 --check detail.0.type eq string_pattern_mismatch --check detail.0.loc.1 eq name --save F20.name-rules/get
  control-agent-server api POST /api/profiles/-qa-bad --json '{"llm": {"model": "openai/qa"}}' --expect 422
  control-agent-server api POST /api/profiles/-qa-bad/validate --json '{"llm": {"model": "openai/qa"}}' --expect 422
  control-agent-server api POST /api/profiles/-qa-bad/activate --expect 422
  control-agent-server api POST /api/profiles/-qa-bad/rename --json '{"new_name": "qa-ok"}' --expect 422
  control-agent-server api DELETE /api/profiles/-qa-bad --expect 422
  LONG="qa-$(printf 'x%.0s' $(seq 61))"
  test "${#LONG}" = 64
  control-agent-server api POST "/api/profiles/$LONG" --json '{"llm": {"model": "openai/qa"}}' --expect 201
  control-agent-server api GET "/api/profiles/${LONG}x" --expect 422 --check detail.0.type eq string_too_long --save F20.name-rules/too-long
  control-agent-server api DELETE "/api/profiles/$LONG" --expect 200
  control-agent-server api POST /api/profiles/qa-bad-body --json '{}' --expect 422 --check detail.0.loc.1 eq llm --save F20.name-rules/no-llm
  control-agent-server api POST /api/profiles/qa-bad-body --json '{"llm": {"api_key": "sk-qa-f20"}}' --expect 422 \
    --check detail.0.msg contains 'model must be specified' --save F20.name-rules/no-model
  control-agent-server api GET /api/profiles/qa-bad-body --expect 404
  control-agent-server api GET /api/profiles --check profiles len-eq 4
  ```
  Every `-qa-bad` call is 422 on the `name` path parameter, 64 characters
  save and 65 are 422 `string_too_long`, both bad bodies are 422, and the list
  is back to four profiles (two preset, `qa-flash`, `qa-nokey`).
- **Profile limit (`F20.profile-limit`).** Fill the store to 50, then create
  and overwrite.
  ```sh
  N=$(control-agent-server api GET /api/profiles --field profiles | jq length)
  for i in $(seq $((N + 1)) 50); do
    control-agent-server api POST "/api/profiles/qa-cap-$i" --json '{"llm": {"model": "openai/qa-cap"}}' --expect 201 --field name
  done
  control-agent-server api GET /api/profiles --check profiles len-eq 50 --max-chars 200
  control-agent-server api POST /api/profiles/qa-cap-51 --json '{"llm": {"model": "openai/qa-cap"}}' --expect 409 \
    --check detail eq 'Profile limit reached (50). Delete a profile before saving a new one.' --save F20.profile-limit/create-51st
  control-agent-server api GET /api/profiles/qa-cap-51 --expect 404
  control-agent-server api POST /api/profiles/qa-nokey --json '{"llm": {"model": "openai/qa-nokey", "temperature": 0.25}, "include_secrets": false}' \
    --expect 201 --save F20.profile-limit/overwrite-at-cap
  control-agent-server api GET /api/profiles/qa-nokey --check config.temperature eq 0.25
  for i in $(seq $((N + 1)) 50); do
    control-agent-server api DELETE "/api/profiles/qa-cap-$i" --expect 200 --field name
  done
  control-agent-server api GET /api/profiles --check profiles len-eq "$N"
  ```
  The 51st profile is 409 and not created; overwriting `qa-nokey` at the cap
  is 201 and its new `temperature` reads back; the filler profiles are
  deleted again.
- **Validate a working config (`F20.validate-live`).** Pre-flight the real
  DeepSeek flash model, once with the plaintext key and once with the
  `encrypted` token of `qa-flash`.
  ```sh
  printf '{"llm": {"model": "deepseek/deepseek-flash", "api_key": "%s", "num_retries": 0}}' "$DEEPSEEK_API_KEY" \
    | control-agent-server api POST /api/profiles/qa-draft/validate --stdin --timeout 120 --expect 200 \
      --check valid eq true --check error missing --save F20.validate-live/plaintext-key
  ENC=$(control-agent-server api GET /api/profiles/qa-flash --header 'X-Expose-Secrets: encrypted' --field config.api_key)
  control-agent-server api POST /api/profiles/qa-draft/validate --timeout 120 --expect 200 \
    --json "{\"llm\": {\"model\": \"deepseek/deepseek-flash\", \"api_key\": \"$ENC\", \"num_retries\": 0}}" \
    --check valid eq true --save F20.validate-live/encrypted-key
  control-agent-server api GET /api/profiles/qa-draft --expect 404
  control-agent-server api GET /api/profiles --check profiles len-eq 4
  ```
  Both answer `{"valid": true, "error": null}` (the token was decrypted
  before the call; sent as-is DeepSeek would reject it), and `qa-draft` was
  never saved.
- **Validate rejects (`F20.validate-rejects`).** Pre-flight a model DeepSeek
  does not serve, then an invalid key.
  ```sh
  printf '{"llm": {"model": "deepseek/qa-no-such-model", "api_key": "%s", "num_retries": 0}}' "$DEEPSEEK_API_KEY" \
    | control-agent-server api POST /api/profiles/qa-draft/validate --stdin --timeout 120 --expect 200 \
      --check valid eq false --check error.type eq LLMBadRequestError --save F20.validate-rejects/unknown-model
  control-agent-server api POST /api/profiles/qa-draft/validate --timeout 120 --expect 200 \
    --json '{"llm": {"model": "deepseek/deepseek-flash", "api_key": "sk-qa-f20-invalid-key", "num_retries": 0}}' \
    --check valid eq false --check error.type exists --check error.message not-contains sk-qa-f20-invalid-key \
    --save F20.validate-rejects/invalid-key
  control-agent-server api GET /api/profiles/qa-draft --expect 404
  ```
  Both are 200 with `valid: false` and a typed `error`; the provider's
  message is passed through redacted and does not contain the posted key.
- **DeepSeek 401 type (`F20.validate-bad-key-type`), known bug.** The invalid
  DeepSeek key should be classified like any provider 401.
  ```sh
  control-agent-server api POST /api/profiles/qa-draft/validate --timeout 120 --expect 200 \
    --json '{"llm": {"model": "deepseek/deepseek-flash", "api_key": "sk-qa-f20-invalid-key", "num_retries": 0}}' \
    --check valid eq false --check error.type eq LLMAuthenticationError --save F20.validate-bad-key-type/deepseek-401
  ```
  Expected `LLMAuthenticationError` (what an OpenAI-compatible 401 gives in
  `F20.validate-provider-errors`). Today it is `LLMBadRequestError`: DeepSeek
  answers HTTP 401 with `Authentication Fails, Your api key: ... is invalid`,
  LiteLLM raises it as `BadRequestError`, and the SDK's auth heuristics
  (`AUTH_PATTERNS` in `openhands-sdk/openhands/sdk/llm/exceptions/classifier.py`)
  do not match that text, so clients cannot tell a bad key from a bad request.
- **Provider failures (`F20.validate-provider-errors`).** Script an
  `llm-stub` to answer 401, 500, 429 and to hang, and point a draft with
  retries off at it and at a closed port.
  ```sh
  STUB=$(control-agent-server fixture llm-stub --name qa-f20-stub --step status:401 --print-path)
  STUB_LLM="{\"model\": \"openai/qa-stub\", \"base_url\": \"$STUB/v1\", \"api_key\": \"qa-stub-key\", \"num_retries\": 0}"
  control-agent-server api POST /api/profiles/qa-stub/validate --json "{\"llm\": $STUB_LLM}" --timeout 60 --expect 200 \
    --check valid eq false --check error.type eq LLMAuthenticationError --save F20.validate-provider-errors/401
  control-agent-server sink read --name qa-f20-stub --contains 'Reply with one token.' --expect-min 1 --save F20.validate-provider-errors/stub-request
  control-agent-server sink read --name qa-f20-stub --contains '"max_tokens": 1' --expect-min 1
  control-agent-server fixture llm-stub --name qa-f20-stub --step status:500
  control-agent-server api POST /api/profiles/qa-stub/validate --json "{\"llm\": $STUB_LLM}" --timeout 60 --expect 200 \
    --check valid eq false --check error.type eq LLMServiceUnavailableError --save F20.validate-provider-errors/500
  control-agent-server fixture llm-stub --name qa-f20-stub --step status:429
  control-agent-server api POST /api/profiles/qa-stub/validate --json "{\"llm\": $STUB_LLM}" --timeout 60 --expect 200 \
    --check valid eq true --check error missing --save F20.validate-provider-errors/429
  control-agent-server fixture llm-stub --name qa-f20-stub --step hang:30
  control-agent-server api POST /api/profiles/qa-stub/validate --timeout 60 --expect 200 \
    --json "{\"llm\": {\"model\": \"openai/qa-stub\", \"base_url\": \"$STUB/v1\", \"api_key\": \"qa-stub-key\", \"num_retries\": 0, \"timeout\": 3}}" \
    --check valid eq true --save F20.validate-provider-errors/timeout
  control-agent-server api POST /api/profiles/qa-unreachable/validate --timeout 60 --expect 200 \
    --json '{"llm": {"model": "openai/qa-unreachable", "base_url": "http://127.0.0.1:9/v1", "api_key": "qa-key", "num_retries": 0}}' \
    --check valid eq false --check error.type eq LLMServiceUnavailableError --save F20.validate-provider-errors/unreachable
  control-agent-server api GET /api/profiles --check profiles len-eq 4
  ```
  The stub's first request carries the system message `Reply with one
  token.`, a user `ping` and `max_tokens: 1`; 401 maps to
  `LLMAuthenticationError`, 500 and the closed port to
  `LLMServiceUnavailableError` (`valid: false`), while 429 and the 3-second
  timeout are transient (`valid: true`). Nothing is saved.
- **Unreachable endpoint is slow (`F20.validate-unreachable-bounded`), known bug.**
  The same closed port with the default retry policy (no `num_retries` in the
  body).
  ```sh
  control-agent-server api POST /api/profiles/qa-unreachable/validate --timeout 30 --expect 200 \
    --json '{"llm": {"model": "openai/qa-unreachable", "base_url": "http://127.0.0.1:9/v1", "api_key": "qa-key"}}' \
    --check valid eq false --check error.type eq LLMServiceUnavailableError --save F20.validate-unreachable-bounded/default-retries
  ```
  Expected a verdict within 30 s. Today the client gives up (`ReadTimeout`,
  exit 3): `validate` calls the posted LLM unchanged, so a connection error is
  retried with the LLM's defaults (`num_retries` 5, waits of 8 to 64 s), and
  the server answers `valid: false` only after about 120 s, twice the
  TypeScript `ProfilesClient`'s 60 s default timeout.
- **Hanging provider is slower (`F20.validate-hang-bounded`), known bug.**
  An `llm-stub` that never answers, with the default timeout and retries.
  ```sh
  HANG=$(control-agent-server fixture llm-stub --name qa-f20-hang --step hang:900 --print-path)
  control-agent-server api POST /api/profiles/qa-hang/validate --timeout 30 --expect 200 \
    --json "{\"llm\": {\"model\": \"openai/qa-stub\", \"base_url\": \"$HANG/v1\", \"api_key\": \"qa-stub-key\"}}" \
    --check valid exists --save F20.validate-hang-bounded/default-timeout
  ```
  Expected a verdict within 30 s. Today each attempt waits for the LLM's
  300 s `timeout` and the timeout is retried, so the request stays open for
  about half an hour and then answers `valid: true` (a timeout counts as
  transient), approving a provider that never answered.
- **Activate (`F20.activate`).** Make `qa-flash` the active LLM and read the
  settings back.
  ```sh
  control-agent-server api POST /api/profiles/qa-flash/activate --expect 200 --check name eq qa-flash --check llm_applied eq true \
    --check message eq "Profile 'qa-flash' activated and applied to current settings" --save F20.activate/activate
  control-agent-server api GET /api/profiles --check active_profile eq qa-flash --save F20.activate/list
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --expect 200 --max-chars 300 \
    --check active_profile eq qa-flash --check agent_settings.llm.model eq deepseek/deepseek-flash \
    --check agent_settings.llm.api_key eq "$DEEPSEEK_API_KEY" --check agent_settings.llm.num_retries eq 0 \
    --check llm_api_key_is_set eq true --save F20.activate/settings
  control-agent-server state cat home/.openhands/settings.json --max-chars 300 \
    --check active_profile eq qa-flash --check agent_settings.llm.api_key matches '^gAAAAA'
  ```
  The response says the LLM was applied; settings carry `qa-flash`'s model,
  key and `num_retries: 0` (the preset's profile has 5), and `settings.json`
  stores the key encrypted.
- **Activation drives conversations (`F20.activate-conversation`).** Start a
  conversation from the saved settings with no tools and a one-word prompt.
  ```sh
  CID=$(control-agent-server conversation start --tools none --no-autotitle --prompt 'Reply with one word: pong' --wait --timeout 180 --print-id)
  control-agent-server api GET "/api/conversations/$CID" --expect 200 --max-chars 300 \
    --check execution_status eq finished --check agent.llm.model eq deepseek/deepseek-flash --check agent.llm.num_retries eq 0 \
    --check stats.usage_to_metrics.default.model_name eq deepseek/deepseek-flash \
    --check stats.usage_to_metrics.default.accumulated_token_usage.prompt_tokens gt 0 --save F20.activate-conversation/conversation
  control-agent-server api DELETE "/api/conversations/$CID" --expect 200
  ```
  The conversation finishes on `deepseek/deepseek-flash` with
  `num_retries: 0` (so the agent came from `qa-flash`, not the preset), and
  its usage metrics show real prompt tokens. The conversation is deleted.
- **ACP settings (`F20.activate-acp`).** Switch the agent kind to ACP,
  activate, then restore.
  ```sh
  control-agent-server api PATCH /api/settings --json '{"agent_settings_diff": {"agent_kind": "acp"}}' --expect 200 --max-chars 200 \
    --check agent_settings.agent_kind eq acp
  control-agent-server api POST /api/profiles/qa-nokey/activate --expect 200 --check llm_applied eq false \
    --check message eq "Profile 'qa-nokey' activated" --save F20.activate-acp/activate
  control-agent-server api GET /api/settings --expect 200 --max-chars 200 --check active_profile eq qa-nokey \
    --check agent_settings.agent_kind eq acp --check agent_settings.llm missing --save F20.activate-acp/settings
  control-agent-server api PATCH /api/settings --json '{"agent_settings_diff": {"agent_kind": "openhands"}}' --expect 200 --max-chars 200 \
    --check agent_settings.agent_kind eq openhands
  control-agent-server api POST /api/profiles/qa-flash/activate --expect 200 --check llm_applied eq true
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --max-chars 200 --check active_profile eq qa-flash \
    --check agent_settings.llm.model eq deepseek/deepseek-flash --check agent_settings.llm.api_key eq "$DEEPSEEK_API_KEY"
  ```
  On ACP settings the activation answers `llm_applied: false` and only moves
  `active_profile`; back on OpenHands settings `qa-flash` is re-activated for
  the next bullets.
- **Dangling provider link (`F20.activate-dangling-provider`).** Save a
  profile linked to a provider connection id that does not exist, with an
  inline key and `base_url`.
  ```sh
  control-agent-server api POST /api/profiles/qa-linked --expect 201 \
    --json '{"llm": {"model": "openai/qa-linked", "api_key": "sk-qa-f20-linked", "base_url": "http://127.0.0.1:9/v1", "provider_connection_id": "qa-no-such-connection"}}'
  control-agent-server state cat home/.openhands/profiles/qa-linked.json --not-contains sk-qa-f20-linked \
    --check provider_connection_id eq qa-no-such-connection --check api_key missing --check base_url missing
  control-agent-server api GET /api/profiles \
    --check profiles contains '"name": "qa-linked", "model": "openai/qa-linked", "base_url": null, "provider_connection_id": "qa-no-such-connection", "provider_connection_broken": true, "api_key_set": false' \
    --save F20.activate-dangling-provider/list
  control-agent-server api GET /api/profiles/qa-linked --header 'X-Expose-Secrets: plaintext' --expect 200 \
    --check config.provider_connection_id eq qa-no-such-connection --check config.api_key missing --check api_key_set eq false
  control-agent-server api POST /api/profiles/qa-linked/activate --expect 422 \
    --check detail eq "Profile 'qa-linked' references provider connection 'qa-no-such-connection', which does not exist. Update the profile or recreate the connection." \
    --save F20.activate-dangling-provider/activate
  control-agent-server api GET /api/profiles --check active_profile eq qa-flash
  control-agent-server api DELETE /api/profiles/qa-linked --expect 200
  ```
  The inline key and `base_url` are dropped on save (the connection owns
  them), the list flags the link as broken, `GET` still works, and the
  activation is 422 with `qa-flash` still active.
- **Restart (`F20.persist-restart`).** Restart the run and read everything
  back.
  ```sh
  control-agent-server restart
  control-agent-server api GET /api/profiles --expect 200 --check active_profile eq qa-flash --check profiles len-eq 4 \
    --check profiles contains '"name": "qa-flash", "model": "deepseek/deepseek-flash", "base_url": null, "provider_connection_id": null, "provider_connection_broken": false, "api_key_set": true' \
    --check profiles contains '"name": "qa-nokey", "model": "openai/qa-nokey", "base_url": null, "provider_connection_id": null, "provider_connection_broken": false, "api_key_set": false' \
    --save F20.persist-restart/list
  control-agent-server api GET /api/profiles/qa-flash --header 'X-Expose-Secrets: plaintext' --expect 200 \
    --check config.api_key eq "$DEEPSEEK_API_KEY" --check config.num_retries eq 0 --save F20.persist-restart/plaintext
  control-agent-server api GET /api/profiles/qa-nokey --check config.temperature eq 0.25
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --max-chars 200 \
    --check active_profile eq qa-flash --check agent_settings.llm.api_key eq "$DEEPSEEK_API_KEY"
  ```
  The four profiles, `qa-flash`'s decryptable key and options, `qa-nokey`'s
  overwrite and the active pointer all survive.
- **Rename (`F20.rename`).** Rename the active profile that `qa-f20-agent`
  cites.
  ```sh
  control-agent-server api POST /api/profiles/qa-flash/rename --json '{"new_name": "qa-fast"}' --expect 200 --check name eq qa-fast \
    --check message eq "Profile 'qa-flash' renamed to 'qa-fast'" --save F20.rename/rename
  control-agent-server api GET /api/profiles/qa-flash --expect 404
  control-agent-server api GET /api/profiles/qa-fast --header 'X-Expose-Secrets: plaintext' --expect 200 \
    --check config.model eq deepseek/deepseek-flash --check config.api_key eq "$DEEPSEEK_API_KEY"
  control-agent-server api GET /api/profiles --check active_profile eq qa-fast --check profiles not-contains '"name": "qa-flash"' --save F20.rename/list
  control-agent-server api GET /api/settings --max-chars 200 --check active_profile eq qa-fast --check agent_settings.llm.model eq deepseek/deepseek-flash
  control-agent-server api GET /api/agent-profiles/qa-f20-agent --expect 200 --max-chars 200 --check profile.llm_profile_ref eq qa-fast \
    --save F20.rename/agent-profile
  test -f "$AGENT_SERVER_VERIFY_RUN/home/.openhands/profiles/qa-fast.json"
  test ! -e "$AGENT_SERVER_VERIFY_RUN/home/.openhands/profiles/qa-flash.json"
  ```
  The old name is gone, the new one keeps the key, `active_profile` is
  `qa-fast` in the list and in settings, and the agent profile's
  `llm_profile_ref` follows.
- **Rename errors (`F20.rename-errors`).** Rename onto a taken name, onto
  itself, and to invalid names.
  ```sh
  control-agent-server api POST /api/profiles/qa-fast/rename --json '{"new_name": "qa-nokey"}' --expect 409 \
    --check detail eq "Profile 'qa-nokey' already exists" --save F20.rename-errors/conflict
  control-agent-server api GET /api/profiles/qa-nokey --check config.model eq openai/qa-nokey --check config.temperature eq 0.25
  control-agent-server api POST /api/profiles/qa-fast/rename --json '{"new_name": "qa-fast"}' --expect 200 \
    --check message eq "Profile 'qa-fast' unchanged (same name)" --save F20.rename-errors/same-name
  control-agent-server api POST /api/profiles/qa-fast/rename --json '{"new_name": ".qa-hidden"}' --expect 422 --check detail.0.loc.1 eq new_name
  control-agent-server api POST /api/profiles/qa-fast/rename --json '{}' --expect 422 --check detail.0.type eq missing
  control-agent-server api GET /api/profiles --check active_profile eq qa-fast --check profiles len-eq 4
  ```
  The conflict is 409 and both profiles are untouched; the same-name rename
  is a 200 no-op; the bad bodies are 422.
- **Guarded delete (`F20.delete-guarded`).** Delete the profile
  `qa-f20-agent` still cites.
  ```sh
  control-agent-server api DELETE /api/profiles/qa-fast --expect 409 \
    --check detail eq 'LLM profile is referenced by 1 agent profile(s): qa-f20-agent' --save F20.delete-guarded/delete
  control-agent-server api GET /api/profiles/qa-fast --expect 200
  control-agent-server api GET /api/profiles --check active_profile eq qa-fast
  control-agent-server api DELETE /api/agent-profiles/qa-f20-agent --expect 200
  ```
  The delete is 409 naming the referrer and the profile stays active; the
  agent profile is then deleted so `F20.delete` can proceed.
- **Delete (`F20.delete`).** Delete the active profile, twice.
  ```sh
  control-agent-server api DELETE /api/profiles/qa-fast --expect 200 --check name eq qa-fast \
    --check message eq "Profile 'qa-fast' deleted" --save F20.delete/delete
  control-agent-server api GET /api/profiles/qa-fast --expect 404
  control-agent-server api GET /api/profiles --check active_profile missing --check profiles len-eq 3 \
    --check profiles not-contains '"name": "qa-fast"' --save F20.delete/list
  control-agent-server api GET /api/settings --header 'X-Expose-Secrets: plaintext' --max-chars 200 --check active_profile missing \
    --check agent_settings.llm.model eq deepseek/deepseek-flash --check agent_settings.llm.api_key eq "$DEEPSEEK_API_KEY" \
    --save F20.delete/settings
  test ! -e "$AGENT_SERVER_VERIFY_RUN/home/.openhands/profiles/qa-fast.json"
  control-agent-server api DELETE /api/profiles/qa-fast --expect 200 --check message eq "Profile 'qa-fast' deleted" --save F20.delete/repeat
  control-agent-server api POST /api/profiles/deepseek-flash/activate --expect 200 --check llm_applied eq true
  ```
  The profile and its file are gone and `active_profile` is `null` in both
  views, while `agent_settings.llm` still holds the deleted profile's model
  and key; the repeated delete is 200 too. `deepseek-flash` is re-activated
  to restore the preset state.
- **Secret key rotation (`F20.secret-key-rotation`), known bug.** Save a
  profile, restart with a new secret key, then activate it.
  ```sh
  control-agent-server api POST /api/profiles/qa-rotate --json '{"llm": {"model": "openai/qa-rotate", "api_key": "sk-qa-f20-rotate"}}' --expect 201
  control-agent-server restart --rotate-secret-key
  control-agent-server state cat home/.openhands/profiles/qa-rotate.json --check api_key matches '^gAAAAA'
  control-agent-server api GET /api/profiles/qa-rotate --header 'X-Expose-Secrets: plaintext' --expect 2xx,4xx --save F20.secret-key-rotation/detail
  control-agent-server api GET /api/profiles --expect 2xx,4xx --save F20.secret-key-rotation/list
  control-agent-server api POST /api/profiles/qa-rotate/activate --expect 4xx --save F20.secret-key-rotation/activate
  control-agent-server api GET /api/settings --max-chars 200 --check active_profile eq deepseek-flash
  ```
  Expected the activation to be refused (4xx) while the stored key cannot be
  decrypted, leaving `deepseek-flash` active. Today the file still holds the
  old token, `GET` by name says `api_key_set: false` with a `null` key while
  the list still says `api_key_set: true`, and the activation answers 200
  `activated and applied to current settings` after writing an LLM with
  `api_key: null` into the settings (`llm_api_key_is_set` becomes `false`),
  so the next conversation fails at the provider. The cipher returns `None`
  for a token it cannot decrypt instead of raising
  (`openhands-sdk/openhands/sdk/utils/cipher.py`), and the profile store
  loads that silently. Run last: every stored secret of this run is now
  unreadable.

## Gotchas

- The DeepSeek flash model string is `deepseek/deepseek-flash` (what the
  `deepseek` preset saves). `deepseek/deepseek-v4.1-flash` saves fine (models
  are not checked on save) but `validate` answers `valid: false`,
  `LLMBadRequestError`: DeepSeek only serves `deepseek-flash` and
  `deepseek-v4-pro`.
- `validate` uses the posted LLM's own retry and timeout policy (defaults
  `num_retries` 5, `retry_min_wait` 8, `retry_max_wait` 64, `timeout` 300).
  Always send `"num_retries": 0` (and a small `timeout` against stubs) unless
  the duration is what you test, and give the CLI a `--timeout` longer than
  the policy; `llm set` and `llm preset` validate with a 120 s client timeout.
  Requests the CLI gave up on keep running in the server until the policy
  ends.
- `validate` never reads the stored profile: the body's `llm` is required and
  the path name only appears in the log. To pre-flight a stored profile, read
  it with `X-Expose-Secrets: encrypted` and post that config back.
- Rate limits and timeouts count as transient and answer `valid: true`; a
  provider 503 or a refused connection is `valid: false`. A `valid: true` is
  therefore not proof that the provider answered.
- A real DeepSeek bad key is `LLMBadRequestError`, not
  `LLMAuthenticationError` (`F20.validate-bad-key-type`); match on `valid`,
  not on `error.type`, when the provider is DeepSeek.
- The list's `api_key_set` is computed from the raw file without decrypting
  (any non-empty value except `**********` counts), while `GET` by name
  decrypts; they disagree when a token cannot be decrypted
  (`F20.secret-key-rotation`). A linked provider connection's key counts as
  the profile's key in both.
- Saving never changes `active_profile`, even when the active profile is
  overwritten: `agent_settings.llm` keeps the old copy until the profile is
  activated again. Deleting the active profile clears the pointer but leaves
  the applied LLM in `agent_settings.llm`.
- Activation on ACP settings only moves the pointer. Switching
  `agent_kind` back to `openhands` with `PATCH /api/settings` resets
  `agent_settings.llm` to the defaults while `active_profile` keeps naming the
  profile, so `RemoteWorkspace.get_llm()` (which follows the pointer) and a
  conversation started from settings disagree until the profile is activated
  again.
- `GET /api/agent-profiles` (the list) seeds a `default` agent profile that
  references the active LLM profile when the agent-profile store is empty;
  after that, deleting the active LLM profile is 409. This family only reads
  agent profiles by name, which seeds nothing.
- Names ending in `.json` are stored without the suffix, so `foo` and
  `foo.json` are the same profile.
- `launch` always sets `OH_SECRET_KEY` (an empty `--env OH_SECRET_KEY=` still
  yields a cipher), so the no-cipher behaviors (keys stored in plaintext,
  `X-Expose-Secrets: encrypted` answering 503) are not reachable with the
  current CLI.
- Profile routes emit no WebSocket events; the second views are
  `GET /api/settings`, the list and the files on disk.
- The closed port `127.0.0.1:9` stands in for an unreachable provider; if
  something listens there on your machine, pick another closed port.
