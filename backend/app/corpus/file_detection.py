from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


class FileTypeDetectionError(ValueError):
    """Raised when a file cannot be trusted as the type claimed by its name."""


@dataclass(frozen=True)
class PdfPageProfile:
    page_number: int
    profile: str
    char_count: int
    image_count: int
    image_area_ratio: float = 0.0
    ocr_required: bool = False


@dataclass(frozen=True)
class PdfPreflight:
    content_profile: str
    page_count: int
    pages: list[PdfPageProfile] = field(default_factory=list)
    empty_text_pages: int = 0
    text_density: float = 0.0
    encrypted: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def ocr_required(self) -> bool:
        return self.content_profile in {"scanned_pdf", "mixed_pdf"}

    @property
    def non_empty_page_ratio(self) -> float:
        if not self.page_count:
            return 0.0
        return sum(page.char_count > 0 for page in self.pages) / self.page_count


_MAGIC = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
}
_OFFICE_EXTENSIONS = {".docx": "word/", ".pptx": "ppt/", ".xlsx": "xl/"}


def _zip_matches_extension(content: bytes, extension: str) -> bool:
    marker = _OFFICE_EXTENSIONS.get(extension)
    if marker is None:
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            return "[Content_Types].xml" in names and any(name.startswith(marker) for name in names)
    except (OSError, zipfile.BadZipFile):
        return False


