import asyncio
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
from ..helpers.search import search_topics
from ..llm import get_provider_error_detail
from ..prompts.research import build_research_messages


def _parse_list_input(text: str) -> list[str]:
    """Parse a string into a list of items.

    Items can be separated by semicolons, newlines, or both.
    """
    if not text or not text.strip():
        return []
    # Split by semicolons first, then by newlines
    items = []
    for semicolon_part in text.split(";"):
        for line in semicolon_part.split("\n"):
            stripped = line.strip()
            if stripped:
                items.append(stripped)
    return items


def build_research_filename(title: str, output_format: str) -> str:
    """Build a safe filename for the research document."""
    safe_title = re.sub(r"[^\w\s-]", "", title).strip()[:50]
    safe_title = re.sub(r"[-\s]+", "_", safe_title)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = ".odt" if output_format.lower() == "odt" else ".docx"
    return f"pesquisa_{safe_title}_{timestamp}{ext}"


async def send_research_result(
    interaction: discord.Interaction,
    content: str,
    filename: str,
    file_bytes: bytes,
) -> None:
    """Send the research result as a file or in a thread if too large."""
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
            f"📄 **Pesquisa concluída!** O documento foi dividido em {len(chunks)} partes.\n"
            + "(O arquivo original excede o limite de tamanho do Discord, então foi enviado em mensagens.)"
        )

        for i, chunk in enumerate(chunks, 1):
            await thread.send(f"**Parte {i}/{len(chunks)}**\n```\n{chunk}\n```")

        await interaction.followup.send(
            f"Pesquisa concluída! O documento foi enviado na thread: {thread.mention}"
        )


# Choices for the slash command
TIPO_DOCUMENTO_CHOICES = [
    discord.app_commands.Choice(name="Artigo", value="artigo"),
    discord.app_commands.Choice(name="Monografia", value="monografia"),
    discord.app_commands.Choice(name="Peça processual", value="peca_processual"),
    discord.app_commands.Choice(name="Estudo de caso", value="estudo_de_caso"),
]

PROFUNDIDADE_CHOICES = [
    discord.app_commands.Choice(name="Superficial (resumo geral)", value="superficial"),
    discord.app_commands.Choice(name="Médio (equilíbrio)", value="medio"),
    discord.app_commands.Choice(
        name="Aprofundado (análise detalhada)", value="aprofundado"
    ),
]

PUBLICO_CHOICES = [
    discord.app_commands.Choice(name="Professor", value="professor"),
    discord.app_commands.Choice(name="Tribunal", value="tribunal"),
    discord.app_commands.Choice(name="Estudo pessoal", value="estudo_pessoal"),
]

FORMATO_CHOICES = [
    discord.app_commands.Choice(name="DOCX (Microsoft Word)", value="docx"),
    discord.app_commands.Choice(name="ODT (LibreOffice)", value="odt"),
]


