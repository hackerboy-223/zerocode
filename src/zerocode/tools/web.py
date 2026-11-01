from __future__ import annotations

import ipaddress
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse

import httpx

from ..errors import ToolError
from ..tokens import truncate_text
from .base import Tool, ToolContext, ToolRegistry

MAX_BYTES = 2_000_000
USER_AGENT = "zerocode/0.1 (+https://github.com/hackerboy-223/zerocode)"
BLOCK_TAGS = {
    "article",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS and self.skip:
            self.skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self._in_title:
            self.title += data
        else:
            self.parts.append(data)


class _DuckParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._link: dict[str, str] | None = None
        self._snippet: dict[str, str] | None = None
        self._capture: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        values = dict(attrs)
        classes = str(values.get("class") or "").split()
        href = values.get("href") or ""
        if "result__a" in classes:
            self._link = {"href": href, "title": ""}
            self._capture = self._link
        elif "result__snippet" in classes:
            self._snippet = {"text": ""}
            self._capture = self._snippet

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            key = "title" if "title" in self._capture else "text"
            self._capture[key] += data

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._capture is None:
            return
        if self._capture is self._link:
            if self._link is not None:
                self.results.append(
                    {
                        "title": " ".join(self._link["title"].split()),
                        "url": _clean_ddg_url(self._link["href"]),
                        "snippet": "",
                    }
                )
            self._link = None
        elif self._capture is self._snippet:
            if self.results and self._snippet is not None:
                self.results[-1]["snippet"] = " ".join(self._snippet["text"].split())
            self._snippet = None
        self._capture = None


def _clean_ddg_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return unquote(target[0])
    return href


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ToolError("Seules les URL HTTP(S) sont autorisees.")
    if not parsed.hostname:
        raise ToolError("URL invalide: hote manquant.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port)
    except OSError as exc:
        raise ToolError(f"Impossible de resoudre {parsed.hostname}: {exc}") from exc
    for item in addresses:
        address = ipaddress.ip_address(item[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
        ):
            raise ToolError("Les adresses locales et privees sont refusees.")
    return url


def _request(url: str, *, timeout: float = 20.0) -> tuple[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,*/*"}
    current = _validate_url(url)
    with httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        headers=headers,
        limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
    ) as client:
        for _ in range(6):
            response = client.get(current)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    break
                current = _validate_url(urljoin(current, location))
                continue
            response.raise_for_status()
            raw = response.content[:MAX_BYTES]
            content_type = response.headers.get("content-type", "")
            text = raw.decode(response.encoding or "utf-8", errors="replace")
            return text, content_type
    raise ToolError("Trop de redirections.")


def fetch_url(args: dict[str, Any], ctx: ToolContext) -> str:
    url = str(args["url"]).strip()
    if not url:
        raise ToolError("URL vide.")
    try:
        text, content_type = _request(url, timeout=float(args.get("timeout", 20)))
    except httpx.HTTPError as exc:
        raise ToolError(f"Requete echouee: {exc}") from exc
    if "html" in content_type.lower() or "<html" in text[:500].lower():
        parser = _TextParser()
        parser.feed(text)
        title = " ".join(parser.title.split())
        body = _normalize("\n".join(parser.parts))
        if title:
            body = f"# {title}\n\n{body}"
    else:
        body = text
    return truncate_text(body.strip() or "(page vide)", ctx.max_output_chars)


def web_search(args: dict[str, Any], ctx: ToolContext) -> str:
    query = str(args["query"]).strip()
    if not query:
        raise ToolError("Requete vide.")
    limit = min(max(1, int(args.get("max_results", 5))), 10)
    try:
        text, _ = _request(
            "https://html.duckduckgo.com/html/?" + urlencode({"q": query}),
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise ToolError(f"Recherche echouee: {exc}") from exc
    parser = _DuckParser()
    parser.feed(text)
    results = [item for item in parser.results if item["url"]][:limit]
    if not results:
        return "(aucun resultat)"
    lines: list[str] = []
    for index, item in enumerate(results, start=1):
        lines.append(f"{index}. {item['title'] or item['url']}")
        lines.append(f"   {item['url']}")
        if item["snippet"]:
            lines.append(f"   {item['snippet']}")
    return truncate_text("\n".join(lines), ctx.max_output_chars)


def _normalize(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        cleaned = " ".join(line.split())
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def register_web_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="fetch",
            description=(
                "Fetch a public HTTP(S) page and return readable text. "
                "Local and private network addresses are refused."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Public HTTP(S) URL."},
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds. Default 20.",
                    },
                },
                "required": ["url"],
            },
            handler=fetch_url,
            approval="never",
        )
    )
    registry.register(
        Tool(
            name="web_search",
            description=(
                "Search the public web with DuckDuckGo and return titles, URLs and snippets."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results. Default 5, max 10.",
                    },
                },
                "required": ["query"],
            },
            handler=web_search,
            approval="never",
        )
    )
