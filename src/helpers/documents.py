from io import BytesIO
from typing import cast
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import pandoc

import discord
import httpx

from ..constants import (
    SUPPORTED_WORD_ATTACHMENT_EXTENSIONS,
    SUPPORTED_WORD_CONTENT_TYPES,
)

try:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt
except ImportError:
    Document = None
    Pt = WD_ALIGN_PARAGRAPH = Cm = None  # pyright: ignore[reportConstantRedefinition]


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


def _run_pandoc(markdown_text: str, output_format: str) -> bytes:
    try:
        doc = pandoc.read(source=markdown_text, format="markdown")
    except RuntimeError as exc:
        raise RuntimeError(
            "pandoc is required to generate documents. "
            "Install it from https://pandoc.org/installing.html"
        ) from exc
    return cast(bytes, pandoc.write(doc, format=output_format))


def _apply_abnt_docx(docx_bytes: bytes) -> bytes:
    if Document is None:
        return docx_bytes

    doc = Document(BytesIO(docx_bytes))

    section = doc.sections[0]
    section.page_width = Cm(21)  # pyright: ignore[reportOptionalCall]
    section.page_height = Cm(29.7)  # pyright: ignore[reportOptionalCall]
    section.top_margin = Cm(3)  # pyright: ignore[reportOptionalCall]
    section.bottom_margin = Cm(2)  # pyright: ignore[reportOptionalCall]
    section.left_margin = Cm(3)  # pyright: ignore[reportOptionalCall]
    section.right_margin = Cm(2)  # pyright: ignore[reportOptionalCall]

    try:
        normal = doc.styles["Normal"]
    except KeyError:
        pass
    else:
        normal.font.name = "Times New Roman"  # pyright: ignore[reportAttributeAccessIssue]
        normal.font.size = Pt(12)  # pyright: ignore[reportAttributeAccessIssue,reportOptionalCall]
        normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
        normal.paragraph_format.line_spacing = 1.5  # pyright: ignore[reportAttributeAccessIssue]

    for name in ("Heading 1", "Heading 2", "Heading 3", "heading 1", "heading 2", "heading 3"):
        try:
            heading = doc.styles[name]
        except KeyError:
            continue
        heading.font.name = "Times New Roman"  # pyright: ignore[reportAttributeAccessIssue]
        heading.font.size = Pt(12)  # pyright: ignore[reportAttributeAccessIssue,reportOptionalCall]
        heading.font.bold = True  # pyright: ignore[reportAttributeAccessIssue]
        heading.paragraph_format.line_spacing = 1.5  # pyright: ignore[reportAttributeAccessIssue]
        heading.paragraph_format.space_before = Pt(12)  # pyright: ignore[reportAttributeAccessIssue,reportOptionalCall]
        heading.paragraph_format.space_after = Pt(6)  # pyright: ignore[reportAttributeAccessIssue,reportOptionalCall]

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def generate_docx_document(content: str, title: str) -> bytes:
    md = f"# {title}\n\n{content}"
    return _apply_abnt_docx(_run_pandoc(md, "docx"))


def generate_odt_document(content: str, title: str) -> bytes:
    md = f"# {title}\n\n{content}"
    return _run_pandoc(md, "odt")


def generate_document(
    content: str, title: str, output_format: str
) -> tuple[bytes, str]:
    """Generate a document in the specified format.

    Returns a tuple of (file_bytes, filename_suffix).
    """
    if output_format.lower() == "odt":
        return generate_odt_document(content, title), ".odt"
    return generate_docx_document(content, title), ".docx"
