"""KTSL report engine — data models, Markdown renderer, and HTML renderer.

This package provides the Layer 3 reporting layer for the KTSL KP toolchain.
It consumes data models produced by the Layer 4 orchestration layer
(SessionAuditTracker, PublishGate) and renders them as Markdown or HTML reports.
"""

from __future__ import annotations

from .session_reports import (
    BarrierStateView,
    CouplingStateView,
    EventSummary,
    KnowledgeItemView,
    ModuleStaticCheck,
    PublishReport,
    SessionReport,
    ValidateIssue,
    ValidateReport,
    ViolationEvent,
)

__all__ = [
    "BarrierStateView",
    "CouplingStateView",
    "EventSummary",
    "KnowledgeItemView",
    "ModuleStaticCheck",
    "PublishReport",
    "SessionReport",
    "ValidateIssue",
    "ValidateReport",
    "ViolationEvent",
]
