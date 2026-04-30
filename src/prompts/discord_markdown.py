from pathlib import Path
from typing import Optional

DISCORD_MARKDOWN_REFERENCE_PATH = Path(__file__).with_name("discord_markdown_ref.md")


def load_discord_markdown_reference() -> str:
    try:
        reference = DISCORD_MARKDOWN_REFERENCE_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(
            "Não foi possível carregar a referência de markdown do Discord em "
            f"{DISCORD_MARKDOWN_REFERENCE_PATH}"
        ) from exc

    if not reference:
        raise RuntimeError(
            "O arquivo de referência de markdown do Discord está vazio: "
            f"{DISCORD_MARKDOWN_REFERENCE_PATH}"
        )

    return reference


def build_system_prompt(base_prompt: Optional[str]) -> str:
    markdown_reference = load_discord_markdown_reference()
    reference_intro = (
        "Regras obrigatórias de markdown do Discord:\n"
        "- Modo padrão: texto simples.\n"
        "- Use somente as marcações documentadas abaixo.\n"
        "- Não invente sintaxe de markdown que não exista no Discord.\n\n"
        "- Em títulos com '#', use no máximo até '###'. Nunca use '####', '#####' ou '######'.\n\n"
        "- Nunca use LaTeX/sintaxe matemática ou markdown estendido.\n\n"
        f"{markdown_reference}"
    )
    base = (base_prompt or "").strip()
    return f"{base}\n\n{reference_intro}" if base else reference_intro
