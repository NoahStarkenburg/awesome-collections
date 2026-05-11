"""CLIP model loader + image/text embedding passes.

Loads `open_clip` ViT-B/32 lazily so server startup stays fast — `ping` works
without ever loading CLIP. Embedding functions normalize vectors to unit length
and serialize them as float32 BLOBs for the `embeddings` table.
"""
from __future__ import annotations

import logging
import os
import struct
import threading
from pathlib import Path
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


def _vector_to_blob(vec) -> bytes:
    """Pack a torch tensor / numpy array / iterable of floats as little-endian float32."""
    if hasattr(vec, "detach"):
        vec = vec.detach().cpu().numpy()
    if hasattr(vec, "tolist"):
        vec = vec.tolist()
    flat = list(vec[0]) if isinstance(vec, list) and vec and isinstance(vec[0], list) else list(vec)
    return struct.pack(f"<{len(flat)}f", *flat)


def embed_image(image_path: str | Path) -> bytes:
    """Compute the L2-normalized CLIP embedding for an image. Returns float32 BLOB.

    Raises FileNotFoundError if the path doesn't exist; ImportError if open_clip
    isn't installed. Other I/O / model errors propagate so the caller can decide
    whether to skip-and-continue or surface.
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(image_path)

    state = load()
    torch = state["torch"]
    from PIL import Image  # type: ignore[import-not-found]

    with Image.open(path) as img:
        img = img.convert("RGB")
        tensor = state["preprocess"](img).unsqueeze(0).to(state["device"])

    with torch.no_grad():
        features = state["model"].encode_image(tensor)
        features = features / features.norm(dim=-1, keepdim=True)

    return _vector_to_blob(features.squeeze(0))


def embed_text(query: str) -> list[float]:
    """Compute the L2-normalized CLIP embedding for a text query.

    Returns a Python list of floats (not a BLOB) — callers feed this directly
    into `store.nearest_neighbors`, which expects an unwrapped vector.
    """
    if not query.strip():
        raise ValueError("Empty query")

    state = load()
    torch = state["torch"]
    tokenizer = state["tokenizer"]

    tokens = tokenizer([query]).to(state["device"])
    with torch.no_grad():
        features = state["model"].encode_text(tokens)
        features = features / features.norm(dim=-1, keepdim=True)

    return features.squeeze(0).detach().cpu().tolist()
