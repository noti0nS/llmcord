import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, cast

import discord
from discord.ext import commands
from openai import APIError

from ..config import build_openai_chat_completion_kwargs, get_config, get_openai_config
from ..helpers.async_utils import await_task_with_heartbeats
from ..helpers.content import get_completion_text
from ..helpers.documents import generate_document
from ..helpers.llm import get_provider_error_detail
from ..helpers.search import fetch_page_content, search_topics
from ..prompts.pesquisa import build_pesquisa_messages

WEB_SEARCH_TOOL: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Busca na web por artigos jurídicos, jurisprudência, doutrina e fontes acadêmicas. "
                "Use quando precisar de informações atualizadas ou fontes específicas não disponíveis "
                "em seus dados de treinamento."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Termo de busca em português para encontrar fontes jurídicas relevantes",
                    }
                },
                "required": ["query"],
            },
        },
    }
]

FETCH_PAGE_TOOL: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": (
                "Acessa o conteúdo completo de uma página web. "
                "Use para obter o texto integral de artigos, decisões, doutrina "
                "e outras fontes acadêmicas encontradas nas buscas. "
                "Retorna o texto extraído da página (limitado a ~8000 caracteres). "
                "Só use para URLs retornadas pela ferramenta web_search."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL completa da página a ser acessada (ex: https://exemplo.com/artigo)",
                    }
                },
                "required": ["url"],
            },
        },
    }
]

ALL_PESQUISA_TOOLS = WEB_SEARCH_TOOL + FETCH_PAGE_TOOL

FORMATO_CHOICES = [
    discord.app_commands.Choice(name="DOCX (Microsoft Word)", value="docx"),
    discord.app_commands.Choice(name="ODT (LibreOffice)", value="odt"),
]


def build_pesquisa_filename(title: str, output_format: str) -> str:
    safe_title = re.sub(r"[^\w\s-]", "", title).strip()[:50]
    safe_title = re.sub(r"[-\s]+", "_", safe_title)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = ".odt" if output_format.lower() == "odt" else ".docx"
    return f"pesquisa_{safe_title}_{timestamp}{ext}"


async def send_pesquisa_result(
    interaction: discord.Interaction,
    content: str,
    filename: str,
    file_bytes: bytes,
) -> None:
    max_file_size = 7.5 * 1024 * 1024

    if len(file_bytes) < max_file_size:
        file = discord.File(
            fp=__import__("io").BytesIO(file_bytes),
            filename=filename,
        )
        await interaction.followup.send(
            "Pesquisa concluída! Aqui está o documento:",
            file=file,
        )
    else:
        channel = interaction.channel
        if channel is None:
            await interaction.followup.send(
                "Não foi possível criar uma thread para enviar o documento.",
            )
            return

        thread_name = (
            f"Pesquisa: {filename.replace('.docx', '').replace('.odt', '')[:80]}"
        )
        thread = await cast(discord.TextChannel, channel).create_thread(
            name=thread_name,
            type=discord.ChannelType.public_thread,
        )

        max_message_length = 1900
        chunks = []
        current_chunk = ""

        for line in content.split("\n"):
            if len(current_chunk) + len(line) + 1 > max_message_length:
                chunks.append(current_chunk)
                current_chunk = line + "\n"
            else:
                current_chunk += line + "\n"

        if current_chunk:
            chunks.append(current_chunk)

        await thread.send(
            f"**Pesquisa concluída!** O documento foi dividido em {len(chunks)} partes.\n"
            + "(O arquivo original excede o limite de tamanho do Discord, então foi enviado em mensagens.)"
        )

        for i, chunk in enumerate(chunks, 1):
            await thread.send(f"**Parte {i}/{len(chunks)}**\n```\n{chunk}\n```")

        await interaction.followup.send(
            f"Pesquisa concluída! O documento foi enviado na thread: {thread.mention}"
        )


def _format_tool_call(tool_call: Any) -> dict[str, Any]:
    return {
        "id": tool_call.id,
        "type": "function",
        "function": {
            "name": tool_call.function.name,
            "arguments": tool_call.function.arguments,
        },
    }


