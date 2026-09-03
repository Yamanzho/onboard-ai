"""Canonical embedding identity and index compatibility checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.exceptions import ValidationError
from app.db.enums import KnowledgeIndexStatus


class EmbeddingDimensionMismatchError(ValidationError):
    """An embedding provider returned a vector outside its declared space."""


class EmbeddingCompatibilityState(StrEnum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE_PROVIDER = "incompatible_provider"
    INCOMPATIBLE_MODEL = "incompatible_model"
    INCOMPATIBLE_DIMENSION = "incompatible_dimension"
    MISSING_INDEX_METADATA = "missing_index_metadata"
    NOT_INDEXED = "not_indexed"


@dataclass(frozen=True, slots=True)
class EmbeddingIdentity:
    provider: str
    model: str
    dimension: int

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower()
        model = self.model.strip()
        if not provider:
            raise ValueError("embedding provider must not be empty")
        if not model:
            raise ValueError("embedding model must not be empty")
        if isinstance(self.dimension, bool) or not isinstance(self.dimension, int):
            raise ValueError("embedding dimension must be a positive integer")
        if self.dimension < 1:
            raise ValueError("embedding dimension must be a positive integer")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", model)


@dataclass(frozen=True, slots=True)
class EmbeddingCompatibility:
    state: EmbeddingCompatibilityState
    active: EmbeddingIdentity
    indexed: EmbeddingIdentity | None

    @property
    def compatible(self) -> bool:
        return self.state is EmbeddingCompatibilityState.COMPATIBLE

    @property
    def reindex_required(self) -> bool:
        return not self.compatible

    @property
    def reason(self) -> str | None:
        reasons = {
            EmbeddingCompatibilityState.INCOMPATIBLE_PROVIDER: "provider_changed",
            EmbeddingCompatibilityState.INCOMPATIBLE_MODEL: "model_changed",
            EmbeddingCompatibilityState.INCOMPATIBLE_DIMENSION: "dimension_changed",
            EmbeddingCompatibilityState.MISSING_INDEX_METADATA: "metadata_missing",
            EmbeddingCompatibilityState.NOT_INDEXED: "not_indexed",
        }
        return reasons.get(self.state)


def embedding_identity_from_provider(
    provider: object,
) -> EmbeddingIdentity:
    """Read the non-secret semantic identity exposed by an embedding provider."""
    return EmbeddingIdentity(
        provider=getattr(provider, "provider_name", ""),
        model=getattr(provider, "model", ""),
        dimension=getattr(provider, "dimension", 0),
    )


def active_embedding_identity() -> EmbeddingIdentity:
    """Resolve the process-global active provider without exposing credentials."""
    from app.services.ai.embeddings import get_embedding_provider

    return embedding_identity_from_provider(get_embedding_provider())


def embedding_compatibility(
    *,
    active: EmbeddingIdentity,
    index_status: str,
    embedding_provider: str | None,
    embedding_model: str | None,
    embedding_dimension: int | None,
) -> EmbeddingCompatibility:
    """Compare active configuration with one version's durable index metadata."""
    if index_status != KnowledgeIndexStatus.INDEXED.value:
        return EmbeddingCompatibility(
            EmbeddingCompatibilityState.NOT_INDEXED,
            active,
            None,
        )
    if (
        embedding_provider is None
        or embedding_model is None
        or embedding_dimension is None
        or not embedding_provider.strip()
        or not embedding_model.strip()
    ):
        return EmbeddingCompatibility(
            EmbeddingCompatibilityState.MISSING_INDEX_METADATA,
            active,
            None,
        )
    try:
        indexed = EmbeddingIdentity(
            provider=embedding_provider,
            model=embedding_model,
            dimension=embedding_dimension,
        )
    except (TypeError, ValueError):
        return EmbeddingCompatibility(
            EmbeddingCompatibilityState.MISSING_INDEX_METADATA,
            active,
            None,
        )
    if active.provider != indexed.provider:
        state = EmbeddingCompatibilityState.INCOMPATIBLE_PROVIDER
    elif active.model != indexed.model:
        state = EmbeddingCompatibilityState.INCOMPATIBLE_MODEL
    elif active.dimension != indexed.dimension:
        state = EmbeddingCompatibilityState.INCOMPATIBLE_DIMENSION
    else:
        state = EmbeddingCompatibilityState.COMPATIBLE
    return EmbeddingCompatibility(state, active, indexed)


def version_embedding_compatibility(
    version: object,
    *,
    active: EmbeddingIdentity,
) -> EmbeddingCompatibility:
    """Compare a loaded version without coupling the helper to its ORM class."""
    return embedding_compatibility(
        active=active,
        index_status=str(getattr(version, "index_status", "")),
        embedding_provider=getattr(version, "embedding_provider", None),
        embedding_model=getattr(version, "embedding_model", None),
        embedding_dimension=getattr(version, "embedding_dimension", None),
    )
