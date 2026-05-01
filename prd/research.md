# PRD: `/research` Command — Academic Legal Research Generator

## 1. Overview

### Purpose
Enable law students to generate complete ABNT-formatted academic documents for NPJ (Núcleo de Prática Jurídica) assignments by providing research topics, with automatic web search and document generation.

### Target Users
Law students at Brazilian universities who need to produce academic legal research documents for NPJ assignments, moot courts, and coursework.

---

## 2. Problem Statement

Law students frequently need to produce structured academic legal research documents (monographs, research papers, case analyses) following ABNT formatting standards. Current workflow:
1. Manual web research for each topic
2. Copy-paste content into a document
3. Manually format ABNT citations (footnotes)
4. Format document structure (intro, development, conclusion)
5. Compile references

This is time-consuming and error-prone. Students would benefit from an automated tool that:
- Searches multiple legal topics automatically
- Generates ABNT-formatted content with proper citations
- Outputs a ready-to-deliver document file

---

## 3. User Stories

| ID | Story | Priority |
|----|-------|----------|
| US-01 | As a law student, I want to input a list of legal topics and receive a complete ABNT-formatted academic document, so I can submit it directly to my professor. | Must |
| US-02 | As a law student, I want to choose between DOCX and ODT output formats, so I can edit the document in my preferred word processor. | Must |
| US-03 | As a law student, I want the bot to search the web for each topic separately and include all relevant sources, so I don't miss important references. | Must |
| US-04 | As a law student, I want the document to include proper ABNT footnotes and a references section, so the document is academically valid. | Must |
| US-05 | As a law student, I want the bot to warn me if web search fails and use fallback content, so I still get a usable document. | Should |
| US-06 | As a law student, I want to receive the document as a file attachment when it's small, or as threaded messages when it's large, so I can always access the content. | Should |

---

## 4. Functional Requirements

### FR-01: Command Interface
- **Input**: Slash command `/research` with arguments:
  - `topic` (string, required): Long text containing research topics and optional pieces list
  - `format` (string, optional): `"docx"` or `"odt"`, default `"docx"`
- **Example invocation**:
  ```
  /research topic:NPJ
  
  Pesquisa: regimento do tribunal (procurar de quem é a competência de julgar questões de alvará judicial)
  
  Pesquisa: Contestação 
  
  3 peças.
  petição inicial
  Contestação
  Contestação com reconvenção
  ```

### FR-02: Input Parser
- Parse lines starting with `Pesquisa:` as research topics
- Parse lines starting with `Pesquisa:` followed by parentheses as detailed queries
- Parse lines under `X peças` marker as document pieces to produce
- Extract plain topic names for web search

### FR-03: Web Search Integration
- For each topic, perform web search using DuckDuckGo
- Retrieve top N results per topic (configurable, default 5)
- Store: URL, title, snippet/description for each result
- If search returns no results → flag topic for fallback generation
- If search fails entirely (timeout, error) → warn user, continue with fallback

### FR-04: ABNT Document Generation
**Structure**:
1. **Título** (topic or auto-generated from input)
2. **Resumo** (auto-generated abstract, 150-300 words)
3. **Introdução** (context and objectives)
4. **Desenvolvimento** (one section per topic with content + footnotes)
5. **Conclusão** (summary of findings)
6. **Referências** (full bibliography)

**Formatting**:
- Footnotes for citations (ABNT padrão)
- Reference list at end in ABNT format
- Proper heading hierarchy (1, 2, 3)
- Times New Roman 12pt, 1.5 line spacing (configurable in code)

### FR-05: File Output
- Generate `.docx` using `python-docx`
- Generate `.odt` using `odfpy`
- Filename format: `pesquisa_[topic_slug]_[timestamp].docx`

### FR-06: Delivery Strategy
| Condition | Action |
|-----------|--------|
| File size < 8MB | Send as Discord file attachment |
| File size > 8MB | Create new thread in channel, send chunked messages |

### FR-07: Fallback Behavior
- When web search fails or returns no results:
  - Generate content using LLM's training knowledge
  - Add warning note in document: "⚠️ A busca web não retornou resultados para [tópico]. O conteúdo a seguir foi gerado com base no conhecimento do modelo."
  - Do not include footnote for fallback content

### FR-08: Configuration
- `max_topics`: Maximum number of topics to process (default: 10)
- `search_results_per_topic`: Number of search results per topic (default: 5)
- `max_document_chars`: Maximum characters in document content (default: 50000)

---

## 5. Non-Functional Requirements

### Performance
- Search should complete within 30 seconds per topic
- Document generation should complete within 60 seconds
- Total execution time should not exceed 5 minutes for 10 topics

### Reliability
- If search fails for some topics, continue with successful ones
- Always produce output (fallback if needed)
- Log all errors for debugging

### Security
- No external API keys required (DuckDuckGo is free)
- Config remains in config.yaml (not modified)

### Localization
- All user-facing messages in Portuguese (PT-BR)
- Document content in Portuguese

---

## 6. Technical Architecture

### Dependencies
| Package | Purpose |
|---------|---------|
| `duckduckgo-search` | Web search (no API key) |
| `python-docx` | DOCX file generation |
| `odfpy` | ODT file generation |

### File Structure
```
src/
├── commands/
│   ├── research.py      # /research command
│   └── ...
├── prompts/
│   ├── research.py      # System prompt for document generation
│   └── ...
├── helpers/
│   ├── documents.py    # DOCX/ODT generation helpers
│   └── ...
```

### Data Flow
```
User Input → Parser → Topic List
                         ↓
                   Web Search (DuckDuckGo)
                         ↓
                   Search Results per Topic
                         ↓
                   LLM Content Generation (with sources)
                         ↓
                   ABNT Document Builder
                         ↓
                   File Generator (DOCX/ODT)
                         ↓
                   Delivery (file or thread)
```

---

## 7. Edge Cases

| Scenario | Expected Behavior |
|----------|---------------------|
| No topics provided | Show error: "Nenhum tópico de pesquisa fornecido." |
| Topic list exceeds max_topics | Process first N topics, warn user |
| Search timeout for topic | Continue, mark topic for fallback |
| All searches fail | Generate full document from LLM, warn user |
| Document too large | Switch to thread delivery |
| Invalid format choice | Default to docx |
| User has no permission | Show permission error |

---

## 8. Success Metrics

- `/research` command responds within 5 minutes
- Generated documents contain proper ABNT footnote citations
- Output files are editable in Microsoft Word and LibreOffice
- Fallback warning appears when search returns no results
- Thread delivery works for documents > 8MB

---

## 9. Out of Scope (Phase 1)

- User-provided attachments as sources
- Citation database / reference manager integration
- Multiple output formats (PDF, LaTeX)
- Collaborative editing
- Citation style customization
- Web search provider swapping (DuckDuckGo only for now)

---

## 10. Dependencies on Other Features

- `/research` is a standalone command (does not require task routing)
- Can be used independently from the main chat flow
- No changes required to `bot.py` on_message() flow

---

## 11. Related Documentation

- IMPLEMENTATION.md — Step 3: Build research mode
- `src/commands/abnt.py` — Reference for document command implementation
- `src/prompts/abnt.py` — Reference for ABNT prompt structure