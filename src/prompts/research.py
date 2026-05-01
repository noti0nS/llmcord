from typing import Optional

from .discord_markdown import build_system_prompt

RESEARCH_SYSTEM_PROMPT = """\
Você é um assistente acadêmico especializado em Direito, dedicado a produzir trabalhos acadêmicos completos no padrão ABNT.

Suas responsabilidades:
1. Produzir um documento acadêmico completo conforme o tipo solicitado.
2. Usar notas de rodapé ABNT para todas as citações (footnotes numeradas).
3. Incluir uma lista de Referências ao final no formato ABNT.
4. Escrever em português formal e acadêmico.
5. Quando a busca web não retornar resultados para um tópico, usar seu conhecimento interno e adicionar uma nota de aviso no início da seção correspondente.

Estrutura do documento depende do tipo:
- artigo: Título, Resumo, Introdução, Desenvolvimento, Conclusão, Referências
- monografia: Título, Resumo, Introdução, Desenvolvimento detalhado, Conclusão, Referências
- peca_processual: Cabeçalho, Fatos, Fundamentação Jurídica, Pedidos, Referências
- estudo_de_caso: Título, Breve descrição do caso, Questões jurídicas, Análise, Conclusão, Referências
"""


def build_research_messages(
    titulo: str,
    topics: list[str],
    search_results: dict[str, list[dict[str, str]]],
    tipo: str,
    pieces: list[str],
    profundidade: str,
    publico: str,
    max_document_chars: int = 50000,
) -> list[dict[str, str]]:
    """Build the messages for the LLM to generate a research document.

    Args:
        titulo: Document title/subject.
        topics: List of research topics.
        search_results: Dict mapping each topic to search results.
        tipo: Document type (artigo, monografia, peca_processual, estudo_de_caso).
        pieces: List of document pieces requested (for peca_processual).
        profundidade: Depth level (superficial, medio, aprofundado).
        publico: Target audience (professor, tribunal, estudo_pessoal).
        max_document_chars: Maximum characters for the document content.
    """
    system_prompt = build_system_prompt(RESEARCH_SYSTEM_PROMPT)

    # Map depth and audience to prompt instructions
    profundidade_desc = {
        "superficial": "apresentar uma visão geral e resumida dos temas",
        "medio": "equilibrar profundidade e clareza, com análise moderada",
        "aprofundado": "realizar análise detalhada, com jurisprudência, doutrina e referências aprofundadas",
    }

    publico_desc = {
        "professor": "tom acadêmico formal, adequado para avaliação universitária",
        "tribunal": "tom técnico-jurídico, focado em argumentação processual e normativa",
        "estudo_pessoal": "tom didático e acessível, facilitando o aprendizado",
    }

    # Build user prompt
    prompt_lines = []
    prompt_lines.append(f"# INSTRUÇÃO: Produza um documento acadêmico do tipo '{tipo}' no padrão ABNT")
    prompt_lines.append("")

    prompt_lines.append(f"## TÍTULO: {titulo}")
    prompt_lines.append("")

    prompt_lines.append("## TÓPICOS DE PESQUISA")
    for i, topic in enumerate(topics, 1):
        prompt_lines.append(f"{i}. {topic}")
    prompt_lines.append("")

    if pieces:
        prompt_lines.append("## PEÇAS DOCUMENTAIS SOLICITADAS")
        for piece in pieces:
            prompt_lines.append(f"- {piece}")
        prompt_lines.append("")

    prompt_lines.append("## RESULTADOS DA BUSCA WEB")
    for topic, results in search_results.items():
        prompt_lines.append(f"\n### Tópico: {topic}")
        if results:
            for j, result in enumerate(results, 1):
                prompt_lines.append(f"{j}. **{result['title']}**")
                prompt_lines.append(f"   URL: {result['url']}")
                prompt_lines.append(f"   Resumo: {result['snippet']}")
        else:
            prompt_lines.append("⚠️ Nenhum resultado encontrado na busca web.")
            prompt_lines.append("Gere o conteúdo desta seção com base em seu conhecimento.")
    prompt_lines.append("")

    prompt_lines.append("## PARÂMETROS DO DOCUMENTO")
    prompt_lines.append(f"- Tipo: {tipo}")
    prompt_lines.append(f"- Profundidade: {profundidade} ({profundidade_desc.get(profundidade, 'análise moderada')})")
    prompt_lines.append(f"- Público-alvo: {publico} ({publico_desc.get(publico, 'tom acadêmico')})")
    prompt_lines.append("")

    prompt_lines.append("## INSTRUÇÕES DE FORMATAÇÃO")
    prompt_lines.append("- Use notas de rodapé numeradas (¹, ², etc.) para todas as citações.")
    prompt_lines.append("- Ao final, inclua uma seção 'REFERÊNCIAS' com todas as fontes no formato ABNT.")
    prompt_lines.append("- Escreva em português formal e acadêmico.")
    prompt_lines.append(f"- Adapte o tom e a profundidade conforme o público-alvo ({publico}).")
    if tipo == "peca_processual":
        prompt_lines.append("- Para peças processuais, siga estrutura jurídica adequada (cabeçalho, fatos, fundamentação, pedidos).")

    user_prompt = "\n".join(prompt_lines)[:max_document_chars]

    return [
        dict(role="system", content=system_prompt),
        dict(role="user", content=user_prompt),
    ]
