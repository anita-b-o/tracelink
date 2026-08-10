from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment

from tracelink.connectors.errors import ConnectorError
from tracelink.connectors.models import ConnectorFetchResult, ExtractedHtml
from tracelink.connectors.url_safety import normalize_url
from tracelink.domain.normalization import collapse_whitespace

REMOVABLE_TAGS = ("script", "style", "noscript", "template", "nav", "footer", "aside", "form")
MAX_OUTGOING_LINKS = 100


def _metadata_content(soup: BeautifulSoup, *selectors: tuple[str, str]) -> str | None:
    for attribute, value in selectors:
        tag = soup.find("meta", attrs={attribute: value})
        if tag is not None and isinstance(tag.get("content"), str):
            content = collapse_whitespace(str(tag["content"]))
            if content:
                return content
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def extract_html(fetch: ConnectorFetchResult) -> ExtractedHtml:
    if fetch.content_type == "text/plain":
        return ExtractedHtml(visible_text=collapse_whitespace(fetch.text))

    soup = BeautifulSoup(fetch.text, "html.parser")
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    for tag in soup.find_all(REMOVABLE_TAGS):
        tag.decompose()

    title = collapse_whitespace(soup.title.get_text(" ")) if soup.title else None
    description = _metadata_content(soup, ("name", "description"), ("property", "og:description"))
    language = None
    if soup.html is not None and isinstance(soup.html.get("lang"), str):
        language = collapse_whitespace(str(soup.html["lang"])) or None

    canonical_url = None
    canonical = soup.find("link", rel="canonical")
    if canonical is not None and isinstance(canonical.get("href"), str):
        try:
            canonical_url = normalize_url(urljoin(fetch.url, str(canonical["href"])))
        except ConnectorError:
            canonical_url = None

    published_value = _metadata_content(
        soup,
        ("property", "article:published_time"),
        ("name", "date"),
        ("name", "pubdate"),
    )
    if published_value is None:
        time_tag = soup.find("time", attrs={"datetime": True})
        if time_tag is not None:
            published_value = str(time_tag.get("datetime"))

    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        try:
            link = normalize_url(urljoin(fetch.url, str(anchor["href"])))
        except ConnectorError:
            continue
        if link not in seen:
            seen.add(link)
            links.append(link)
        if len(links) == MAX_OUTGOING_LINKS:
            break

    return ExtractedHtml(
        title=title or None,
        visible_text=collapse_whitespace(soup.get_text(" ")),
        canonical_url=canonical_url,
        description=description,
        language=language,
        published_at=_parse_datetime(published_value),
        outgoing_links=links,
        metadata={"parser": "beautifulsoup-html.parser"},
    )
