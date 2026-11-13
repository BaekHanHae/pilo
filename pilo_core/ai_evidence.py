"""Evidence integrity verification primitives for PILO AI attempts.

This module verifies bytes supplied by a trusted Core-owned reader.
It does not authorize access, establish provenance, or validate worktree effects.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable


class EvidenceRejected(ValueError):
    """Evidence is missing, oversized, or does not match its digest."""


_DIGEST = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class VerifiedEvidence:
    reference: str
    sha256: str
    size_bytes: int


def verify_evidence(
    reference: str,
    expected_sha256: str,
    reader: Callable[[str], bytes],
    *,
    max_bytes: int = 8 * 1024 * 1024,
) -> VerifiedEvidence:
    """Read and hash evidence using a Core-controlled, authorized reader.

    Never pass a reader supplied by an untrusted adapter. The caller must
    separately validate the reference's provenance and project ownership.
    """
    if not isinstance(reference, str) or not reference.strip():
        raise EvidenceRejected("Missing evidence reference")
    if not isinstance(expected_sha256, str) or not _DIGEST.fullmatch(expected_sha256):
        raise EvidenceRejected("Invalid expected SHA-256")
    if type(max_bytes) is not int or max_bytes <= 0:
        raise EvidenceRejected("Invalid evidence size limit")
    data = reader(reference)
    if not isinstance(data, bytes):
        raise EvidenceRejected("Evidence reader must return bytes")
    if len(data) > max_bytes:
        raise EvidenceRejected("Evidence exceeds maximum size")
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256:
        raise EvidenceRejected("Evidence digest mismatch")
    return VerifiedEvidence(reference=reference, sha256=actual, size_bytes=len(data))
