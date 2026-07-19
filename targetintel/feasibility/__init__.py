"""Immutable, descriptive target-feasibility contracts for v0.4.0.

This package deliberately has no dependency on scoring, ranking, role,
LLM, or modality-evaluation modules.
"""

from .models import (
    AVAILABILITY_STATES,
    FEASIBILITY_DIMENSIONS,
    TARGET_IDENTIFIER_TYPES,
    THERAPEUTIC_MODALITIES,
    FeasibilityObservation,
    TargetFeasibilityProfile,
    TargetFeasibilityRequest,
)
from .validation import (
    ValidationError,
    ValidationIssue,
    require_valid_observation,
    require_valid_profile,
    require_valid_request,
    validate_observation,
    validate_profile,
    validate_request,
)
from .opentargets_models import OpenTargetsFetchRequest, OpenTargetsFetchResult, OpenTargetsQueryPlan, OpenTargetsCoverageReport, OpenTargetsTargetRecord, OpenTargetsTargetResolution, OpenTargetsTransportResponse
from .opentargets_ingestion import fetch_opentargets

__all__ = [
    "AVAILABILITY_STATES", "FEASIBILITY_DIMENSIONS", "TARGET_IDENTIFIER_TYPES",
    "THERAPEUTIC_MODALITIES", "FeasibilityObservation", "TargetFeasibilityProfile",
    "TargetFeasibilityRequest", "ValidationError", "ValidationIssue",
    "require_valid_observation", "require_valid_profile", "require_valid_request",
    "validate_observation", "validate_profile", "validate_request",
    "OpenTargetsFetchRequest", "OpenTargetsFetchResult", "OpenTargetsQueryPlan", "OpenTargetsCoverageReport", "OpenTargetsTargetRecord", "OpenTargetsTargetResolution", "OpenTargetsTransportResponse", "fetch_opentargets",
]