def _format_search_results(results: list[dict[str, Any]]) -> str:
    formatted = []
    for r in results:
        formatted.append(
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("snippet", ""),
            }
        )
    return json.dumps(formatted, ensure_ascii=False)


def register_pesquisa_command(
    discord_bot: commands.Bot,
    state: Any,
) -> None:
    @discord_bot.tree.command(
        name="pesquisa",
        description="Gere um documento acadêmico ABNT a partir de uma descrição de pesquisa",
    )
    @discord.app_commands.describe(
        topic="Descreva sua pesquisa em texto livre: tema, tipo de documento, tópicos, etc.",
        format="Formato do arquivo de saída",
    )
    @discord.app_commands.choices(
        format=FORMATO_CHOICES,
    )
    async def pesquisa_command(  # pyright: ignore[reportUnusedFunction]
        interaction: discord.Interaction,
        topic: str,
        format: discord.app_commands.Choice[str] | None = None,
    ) -> None:
        state.config = await asyncio.to_thread(get_config)

        formato_valor = format.value if format else "docx"

        if not topic.strip():
            await interaction.response.send_message(
                "Descreva sua pesquisa. Exemplo: "
                + "`Preciso de uma monografia sobre alvará judicial no TJSP, aprofundada para professor.`",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Pesquisando e gerando o documento... Isso pode levar alguns minutos.",
            ephemeral=True,
        )

        logging.info(
            "Pesquisa started (user ID: %s, topic_len: %s, formato: %s)",
            interaction.user.id,
            len(topic),
            formato_valor,
        )

        messages: list[dict[str, Any]] = build_pesquisa_messages(topic)

        research_config = state.config.get("research", {})
        max_iterations = research_config.get("max_tool_iterations", 15)
        search_results_count = research_config.get("search_results_per_topic", 8)
        max_pages = research_config.get("max_page_fetches", 5)

        openai_client, openai_config = get_openai_config(state.config, state.curr_model)

        raw_output = ""
        request_started_at = datetime.now().timestamp()
        pages_fetched = 0

        try:
            for iteration in range(max_iterations):
                logging.info(
                    "Pesquisa LLM iteration %s/%s (user ID: %s, model: %s)",
                    iteration + 1,
                    max_iterations,
                    interaction.user.id,
                    openai_config["model"],
                )

                completion_task = asyncio.create_task(
                    openai_client.chat.completions.create(
                        **build_openai_chat_completion_kwargs(
                            openai_config,
                            messages,
                            stream=False,
                            tools=ALL_PESQUISA_TOOLS,
                        )
                    )
                )
                completion = await await_task_with_heartbeats(
                    completion_task,
                    (
                        "Pesquisa LLM request still running "
                        f"(user ID: {interaction.user.id}, "
                        f"model: {openai_config['model']})"
                    ),
                )

                if not completion.choices:
                    raise RuntimeError("LLM returned no choices")

                choice = completion.choices[0]

                # Handle tool calls
                if (
                    choice.finish_reason == "tool_calls"
                    and choice.message
                    and choice.message.tool_calls
                ):
                    tool_calls = choice.message.tool_calls

                    tool_summary = [
                        f"{tc.function.name}({tc.function.arguments})"
                        for tc in tool_calls
                    ]
                    logging.info(
                        "Pesquisa tool calls requested (user ID: %s): %s",
                        interaction.user.id,
                        "; ".join(tool_summary),
                    )

                    messages.append(
                        {
                            "role": "assistant",
                            "content": choice.message.content or "",
                            "tool_calls": [_format_tool_call(tc) for tc in tool_calls],
                        }
                    )

                    for tc in tool_calls:
                        if tc.function.name == "web_search":
                            try:
                                args = json.loads(tc.function.arguments)
                            except json.JSONDecodeError:
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tc.id,
                                        "content": "Erro: argumentos inválidos.",
                                    }
                                )
                                continue

                            query = args.get("query", "")
                            logging.info(
                                "Pesquisa web_search (user ID: %s, query: %s)",
                                interaction.user.id,
                                query,
                            )

                            try:
                                results = await search_topics(
                                    [query],
                                    max_results=search_results_count,
                                )
                                search_data = results.get(query, [])
                            except Exception:
                                logging.exception(
                                    "Pesquisa web search failed for query: %s",
                                    query,
                                )
                                search_data = []

                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "content": _format_search_results(search_data),
                                }
                            )

                        elif tc.function.name == "fetch_page":
                            if pages_fetched >= max_pages:
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tc.id,
                                        "content": (
                                            "Limite de páginas atingido. "
                                            "Continue com as fontes já obtidas."
                                        ),
                                    }
                                )
                                continue

                            try:
                                args = json.loads(tc.function.arguments)
                            except json.JSONDecodeError:
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tc.id,
                                        "content": "Erro: argumentos inválidos.",
                                    }
                                )
                                continue

                            url = args.get("url", "")
                            logging.info(
                                "Pesquisa fetch_page (user ID: %s, url: %s)",
                                interaction.user.id,
                                url,
                            )
                            pages_fetched += 1

                            page_content = await fetch_page_content(url)
                            if page_content:
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tc.id,
                                        "content": page_content,
                                    }
                                )
                            else:
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tc.id,
                                        "content": (
                                            "Não foi possível acessar o conteúdo "
                                            "desta página. Tente outra URL ou "
                                            "continue com as fontes disponíveis."
                                        ),
                                    }
                                )

                    continue

                # Handle stop (document complete)
                if choice.finish_reason == "stop":
                    raw_output = get_completion_text(completion)
                    if raw_output:
                        break
                    continue

                # Handle length (max_tokens reached)
                if choice.finish_reason == "length":
                    logging.warning(
                        "Pesquisa LLM reached max_tokens (user ID: %s)",
                        interaction.user.id,
                    )
                    raw_output = get_completion_text(completion)
                    break

                # Handle content_filter
                if choice.finish_reason == "content_filter":
                    logging.error(
                        "Pesquisa LLM content filter triggered (user ID: %s)",
                        interaction.user.id,
                    )
                    await interaction.followup.send(
                        "A geração do documento foi bloqueada pelo filtro de conteúdo do provedor."
                    )
                    return

                # Unexpected finish reason — capture whatever content exists
                raw_output = get_completion_text(completion)
                if raw_output:
                    break

            # If loop exhausted without content, force final generation
            if not raw_output.strip():
                logging.warning(
                    "Pesquisa tool loop exhausted, forcing final generation (user ID: %s)",
                    interaction.user.id,
                )
                force_task = asyncio.create_task(
                    openai_client.chat.completions.create(
                        **build_openai_chat_completion_kwargs(
                            openai_config,
                            messages,
                            stream=False,
                            tool_choice="none",
                        )
                    )
                )
                force_completion = await await_task_with_heartbeats(
                    force_task,
                    "Pesquisa final generation still running",
                )
                raw_output = get_completion_text(force_completion)

            elapsed = datetime.now().timestamp() - request_started_at
            logging.info(
                "Pesquisa LLM request completed (user ID: %s, model: %s, elapsed: %.2fs)",
                interaction.user.id,
                openai_config["model"],
                elapsed,
            )

        except APIError as exc:
            logging.exception(
                "Provider error while generating pesquisa: %s",
                get_provider_error_detail(exc),
            )
            await interaction.followup.send(
                "O provedor do modelo interrompeu a geração do documento. "
                + f"Detalhe do provedor: `{str(exc)[:500]}`"
            )
            return
        except Exception:
            logging.exception("Error while generating pesquisa document")
            await interaction.followup.send(
                "Não consegui gerar o documento de pesquisa agora. "
                + "Verifique os logs e tente novamente."
            )
            return

        if not raw_output.strip():
            await interaction.followup.send(
                "Não foi possível gerar o conteúdo do documento."
            )
            return

        # Generate document file
        try:
            file_bytes, _ = generate_document(raw_output, topic, formato_valor)
            filename = build_pesquisa_filename(topic, formato_valor)
        except Exception:
            logging.exception("Error while generating document file")
            await interaction.followup.send(
                "Não consegui gerar o arquivo do documento. "
                + "O conteúdo será enviado em mensagens."
            )
            await send_pesquisa_result(interaction, raw_output, "pesquisa.txt", b"")
            return

        await send_pesquisa_result(interaction, raw_output, filename, file_bytes)