def _matches_magic(content: bytes, extension: str) -> bool:
    signatures = _MAGIC.get(extension)
    if signatures:
        return any(content.startswith(signature) for signature in signatures)
    if extension == ".webp":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    if extension in _OFFICE_EXTENSIONS:
        return content.startswith(b"PK") and _zip_matches_extension(content, extension)
    if extension in {".doc", ".xls", ".ppt"}:
        return content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") or content.lstrip().startswith(b"{\\rtf")
    return True


def detect_file_type(filename: str | None, content_type: str | None, content: bytes) -> str:
    """Validate a claimed upload type and return a normalized logical type."""
    name = Path(filename or "").name
    extension = Path(name).suffix.lower()
    if not extension:
        raise FileTypeDetectionError("missing_file_extension")
    if not content:
        raise FileTypeDetectionError("empty_file")
    expected_mime = {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".xls": "application/vnd.ms-excel",
        ".ppt": "application/vnd.ms-powerpoint",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".html": "text/html", ".htm": "text/html",
        ".md": "text/markdown", ".markdown": "text/markdown",
    }.get(extension)
    if expected_mime is None:
        raise FileTypeDetectionError("unsupported_extension")
    # A number of desktop exporters produce RTF but let the caller name the
    # file ``.docx``.  It is still a Word document from the user's point of
    # view, but it is not an OOXML/DOCX package.  Classify it by its bytes so
    # it reaches the compatible RTF parser instead of failing as a corrupt ZIP.
    is_rtf_payload = content.lstrip().startswith(b"{\\rtf")
    if content_type and content_type not in {expected_mime, "application/octet-stream"}:
        raise FileTypeDetectionError("mime_mismatch")
    if not (extension == ".docx" and is_rtf_payload) and not _matches_magic(content, extension):
        raise FileTypeDetectionError("magic_bytes_mismatch")
    if extension == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise FileTypeDetectionError("encrypted_pdf")
        except FileTypeDetectionError:
            raise
        except Exception as exc:
            raise FileTypeDetectionError("corrupted_pdf") from exc
    elif extension in {".png", ".jpg", ".jpeg"}:
        try:
            from PIL import Image
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
        except Exception as exc:
            raise FileTypeDetectionError("corrupted_image") from exc
    logical_type = {
        ".pdf": "pdf", ".doc": "doc", ".docx": "docx", ".ppt": "ppt", ".pptx": "pptx", ".xls": "xls", ".xlsx": "xlsx",
        ".png": "image", ".jpg": "image", ".jpeg": "image",
        ".html": "html", ".htm": "html", ".md": "markdown", ".markdown": "markdown",
    }[extension]
    return "doc" if extension == ".docx" and is_rtf_payload else logical_type


def preflight_pdf(path: str | Path, *, min_chars_per_page: int = 30, scanned_page_ratio: float = 0.7) -> PdfPreflight:
    """Inspect PDF pages without treating text extraction as OCR."""
    path = Path(path)
    # PyMuPDF performs the read-only page scan in one native pass and avoids
    # the high cost of extracting every page twice on large scanned PDFs.
    try:
        import fitz
        document = fitz.open(str(path))
        if document.needs_pass:
            page_count = len(document)
            document.close()
            return PdfPreflight("invalid_pdf", page_count, encrypted=True, warnings=["encrypted_pdf"])
        pages: list[PdfPageProfile] = []
        for index, page in enumerate(document, start=1):
            text = str(page.get_text("text") or "").strip()
            chars = len(text)
            # Counting image objects is enough for the OCR branch decision.
            # Resolving every image xref/bbox is prohibitively expensive for
            # large scanned PDFs, so area is intentionally left for the
            # optional visual stage.
            image_count = len(page.get_images(full=True))
            image_area_ratio = 0.0
            profile = (
                "text_page" if chars >= min_chars_per_page
                else "scanned_page" if chars == 0 and image_count
                else "mixed_page" if chars < min_chars_per_page and image_count
                else "scanned_page" if chars == 0
                else "mixed_page"
            )
            pages.append(PdfPageProfile(index, profile, chars, image_count, image_area_ratio, profile != "text_page"))
        document.close()
        page_count = len(pages)
        empty_pages = sum(page.profile == "scanned_page" for page in pages)
        scanned_pages = sum(page.profile != "text_page" for page in pages)
        total_chars = sum(page.char_count for page in pages)
        if page_count and empty_pages / page_count >= scanned_page_ratio:
            content_profile = "scanned_pdf"
        elif scanned_pages:
            content_profile = "mixed_pdf"
        else:
            content_profile = "text_pdf"
        warnings: list[str] = []
        if any(page.image_area_ratio >= 0.65 for page in pages):
            warnings.append("large_page_images_detected")
        if total_chars and total_chars / max(page_count, 1) < min_chars_per_page:
            warnings.append("low_text_density")
        return PdfPreflight(content_profile, page_count, pages, empty_pages, total_chars / max(page_count, 1), warnings=warnings)
    except ImportError:
        pass
    except Exception as exc:
        # Preserve the previous pypdf path for malformed/encrypted files when
        # fitz cannot open a document.
        logger = __import__("logging").getLogger(__name__)
        logger.debug("fitz_pdf_preflight_failed path=%s failure_type=%s", path.name, type(exc).__name__)

    from pypdf import PdfReader
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            return PdfPreflight("invalid_pdf", len(reader.pages), encrypted=True, warnings=["encrypted_pdf"])
        pages: list[PdfPageProfile] = []
        fitz_document = None
        try:
            import fitz
            fitz_document = fitz.open(str(path))
        except Exception:
            fitz_document = None
        for index, page in enumerate(reader.pages, start=1):
            text = str(page.extract_text() or "").strip()
            try:
                image_count = len(page.images)
            except Exception:
                image_count = 0
            chars = len(text)
            image_area_ratio = 0.0
            if fitz_document is not None and index - 1 < len(fitz_document):
                try:
                    visual_page = fitz_document[index - 1]
                    page_area = max(float(visual_page.rect.width * visual_page.rect.height), 1.0)
                    image_info = visual_page.get_image_info(xrefs=True)
                    image_area = sum(max(0.0, float(item["bbox"][2] - item["bbox"][0])) * max(0.0, float(item["bbox"][3] - item["bbox"][1])) for item in image_info if item.get("bbox"))
                    image_area_ratio = min(1.0, image_area / page_area)
                    image_count = max(image_count, len(image_info))
                except Exception:
                    pass
            if chars >= min_chars_per_page:
                profile = "text_page"
            elif chars == 0 and image_count:
                profile = "scanned_page"
            elif chars < min_chars_per_page and image_count:
                profile = "mixed_page"
            else:
                profile = "scanned_page" if chars == 0 else "mixed_page"
            pages.append(PdfPageProfile(index, profile, chars, image_count, image_area_ratio, profile != "text_page"))
        if fitz_document is not None:
            fitz_document.close()
    except Exception as exc:
        raise FileTypeDetectionError("corrupted_pdf") from exc
    page_count = len(pages)
    empty_pages = sum(page.profile == "scanned_page" for page in pages)
    scanned_pages = sum(page.profile != "text_page" for page in pages)
    total_chars = sum(page.char_count for page in pages)
    if page_count and empty_pages / page_count >= scanned_page_ratio:
        content_profile = "scanned_pdf"
    elif scanned_pages:
        content_profile = "mixed_pdf"
    else:
        content_profile = "text_pdf"
    warnings: list[str] = []
    if any(page.image_area_ratio >= 0.65 for page in pages):
        warnings.append("large_page_images_detected")
    if total_chars and total_chars / max(page_count, 1) < min_chars_per_page:
        warnings.append("low_text_density")
    return PdfPreflight(content_profile, page_count, pages, empty_pages, total_chars / max(page_count, 1), warnings=warnings)


def render_pdf_pages(path: str | Path, output_dir: str | Path) -> list[Path]:
    """Render pages for later OCR/visual processing and return safe paths."""
    try:
        import fitz
    except ImportError as exc:
        raise FileTypeDetectionError("pdf_renderer_unavailable") from exc
    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    with fitz.open(str(path)) as document:
        for index, page in enumerate(document, start=1):
            output = (target / f"page-{index:04d}.png").resolve()
            if target not in output.parents:
                raise FileTypeDetectionError("unsafe_render_path")
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(str(output))
            rendered.append(output)
    return rendered
