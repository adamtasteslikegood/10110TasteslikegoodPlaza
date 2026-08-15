"""Shared Markdown → Confluence storage-format conversion for scripts/pm.

Everything in this repo that publishes to Confluence must emit *storage format*
— strict XHTML with Confluence macros — not arbitrary HTML5. The Confluence
REST API rejects or silently mangles invalid storage (unclosed void tags, raw
HTML, code blocks without the code macro, etc.).

Historically each publisher rolled its own converter: ``pm_daemon`` handed the
markdown to python-markdown, and ``atlassian_pm_link`` used a hand-rolled
line-by-line parser that only understood bullets, numbered lists, code fences
and paragraphs (no tables, no nesting). Both drifted from real storage format.

md2cf's ``ConfluenceRenderer`` is purpose-built for exactly this: a Mistune
renderer that outputs Confluence storage format (``<ac:structured-macro>`` code
blocks, proper tables, correct escaping). Import ``markdown_to_storage`` from
here everywhere instead of re-implementing the conversion.
"""

from __future__ import annotations

import mistune
from md2cf.confluence_renderer import ConfluenceRenderer


def markdown_to_storage(markdown_text: str) -> str:
    """Convert a Markdown string to Confluence storage-format XHTML.

    A fresh renderer is built per call on purpose: ``ConfluenceRenderer``
    accumulates attachment/image state, so reusing one instance across
    documents would leak that state between pages.
    """
    renderer = ConfluenceRenderer(use_xhtml=True)
    convert = mistune.Markdown(renderer=renderer)
    return convert(markdown_text)
