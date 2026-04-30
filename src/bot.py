import asyncio
import json
import logging
from base64 import b64encode
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Any, Literal, Optional, TypeVar
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import discord
import httpx
from discord.app_commands import Choice
from discord.ext import commands
from discord.ui import LayoutView, TextDisplay
from openai import APIError

from .config import (
    build_openai_chat_completion_kwargs,
    get_config,
    get_openai_config,
)
from .llm import get_provider_error_detail
from .prompts import build_abnt_messages

VISION_MODEL_TAGS = (
    "claude",
    "gemini",
    "gemma",
    "gpt-4",
    "gpt-5",
    "grok-4",
    "llama",
    "llava",
    "mistral",
    "o3",
    "o4",
    "vision",
    "vl",
)

EMBED_COLOR_COMPLETE = discord.Color.dark_green()
EMBED_COLOR_INCOMPLETE = discord.Color.orange()

STREAMING_INDICATOR = " ⚪"
EDIT_DELAY_SECONDS = 1

MAX_MESSAGE_NODES = 500

SUPPORTED_WORD_ATTACHMENT_EXTENSIONS = (".docx", ".odt")
SUPPORTED_WORD_CONTENT_TYPES = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.oasis.opendocument.text",
)


@dataclass
class MsgNode:
    role: Literal["user", "assistant"] = "assistant"
    text: Optional[str] = None
    images: list[dict[str, Any]] = field(default_factory=list)
    has_bad_attachments: bool = False
    fetch_parent_failed: bool = False
    parent_msg: Optional[discord.Message] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def user_has_permission(
    user: discord.User | discord.Member,
    channel: Any | None,
    config: dict[str, Any],
) -> bool:
    is_dm = getattr(channel, "type", None) == discord.ChannelType.private

    role_ids = {role.id for role in getattr(user, "roles", ())}
    channel_ids = set(
        filter(
            None,
            (
                getattr(channel, "id", None),
                getattr(channel, "parent_id", None),
                getattr(channel, "category_id", None),
            ),
        )
    )

    allow_dms = config.get("allow_dms", True)
    permissions = config["permissions"]
    user_is_admin = user.id in permissions["users"]["admin_ids"]

    (
        (allowed_user_ids, blocked_user_ids),
        (allowed_role_ids, blocked_role_ids),
        (allowed_channel_ids, blocked_channel_ids),
    ) = (
        (perm["allowed_ids"], perm["blocked_ids"])
        for perm in (
            permissions["users"],
            permissions["roles"],
            permissions["channels"],
        )
    )

    allow_all_users = (
        not allowed_user_ids if is_dm else not allowed_user_ids and not allowed_role_ids
    )
    is_good_user = (
        user_is_admin
        or allow_all_users
        or user.id in allowed_user_ids
        or any(role_id in allowed_role_ids for role_id in role_ids)
    )
    is_bad_user = (
        not is_good_user
        or user.id in blocked_user_ids
        or any(role_id in blocked_role_ids for role_id in role_ids)
    )

    allow_all_channels = not allowed_channel_ids
    is_good_channel = (
        user_is_admin or allow_dms
        if is_dm
        else allow_all_channels
        or any(channel_id in allowed_channel_ids for channel_id in channel_ids)
    )
    is_bad_channel = not is_good_channel or any(
        channel_id in blocked_channel_ids for channel_id in channel_ids
    )

    return not is_bad_user and not is_bad_channel


def attachment_is_supported_word_document(attachment: discord.Attachment) -> bool:
    content_type = attachment.content_type or ""
    filename = attachment.filename.lower()
    return content_type in SUPPORTED_WORD_CONTENT_TYPES or filename.endswith(
        SUPPORTED_WORD_ATTACHMENT_EXTENSIONS
    )


