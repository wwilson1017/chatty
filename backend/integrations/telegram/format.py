"""Markdown-to-Telegram-HTML converter.

Converts standard Markdown (as produced by AI models) into Telegram's
supported HTML subset.  Falls back gracefully — callers should catch
exceptions and send plain text if conversion fails.
"""

import re

_PLACEHOLDER_PREFIX = "\x00TGFMT"


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def markdown_to_telegram_html(text: str) -> str:
    """Convert standard Markdown to Telegram-compatible HTML.

    Handles bold, italic, strikethrough, inline code, fenced code blocks,
    links, headers, and blockquotes.  Returns HTML suitable for Telegram's
    ``parse_mode="HTML"``.
    """
    if not text:
        return text

    placeholders: list[str] = []

    def _placeholder(html: str) -> str:
        idx = len(placeholders)
        placeholders.append(html)
        return f"{_PLACEHOLDER_PREFIX}{idx}\x00"

    # 1. Extract fenced code blocks before anything else
    def _fenced_code(m: re.Match) -> str:
        lang = m.group(1) or ""
        code = _escape_html(m.group(2))
        if lang:
            return _placeholder(f'<pre><code class="language-{_escape_html(lang)}">{code}</code></pre>')
        return _placeholder(f"<pre><code>{code}</code></pre>")

    result = re.sub(r"```(\w*)\n(.*?)```", _fenced_code, text, flags=re.DOTALL)

    # 2. Extract inline code
    def _inline_code(m: re.Match) -> str:
        return _placeholder(f"<code>{_escape_html(m.group(1))}</code>")

    result = re.sub(r"`([^`]+)`", _inline_code, result)

    # 3. Extract links (before HTML-escaping to avoid double-escaping URLs)
    def _link(m: re.Match) -> str:
        label = _escape_html(m.group(1))
        href = _escape_html(m.group(2))
        return _placeholder(f'<a href="{href}">{label}</a>')

    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, result)

    # 4. HTML-escape remaining text
    result = _escape_html(result)

    # 5. Block elements — headers
    result = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", result, flags=re.MULTILINE)

    # 6. Block elements — blockquotes (merge consecutive lines)
    def _blockquote(m: re.Match) -> str:
        lines = m.group(0).split("\n")
        inner = "\n".join(re.sub(r"^&gt;\s?", "", line) for line in lines)
        return f"<blockquote>{inner}</blockquote>"

    result = re.sub(r"^&gt;\s?.+(?:\n&gt;\s?.+)*", _blockquote, result, flags=re.MULTILINE)

    # 7. Inline elements — bold before italic
    result = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", result)
    result = re.sub(r"__(.+?)__", r"<b>\1</b>", result)

    # Italic — single * only (skip _ to avoid false positives in URLs)
    result = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", result)

    # Strikethrough
    result = re.sub(r"~~(.+?)~~", r"<s>\1</s>", result)

    # 8. Restore placeholders
    for idx, html in enumerate(placeholders):
        result = result.replace(f"{_PLACEHOLDER_PREFIX}{idx}\x00", html)

    return result
