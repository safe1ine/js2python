"""Interfaces for parsing JavaScript source code."""

from .es5_parser import ParseError, ParseResult, parse_es5, parse_js

__all__ = ["ParseError", "ParseResult", "parse_es5", "parse_js"]
