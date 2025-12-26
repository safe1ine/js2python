"""
Front-end integration utilities stitching together parsing and scope analysis.

The `run_frontend` function accepts raw JavaScript source, invokes the parser to
obtain an AST, optionally runs scope/binding analysis, and persists cached
artefacts when requested. Downstream phases can consume the aggregated result to
drive transformations or diagnostics without reimplementing these steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from analyzer import AnalysisResult, analyze_bindings
from parser import ParseResult, parse_js


@dataclass(frozen=True)
class FrontEndResult:
    """Combined output from the parsing and analysis pipeline."""

    parse: ParseResult
    analysis: Optional[AnalysisResult]

    @property
    def has_ast(self) -> bool:
        return self.parse.ast is not None

    @property
    def diagnostics(self):
        """Aggregate diagnostics from parse recovery and semantic issues."""
        diagnostics = list(self.parse.errors)
        if self.analysis:
            diagnostics.extend(self.analysis.issues)
        return diagnostics


def run_frontend(
    source: str,
    *,
    source_name: str = "<input>",
    tolerant: bool = True,
    analyze: bool = True,
    source_type: str = "script",
    cache_dir: Optional[Union[str, Path]] = None,
) -> FrontEndResult:
    """
    Execute parsing and optional scope analysis for JavaScript input.

    Args:
        source: Raw JavaScript source text.
        source_name: Identifier used in diagnostics, e.g. file path.
        tolerant: Forwarded to parser; when True esprima attempts recovery.
        analyze: Toggle to disable semantic analysis for performance/testing.
        source_type: `"script"` or `"module"` to control parsing of import/export.
        cache_dir: Optional directory to write parse artefacts (`None` disables).

    Returns:
        FrontEndResult containing the parser output and optional analysis result.
    """
    parse_result = parse_js(
        source,
        source_name=source_name,
        tolerant=tolerant,
        source_type=source_type,
    )

    analysis_result: Optional[AnalysisResult] = None
    if analyze and parse_result.ast is not None:
        analysis_result = analyze_bindings(parse_result.ast, source_name=source_name)

    if cache_dir is not None:
        _persist_parse(cache_dir, parse_result)

    return FrontEndResult(parse=parse_result, analysis=analysis_result)


def _persist_parse(cache_dir: Union[str, Path], parse_result: ParseResult) -> None:
    """Store the raw parse output to disk for reuse in subsequent runs."""
    path = Path(cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    cache_file = path / f"{parse_result.source_hash}.json"
    cache_file.write_text(parse_result.to_json(), encoding="utf-8")


__all__ = ["FrontEndResult", "run_frontend"]