def register_research_command(
    discord_bot: commands.Bot,
    state: Any,
) -> None:
    @discord_bot.tree.command(
        name="research",
        description="Gere um documento acadêmico ABNT a partir de tópicos de pesquisa",
    )
    @discord.app_commands.describe(
        titulo="Título ou tema principal da pesquisa (ex: NPJ)",
        topicos="Tópicos de pesquisa, separados por ponto-e-vírgula ou nova linha",
        tipo="Tipo de documento a gerar",
        pecas="Peças processuais (quando tipo=peça processual), separadas por ponto-e-vírgula",
        profundidade="Nível de profundidade do conteúdo",
        publico="Público-alvo do documento",
        formato="Formato do arquivo de saída",
    )
    @discord.app_commands.choices(
        tipo=TIPO_DOCUMENTO_CHOICES,
        profundidade=PROFUNDIDADE_CHOICES,
        publico=PUBLICO_CHOICES,
        formato=FORMATO_CHOICES,
    )
    async def research_command(
        interaction: discord.Interaction,
        titulo: str,
        topicos: str,
        tipo: discord.app_commands.Choice[str] | None = None,
        pecas: str | None = None,
        profundidade: discord.app_commands.Choice[str] | None = None,
        publico: discord.app_commands.Choice[str] | None = None,
        formato: discord.app_commands.Choice[str] | None = None,
    ) -> None:
        state.config = await asyncio.to_thread(get_config)

        # Resolve choices
        tipo_valor = tipo.value if tipo else "artigo"
        profundidade_valor = profundidade.value if profundidade else "medio"
        publico_valor = publico.value if publico else "professor"
        formato_valor = formato.value if formato else "docx"

        # Parse topics
        topics_list = _parse_list_input(topicos)
        if not topics_list:
            await interaction.response.send_message(
                "Nenhum tópico de pesquisa fornecido. Informe pelo menos um tópico.",
                ephemeral=True,
            )
            return

        # Parse pieces (only relevant for peca_processual)
        pieces_list = _parse_list_input(pecas) if pecas else []

        # Check max topics
        max_topics = state.config.get("research", {}).get("max_topics", 10)
        if len(topics_list) > max_topics:
            topics_list = topics_list[:max_topics]
            await interaction.response.send_message(
                f"⚠️ Limite de {max_topics} tópicos excedido. Apenas os primeiros {max_topics} serão pesquisados.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"🔍 Pesquisando {len(topics_list)} tópico(s)... Isso pode levar alguns minutos.",
                ephemeral=True,
            )

        # Web search
        search_results_per_topic = state.config.get("research", {}).get(
            "search_results_per_topic", 5
        )
        logging.info(
            "Research search started (user ID: %s, titulo: %s, topics: %s, tipo: %s, formato: %s)",
            interaction.user.id,
            titulo,
            len(topics_list),
            tipo_valor,
            formato_valor,
        )

        try:
            search_results = await search_topics(
                topics_list,
                max_results=search_results_per_topic,
            )
        except Exception:
            logging.exception("Research web search failed")
            search_results = {t: [] for t in topics_list}

        fallback_topics = [t for t, r in search_results.items() if not r]
        if fallback_topics:
            logging.warning(
                "Research fallback topics (user ID: %s): %s",
                interaction.user.id,
                fallback_topics,
            )

        # Build LLM messages
        max_document_chars = state.config.get("research", {}).get(
            "max_document_chars", 50000
        )
        messages = build_research_messages(
            titulo=titulo,
            topics=topics_list,
            search_results=search_results,
            tipo=tipo_valor,
            pieces=pieces_list,
            profundidade=profundidade_valor,
            publico=publico_valor,
            max_document_chars=max_document_chars,
        )

        # Generate document with LLM
        openai_client, openai_config = get_openai_config(state.config, state.curr_model)

        raw_output = ""
        request_started_at = datetime.now().timestamp()
        try:
            logging.info(
                "Research LLM request started (user ID: %s, model: %s, topics: %s)",
                interaction.user.id,
                openai_config["model"],
                len(topics_list),
            )
            completion_task = asyncio.create_task(
                openai_client.chat.completions.create(
                    **build_openai_chat_completion_kwargs(
                        openai_config, messages, stream=False
                    )
                )
            )
            completion = await await_task_with_heartbeats(
                completion_task,
                (
                    "Research LLM request still running "
                    f"(user ID: {interaction.user.id}, model: {openai_config['model']})"
                ),
            )
            elapsed = datetime.now().timestamp() - request_started_at
            logging.info(
                "Research LLM request completed (user ID: %s, model: %s, elapsed: %.2fs)",
                interaction.user.id,
                openai_config["model"],
                elapsed,
            )
            raw_output = get_completion_text(completion)
        except APIError as exc:
            logging.exception(
                "Provider error while generating research: %s",
                get_provider_error_detail(exc),
            )
            await interaction.followup.send(
                "O provedor do modelo interrompeu a geração do documento. "
                + f"Detalhe do provedor: `{str(exc)[:500]}`"
            )
            return
        except Exception:
            logging.exception("Error while generating research document")
            await interaction.followup.send(
                "Não consegui gerar o documento de pesquisa agora. Verifique os logs e tente novamente."
            )
            return

        if not raw_output.strip():
            await interaction.followup.send(
                "Não foi possível gerar o conteúdo do documento."
            )
            return

        # Generate document file
        try:
            file_bytes, _ = generate_document(raw_output, titulo, formato_valor)
            filename = build_research_filename(titulo, formato_valor)
        except Exception:
            logging.exception("Error while generating document file")
            await interaction.followup.send(
                "Não consegui gerar o arquivo do documento. O conteúdo será enviado em mensagens."
            )
            await send_research_result(interaction, raw_output, "pesquisa.txt", b"")
            return

        await send_research_result(interaction, raw_output, filename, file_bytes)