def extract_docx_text(document_bytes: bytes) -> str:
    try:
        with ZipFile(BytesIO(document_bytes)) as docx:
            document_xml = docx.read("word/document.xml")
    except (BadZipFile, KeyError) as exc:
        raise ValueError("invalid_docx") from exc

    root = ElementTree.fromstring(document_xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []

    for paragraph in root.findall(".//w:body//w:p", namespace):
        parts = []
        for node in paragraph.iter():
            if node.tag == f"{{{namespace['w']}}}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{{{namespace['w']}}}tab":
                parts.append("\t")
            elif node.tag in (f"{{{namespace['w']}}}br", f"{{{namespace['w']}}}cr"):
                parts.append("\n")

        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs)


def extract_odt_text(document_bytes: bytes) -> str:
    try:
        with ZipFile(BytesIO(document_bytes)) as odt:
            content_xml = odt.read("content.xml")
    except (BadZipFile, KeyError) as exc:
        raise ValueError("invalid_odt") from exc

    root = ElementTree.fromstring(content_xml)
    namespace = {"text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0"}

    paragraphs = []
    text_tags = {f"{{{namespace['text']}}}h", f"{{{namespace['text']}}}p"}

    for node in root.iter():
        if node.tag in text_tags:
            text = "".join(node.itertext()).strip()
            if text:
                paragraphs.append(text)

    return "\n\n".join(paragraphs)


async def read_word_attachment(
    attachment: discord.Attachment, max_chars: int, http_client: httpx.AsyncClient
) -> tuple[str, bool]:
    if not attachment_is_supported_word_document(attachment):
        raise ValueError("unsupported")

    response = await http_client.get(attachment.url)
    response.raise_for_status()

    if attachment.filename.lower().endswith(".odt"):
        text = extract_odt_text(response.content)
    else:
        text = extract_docx_text(response.content)

    return text[:max_chars], len(text) > max_chars


def get_completion_text(completion: Any) -> str:
    if not (choice := completion.choices[0] if completion.choices else None):
        return ""

    message = getattr(choice, "message", None)
    content = getattr(message, "content", "")

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        chunks = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
                continue

            part_type = getattr(part, "type", None)
            part_text = getattr(part, "text", None)
            if part_type == "text" and isinstance(part_text, str):
                chunks.append(part_text)

        return "".join(chunks).strip()

    return str(content).strip()


def parse_abnt_evaluation_json(raw_content: str) -> tuple[float, list[str]]:
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc

    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")

    score = payload.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("invalid_score")

    improvements = payload.get("improvements")
    if not isinstance(improvements, list):
        raise ValueError("invalid_improvements")

    normalized_improvements = []
    for improvement in improvements:
        if not isinstance(improvement, str):
            raise ValueError("invalid_improvement_item")

        clean_text = improvement.strip()
        if clean_text:
            normalized_improvements.append(clean_text)

    normalized_score = max(0.0, min(1.0, float(score)))
    return normalized_score, normalized_improvements


def build_abnt_result_message(score: float, improvements: list[str]) -> str:
    score_percent = round(score * 100)

    if score >= 0.9:
        return (
            f"Análise ABNT concluída. Pontuação: {score_percent}%.\n"
            "Seu documento já está bom o suficiente."
        )

    if improvements:
        improvement_lines = "\n".join(
            f"- {improvement}" for improvement in improvements
        )
    else:
        improvement_lines = "- Nenhum ponto específico foi retornado pelo avaliador."

    if score >= 0.7:
        return (
            f"Análise ABNT concluída. Pontuação: {score_percent}%.\n"
            "Seu documento está no caminho certo. Ajuste os pontos abaixo para melhorar ainda mais:\n"
            f"{improvement_lines}"
        )

    return (
        f"Análise ABNT concluída. Pontuação: {score_percent}%.\n"
        "Seu documento precisa de revisão para atender melhor às normas ABNT. Priorize os pontos abaixo:\n"
        f"{improvement_lines}"
    )


T = TypeVar("T")


