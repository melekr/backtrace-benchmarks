"""Minimal YAML subset loader used when PyYAML is not installed.

Supports what schema/metrics.yml and thresholds.yml use: block mappings, block
sequences, flow mappings ``{a: 1, b: "x"}``, flow sequences ``["a", 'b']``,
comments, single/double quoted strings and plain scalars (int, float, bool,
null, string). Anchors, tags, multi-line scalars and multi-document streams are
not supported and raise ``YamlMiniError``.
"""
from __future__ import annotations

import re
from typing import Any, List, Tuple


class YamlMiniError(ValueError):
    pass


_INT_RE = re.compile(r"^[-+]?(0|[1-9][0-9_]*)$")
_FLOAT_RE = re.compile(r"^[-+]?(\d[\d_]*)?\.\d[\d_]*([eE][-+]?\d+)?$|^[-+]?\d[\d_]*[eE][-+]?\d+$")


def _strip_comment(line: str) -> str:
    out = []
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        else:
            if ch in ("'", '"'):
                quote = ch
                out.append(ch)
            elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
                break
            else:
                out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _scalar(tok: str) -> Any:
    t = tok.strip()
    if t == "" or t in ("~", "null", "Null", "NULL"):
        return None
    if t in ("true", "True", "TRUE"):
        return True
    if t in ("false", "False", "FALSE"):
        return False
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        body = t[1:-1]
        if t[0] == '"':
            body = bytes(body, "utf-8").decode("unicode_escape")
        else:
            body = body.replace("''", "'")
        return body
    if _INT_RE.match(t):
        return int(t.replace("_", ""))
    if _FLOAT_RE.match(t):
        return float(t.replace("_", ""))
    return t


class _Flow:
    """Parser for flow collections and inline scalars."""

    def __init__(self, text: str):
        self.s = text
        self.i = 0

    def _ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def parse_value(self) -> Any:
        self._ws()
        if self.i >= len(self.s):
            return None
        ch = self.s[self.i]
        if ch == "{":
            return self._mapping()
        if ch == "[":
            return self._sequence()
        return _scalar(self._plain(stop=",]}"))

    def _quoted(self) -> str:
        q = self.s[self.i]
        j = self.i + 1
        while j < len(self.s):
            if self.s[j] == "\\" and q == '"':
                j += 2
                continue
            if self.s[j] == q:
                if q == "'" and j + 1 < len(self.s) and self.s[j + 1] == "'":
                    j += 2
                    continue
                break
            j += 1
        if j >= len(self.s):
            raise YamlMiniError(f"unterminated quoted string: {self.s}")
        tok = self.s[self.i : j + 1]
        self.i = j + 1
        return tok

    def _plain(self, stop: str) -> str:
        self._ws()
        if self.i < len(self.s) and self.s[self.i] in "'\"":
            return self._quoted()
        j = self.i
        while j < len(self.s) and self.s[j] not in stop:
            if self.s[j] == ":" and (j + 1 == len(self.s) or self.s[j + 1] in " \t" or self.s[j + 1] in stop):
                break
            j += 1
        tok = self.s[self.i : j]
        self.i = j
        return tok

    def _mapping(self) -> dict:
        assert self.s[self.i] == "{"
        self.i += 1
        out: dict = {}
        while True:
            self._ws()
            if self.i >= len(self.s):
                raise YamlMiniError(f"unterminated flow mapping: {self.s}")
            if self.s[self.i] == "}":
                self.i += 1
                return out
            key = _scalar(self._plain(stop=":,}"))
            self._ws()
            if self.i < len(self.s) and self.s[self.i] == ":":
                self.i += 1
                val = self.parse_value()
            else:
                val = None
            out[key] = val
            self._ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1

    def _sequence(self) -> list:
        assert self.s[self.i] == "["
        self.i += 1
        out: list = []
        while True:
            self._ws()
            if self.i >= len(self.s):
                raise YamlMiniError(f"unterminated flow sequence: {self.s}")
            if self.s[self.i] == "]":
                self.i += 1
                return out
            out.append(self.parse_value())
            self._ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1


