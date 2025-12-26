"""Semantic analysis helpers for ES5/ES6 JavaScript."""

from .scope_tracker import (
    AnalysisIssue,
    AnalysisResult,
    Binding,
    BindingKind,
    Scope,
    ScopeType,
    analyze_bindings,
)

__all__ = [
    "AnalysisIssue",
    "AnalysisResult",
    "Binding",
    "BindingKind",
    "Scope",
    "ScopeType",
    "analyze_bindings",
]
