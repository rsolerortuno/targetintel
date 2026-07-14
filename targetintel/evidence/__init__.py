"""Typed contracts and optional immutable storage for the evidence layer."""

from .models import EvidenceItem, ProvenanceStep, RetrievalAttempt
from .store import EvidenceStore, HashCollisionError, ImmutableEvidenceError, InsertResult
from .validation import (
    SemanticValidationContext,
    ValidationError,
    ValidationIssue,
    require_semantically_valid,
    validate_semantic,
)

__all__ = [
    "EvidenceItem",
    "ProvenanceStep",
    "RetrievalAttempt",
    "EvidenceStore",
    "HashCollisionError",
    "ImmutableEvidenceError",
    "InsertResult",
    "SemanticValidationContext",
    "ValidationError",
    "ValidationIssue",
    "require_semantically_valid",
    "validate_semantic",
]
