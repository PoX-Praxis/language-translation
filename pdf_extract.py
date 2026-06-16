"""
PDF text extraction module.
Extracts text + coordinates directly from text-based PDFs (no OCR needed).
Falls back to image rendering for scanned/image PDFs.
"""

import logging

logger = logging.getLogger(__name__)

PDF_TEXT_MIN_CHARS = 20

_fitz_available = None


def is_available():
    global _fitz_available
    if _fitz_available is not None:
        return _fitz_available
    try:
        import fitz  # noqa: F401
        _fitz_available = True
    except ImportError:
        _fitz_available = False
        logger.info("PDF extraction disabled: PyMuPDF not installed")
    return _fitz_available


def extract_text_blocks_from_pdf(pdf_path, page_num=0, render_scale=2.0):
    if not is_available():
        return None, None

    import fitz

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        logger.exception("Failed to open PDF: %s", pdf_path)
        return None, None

    if page_num >= len(doc):
        doc.close()
        return None, None

    page = doc[page_num]

    plain_text = page.get_text()
    is_text_pdf = len(plain_text.strip()) >= PDF_TEXT_MIN_CHARS

    if is_text_pdf:
        blocks = _extract_text_blocks(page, render_scale)
        page_img = _render_page(page, render_scale)
        doc.close()
        return blocks, page_img
    else:
        page_img = _render_page(page, render_scale)
        doc.close()
        return None, page_img


def _extract_text_blocks(page, scale):
    import fitz

    text_dict = page.get_text("dict")
    blocks = []

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue

        lines_text = []
        min_x = float("inf")
        min_y = float("inf")
        max_x = 0
        max_y = 0
        char_heights = []

        for line in block.get("lines", []):
            spans_text = []
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if text:
                    spans_text.append(text)
                    char_heights.append(span.get("size", 12))
            if spans_text:
                lines_text.append(" ".join(spans_text))

            bbox = line.get("bbox", (0, 0, 0, 0))
            min_x = min(min_x, bbox[0])
            min_y = min(min_y, bbox[1])
            max_x = max(max_x, bbox[2])
            max_y = max(max_y, bbox[3])

        full_text = "\n".join(lines_text)
        if not full_text.strip():
            continue

        import numpy as np
        median_h = int(np.median(char_heights)) if char_heights else 12

        pad_x = 4
        pad_y = 2
        blocks.append({
            "x": max(0, int(min_x * scale) - pad_x),
            "y": max(0, int(min_y * scale) - pad_y),
            "w": int((max_x - min_x) * scale) + pad_x * 2,
            "h": int((max_y - min_y) * scale) + pad_y * 2,
            "text": full_text,
            "median_char_h": int(median_h * scale),
            "median_conf": 100,
        })

    return blocks


def _render_page(page, scale):
    from PIL import Image

    mat = __import__("fitz").Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return img
