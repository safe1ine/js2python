"""Interfaces for parsing ES5 JavaScript source code."""

from .es5_parser import ParseError, ParseResult, parse_es5

__all__ = ["ParseError", "ParseResult", "parse_es5"]
