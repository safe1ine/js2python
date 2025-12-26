"""
Command-line interface for converting ES5 JavaScript files to Python.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from emitter import EmitOptions, emit_module
from frontend import run_frontend
from transformer import TransformError, transform_program


def _format_location(line: int | None, column: int | None) -> str:
    if line is None:
        return ""
    if column is None:
        return f":{line}"
    return f":{line}:{column}"


def _print_diagnostics(messages: List[str]) -> None:
    if not messages:
        return
    for message in messages:
        sys.stderr.write(message + "\n")


def _collect_diagnostics(args, frontend_result, transform_result, runtime_notice: str | None):
    diagnostics: List[str] = []
    source_name = frontend_result.parse.source_name

    for error in frontend_result.parse.errors:
        loc = _format_location(error.line, error.column)
        diagnostics.append(f"ERROR {source_name}{loc}: {error.description}")

    analysis = frontend_result.analysis
    if analysis:
        for issue in analysis.issues:
            loc = _format_location(issue.loc.line, issue.loc.column)
            diagnostics.append(f"WARNING {source_name}{loc}: {issue.message}")

    if transform_result.diagnostics:
        for message in transform_result.diagnostics:
            diagnostics.append(f"INFO {source_name}: {message}")

    if runtime_notice:
        diagnostics.append(f"INFO {source_name}: {runtime_notice}")

    return diagnostics


def convert_command(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        sys.stderr.write(f"ERROR: Input file not found: {input_path}\n")
        return 1

    try:
        source = input_path.read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"ERROR: Failed to read {input_path}: {exc}\n")
        return 1

    source_type = "module" if getattr(args, "module", False) else "script"

    frontend_result = run_frontend(
        source,
        source_name=str(input_path),
        tolerant=not args.strict,
        analyze=True,
        source_type=source_type,
    )

    if frontend_result.parse.ast is None:
        sys.stderr.write("ERROR: Parsing failed; no AST produced.\n")
        for error in frontend_result.parse.errors:
            loc = _format_location(error.line, error.column)
            sys.stderr.write(f"  {error.description}{loc}\n")
        return 1

    try:
        transform_result = transform_program(
            frontend_result.parse.ast, source_name=str(input_path)
        )
    except TransformError as exc:
        sys.stderr.write(f"ERROR: Transformation failed: {exc}\n")
        return 1

    runtime_notice = None
    emit_options = EmitOptions()
    if args.runtime != "skip":
        runtime_notice = "Runtime bundling is not implemented yet; skipping."

    emit_result = emit_module(transform_result.module, emit_options)

    output_path = Path(args.out) if args.out else input_path.with_suffix(".py")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(emit_result.source, encoding="utf-8")

    diagnostics = _collect_diagnostics(args, frontend_result, transform_result, runtime_notice)
    _print_diagnostics(diagnostics)

    has_errors = bool(frontend_result.parse.errors)
    if args.strict and (frontend_result.analysis and frontend_result.analysis.issues):
        has_errors = True
    if args.strict and transform_result.diagnostics:
        has_errors = True

    return 1 if has_errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="js2python", description="Convert ES5 JavaScript to Python")
    subparsers = parser.add_subparsers(dest="command")

    convert_parser = subparsers.add_parser("convert", help="Convert a single JS file to Python")
    convert_parser.add_argument("input", help="Path to the ES5 JavaScript file")
    convert_parser.add_argument(
        "--out",
        help="Output Python file path (defaults to same directory with .py extension)",
    )
    convert_parser.add_argument(
        "--runtime",
        choices=["include", "skip"],
        default="skip",
        help="Include JS compatibility runtime (not yet implemented)",
    )
    convert_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors and disable tolerant parsing.",
    )
    convert_parser.add_argument(
        "--module",
        action="store_true",
        help="Parse the input as an ES module (enables import/export syntax).",
    )
    convert_parser.set_defaults(func=convert_command)

    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
