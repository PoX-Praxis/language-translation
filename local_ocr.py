"""
Optional local VLM-based OCR for low-confidence text blocks.
Falls back gracefully if dependencies (torch, transformers) are not installed.
"""

import io
import logging

logger = logging.getLogger(__name__)

_model = None
_processor = None
_tokenizer = None
_device = None
_available = None


def is_available():
    global _available
    if _available is not None:
        return _available
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        _available = True
    except ImportError:
        _available = False
        logger.info("Local OCR disabled: torch/transformers not installed")
    return _available


def _load_model():
    global _model, _processor, _tokenizer, _device

    if _model is not None:
        return

    import torch
    from transformers import AutoModel, AutoTokenizer

    model_name = "stepfun-ai/GOT-OCR2_0"
    _device = "cuda" if torch.cuda.is_available() else "cpu"
    if _device == "cpu":
        logger.warning("Local OCR running on CPU — expect slow inference")

    logger.info("Loading local OCR model: %s on %s", model_name, _device)

    _tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    _model = AutoModel.from_pretrained(
        model_name,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
        device_map=_device,
        torch_dtype=torch.float16 if _device == "cuda" else torch.float32,
    )
    _model.eval()
    logger.info("Local OCR model loaded")


def local_ocr_image(pil_crop):
    if not is_available():
        return None

    try:
        _load_model()

        img_rgb = pil_crop.convert("RGB")

        result = _model.chat(_tokenizer, img_rgb, ocr_type="ocr")
        if result and isinstance(result, str):
            return result.strip()
        return None

    except Exception:
        logger.exception("Local OCR failed")
        return None
