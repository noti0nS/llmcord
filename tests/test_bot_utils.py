from dataclasses import dataclass

import discord

from src.bot import (
    attachment_is_supported_word_document,
    build_abnt_result_message,
    get_completion_text,
    parse_abnt_evaluation_json,
    user_has_permission,
)


@dataclass
class _Role:
    id: int


@dataclass
class _User:
    id: int
    roles: list[_Role]


@dataclass
class _Channel:
    type: discord.ChannelType
    id: int
    parent_id: int | None = None
    category_id: int | None = None


@dataclass
class _Attachment:
    filename: str
    content_type: str | None


@dataclass
class _CompletionMessage:
    content: str | list[dict[str, str]]


@dataclass
class _CompletionChoice:
    message: _CompletionMessage


@dataclass
class _Completion:
    choices: list[_CompletionChoice]


def _base_permissions_config() -> dict:
    return {
        "allow_dms": True,
        "permissions": {
            "users": {"admin_ids": [], "allowed_ids": [], "blocked_ids": []},
            "roles": {"allowed_ids": [], "blocked_ids": []},
            "channels": {"allowed_ids": [], "blocked_ids": []},
        },
    }


def test_user_has_permission_respects_blocked_user() -> None:
    config = _base_permissions_config()
    config["permissions"]["users"]["blocked_ids"] = [42]

    user = _User(id=42, roles=[])
    channel = _Channel(type=discord.ChannelType.text, id=10)

    assert user_has_permission(user, channel, config) is False


def test_user_has_permission_allows_dm_when_enabled() -> None:
    config = _base_permissions_config()
    user = _User(id=100, roles=[])
    dm_channel = _Channel(type=discord.ChannelType.private, id=1)

    assert user_has_permission(user, dm_channel, config) is True


def test_attachment_word_support_by_extension_and_content_type() -> None:
    assert (
        attachment_is_supported_word_document(
            _Attachment(filename="file.docx", content_type=None)
        )
        is True
    )
    assert (
        attachment_is_supported_word_document(
            _Attachment(filename="file.bin", content_type="application/vnd.oasis.opendocument.text")
        )
        is True
    )
    assert (
        attachment_is_supported_word_document(
            _Attachment(filename="file.pdf", content_type="application/pdf")
        )
        is False
    )


def test_parse_abnt_evaluation_json_normalizes_score_and_improvements() -> None:
    score, improvements = parse_abnt_evaluation_json(
        '{"score": 1.5, "improvements": ["  Ajustar referencias  ", ""]}'
    )

    assert score == 1.0
    assert improvements == ["Ajustar referencias"]


def test_parse_abnt_evaluation_json_rejects_invalid_payload() -> None:
    try:
        parse_abnt_evaluation_json('{"score": "alto", "improvements": []}')
    except ValueError as exc:
        assert str(exc) == "invalid_score"
    else:
        raise AssertionError("Expected ValueError for invalid score")


def test_build_abnt_result_message_for_good_enough_score() -> None:
    message = build_abnt_result_message(0.95, ["Padronizar citacoes"])
    assert "bom o suficiente" in message


def test_build_abnt_result_message_for_mid_score_lists_improvements() -> None:
    message = build_abnt_result_message(0.8, ["Padronizar citacoes", "Revisar referencias"])
    assert "caminho certo" in message
    assert "- Padronizar citacoes" in message
    assert "- Revisar referencias" in message


def test_get_completion_text_reads_string_content() -> None:
    completion = _Completion(
        choices=[_CompletionChoice(message=_CompletionMessage(content="  {\"score\": 0.9, \"improvements\": []}  "))]
    )
    assert get_completion_text(completion) == '{"score": 0.9, "improvements": []}'


def test_get_completion_text_reads_text_parts() -> None:
    completion = _Completion(
        choices=[
            _CompletionChoice(
                message=_CompletionMessage(
                    content=[
                        {"type": "text", "text": '{"score":0.8,'},
                        {"type": "text", "text": '"improvements":["X"]}'},
                    ]
                )
            )
        ]
    )
    assert get_completion_text(completion) == '{"score":0.8,"improvements":["X"]}'

