from __future__ import annotations

from pydantic import BaseModel


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: str = "error"


class ValidationResult(BaseModel):
    passed: bool
    issues: list[ValidationIssue] = []

