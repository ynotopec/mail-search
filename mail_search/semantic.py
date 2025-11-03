"""Lightweight embedding utilities used to power semantic search."""

from __future__ import annotations

from abc import ABC, abstractmethod
from array import array
import hashlib
import os
from typing import Sequence


def _tokenize(text: str) -> list[str]:
    """Return a simple list of lowercase tokens extracted from *text*."""

    tokens: list[str] = []
    current: list[str] = []
    for char in text.lower():
        if char.isalnum():
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current.clear()
    if current:
        tokens.append("".join(current))
    return tokens


def _normalise(vector: list[float]) -> None:
    """Normalise the vector in-place using the Euclidean norm."""

    norm_sq = sum(component * component for component in vector)
    if norm_sq == 0:
        return
    norm = norm_sq ** 0.5
    for index, value in enumerate(vector):
        vector[index] = value / norm


class EmbeddingBackend(ABC):
    """Abstract base class for embedding implementations."""

    identifier: str

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return a list of embeddings for the provided *texts*."""


class HashEmbeddingBackend(EmbeddingBackend):
    """Deterministic embedding based on token hashing.

    The implementation is intentionally simple and entirely based on the
    standard library so that it can run in restricted environments.  While it
    does not provide state-of-the-art semantic similarity, it produces dense
    vectors that behave reasonably well for approximate similarity queries and
    can be used as an offline fallback.
    """

    def __init__(self, dimension: int = 256) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be a positive integer")
        self.dimension = dimension
        self.identifier = f"hash/{dimension}"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimension
            for token in _tokenize(text):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
                for offset in range(0, len(digest), 4):
                    chunk = int.from_bytes(digest[offset : offset + 4], "little", signed=False)
                    index = chunk % self.dimension
                    vector[index] += 1.0
            _normalise(vector)
            vectors.append(vector)
        return vectors


class SentenceTransformerBackend(EmbeddingBackend):
    """Wrapper around :mod:`sentence_transformers` models."""

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.identifier = f"sentence-transformers/{model_name}"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        embeddings = self.model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return [embedding.astype("float32").tolist() for embedding in embeddings]


def load_backend(name: str) -> EmbeddingBackend:
    """Load an embedding backend based on *name*.

    Supported values include::

        hash[:DIM]               Hash-based embeddings (default dimension: 256)
        sentence-transformers/MODEL

    Any other value is treated as a direct :mod:`sentence_transformers` model
    name for convenience.
    """

    if name.startswith("hash"):
        parts = name.split(":", 1)
        dimension = int(parts[1]) if len(parts) == 2 else 256
        return HashEmbeddingBackend(dimension=dimension)
    if name.startswith("sentence-transformers/"):
        model = name.split("/", 1)[1]
    else:
        model = name
    return SentenceTransformerBackend(model)


def load_default_backend(explicit: str | None = None) -> EmbeddingBackend:
    """Return a backend following the configuration and environment."""

    if explicit:
        return load_backend(explicit)
    env_backend = os.getenv("MAIL_SEARCH_EMBEDDING_BACKEND")
    if env_backend:
        try:
            return load_backend(env_backend)
        except Exception:
            pass
    try:
        return SentenceTransformerBackend("all-MiniLM-L6-v2")
    except Exception:
        return HashEmbeddingBackend()


def serialise_vector(vector: Sequence[float]) -> bytes:
    """Serialise a vector of floats into a byte representation."""

    data = array("f", vector)
    return data.tobytes()


def deserialise_vector(blob: bytes) -> list[float]:
    """Reconstruct a float vector previously serialised."""

    data = array("f")
    data.frombytes(blob)
    return data.tolist()


def cosine_similarity(lhs: Sequence[float], rhs: Sequence[float]) -> float:
    """Return the cosine similarity between *lhs* and *rhs*."""

    numerator = 0.0
    lhs_norm_sq = 0.0
    rhs_norm_sq = 0.0
    for left, right in zip(lhs, rhs):
        numerator += left * right
        lhs_norm_sq += left * left
        rhs_norm_sq += right * right
    if lhs_norm_sq == 0.0 or rhs_norm_sq == 0.0:
        return 0.0
    denominator = (lhs_norm_sq ** 0.5) * (rhs_norm_sq ** 0.5)
    return numerator / denominator


def body_preview(text: str, length: int = 160) -> str:
    """Return a compact snippet suitable for CLI display."""

    collapsed = " ".join(text.split())
    if len(collapsed) <= length:
        return collapsed
    return collapsed[: length - 1].rstrip() + "…"

