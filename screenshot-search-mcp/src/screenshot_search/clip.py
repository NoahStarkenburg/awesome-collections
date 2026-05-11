"""CLIP model loader.

Loads `open_clip` ViT-B/32 with CPU-friendly defaults. The model is heavy
(~150 MB weights + Torch state) so we lazy-load on first call — server
startup stays fast and `ping` works without ever loading CLIP.

Image and text embedding passes are added in sibling commits.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MODEL = "ViT-B-32"
DEFAULT_PRETRAINED = "openai"
MODEL_TAG = f"open_clip/{DEFAULT_MODEL}/{DEFAULT_PRETRAINED}"

_state: dict[str, Any] = {}
_lock = threading.Lock()


def model_tag() -> str:
    """Identifier used to key embeddings in the `embeddings` table."""
    return MODEL_TAG


def load() -> dict[str, Any]:
    """Lazy-load the CLIP model. Returns a dict with model/preprocess/tokenizer/device.

    The first call may take 30–60s on a cold cache (downloads ~150 MB).
    Subsequent calls return immediately. Raises ImportError if `open_clip_torch`
    is not installed (caller decides whether to error or degrade).
    """
    if "model" in _state:
        return _state
    with _lock:
        if "model" in _state:
            return _state

        try:
            import open_clip  # type: ignore[import-not-found]
            import torch  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "open_clip_torch is required for visual search. "
                "Install with: pip install open-clip-torch"
            ) from exc

        device = "cuda" if (os.environ.get("CLIP_USE_CUDA") and torch.cuda.is_available()) else "cpu"
        log.info("Loading CLIP %s/%s on %s …", DEFAULT_MODEL, DEFAULT_PRETRAINED, device)
        model, _, preprocess = open_clip.create_model_and_transforms(
            DEFAULT_MODEL, pretrained=DEFAULT_PRETRAINED, device=device
        )
        model.eval()
        tokenizer = open_clip.get_tokenizer(DEFAULT_MODEL)

        _state.update(
            {
                "model": model,
                "preprocess": preprocess,
                "tokenizer": tokenizer,
                "device": device,
                "open_clip": open_clip,
                "torch": torch,
            }
        )
        log.info("CLIP loaded.")
        return _state


def is_loaded() -> bool:
    return "model" in _state


def reset() -> None:
    """Drop the cached model. Test-only — releases memory between runs."""
    with _lock:
        _state.clear()
