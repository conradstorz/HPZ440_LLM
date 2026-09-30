"""Collapse an HTML email body to readable text. Copied from GTE src/gte/connectors/gmail/htmltext.py."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_SKIP_TAGS = {"script", "style", "head"}
_BLOCK_TAGS = {"p", "div", "br", "tr", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6",
               "ul", "ol", "section", "article", "header", "footer", "blockquote"}
_WS_RUN = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n\s*\n\s*")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data.replace("\n", " "))

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    if not html or not html.strip():
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    lines = [_WS_RUN.sub(" ", line).strip() for line in parser.text().splitlines()]
    text = "\n".join(line for line in lines if line)
    return _BLANK_LINES.sub("\n", text).strip()
