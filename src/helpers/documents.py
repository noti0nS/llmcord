from io import BytesIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import discord
import httpx

from ..constants import (
    SUPPORTED_WORD_ATTACHMENT_EXTENSIONS,
    SUPPORTED_WORD_CONTENT_TYPES,
)

try:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
except ImportError:
    Document = None
    Pt = WD_ALIGN_PARAGRAPH = None  # pyright: ignore[reportConstantRedefinition]

try:
    from odf import opendocument
    from odf.style import ParagraphProperties, Style, TextProperties
    from odf.text import P
except ImportError:  # pragma: no cover
    opendocument = None
    Style = ParagraphProperties = TextProperties = None
    P = None  # pyright: ignore[reportConstantRedefinition]


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


def generate_docx_document(content: str, title: str) -> bytes:
    """Generate a DOCX file from plain text content."""
    if Document is None:
        raise RuntimeError("python-docx is required to generate DOCX files")

    doc = Document()

    # Set default font
    style = doc.styles["Normal"]
    font = style.font  # pyright: ignore[reportAttributeAccessIssue]
    font.name = "Times New Roman"
    font.size = Pt(12)  # pyright: ignore[reportOptionalCall]

    # Add title
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER  # pyright: ignore[reportOptionalMemberAccess]
    title_run = title_para.add_run(title)
    title_run.bold = True
    title_run.font.size = Pt(14)  # pyright: ignore[reportOptionalMemberAccess,reportOptionalCall]

    # Add content paragraphs
    for line in content.split("\n"):
        if line.strip():
            doc.add_paragraph(line.strip())
        else:
            # Add empty paragraph for spacing
            doc.add_paragraph()

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def generate_odt_document(content: str, title: str) -> bytes:
    """Generate an ODT file from plain text content."""
    if opendocument is None:
        raise RuntimeError("odfpy is required to generate ODT files")

    doc = opendocument.OpenDocumentText()

    # Create styles
    title_style = Style(name="Title", family="paragraph")  # pyright: ignore[reportOptionalCall]
    title_style.addElement(ParagraphProperties(textalign="center"))  # pyright: ignore[reportOptionalCall]
    title_text_props = TextProperties(  # pyright: ignore[reportOptionalCall]
        fontsize="14pt", fontweight="bold", fontfamily="Times New Roman"
    )
    title_style.addElement(title_text_props)
    doc.styles.addElement(title_style)

    normal_style = Style(name="Normal", family="paragraph")  # pyright: ignore[reportOptionalCall]
    normal_text_props = TextProperties(fontsize="12pt", fontfamily="Times New Roman")  # pyright: ignore[reportOptionalCall]
    normal_style.addElement(normal_text_props)
    doc.styles.addElement(normal_style)

    # Add title
    title_para = P(text=title, stylename=title_style)  # pyright: ignore[reportOptionalCall]
    doc.text.addElement(title_para)  # pyright: ignore[reportAttributeAccessIssue]

    # Add content paragraphs
    for line in content.split("\n"):
        if line.strip():
            para = P(text=line.strip(), stylename=normal_style)  # pyright: ignore[reportOptionalCall]
            doc.text.addElement(para)  # pyright: ignore[reportAttributeAccessIssue]
        else:
            para = P(text="", stylename=normal_style)  # pyright: ignore[reportOptionalCall]
            doc.text.addElement(para)  # pyright: ignore[reportAttributeAccessIssue]

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def generate_document(
    content: str, title: str, output_format: str
) -> tuple[bytes, str]:
    """Generate a document in the specified format.

    Returns a tuple of (file_bytes, filename_suffix).
    """
    if output_format.lower() == "odt":
        return generate_odt_document(content, title), ".odt"
    return generate_docx_document(content, title), ".docx"
