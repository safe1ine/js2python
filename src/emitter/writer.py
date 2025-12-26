"""
Serialize Python AST modules to source code, ready for writing to disk.

The emitter currently relies on the stdlib `ast.unparse` API (Python 3.11+) to
produce source, and exposes hooks for appending runtime snippets or post-format
steps. Formatting integrations (e.g. black) can be layered later by invoking
the returned command list prior to writing to disk.
"""

from __future__ import annotations

import ast
import io
from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class EmitOptions:
    include_runtime: bool = False
    runtime_snippets: Optional[Iterable[str]] = None
    trailing_newline: bool = True


@dataclass(frozen=True)
class EmitResult:
    source: str
    runtime: Optional[str]


def emit_module(module: ast.Module, options: Optional[EmitOptions] = None) -> EmitResult:
    """
    Render the given AST module to Python source text.
    """
    options = options or EmitOptions()

    buffer = io.StringIO()
    buffer.write(ast.unparse(module))
    if options.trailing_newline:
        buffer.write("\n")

    runtime_text: Optional[str] = None
    if options.include_runtime and options.runtime_snippets:
        runtime_lines: List[str] = []
        for snippet in options.runtime_snippets:
            runtime_lines.append(snippet.rstrip())
        runtime_text = "\n".join(runtime_lines) + ("\n" if runtime_lines else "")

    source = buffer.getvalue()
    if runtime_text:
        source = source + "\n" + runtime_text

    return EmitResult(source=source, runtime=runtime_text)


__all__ = ["EmitOptions", "EmitResult", "emit_module"]
