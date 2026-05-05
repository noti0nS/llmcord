# PRD: `/pesquisa` Command — Academic Legal Research Generator

## 1. Overview

### Purpose
Enable law students to generate complete ABNT-formatted academic documents for NPJ (Núcleo de Prática Jurídica) assignments by describing their research in natural language. The LLM autonomously decides what to search, when to search, and how to structure the document.

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
- Interprets natural language research requests
- Searches the web autonomously using LLM function calling
- Generates ABNT-formatted content with proper citations
- Outputs a ready-to-deliver document file

---

## 3. User Stories

| ID | Story | Priority |
|----|-------|----------|
| US-01 | As a law student, I want to describe my research in free text and receive a complete ABNT-formatted academic document, so I can submit it directly to my professor. | Must |
| US-02 | As a law student, I want to choose between DOCX and ODT output formats, so I can edit the document in my preferred word processor. | Must |
| US-03 | As a law student, I want the bot to search the web for relevant sources autonomously, so I don't need to manually specify search queries. | Must |
| US-04 | As a law student, I want the document to include proper ABNT footnotes and a references section, so the document is academically valid. | Must |
| US-05 | As a law student, I want the bot to continue generating even if some web searches fail, so I still get a usable document. | Should |
| US-06 | As a law student, I want to receive the document as a file attachment when it's small, or as threaded messages when it's large, so I can always access the content. | Should |

---

## 4. Functional Requirements

### FR-01: Command Interface
- **Input**: Slash command `/pesquisa` with arguments:
  - `topic` (string, required): Free-text description of the research. The user describes what they need in natural language — subject, document type, depth, audience, specific topics, document pieces, etc. The LLM interprets this autonomously.
  - `format` (string, optional): `"docx"` or `"odt"`, default `"docx"`
- **Example invocations**:
  ```
  /pesquisa topic: Preciso de uma monografia sobre alvará judicial no TJSP.
  Quero algo aprofundado para professor. Pesquise o regimento do tribunal.

  /pesquisa topic: NPJ
  Pesquisa: regimento do tribunal
  Pesquisa: Contestação
  3 peças: petição inicial, contestação, contestação com reconvenção
  ```

### FR-02: Web Search via LLM Tool Calling
- A `web_search(query)` function tool is registered with the LLM via OpenAI's native function calling API.
- The LLM decides **when** to search and **what** to search for. No upfront search is performed.
- Each tool call executes a DuckDuckGo search and returns structured results (title, url, snippet) injected back into the conversation as tool response messages.
- The LLM may call the tool multiple times across multiple turns.

### FR-03: Tool-Calling Loop
- Messages are built with system prompt + user input + tool definitions.
- A loop sends messages to the LLM and processes responses:
  - `finish_reason == "stop"` with content → document is complete, exit loop.
  - `finish_reason == "tool_calls"` → execute web searches, append results as tool messages, continue loop.
  - Loop has a configurable maximum iteration limit (`max_tool_iterations`, default 10).
  - If the loop exhausts, force a final call with `tool_choice="none"` to generate the document.
- Each iteration is logged (model, iteration count, tool calls made).

