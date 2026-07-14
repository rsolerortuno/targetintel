"""Typed, dependency-free contracts for the optional evidence layer."""

from .models import EvidenceItem, ProvenanceStep, RetrievalAttempt
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
    "SemanticValidationContext",
    "ValidationError",
    "ValidationIssue",
    "require_semantically_valid",
    "validate_semantic",
]
