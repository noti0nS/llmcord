from typing import Any

import discord
from openai import APIError, AsyncOpenAI


async def stream_completion_to_channel(
    channel: discord.abc.Messageable,
    openai_client: AsyncOpenAI,
    openai_config: dict[str, Any],
    messages: list[dict[str, Any]],
) -> str:
    finish_reason = None
    response_chunks = []
    pending_content = ""
    max_message_length = 2000

    async for chunk in await openai_client.chat.completions.create(
        **openai_config, messages=messages, stream=True
    ):
        if finish_reason is not None:
            break

        if not (choice := chunk.choices[0] if chunk.choices else None):
            continue

        finish_reason = choice.finish_reason
        new_content = choice.delta.content or ""

        if pending_content == "" and new_content == "":
            continue

        pending_content += new_content

        while len(pending_content) >= max_message_length:
            split_at = pending_content.rfind("\n\n", 0, max_message_length)
            if split_at < max_message_length // 2:
                split_at = pending_content.rfind("\n", 0, max_message_length)
            if split_at < max_message_length // 2:
                split_at = max_message_length

            chunk_content = pending_content[:split_at].strip()
            if chunk_content:
                response_chunks.append(chunk_content)
                await channel.send(chunk_content)

            pending_content = pending_content[split_at:].lstrip()

    if pending_content.strip():
        response_chunks.append(pending_content.strip())
        await channel.send(pending_content.strip())

    return "\n".join(response_chunks)


def get_provider_error_detail(exc: APIError) -> str:
    parts = [str(exc)]

    if code := getattr(exc, "code", None):
        parts.append(f"code={code}")
    if body := getattr(exc, "body", None):
        parts.append(f"body={body}")

    return "; ".join(parts)

