"""Small tolerant HTML DOM and the CSS subset used by the Maps data file.

Google Maps markup is large and often malformed by the time it is serialized. The parser only
needs tags, attributes and text to apply the owner-editable selectors; it deliberately does not
try to be a browser.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                  "param", "source", "track", "wbr"})
SKIP_TEXT = frozenset({"script", "style"})
AUTO_CLOSE = {"p": {"p"}, "li": {"li"}, "tr": {"tr"}, "td": {"td", "th"}, "th": {"td", "th"},
              "option": {"option"}}


class SelectionError(ValueError):
    """A selector in the data file is not in the supported subset."""


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict | None = None, parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []
        self.parent = parent

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self.tag} {self.attrs}>"

    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name.lower(), default)

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._parts())).strip()

    def _parts(self):
        for child in self.children:
            yield child if isinstance(child, str) else child.text

    def descendants(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.descendants()

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def select(self, selector: str) -> list["Node"]:
        parts = compile_selector(selector)
        current = [self]
        for part in parts:
            found = []
            seen = set()
            for node in current:
                for candidate in node.descendants():
                    if id(candidate) in seen:
                        continue
                    if matches(candidate, part):
                        seen.add(id(candidate))
                        found.append(candidate)
            current = found
        return current

    def first(self, selector: str) -> "Node | None":
        found = self.select(selector)
        return found[0] if found else None


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack = [self.root]
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        closes = AUTO_CLOSE.get(tag)
        if closes and self.stack[-1].tag in closes:
            self.stack.pop()
        parent = self.stack[-1]
        node = Node(tag, {name.lower(): (value or "") for name, value in attrs}, parent)
        parent.children.append(node)
        if tag in SKIP_TEXT:
            self.skip += 1
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        parent = self.stack[-1]
        parent.children.append(Node(tag, {name.lower(): (value or "") for name, value in attrs},
                                    parent))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP_TEXT and self.skip:
            self.skip -= 1
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        if self.skip or not data.strip():
            return
        self.stack[-1].children.append(data)


def parse(html: str) -> Node:
    builder = _Builder()
    builder.feed(html or "")
    builder.close()
    return builder.root


def _split_selector(selector: str) -> list[str]:
    """Split on descendant spaces, never inside quotes or an attribute block."""
    tokens, current, quote, depth = [], [], "", 0
    for char in selector:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char == "[":
            depth += 1
            current.append(char)
        elif char == "]":
            depth = max(0, depth - 1)
            current.append(char)
        elif char.isspace() and depth == 0:
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


ATTR = re.compile(
    r"\[\s*(?P<attr>[a-zA-Z_:][-\w:.]*)\s*"
    r"(?:(?P<op>\^=|\$=|\*=|=)\s*(?P<value>\"[^\"]*\"|'[^']*'|[^\]\s]+))?\s*\]"
)
TAG = re.compile(r"[a-zA-Z][\w-]*")


def compile_selector(selector: str) -> tuple[dict, ...]:
    parts = []
    for raw in _split_selector(selector or ""):
        match = TAG.match(raw)
        tag = match.group(0).lower() if match else ""
        rest = raw[match.end():] if match else raw
        attributes = []
        while rest:
            attribute = ATTR.match(rest)
            if not attribute:
                raise SelectionError(f"unsupported selector {selector!r}")
            value = attribute.group("value")
            if value and len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            attributes.append({"name": attribute.group("attr").lower(),
                               "op": attribute.group("op") or "",
                               "value": value or ""})
            rest = rest[attribute.end():]
        if not tag and not attributes:
            raise SelectionError("empty selector")
        parts.append({"tag": tag, "attributes": attributes})
    if not parts:
        raise SelectionError("empty selector")
    return tuple(parts)


def matches(node: Node, part: dict) -> bool:
    if part["tag"] and node.tag != part["tag"]:
        return False
    for attribute in part["attributes"]:
        name = attribute["name"]
        if name not in node.attrs:
            return False
        value = node.attrs[name].casefold()
        wanted = attribute["value"].casefold()
        if attribute["op"] == "=" and value != wanted:
            return False
        if attribute["op"] == "^=" and not value.startswith(wanted):
            return False
        if attribute["op"] == "$=" and not value.endswith(wanted):
            return False
        if attribute["op"] == "*=" and wanted not in value:
            return False
    return True


def text_of(node: Node | None) -> str:
    return node.text if node is not None else ""
