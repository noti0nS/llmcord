# Agent Instructions for `llmcord`

## Build, run, and verification commands

| Task | Command |
|------|---------|
| Install dependencies | `python -m pip install -U -r requirements.txt` |
| Run bot locally | `python llmcord.py` |
| Run tests | `pytest` |
| Run with Docker Compose | `docker compose up` |
| Build Docker image | `docker build -t llmcord .` |

No lint, typecheck, or CI config exists. Tests are plain pytest.

## High-level architecture

- Modular async Discord bot under `src/`, driven by `config.yaml` (copy from `config-example.yaml`).
- Entry point: `llmcord.py` → `src/main.py:run()` → `asyncio.run(main())`.
- `src/bot.py:create_discord_bot()` registers all event handlers and slash commands inside a factory closure.
- Incoming messages are processed in `on_message()`:
  1. Gating: DM/mention checks, then `user_has_permission()` (users/roles/channels, `admin_ids` override).
  2. Conversation rebuild: walks reply links, thread starter messages, and adjacent same-author history using the global `msg_nodes` cache.
  3. Content normalization: text, embeds, text-display components, text attachments, and optional images.
  4. LLM call via `AsyncOpenAI` using `src/config.py:get_openai_config()` + `build_openai_chat_completion_kwargs()`.
  5. Response streaming is handled **inline in `on_message()`**; `src/llm.py:stream_completion_to_channel()` is an unused helper.
- Config is hot-reloaded at the start of `on_message()` and in `/model` autocomplete when `curr_str == ""`.
- Message state is cached in a global `msg_nodes: dict[int, MsgNode]` with per-node `asyncio.Lock`.

## Runtime file dependencies

- `config.yaml` is required at runtime.
- `src/prompts/abnt_reference.md` and `src/prompts/discord_markdown_ref.md` are loaded at runtime; missing files crash the bot.

## Key repository conventions

- **Model key format:** `<provider>/<model>` in `config.yaml`; optional `:vision` suffix is stripped before API calls and does not enable vision support.
- **Vision heuristic:** image acceptance is determined by `VISION_MODEL_TAGS` substring matching against the model key in `bot.py` (e.g., `gpt-5`, `claude`, `grok-4`, `llama`).
- **Default model:** startup model is the first key in `config["models"]` (`curr_model = next(iter(config["models"]))`), so YAML order matters.
- **Parameter merging:** request `extra_body` is merged from provider-level `extra_body` and per-model parameters (`|` merge).
- **System prompt:** `build_system_prompt()` always appends the Discord markdown reference to whatever is configured in `system_prompt`.
- **User message prefix:** user messages sent to the LLM are prefixed as `<@DISCORD_ID>: ...`; preserve this format.
- **Response modes:** `use_plain_responses: true` disables embed streaming, warning messages, and uses `LayoutView` + `TextDisplay` instead.
- **ABNT command:** uses non-streaming completion (`stream=False`) and expects a structured JSON response (`score` + `improvements`).
- **Cache eviction:** `MAX_MESSAGE_NODES` bounds `msg_nodes`; eviction removes oldest message IDs first.
- **Localization:** all bot user-facing responses must be in PT-BR.

## Module map

- `src/main.py`: async entrypoint, bot startup, login failure handling.
- `src/config.py`: YAML loading, sensitive value masking, OpenAI client/request config building.
- `src/bot.py`: `MsgNode`, permission logic, document parsers (`docx`/`odt`), `create_discord_bot()` factory with all handlers.
- `src/llm.py`: `get_provider_error_detail()` (used); `stream_completion_to_channel()` (unused helper).
- `src/prompts/abnt.py`: ABNT prompt constants, reference loading, `build_abnt_messages()`.
- `src/prompts/discord_markdown.py`: Discord markdown reference loading and system prompt building.
- `tests/`: pytest unit tests for pure logic (prompts, config, bot utilities).
