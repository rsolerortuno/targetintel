"""Read-only, explicitly filtered evidence-card reporting helpers.

This module deliberately does not aggregate evidence into a target-level
scientific conclusion.  It turns stored, finalized observations into display
data while retaining every eligible observation as a separate record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .independence import EvidenceIndependenceGrouper
from .models import EvidenceItem


NORMAL_CARD_STATUSES = frozenset({"citation_verified", "manually_curated"})
AUDIT_CARD_STATUSES = frozenset({"citation_unverified", "rejected"})
UNVERIFIED_EVIDENCE_LABEL = "Unverified evidence"


@dataclass(frozen=True)
class EvidenceCardMetrics:
    """Explicit record- and provenance-level counts for one target."""

    record_count: int
    publication_count: int
    experiment_count: int
    patient_cohort_count: int
    independent_family_count: int
    ineligible_record_count: int


@dataclass(frozen=True)
class EvidenceCard:
    """Verified, stored observations and their non-interpretive metrics."""

    target_symbol: str
    items: tuple[EvidenceItem, ...]
    metrics: EvidenceCardMetrics


@dataclass(frozen=True)
class AuditEvidenceItem:
    """A finalized non-normal-report record with its mandatory visible label."""

    item: EvidenceItem
    label: str = UNVERIFIED_EVIDENCE_LABEL


def _known_ids(items: Sequence[EvidenceItem], field: str) -> set[str]:
    return {
        value.strip()
        for item in items
        if isinstance((value := getattr(item, field)), str) and value.strip()
    }


class EvidenceReportDecorator:
    """Produce evidence-card data without modifying stored evidence."""

    def normal_card_items(self, items: Sequence[EvidenceItem]) -> list[EvidenceItem]:
        """Return only finalized records eligible for normal evidence cards."""
        return [item for item in items if item.validation_status in NORMAL_CARD_STATUSES]

    def audit_card_items(self, items: Sequence[EvidenceItem]) -> list[AuditEvidenceItem]:
        """Return finalized audit records with a visible unverified label."""
        return [
            AuditEvidenceItem(item)
            for item in items
            if item.validation_status in AUDIT_CARD_STATUSES
        ]

    def metrics(self, items: Sequence[EvidenceItem]) -> EvidenceCardMetrics:
        """Calculate counts without selecting a representative family member."""
        grouper = EvidenceIndependenceGrouper()
        return EvidenceCardMetrics(
            record_count=len(items),
            publication_count=len(_known_ids(items, "publication_id")),
            experiment_count=len(_known_ids(items, "experiment_id")),
            patient_cohort_count=len(_known_ids(items, "patient_cohort_id")),
            # Composite records add no family: only non-composite root-family
            # memberships are counted by the grouper.
            independent_family_count=len(grouper.independent_family_ids(items)),
            ineligible_record_count=sum(not item.independence_eligible for item in items),
        )

    def make_card(self, target_symbol: str, items: Sequence[EvidenceItem]) -> EvidenceCard | None:
        """Make a normal card, or no card when no verified observations exist."""
        normal_items = tuple(self.normal_card_items(items))
        if not normal_items:
            return None
        return EvidenceCard(target_symbol, normal_items, self.metrics(normal_items))
