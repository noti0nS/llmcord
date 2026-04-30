# Copilot Instructions for `llmcord`

## Build, run, and verification commands

| Task                    | Command                                        |
| ----------------------- | ---------------------------------------------- |
| Install dependencies    | `python -m pip install -U -r requirements.txt` |
| Run bot locally         | `python llmcord.py`                            |
| Run tests               | `pytest`                                       |
| Run with Docker Compose | `docker compose up`                            |
| Build Docker image      | `docker build -t llmcord .`                    |

## High-level architecture

- The project is a **modular async bot** organized under `src/` with runtime behavior driven by `config.yaml` (template: `config-example.yaml`).
- Incoming Discord messages are processed in `src/bot.py:on_message()`, which:
  1. Applies DM/mention gating and permission checks (`users`, `roles`, `channels`, plus `admin_ids` override).
  2. Reconstructs conversation context by walking reply links, thread starter messages, and adjacent same-author history.
  3. Normalizes message content (text, embeds, text attachments, optional images) into OpenAI-compatible chat payloads.
  4. Calls an OpenAI-compatible endpoint via `AsyncOpenAI` (configured in `src/config.py:get_openai_config()`) using provider config + model parameters from YAML.
  5. Streams assistant output back to Discord via `src/llm.py:stream_completion_to_channel()` (embed streaming by default, plain text mode when configured).
- Message state is cached in a global `msg_nodes` dictionary keyed by Discord message ID, with per-node `asyncio.Lock` to avoid race conditions and duplicate fetch work.
- Config is hot-reloaded during runtime (notably in `on_message` and `/model` autocomplete), so edits to `config.yaml` take effect without restarting.

## Module organization

- `src/main.py`: process entrypoint (`asyncio.run(...)`, load config, instantiate bot).
- `src/config.py`: `get_config()`, `get_bot_token()`, `get_openai_config()`.
- `src/prompts/abnt.py`: ABNT prompt constants, markdown reference loading, and `build_abnt_messages()`.
- `src/llm.py`: `stream_completion_to_channel()`, `get_provider_error_detail()`.
- `src/bot.py`: `MsgNode`, `create_discord_bot()` factory, all event handlers and slash commands.
- `llmcord.py`: thin compatibility wrapper that calls `src.main.run()`.
- `tests/`: pytest unit tests for pure logic in `prompts`, `config`, and bot utilities.

## Key repository conventions

- **Model key format matters:** models are declared as `<provider>/<model>` in `config.yaml`; optional `:vision` suffix controls image acceptance heuristics.
- **Default model selection:** startup model is the first key in `config["models"]` (`curr_model = next(iter(config["models"]))`), so model order in YAML is significant.
- **OpenAI-compatible abstraction:** every provider is treated as OpenAI-compatible (`base_url`, optional `api_key`, optional `extra_headers` / `extra_query` / `extra_body`).
- **Model/provider parameter merging:** request body extras are merged from provider-level `extra_body` and per-model parameters.
- **User identity convention in prompts:** user messages sent to the LLM are prefixed as `<@DISCORD_ID>: ...`; keep this format when changing prompt construction.
- **Response mode behavior split:** `use_plain_responses: true` disables embed streaming/warnings and uses plain text chunks instead.
- **Cache bound convention:** `MAX_MESSAGE_NODES` limits cached conversation nodes and eviction removes oldest message IDs first.
- **Localization convention:** all bot user-facing responses must be in PT-BR.