def _inline(text: str) -> Any:
    p = _Flow(text)
    v = p.parse_value()
    p._ws()
    if p.i != len(p.s):
        raise YamlMiniError(f"trailing characters in value: {text!r}")
    return v


def _split_key(line: str) -> Tuple[str, str] | None:
    """Return (key, rest) when ``line`` is ``key: rest`` / ``key:``, else None."""
    if line.startswith(("'", '"')):
        p = _Flow(line)
        key_tok = p._quoted()
        rest = line[p.i :]
        if rest.startswith(":") and (len(rest) == 1 or rest[1] in " \t"):
            return str(_scalar(key_tok)), rest[1:].strip()
        return None
    if line.startswith(("[", "{")):
        return None
    m = re.match(r"^([^:\s][^:]*?)\s*:(\s+(.*))?$", line)
    if not m:
        return None
    return m.group(1), (m.group(3) or "").strip()


class _Parser:
    def __init__(self, lines: List[Tuple[int, str]]):
        self.lines = lines  # (indent, text)
        self.pos = 0

    def parse_block(self, indent: int) -> Any:
        if self.pos >= len(self.lines):
            return None
        ind, text = self.lines[self.pos]
        if ind != indent:
            raise YamlMiniError(f"bad indentation at line {self.pos + 1}: {text!r}")
        if text.startswith("- ") or text == "-":
            return self._sequence(indent)
        return self._mapping(indent)

    def _peek_indent(self) -> int:
        return self.lines[self.pos][0] if self.pos < len(self.lines) else -1

    def _mapping(self, indent: int) -> dict:
        out: dict = {}
        while self.pos < len(self.lines):
            ind, text = self.lines[self.pos]
            if ind < indent:
                break
            if ind > indent:
                raise YamlMiniError(f"unexpected indentation at line {self.pos + 1}: {text!r}")
            if text.startswith("- "):
                break
            kv = _split_key(text)
            if kv is None:
                raise YamlMiniError(f"expected 'key: value' at line {self.pos + 1}: {text!r}")
            key, rest = kv
            self.pos += 1
            if rest == "":
                nxt = self._peek_indent()
                if nxt > indent:
                    out[key] = self.parse_block(nxt)
                elif nxt == indent and self.pos < len(self.lines) and self.lines[self.pos][1].startswith("- "):
                    out[key] = self._sequence(indent)
                else:
                    out[key] = None
            else:
                out[key] = _inline(rest)
        return out

    def _sequence(self, indent: int) -> list:
        out: list = []
        while self.pos < len(self.lines):
            ind, text = self.lines[self.pos]
            if ind != indent or not (text.startswith("- ") or text == "-"):
                break
            rest = text[1:].strip()
            if rest == "":
                self.pos += 1
                nxt = self._peek_indent()
                out.append(self.parse_block(nxt) if nxt > indent else None)
                continue
            kv = _split_key(rest)
            if kv is not None and not rest.startswith(("[", "{", "'", '"')):
                # mapping whose first entry sits on the dash line; re-indent it
                child_indent = indent + (len(text) - len(text[1:].lstrip()))
                self.lines[self.pos] = (child_indent, rest)
                out.append(self._mapping(child_indent))
            else:
                self.pos += 1
                out.append(_inline(rest))
        return out


def loads(text: str) -> Any:
    lines: List[Tuple[int, str]] = []
    for raw in text.splitlines():
        if raw.startswith("---") or raw.startswith("%"):
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlMiniError("tabs are not allowed for indentation")
        stripped = _strip_comment(raw)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.strip()))
    if not lines:
        return None
    p = _Parser(lines)
    val = p.parse_block(lines[0][0])
    if p.pos != len(lines):
        raise YamlMiniError(f"could not parse line {p.pos + 1}: {lines[p.pos][1]!r}")
    return val


def load(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return loads(fh.read())
