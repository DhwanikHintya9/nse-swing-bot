"""Read-only PDF inspection and exact, page-scoped evidence excerpt verification."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from nse_swing_bot.events.capture_verification import verify_capture_manifest

MAX_PDF_BYTES = 250 * 1024 * 1024
MAX_PDF_PAGES = 5000
MAX_EMBEDDED_FILES = 500
MAX_NAME_TREE_DEPTH = 32


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _metadata_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _outline_rows(reader: PdfReader) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def visit(items: list[Any]) -> None:
        for item in items:
            if isinstance(item, list):
                visit(item)
                continue
            title = getattr(item, "title", None)
            if not isinstance(title, str) or not title.strip():
                continue
            try:
                page = reader.get_destination_page_number(item) + 1
            except (ValueError, TypeError, IndexError):
                page = None
            rows.append({"title": title.strip(), "page_number": page})

    try:
        visit(reader.outline)
    except (ValueError, TypeError, KeyError):
        return rows
    return rows



def _embedded_file_names(reader: PdfReader, max_files: int) -> list[str]:
    """Read only PDF name-tree labels; do not decompress embedded file streams."""
    def resolve(value: Any) -> Any:
        getter = getattr(value, "get_object", None)
        return getter() if callable(getter) else value

    root = resolve(reader.trailer["/Root"])
    names = resolve(root.get("/Names", {}))
    tree = resolve(names.get("/EmbeddedFiles", {}))
    if not tree:
        return []
    found: list[str] = []
    stack: list[tuple[Any, int]] = [(tree, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_NAME_TREE_DEPTH:
            raise ValueError("PDF embedded-file name tree exceeds depth limit")
        node = resolve(node)
        pairs = node.get("/Names", [])
        if len(pairs) % 2:
            raise ValueError("malformed PDF embedded-file name tree")
        for index in range(0, len(pairs), 2):
            label = str(pairs[index])
            found.append(label)
            if len(found) > max_files:
                raise ValueError("PDF embedded-file count exceeds configured limit")
        for child in reversed(node.get("/Kids", [])):
            stack.append((child, depth + 1))
    return found


def inspect_captured_pdf(
    capture_manifest_path: Path,
    output_manifest_path: Path,
    *,
    max_pdf_bytes: int = MAX_PDF_BYTES,
    max_pages: int = MAX_PDF_PAGES,
    max_embedded_files: int = MAX_EMBEDDED_FILES,
) -> Path:
    """Inspect PDF metadata, page text fingerprints, bookmarks and embedded files.

    The PDF is never rewritten. Embedded files are inventoried and hashed in
    memory but are not extracted. Inspection is not source authentication or
    operator review.
    """
    for name, value in (
        ("max_pdf_bytes", max_pdf_bytes),
        ("max_pages", max_pages),
        ("max_embedded_files", max_embedded_files),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    capture = verify_capture_manifest(capture_manifest_path)
    if capture.archive_path.suffix.lower() != ".pdf":
        raise ValueError("capture must identify a PDF file")
    if capture.byte_length > max_pdf_bytes:
        raise ValueError("PDF exceeds configured byte limit")

    try:
        reader = PdfReader(str(capture.archive_path), strict=False)
        if reader.is_encrypted:
            raise ValueError("encrypted PDFs are not supported for inspection")
        page_count = len(reader.pages)
        if page_count < 1 or page_count > max_pages:
            raise ValueError("PDF page count is outside configured limits")
        page_rows: list[dict[str, Any]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            encoded = text.encode("utf-8")
            page_rows.append({
                "page_number": page_number,
                "text_character_count": len(text),
                "text_sha256": _sha256(encoded),
                "has_extractable_text": bool(text.strip()),
            })

        metadata = reader.metadata
        metadata_fields = (
            "/Title", "/Author", "/Subject", "/Creator", "/Producer",
            "/CreationDate", "/ModDate", "/Keywords",
        )
        metadata_rows = {
            field.lstrip("/").lower(): _metadata_value(metadata.get(field))
            for field in metadata_fields
        } if metadata is not None else {
            field.lstrip("/").lower(): None for field in metadata_fields
        }

        attachment_names = _embedded_file_names(reader, max_embedded_files)
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("PDF could not be parsed safely") from error

    payload = {
        "schema_version": 1,
        "inspection_mode": "captured_pdf_read_only_metadata_and_text_fingerprints",
        "event_id": capture.event_id,
        "source_record_id": capture.source_record_id,
        "source_url": capture.source_url,
        "document_type": capture.document_type,
        "capture_manifest_path": str(capture.manifest_path),
        "pdf_filename": capture.archive_path.name,
        "pdf_byte_length": capture.byte_length,
        "pdf_sha256": capture.sha256,
        "pdf_version": getattr(reader, "pdf_header", None),
        "page_count": page_count,
        "metadata": metadata_rows,
        "bookmarks": _outline_rows(reader),
        "pages": page_rows,
        "embedded_attachment_names": attachment_names,
        "embedded_attachment_count": len(attachment_names),
        "inspection_limitations": [
            "Text extraction may omit scanned/image-only content, layout, tables or handwriting.",
            "Bookmarks and metadata are document-provided labels, not proof of "
            "annexure completeness.",
            "Embedded attachment names are read from the PDF name tree only; streams are not decompressed or extracted.",
            "Inspection does not establish source authenticity, direct review, P1 status "
            "or event admission.",
        ],
    }
    output = output_manifest_path.expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=output.parent, prefix=".pdf-inspection-", delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, output)
    except FileExistsError:
        raise FileExistsError(f"refusing to overwrite PDF inspection manifest: {output}") from None
    finally:
        temporary.unlink(missing_ok=True)
    return output


def verify_exact_pdf_excerpt(
    capture_manifest_path: Path,
    page_number: int,
    exact_excerpt: str,
    *,
    attachment_name: str | None = None,
) -> dict[str, Any]:
    """Verify an exact excerpt exists on one page of a captured PDF.

    For a child PDF captured from a ZIP, the normal capture verifier first
    verifies the full parent ZIP/member lineage. Excerpts are never normalized.
    """
    if not isinstance(page_number, int) or isinstance(page_number, bool) or page_number < 1:
        raise ValueError("page_number must be a positive integer")
    if not isinstance(exact_excerpt, str) or not exact_excerpt.strip():
        raise ValueError("exact_excerpt must be a non-empty string")
    if attachment_name is not None:
        raise ValueError(
            "inspect and capture the embedded attachment separately before excerpt review"
        )
    capture = verify_capture_manifest(capture_manifest_path)
    if capture.archive_path.suffix.lower() != ".pdf":
        raise ValueError("capture must identify a PDF file")
    if capture.byte_length > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds configured byte limit")
    try:
        reader = PdfReader(str(capture.archive_path), strict=False)
        if reader.is_encrypted:
            raise ValueError("encrypted PDFs are not supported for excerpt verification")
        if page_number > len(reader.pages):
            raise ValueError("page_number exceeds PDF page count")
        page_text = reader.pages[page_number - 1].extract_text() or ""
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("PDF page text could not be extracted") from error
    if exact_excerpt not in page_text:
        raise ValueError("exact excerpt does not occur on the specified PDF page")
    return {
        "event_id": capture.event_id,
        "source_record_id": capture.source_record_id,
        "source_url": capture.source_url,
        "document_type": capture.document_type,
        "pdf_sha256": capture.sha256,
        "page_number": page_number,
        "page_text_sha256": _sha256(page_text.encode("utf-8")),
        "exact_excerpt": exact_excerpt,
        "excerpt_sha256": _sha256(exact_excerpt.encode("utf-8")),
        "verification_mode": "exact_substring_match_no_normalization",
        "evidence_review_status": "pending",
    }


def write_excerpt_verification(
    capture_manifest_path: Path,
    output_path: Path,
    page_number: int,
    exact_excerpt: str,
) -> Path:
    """Write an immutable JSON record for one verified page-scoped excerpt."""
    result = verify_exact_pdf_excerpt(capture_manifest_path, page_number, exact_excerpt)
    output = output_path.expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=output.parent, prefix=".pdf-excerpt-", delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, output)
    except FileExistsError:
        raise FileExistsError(f"refusing to overwrite excerpt verification: {output}") from None
    finally:
        temporary.unlink(missing_ok=True)
    return output
