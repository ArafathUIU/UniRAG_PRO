import io
import re
import base64
import logging
from django.conf import settings
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

# Groq vision-capable models, verified against the live /models endpoint on
# 2026-07-23. The previous entries (llama-3.2-*-vision-preview, llava) were
# decommissioned by Groq, so every vision call failed silently and image
# understanding fell back to filename-based guessing.
VISION_MODELS = [
    "qwen/qwen3.6-27b",
]

# Markers produced below when extraction fails for a file.
FALLBACK_MARKERS = ("[Attached Image:", "[No readable content")


def is_fallback_only(combined_text: str) -> bool:
    """
    True when extraction produced no real content — every file block is just a
    fallback marker. Checked per block so one unreadable file doesn't discard
    the successfully extracted content of the others.
    """
    if not combined_text or not combined_text.strip():
        return True
    for block in re.split(r"^===== FILE \d+: .* =====$", combined_text, flags=re.MULTILINE):
        text = block.strip()
        if text and not text.startswith(FALLBACK_MARKERS):
            return False
    return True


def extract_text_from_files(files) -> tuple:
    """
    Extracts and combines text/descriptions from one or more uploaded files of
    any supported type (PDF, DOC/DOCX, images, TXT/CSV/MD, and a generic text
    fallback for everything else).

    Returns a (combined_name, combined_text) tuple:
      - combined_name: short human-readable label for the attachment set.
      - combined_text: each file's extraction, labelled and concatenated so the
        router/LLM can answer across all of them at once.
    """
    if not files:
        return None, None

    names = []
    blocks = []
    for idx, f in enumerate(files, start=1):
        name = getattr(f, "name", f"file_{idx}")
        names.append(name)
        try:
            text = extract_text_from_file(f, name)
        except Exception as e:
            logger.error(f"Failed to extract text from '{name}': {e}")
            text = ""
        if not text or not text.strip():
            text = f"[No readable content could be extracted from {name}]"
        blocks.append(f"===== FILE {idx}: {name} =====\n{text}")

    if len(names) == 1:
        combined_name = names[0]
    else:
        combined_name = f"{len(names)} files: " + ", ".join(names)

    return combined_name, "\n\n".join(blocks)


def extract_text_from_file(file_obj, file_name: str) -> str:
    """
    Extracts readable text and visual descriptions from uploaded files (PDF, DOC/DOCX, TXT, PNG, JPG, JPEG, WEBP).
    Includes OCR/Vision fallback for scanned PDFs and image files.
    """
    ext = file_name.lower().split(".")[-1] if "." in file_name else ""
    file_bytes = file_obj.read()
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)

    if ext == "pdf":
        text = _extract_from_pdf(file_bytes)
        # If PDF text extraction yielded almost nothing (e.g. scanned PDF), fallback to OCR via page rendering
        if len(text.strip()) < 20:
            logger.info(f"PDF '{file_name}' returned minimal text ({len(text)} chars). Attempting page image vision OCR fallback.")
            scanned_text = _ocr_pdf_pages(file_bytes)
            if scanned_text.strip():
                return scanned_text
        return text
    elif ext in ["txt", "csv", "log", "md"]:
        return file_bytes.decode("utf-8", errors="ignore").strip()
    elif ext in ["doc", "docx"]:
        return _extract_from_docx(file_bytes, file_name)
    elif ext in ["png", "jpg", "jpeg", "webp", "bmp", "gif"]:
        return _extract_from_image(file_bytes, ext, file_name)
    else:
        # Generic fallback attempt as text
        try:
            return file_bytes.decode("utf-8", errors="ignore").strip()
        except Exception:
            return ""


def _extract_from_pdf(file_bytes: bytes) -> str:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text_parts = []
        for page in doc:
            p_text = page.get_text("text")
            if p_text:
                text_parts.append(p_text)
        doc.close()
        return "\n".join(text_parts).strip()
    except Exception as e:
        logger.error(f"Error parsing PDF with fitz: {e}")
        return ""


def _ocr_pdf_pages(file_bytes: bytes, max_pages: int = 5) -> str:
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        ocr_texts = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            page_text = _extract_from_image(img_bytes, "png", f"page_{i+1}.png")
            if page_text:
                ocr_texts.append(f"--- Page {i+1} ---\n{page_text}")
        doc.close()
        return "\n".join(ocr_texts).strip()
    except Exception as e:
        logger.error(f"Error doing OCR on PDF pages: {e}")
        return ""


def _extract_from_docx(file_bytes: bytes, file_name: str) -> str:
    try:
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        full_text = [para.text for para in doc.paragraphs if para.text]
        return "\n".join(full_text).strip()
    except Exception as e:
        logger.warning(f"python-docx error or not installed: {e}. Attempting raw string extraction.")
        try:
            return file_bytes.decode("utf-8", errors="ignore").strip()
        except Exception:
            return ""


def _optimize_image_bytes(file_bytes: bytes, ext: str, max_dim: int = 1024) -> tuple:
    """
    Resizes large uploaded images to max 1024x1024 JPEG to fit well within Groq API payload limits.
    """
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(file_bytes))
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(out, format="JPEG", quality=85)
        return out.getvalue(), "image/jpeg"
    except Exception as e:
        logger.warning(f"PIL optimization failed: {e}. Attempting fitz optimization.")
        try:
            import fitz
            doc = fitz.open(stream=file_bytes, filetype=ext if ext else "jpg")
            page = doc[0]
            pix = page.get_pixmap(dpi=100)
            img_bytes = pix.tobytes("jpeg")
            doc.close()
            return img_bytes, "image/jpeg"
        except Exception as e2:
            logger.warning(f"fitz optimization failed: {e2}. Using raw bytes.")
            mime_map = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "webp": "image/webp",
            }
            return file_bytes, mime_map.get(ext.lower(), "image/jpeg")


def _extract_from_image(file_bytes: bytes, ext: str, file_name: str = "image.jpg") -> str:
    api_key = getattr(settings, "GROQ_API_KEY", None)
    if not api_key:
        return f"[Attached Image: {file_name}]"

    # Optimize and compress image bytes to avoid Groq payload size limit errors
    opt_bytes, mime_type = _optimize_image_bytes(file_bytes, ext)
    b64_img = base64.b64encode(opt_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{b64_img}"

    vision_prompt = (
        "Analyze this image thoroughly in detail.\n"
        "1. Describe all visual content, scenes, objects, diagrams, logos, institutional symbols, building/campus features, or layout.\n"
        "2. Transcribe any readable text, titles, numbers, tables, dates, and details present in the image.\n"
        "Provide a rich, structured description and exact text transcription."
    )

    for model_name in VISION_MODELS:
        try:
            llm = ChatGroq(model=model_name, api_key=api_key, temperature=0.1)
            message = HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": vision_prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ]
            )
            res = llm.invoke([message])
            content = res.content if res and isinstance(res.content, str) else ""
            # qwen3.6 is a reasoning model — drop its <think> block, keep the answer
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            if len(content) > 10:
                logger.info(f"Successfully analyzed image '{file_name}' with vision model '{model_name}'.")
                return content
        except Exception as e:
            logger.warning(f"Groq vision model '{model_name}' failed for '{file_name}': {e}. Trying next...")

    # Fallback description if Groq vision model endpoint fails or is rate-limited
    clean_name = file_name.replace("_", " ").replace("-", " ")
    return f"[Attached Image: {file_name}. Topic inferred from filename: '{clean_name}']"
