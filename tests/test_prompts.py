from src.prompts import ABNT_SYSTEM_PROMPT, build_abnt_messages


def test_build_abnt_messages_includes_system_and_filename() -> None:
    messages = build_abnt_messages(
        filename="paper.docx",
        document_text="Conteudo base",
        instructions=None,
        document_was_truncated=False,
        max_document_chars=1000,
        part_number=1,
        part_count=1,
    )

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == ABNT_SYSTEM_PROMPT
    assert "Nome do arquivo: paper.docx" in messages[1]["content"]


def test_build_abnt_messages_adds_part_and_truncation_notice() -> None:
    messages = build_abnt_messages(
        filename="long.odt",
        document_text="Parte do texto",
        instructions="Foque em clareza",
        document_was_truncated=True,
        max_document_chars=1500,
        part_number=3,
        part_count=3,
    )
    user_content = messages[1]["content"]

    assert "Parte: 3/3" in user_content
    assert "Instrucoes adicionais do usuario" in user_content
    assert "primeiros 1,500 caracteres" in user_content

