from typing import Any

import yaml
from openai import AsyncOpenAI


def get_config(filename: str = "config.yaml") -> dict[str, Any]:
    with open(filename, encoding="utf-8") as file:
        return yaml.safe_load(file)


def get_bot_token(config: dict[str, Any]) -> str:
    bot_token = (config.get("bot_token") or "").strip()
    if not bot_token:
        raise RuntimeError("config.yaml is missing Discord bot_token.")
    return bot_token


def get_openai_config(
    config: dict[str, Any], provider_slash_model: str
) -> tuple[AsyncOpenAI, dict[str, Any]]:
    provider, model = provider_slash_model.removesuffix(":vision").split("/", 1)
    provider_config = config["providers"][provider]

    openai_client = AsyncOpenAI(
        base_url=provider_config["base_url"],
        api_key=provider_config.get("api_key", "sk-no-key-required"),
    )

    model_parameters = config["models"].get(provider_slash_model, None)
    extra_body = (provider_config.get("extra_body") or {}) | (
        model_parameters or {}
    ) or None

    return openai_client, dict(
        model=model,
        extra_headers=provider_config.get("extra_headers"),
        extra_query=provider_config.get("extra_query"),
        extra_body=extra_body,
    )

