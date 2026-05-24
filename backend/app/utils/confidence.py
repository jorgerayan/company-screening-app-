"""
Confidence and evidence utilities.
Shared helpers used across LLM modules and the normalizer to produce
consistent confidence levels and evidence type labels.
"""
from typing import List

_CONFIDENCE_ORDER = {"high": 3, "medium": 2, "low": 1}
_EVIDENCE_ORDER = {"verified_fact": 3, "reasonable_inference": 2, "unverifiable": 1}


def merge_confidence(levels: List[str]) -> str:
    """
    Return the minimum (most conservative) confidence level from a list.
    If all modules agree on 'high', returns 'high'.
    A single 'low' drags the merged value down.
    """
    valid = [lv for lv in levels if lv in _CONFIDENCE_ORDER]
    if not valid:
        return "low"
    return min(valid, key=lambda x: _CONFIDENCE_ORDER[x])


def data_coverage_to_confidence(fields_found: int, fields_total: int) -> str:
    """Convert a coverage ratio to a confidence level."""
    if fields_total == 0:
        return "low"
    ratio = fields_found / fields_total
    if ratio >= 0.7:
        return "high"
    if ratio >= 0.4:
        return "medium"
    return "low"


def is_stronger_evidence(a: str, b: str) -> bool:
    """Return True if evidence type `a` is stronger than `b`."""
    return _EVIDENCE_ORDER.get(a, 0) > _EVIDENCE_ORDER.get(b, 0)
