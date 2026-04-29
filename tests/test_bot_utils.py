from dataclasses import dataclass

import discord

from src.bot import (
    attachment_is_supported_word_document,
    get_abnt_thread_name,
    split_document_text,
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


def test_split_document_text_chunks_by_limit() -> None:
    text = "A.\n\nB.\n\nC.\n\nD."
    chunks = split_document_text(text, max_chars=5)

    assert len(chunks) > 1
    assert all(len(chunk) <= 5 for chunk in chunks)


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


def test_abnt_thread_name_is_capped() -> None:
    name = get_abnt_thread_name("x" * 300)
    assert name.startswith("ABNT - ")
    assert len(name) <= 100

