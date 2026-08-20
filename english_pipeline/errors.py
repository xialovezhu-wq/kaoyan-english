"""Typed errors used by the portable English pipeline."""

from __future__ import annotations


class PipelineError(RuntimeError):
    """Base class for expected, user-facing pipeline failures."""


class ValidationError(PipelineError):
    """Input, schema, or state validation failed."""


class SourceHashMismatch(ValidationError):
    """A source object or sentence did not match its declared hash."""


class IdempotencyConflict(PipelineError):
    """An idempotency key was reused with different semantic content."""
