"""
JavaScript parsing utilities built on top of the Python `esprima` port.

The module exposes `parse_js`, which returns the JSON-compatible AST along with
metadata describing the parse run. Consumers can decide whether to allow
recoverable parsing via the `tolerant` flag, and choose between script / module
source types to unlock ES6+ syntax such as import/export.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, List, Optional

import esprima


@dataclass(frozen=True)
class ParseError:
    """Represents a recoverable parsing issue detected by esprima."""

    description: str
    line: Optional[int]
    column: Optional[int]


@dataclass(frozen=True)
class ParseResult:
    """Aggregate of the output AST plus metadata about the parse run."""

    ast: Any
    errors: List[ParseError]
    source_hash: str
    source_name: str

    def to_json(self) -> str:
        """Serialise the parse result to JSON for debugging or caching."""
        payload = {
            "ast": self.ast,
            "errors": [error.__dict__ for error in self.errors],
            "source_hash": self.source_hash,
            "source_name": self.source_name,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


def _hash_source(source: str) -> str:
    """Create a deterministic hash for cache keying."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def parse_js(
    source: str,
    *,
    source_name: str = "<input>",
    tolerant: bool = True,
    source_type: str = "script",
) -> ParseResult:
    """
    Parse JavaScript source text into an esprima AST.

    Args:
        source: Raw JavaScript source code.
        source_name: Optional label used for diagnostics (defaults to `<input>`).
        tolerant: When True, esprima performs error recovery instead of raising.
        source_type: `"script"` or `"module"`; modules enable ES6 import/export.

    Returns:
        ParseResult containing the AST, any recoverable errors, and metadata.

    Raises:
        esprima.Error: If parsing fails and `tolerant` is False.
    """
    options = dict(loc=True, range=True, comment=True, tolerant=tolerant)
    parser = esprima.parseModule if source_type == "module" else esprima.parseScript
    try:
        ast = parser(source, **options)
    except esprima.Error:
        # Re-raise when caller opted into strict error handling.
        if not tolerant:
            raise
        # When tolerant parsing fails hard, convert exception into diagnostics.
        errors = [
            ParseError(description="Failed to parse source.", line=None, column=None)
        ]
        return ParseResult(
            ast=None,
            errors=errors,
            source_hash=_hash_source(source),
            source_name=source_name,
        )

    errors: List[ParseError] = []
    raw_ast = ast.toDict() if hasattr(ast, "toDict") else ast

    if tolerant and isinstance(raw_ast, dict):
        # Collect recoverable errors reported by esprima in tolerant mode.
        for error in raw_ast.get("errors", []):
            errors.append(
                ParseError(
                    description=error.get("description"),
                    line=error.get("lineNumber"),
                    column=error.get("column"),
                )
            )

    return ParseResult(
        ast=raw_ast,
        errors=errors,
        source_hash=_hash_source(source),
        source_name=source_name,
    )


def parse_es5(
    source: str,
    *,
    source_name: str = "<input>",
    tolerant: bool = True,
) -> ParseResult:
    """
    Backwards compatible wrapper for legacy callers expecting ES5-only parsing.
    """
    return parse_js(source, source_name=source_name, tolerant=tolerant, source_type="script")


__all__ = ["ParseResult", "ParseError", "parse_js", "parse_es5"]