async def await_task_with_heartbeats(
    task: asyncio.Task[T], label: str, heartbeat_seconds: float = 10.0
) -> T:
    started_at = datetime.now().timestamp()

    while True:
        try:
            return await asyncio.wait_for(
                asyncio.shield(task), timeout=heartbeat_seconds
            )
        except asyncio.TimeoutError:
            logging.info(
                "%s still running (elapsed: %.2fs)",
                label,
                datetime.now().timestamp() - started_at,
            )


def create_discord_bot(initial_config: Optional[dict[str, Any]] = None) -> commands.Bot:
    config = initial_config or get_config()
    curr_model = next(iter(config["models"]))
    msg_nodes: dict[int, MsgNode] = {}
    last_task_time = 0.0

    intents = discord.Intents.default()
    intents.message_content = True
    activity = discord.CustomActivity(
        name=(config.get("status_message") or "github.com/jakobdylanc/llmcord")[:128]
    )
    discord_bot = commands.Bot(
        intents=intents, activity=activity, command_prefix=commands.when_mentioned
    )
    httpx_client = httpx.AsyncClient()

    @discord_bot.tree.command(
        name="model", description="View or switch the current model"
    )
    async def model_command(interaction: discord.Interaction, model: str) -> None:
        nonlocal curr_model
        interaction_channel_type = getattr(interaction.channel, "type", None)

        if model == curr_model:
            output = f"Current model: `{curr_model}`"
        else:
            user_is_admin = (
                interaction.user.id in config["permissions"]["users"]["admin_ids"]
            )
            if user_is_admin:
                curr_model = model
                output = f"Model switched to: `{model}`"
                logging.info(output)
            else:
                output = "You don't have permission to change the model."

        await interaction.response.send_message(
            output, ephemeral=(interaction_channel_type == discord.ChannelType.private)
        )

    @model_command.autocomplete("model")
    async def model_autocomplete(
        interaction: discord.Interaction, curr_str: str
    ) -> list[Choice[str]]:
        del interaction
        nonlocal config

        if curr_str == "":
            config = await asyncio.to_thread(get_config)

        choices = (
            [Choice(name=f"◉ {curr_model} (current)", value=curr_model)]
            if curr_str.lower() in curr_model.lower()
            else []
        )
        choices += [
            Choice(name=f"○ {model_name}", value=model_name)
            for model_name in config["models"]
            if model_name != curr_model and curr_str.lower() in model_name.lower()
        ]

        return choices[:25]

    @discord_bot.tree.command(
        name="abnt",
        description="Avalie um documento DOCX ou ODT conforme ABNT e receba melhorias",
    )
    async def abnt_command(
        interaction: discord.Interaction,
        document: discord.Attachment,
        instructions: Optional[str] = None,
    ) -> None:
        nonlocal config
        config = await asyncio.to_thread(get_config)

        if not attachment_is_supported_word_document(document):
            await interaction.response.send_message(
                "Tipo de documento não suportado. Envie um arquivo `.docx` ou `.odt`.",
                ephemeral=True,
            )
            return

        if not user_has_permission(interaction.user, interaction.channel, config):
            await interaction.response.send_message(
                "Você não tem permissão para usar este bot aqui.", ephemeral=True
            )
            return

        max_document_chars = config.get("abnt", {}).get(
            "max_document_chars", config.get("max_text", 100000)
        )
        logging.info(
            "ABNT attachment read started (user ID: %s, file: %s)",
            interaction.user.id,
            document.filename,
        )
        try:
            document_text, document_was_truncated = await read_word_attachment(
                document, max_document_chars, httpx_client
            )
        except ValueError:
            await interaction.response.send_message(
                "Tipo de documento não suportado. Envie um arquivo `.docx` ou `.odt`.",
                ephemeral=True,
            )
            return
        except Exception:
            logging.exception("Error while reading ABNT attachment")
            await interaction.response.send_message(
                "Não consegui ler o anexo. Tente novamente com um arquivo `.docx` ou `.odt` válido.",
                ephemeral=True,
            )
            return
        logging.info(
            "ABNT attachment read completed (user ID: %s, file: %s, chars: %s, truncated: %s)",
            interaction.user.id,
            document.filename,
            len(document_text),
            document_was_truncated,
        )

        if not document_text.strip():
            await interaction.response.send_message(
                "O documento anexado parece estar vazio.", ephemeral=True
            )
            return

        is_dm = (
            getattr(interaction.channel, "type", None) == discord.ChannelType.private
        )
        await interaction.response.send_message(
            f"Opa! Estou analisando o documento '**{document.filename}**', {interaction.user.mention}. Um momento...",
            ephemeral=is_dm,
        )

        openai_client, openai_config = get_openai_config(config, curr_model)

        logging.info(
            "ABNT command received (user ID: %s, file: %s, chars: %s)",
            interaction.user.id,
            document.filename,
            len(document_text),
        )

        raw_output = ""
        request_started_at = datetime.now().timestamp()
        try:
            messages = build_abnt_messages(
                filename=document.filename,
                document_text=document_text,
                instructions=instructions,
                document_was_truncated=document_was_truncated,
                max_document_chars=max_document_chars,
            )
            logging.info(
                "ABNT LLM request started (user ID: %s, model: %s, file: %s, message_count: %s)",
                interaction.user.id,
                openai_config["model"],
                document.filename,
                len(messages),
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
                    "ABNT LLM request still running "
                    f"(user ID: {interaction.user.id}, model: {openai_config['model']}, file: {document.filename})"
                ),
            )
            elapsed = datetime.now().timestamp() - request_started_at
            logging.info(
                "ABNT LLM request completed (user ID: %s, model: %s, file: %s, elapsed: %.2fs)",
                interaction.user.id,
                openai_config["model"],
                document.filename,
                elapsed,
            )
            raw_output = get_completion_text(completion)
            score, improvements = parse_abnt_evaluation_json(raw_output)
            output = build_abnt_result_message(score, improvements)
            logging.info(
                "ABNT evaluation parsed (user ID: %s, file: %s, score: %.3f, improvements: %s)",
                interaction.user.id,
                document.filename,
                score,
                len(improvements),
            )
        except ValueError as exc:
            logging.warning(
                "ABNT evaluation JSON parse failed (user ID: %s, file: %s, reason: %s, output_preview: %s)",
                interaction.user.id,
                document.filename,
                exc,
                raw_output[:300],
            )
            await interaction.followup.send(
                "Não consegui interpretar a avaliação ABNT do provedor. Tente novamente em alguns instantes."
            )
            return
        except APIError as exc:
            logging.exception(
                "Provider error while generating ABNT response: %s",
                get_provider_error_detail(exc),
            )
            await interaction.followup.send(
                "O provedor do modelo interrompeu a avaliação ABNT. "
                f"Detalhe do provedor: `{str(exc)[:500]}`"
            )
            return
        except Exception:
            logging.exception("Error while generating ABNT response")
            await interaction.followup.send(
                "Não consegui avaliar o documento em ABNT agora. Verifique os logs do provedor/modelo e tente novamente."
            )
            return

        if not output:
            await interaction.followup.send(
                "Não foi possível gerar o resultado da avaliação ABNT."
            )
            return

        await interaction.followup.send(output)

    @discord_bot.event
    async def on_ready() -> None:
        if client_id := config.get("client_id"):
            logging.info(
                "\n\nBOT INVITE URL:\nhttps://discord.com/oauth2/authorize?client_id=%s&permissions=412317191168&scope=bot\n",
                client_id,
            )

        await discord_bot.tree.sync()

    @discord_bot.event
    async def on_message(new_msg: discord.Message) -> None:
        nonlocal last_task_time, config

        bot_user = discord_bot.user
        if bot_user is None:
            return

        is_dm = new_msg.channel.type == discord.ChannelType.private
        if (not is_dm and bot_user not in new_msg.mentions) or new_msg.author.bot:
            return

        config = await asyncio.to_thread(get_config)
        if not user_has_permission(new_msg.author, new_msg.channel, config):
            return

        openai_client, openai_config = get_openai_config(config, curr_model)
        accept_images = any(tag in curr_model.lower() for tag in VISION_MODEL_TAGS)
        max_text = config.get("max_text", 100000)
        max_images = config.get("max_images", 5) if accept_images else 0
        max_messages = config.get("max_messages", 25)

        messages = []
        user_warnings = set()
        curr_msg = new_msg

        while curr_msg is not None and len(messages) < max_messages:
            curr_node = msg_nodes.setdefault(curr_msg.id, MsgNode())

            async with curr_node.lock:
                if curr_node.text is None:
                    cleaned_content = curr_msg.content.removeprefix(
                        bot_user.mention
                    ).lstrip()

                    good_attachments = [
                        att
                        for att in curr_msg.attachments
                        if (content_type := att.content_type)
                        and any(
                            content_type.startswith(kind) for kind in ("text", "image")
                        )
                    ]

                    attachment_responses = await asyncio.gather(
                        *[httpx_client.get(att.url) for att in good_attachments]
                    )

                    curr_node.role = (
                        "assistant" if curr_msg.author == bot_user else "user"
                    )

                    curr_node.text = "\n".join(
                        ([cleaned_content] if cleaned_content else [])
                        + [
                            "\n".join(
                                filter(
                                    None,
                                    (embed.title, embed.description, embed.footer.text),
                                )
                            )
                            for embed in curr_msg.embeds
                        ]
                        + [
                            content
                            for component in curr_msg.components
                            if component.type == discord.ComponentType.text_display
                            and isinstance(
                                (content := getattr(component, "content", None)), str
                            )
                        ]
                        + [
                            resp.text
                            for att, resp in zip(good_attachments, attachment_responses)
                            if (content_type := att.content_type)
                            and content_type.startswith("text")
                        ]
                    )

                    curr_node.images = [
                        dict(
                            type="image_url",
                            image_url=dict(
                                url=f"data:{content_type};base64,{b64encode(resp.content).decode('utf-8')}"
                            ),
                        )
                        for att, resp in zip(good_attachments, attachment_responses)
                        if (content_type := att.content_type)
                        and content_type.startswith("image")
                    ]

                    if curr_node.role == "user" and (
                        curr_node.text or curr_node.images
                    ):
                        curr_node.text = f"<@{curr_msg.author.id}>: {curr_node.text}"

                    curr_node.has_bad_attachments = len(curr_msg.attachments) > len(
                        good_attachments
                    )

                    try:
                        if (
                            curr_msg.reference is None
                            and bot_user.mention not in curr_msg.content
                            and (
                                prev_msg_in_channel := (
                                    [
                                        message
                                        async for message in curr_msg.channel.history(
                                            before=curr_msg, limit=1
                                        )
                                    ]
                                    or [None]
                                )[0]
                            )
                            and prev_msg_in_channel.type
                            in (discord.MessageType.default, discord.MessageType.reply)
                            and prev_msg_in_channel.author
                            == (
                                bot_user
                                if getattr(curr_msg.channel, "type", None)
                                == discord.ChannelType.private
                                else curr_msg.author
                            )
                        ):
                            curr_node.parent_msg = prev_msg_in_channel
                        else:
                            reference = curr_msg.reference
                            if isinstance(curr_msg.channel, discord.Thread):
                                parent_is_thread_start = (
                                    curr_msg.reference is None
                                    and getattr(curr_msg.channel.parent, "type", None)
                                    == discord.ChannelType.text
                                )

                                if parent_msg_id := (
                                    curr_msg.channel.id
                                    if parent_is_thread_start
                                    else getattr(reference, "message_id", None)
                                ):
                                    if parent_is_thread_start:
                                        parent_channel = curr_msg.channel.parent
                                        assert parent_channel is not None
                                        if isinstance(
                                            parent_channel, discord.TextChannel
                                        ):
                                            curr_node.parent_msg = (
                                                curr_msg.channel.starter_message
                                                or await parent_channel.fetch_message(
                                                    parent_msg_id
                                                )
                                            )
                                        else:
                                            curr_node.parent_msg = (
                                                curr_msg.channel.starter_message
                                            )
                                    else:
                                        curr_node.parent_msg = getattr(
                                            reference, "cached_message", None
                                        ) or await curr_msg.channel.fetch_message(
                                            parent_msg_id
                                        )

                    except (discord.NotFound, discord.HTTPException):
                        logging.exception("Error fetching next message in the chain")
                        curr_node.fetch_parent_failed = True

                if curr_node.images[:max_images]:
                    content = [
                        dict(type="text", text=curr_node.text[:max_text])
                    ] + curr_node.images[:max_images]
                else:
                    content = curr_node.text[:max_text]

                if content != "":
                    messages.append(dict(content=content, role=curr_node.role))

                if len(curr_node.text) > max_text:
                    user_warnings.add(f"⚠️ Max {max_text:,} characters per message")
                if len(curr_node.images) > max_images:
                    user_warnings.add(
                        f"⚠️ Max {max_images} image{'' if max_images == 1 else 's'} per message"
                        if max_images > 0
                        else "⚠️ Can't see images"
                    )
                if curr_node.has_bad_attachments:
                    user_warnings.add("⚠️ Unsupported attachments")
                if curr_node.fetch_parent_failed or (
                    curr_node.parent_msg is not None and len(messages) == max_messages
                ):
                    user_warnings.add(
                        f"⚠️ Only using last {len(messages)} message{'' if len(messages) == 1 else 's'}"
                    )

                curr_msg = curr_node.parent_msg

        logging.info(
            "Message received (user ID: %s, attachments: %s, conversation length: %s):\n%s",
            new_msg.author.id,
            len(new_msg.attachments),
            len(messages),
            new_msg.content,
        )

        if system_prompt := config.get("system_prompt"):
            now = datetime.now().astimezone()
            system_prompt = (
                system_prompt.replace("{date}", now.strftime("%B %d %Y"))
                .replace("{time}", now.strftime("%H:%M:%S %Z%z"))
                .strip()
            )
            messages.append(dict(role="system", content=system_prompt))

        curr_content = finish_reason = None
        response_msgs = []
        response_contents = []

        openai_kwargs = dict(
            model=openai_config["model"],
            messages=messages[::-1],
            stream=True,
            extra_headers=openai_config["extra_headers"],
            extra_query=openai_config["extra_query"],
            extra_body=openai_config["extra_body"],
        )

        use_plain_responses = config.get("use_plain_responses", False)
        response_embed: discord.Embed | None = None
        if use_plain_responses:
            max_message_length = 4000
        else:
            max_message_length = 4096 - len(STREAMING_INDICATOR)
            response_embed = discord.Embed.from_dict(
                dict(
                    fields=[
                        dict(name=warning, value="", inline=False)
                        for warning in sorted(user_warnings)
                    ]
                )
            )

        async def reply_helper(**reply_kwargs: Any) -> None:
            reply_target = new_msg if not response_msgs else response_msgs[-1]
            response_msg = await reply_target.reply(**reply_kwargs)
            response_msgs.append(response_msg)

            msg_nodes[response_msg.id] = MsgNode(parent_msg=new_msg)
            await msg_nodes[response_msg.id].lock.acquire()

        request_started_at = datetime.now().timestamp()
        first_chunk_logged = False
        try:
            logging.info(
                "LLM streaming request started (user ID: %s, model: %s, message_count: %s, plain_mode: %s)",
                new_msg.author.id,
                openai_kwargs["model"],
                len(messages),
                use_plain_responses,
            )
            async with new_msg.channel.typing():
                async for chunk in await openai_client.chat.completions.create(
                    **build_openai_chat_completion_kwargs(
                        openai_config, messages[::-1], stream=True
                    )
                ):
                    if finish_reason is not None:
                        break

                    if not (choice := chunk.choices[0] if chunk.choices else None):
                        continue

                    finish_reason = choice.finish_reason
                    prev_content = curr_content or ""
                    curr_content = choice.delta.content or ""
                    new_content = (
                        prev_content
                        if finish_reason is None
                        else (prev_content + curr_content)
                    )

                    if response_contents == [] and new_content == "":
                        continue

                    start_next_msg = (
                        response_contents == []
                        or len(response_contents[-1] + new_content) > max_message_length
                    )
                    if start_next_msg:
                        response_contents.append("")

                    response_contents[-1] += new_content
                    if not first_chunk_logged and (
                        new_content != "" or finish_reason is not None
                    ):
                        logging.info(
                            "LLM streaming first chunk received (user ID: %s, model: %s, elapsed: %.2fs)",
                            new_msg.author.id,
                            openai_kwargs["model"],
                            datetime.now().timestamp() - request_started_at,
                        )
                        first_chunk_logged = True

                    if not use_plain_responses:
                        assert response_embed is not None
                        time_delta = datetime.now().timestamp() - last_task_time
                        ready_to_edit = time_delta >= EDIT_DELAY_SECONDS
                        msg_split_incoming = (
                            finish_reason is None
                            and len(response_contents[-1] + curr_content)
                            > max_message_length
                        )
                        is_final_edit = finish_reason is not None or msg_split_incoming
                        is_good_finish = (
                            finish_reason is not None
                            and finish_reason.lower() in ("stop", "end_turn")
                        )

                        if start_next_msg or ready_to_edit or is_final_edit:
                            response_embed.description = (
                                response_contents[-1]
                                if is_final_edit
                                else (response_contents[-1] + STREAMING_INDICATOR)
                            )
                            response_embed.color = (
                                EMBED_COLOR_COMPLETE
                                if msg_split_incoming or is_good_finish
                                else EMBED_COLOR_INCOMPLETE
                            )

                            if start_next_msg:
                                await reply_helper(embed=response_embed, silent=True)
                            else:
                                await asyncio.sleep(EDIT_DELAY_SECONDS - time_delta)
                                await response_msgs[-1].edit(embed=response_embed)

                            last_task_time = datetime.now().timestamp()

                if use_plain_responses:
                    for content in response_contents:
                        await reply_helper(
                            view=LayoutView().add_item(TextDisplay(content=content))
                        )
            logging.info(
                "LLM streaming request completed (user ID: %s, model: %s, finish_reason: %s, chunks: %s, elapsed: %.2fs)",
                new_msg.author.id,
                openai_kwargs["model"],
                finish_reason,
                len(response_contents),
                datetime.now().timestamp() - request_started_at,
            )

        except Exception:
            logging.exception(
                "Error while generating response (user ID: %s, model: %s)",
                new_msg.author.id,
                openai_kwargs["model"],
            )

        for response_msg in response_msgs:
            msg_nodes[response_msg.id].text = "".join(response_contents)
            msg_nodes[response_msg.id].lock.release()

        if (num_nodes := len(msg_nodes)) > MAX_MESSAGE_NODES:
            for msg_id in sorted(msg_nodes.keys())[: num_nodes - MAX_MESSAGE_NODES]:
                async with msg_nodes.setdefault(msg_id, MsgNode()).lock:
                    msg_nodes.pop(msg_id, None)

    return discord_bot