### FR-04: ABNT Document Generation
**Structure** (determined by LLM from user request, with guidance in system prompt):
1. **Título** (from user's subject or auto-generated)
2. **Resumo** (auto-generated abstract, 150-300 words)
3. **Introdução** (context and objectives)
4. **Desenvolvimento** (one section per topic with content + footnotes)
5. **Conclusão** (summary of findings)
6. **Referências** (full bibliography in ABNT format)

**Formatting** (instructed via system prompt):
- Footnotes for citations (ABNT padrão)
- Reference list at end in ABNT format
- Proper heading hierarchy
- Formal academic Portuguese

### FR-05: File Output
- Generate `.docx` using `python-docx`
- Generate `.odt` using `odfpy`
- Filename format: `pesquisa_[title_slug]_[timestamp].docx`

### FR-06: Delivery Strategy
| Condition | Action |
|-----------|--------|
| File size < 8MB | Send as Discord file attachment |
| File size > 8MB | Create new thread in channel, send chunked messages |

### FR-07: Fallback Behavior
- When a web search returns no results: indicate empty results in the tool response. The LLM may search again with a different query or generate content from training knowledge.
- When the tool-calling loop exhausts iterations: force a final generation call without tools.
- When the LLM returns no content or errors: surface a user-facing error message.

### FR-08: Configuration
- `research.max_tool_iterations`: Maximum tool-calling loop iterations (default: 10)
- `research.max_document_chars`: Maximum characters in document content (default: 50000)
- `research.search_results_per_topic`: Number of search results per tool call (default: 5)

---

## 5. Non-Functional Requirements

### Performance
- Each web search should complete within 30 seconds.
- Total execution time should not exceed 5 minutes.
- Tool-calling loop overhead is minimal (LLM latency dominates).

### Reliability
- If search fails for some queries, the LLM can retry with different queries.
- Always produce output (fallback if needed).
- Log all tool calls and errors for debugging.

### Security
- No external API keys required for search (DuckDuckGo is free).
- Config remains in config.yaml (not modified).

### Localization
- All user-facing messages in Portuguese (PT-BR).
- Document content in Portuguese.

---

## 6. Technical Architecture

### Dependencies
| Package | Purpose |
|---------|---------|
| `duckduckgo-search` | Web search (no API key) |
| `python-docx` | DOCX file generation |
| `odfpy` | ODT file generation |
| `openai` | LLM function calling + document generation |

### File Structure
```
src/
├── commands/
│   ├── pesquisa.py      # /pesquisa command + tool loop
│   └── ...
├── prompts/
│   ├── pesquisa.py      # System prompt for tool-aware document generation
│   └── ...
├── helpers/
│   ├── documents.py     # DOCX/ODT generation helpers
│   ├── search.py        # DuckDuckGo search (called by tool handler)
│   └── ...
```

### Data Flow
```
User free text → LLM (system prompt + web_search tool definition)
                    ↓
              LLM decides to call web_search("query")
                    ↓
              search_topics() → results injected as tool response
                    ↓
              LLM analyzes results, may search more topics
                    ↓  (up to max_tool_iterations cycles)
              LLM generates complete ABNT document text
                    ↓
              generate_document() → DOCX/ODT bytes
                    ↓
              send_pesquisa_result() → file attachment or thread
```

---

## 7. Edge Cases

| Scenario | Expected Behavior |
|----------|---------------------|
| Empty topic | Show error: "Descreva sua pesquisa." |
| LLM returns document without searching | Accept and proceed (valid path) |
| LLM calls web_search with empty query | Return empty results, let LLM recover |
| Search returns no results | Return `[]` in tool response; LLM may retry or use training knowledge |
| Search throws exception | Return error string in tool response; LLM may retry |
| Tool loop exceeds max iterations | Force final call with `tool_choice="none"` |
| LLM returns finish_reason="length" | Force final call with `tool_choice="none"` |
| LLM returns finish_reason="content_filter" | Show error to user |
| Document too large for file attachment | Switch to thread delivery |
| Invalid format choice | Default to docx |

---

## 8. Success Metrics

- `/pesquisa` command responds within 5 minutes
- Generated documents contain proper ABNT footnote citations
- LLM autonomously searches for relevant sources without manual topic input
- Output files are editable in Microsoft Word and LibreOffice
- Fallback behavior works when searches fail or loop exhausts

---

## 9. Out of Scope (Phase 1)

- User-provided attachments as sources
- Citation database / reference manager integration
- Multiple output formats beyond DOCX/ODT (PDF, LaTeX)
- Collaborative editing
- Citation style customization
- Web search provider swapping (DuckDuckGo only for now)
- Streaming generation (non-streaming for v1)

---

## 10. Dependencies on Other Features

- `/pesquisa` is a standalone command (does not require task routing).
- Relies on `src/helpers/search.py` for DuckDuckGo searches.
- Relies on `src/helpers/documents.py` for file generation.
- Requires OpenAI function calling support from the configured provider/model.

---

## 11. Removed Features (from v1)

These features from the original implementation are replaced by LLM autonomy:
- **Manual topic parsing** (`_parse_list_input`): The LLM interprets the free-text input.
- **Document type selection** (`tipo`): The LLM infers the document type.
- **Depth selection** (`profundidade`): The LLM infers the desired depth.
- **Audience selection** (`publico`): The LLM infers the target audience.
- **Document pieces** (`pecas`): The LLM interprets which pieces to include.
- **Upfront web search**: Replaced by on-demand tool calling.
