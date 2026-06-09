import logging
import re
from typing import Any

PREVIEW_TOKEN_LOG_RE = re.compile(r"(/artifacts/preview-token/)[^/\s?]+")
PREVIEW_TOKEN_REDACTION = r"\1[redacted]"


def mask_preview_token_urls(value: str) -> str:
    """Redact short-lived artifact preview tokens from loggable URL strings."""
    return PREVIEW_TOKEN_LOG_RE.sub(PREVIEW_TOKEN_REDACTION, value)


class PreviewTokenRedactionFilter(logging.Filter):
    """Logging filter that masks preview-token URL segments.

    Uvicorn access logs pass the request path in ``record.args`` rather than
    ``record.msg``, so both fields are rewritten before handlers format them.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_preview_token_urls(record.msg)

        if isinstance(record.args, tuple):
            record.args = tuple(_mask_arg(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _mask_arg(value) for key, value in record.args.items()}

        return True


def _mask_arg(arg: Any) -> Any:
    if isinstance(arg, str):
        return mask_preview_token_urls(arg)
    return arg


def install_preview_token_log_filter() -> None:
    """Install redaction where application and Uvicorn access logs flow."""
    redaction_filter = PreviewTokenRedactionFilter()
    for logger_name in ("", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(logger_name)
        if not any(isinstance(existing, PreviewTokenRedactionFilter) for existing in logger.filters):
            logger.addFilter(redaction_filter)
