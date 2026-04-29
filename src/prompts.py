from typing import Optional

ABNT_SYSTEM_PROMPT = """\
Voce é um assistente academico especializado em formatação ABNT para trabalhos brasileiros.
Reescreva e organize o documento enviado em português formal, preservando o sentido, os dados, as citações e as referências existentes.
Quando houver informação insuficiente para uma referência perfeita, mantenha o item e marque claramente o dado faltante entre colchetes, sem inventar autor, ano, editora, página, DOI ou URL.
Use estrutura acadêmica compátivel com ABNT, linguagem objetiva e seções quando fizerem sentido ao material.
Entregue apenas a versão revisada/formatada, sem explicar o processo.
"""

ABNT_USER_PROMPT = """\
Gere uma versao correta em formato ABNT do documento abaixo.

Regras:
- Corrija ortografia, coesao, pontuacao e padronizacao academica.
- Preserve o conteudo original; nao acrescente fatos externos.
- Padronize citacoes e referencias conforme ABNT quando houver dados suficientes.
- Se uma referencia estiver incompleta, sinalize os campos ausentes entre colchetes.
- Use titulos e subtitulos academicos quando forem apropriados ao texto.
"""

ABNT_PART_PROMPT = """\
Este documento foi dividido para evitar timeout do provedor.
Gere a versao ABNT apenas da parte {part_number} de {part_count}, preservando a continuidade do texto.
Nao crie capa, sumario, introducao geral ou conclusao geral a menos que essa estrutura esteja presente nesta parte.
Nao repita conteudo de outras partes.
"""


def build_abnt_messages(
    filename: str,
    document_text: str,
    instructions: Optional[str],
    document_was_truncated: bool,
    max_document_chars: int,
    part_number: int,
    part_count: int,
) -> list[dict[str, str]]:
    user_prompt = ABNT_USER_PROMPT

    if part_count > 1:
        user_prompt += "\n\n" + ABNT_PART_PROMPT.format(
            part_number=part_number, part_count=part_count
        )

    if instructions:
        user_prompt += f"\n\nInstrucoes adicionais do usuario:\n{instructions.strip()}"

    if document_was_truncated and part_number == part_count:
        user_prompt += f"\n\nAviso: o documento foi limitado aos primeiros {max_document_chars:,} caracteres por configuracao do bot."

    user_prompt += f"\n\nNome do arquivo: {filename}"

    if part_count > 1:
        user_prompt += f"\nParte: {part_number}/{part_count}"

    user_prompt += f"\n\nDocumento:\n{document_text}"

    return [
        dict(role="system", content=ABNT_SYSTEM_PROMPT),
        dict(role="user", content=user_prompt),
    ]

