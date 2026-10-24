import logging
import os
import subprocess

from markdownify import markdownify as md
from readabilipy import simple_json_from_html_string

logger = logging.getLogger(__name__)


class Article:
    url: str

    def __init__(self, title: str, html_content: str):
        self.title = title
        self.html_content = html_content

    def to_markdown(self, including_title: bool = True) -> str:
        markdown = ""
        if including_title:
            markdown += f"# {self.title}\n\n"

        if self.html_content is None or not str(self.html_content).strip():
            markdown += "*No content available*\n"
        else:
            markdown += md(self.html_content)

        return markdown


def readability_js_installed() -> bool:
    """Whether readabilipy's Readability.js dependencies are already installed.

    Without them, readabilipy's node check runs ``npm install`` at call time,
    straight to the internet; that must never happen at run time, so the
    pure-Python path is used instead.
    """
    import readabilipy.simple_json as simple_json

    return os.path.isdir(os.path.join(os.path.dirname(simple_json.__file__), "javascript", "node_modules"))


class ReadabilityExtractor:
    def extract_article(self, html: str) -> Article:
        if not readability_js_installed():
            return self._article(simple_json_from_html_string(html, use_readability=False))
        try:
            article = simple_json_from_html_string(html, use_readability=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            stderr = getattr(exc, "stderr", None)
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            stderr_info = f"; stderr={stderr.strip()}" if isinstance(stderr, str) and stderr.strip() else ""
            logger.warning(
                "Readability.js extraction failed with %s%s; falling back to pure-Python extraction",
                type(exc).__name__,
                stderr_info,
                exc_info=True,
            )
            article = simple_json_from_html_string(html, use_readability=False)
        return self._article(article)

    @staticmethod
    def _article(article: dict) -> Article:
        html_content = article.get("content")
        if not html_content or not str(html_content).strip():
            html_content = "No content could be extracted from this page"

        title = article.get("title")
        if not title or not str(title).strip():
            title = "Untitled"

        return Article(title=title, html_content=html_content)
