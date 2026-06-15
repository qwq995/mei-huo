from __future__ import annotations

from enum import Enum


class DocumentRole(str, Enum):
    bid_markdown = "bid_markdown"
    template = "template"
    support = "support"


class ParseStatus(str, Enum):
    uploaded = "uploaded"
    normalized = "normalized"
    split = "split"
    failed = "failed"


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    needs_repair = "needs_repair"
    passed = "passed"
    failed = "failed"


class RunStatus(str, Enum):
    created = "created"
    running = "running"
    partial_failed = "partial_failed"
    completed = "completed"
    failed = "failed"

