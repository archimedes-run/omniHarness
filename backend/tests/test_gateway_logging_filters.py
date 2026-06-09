import logging

from app.gateway.logging_filters import PreviewTokenRedactionFilter, mask_preview_token_urls


def test_mask_preview_token_urls_redacts_preview_token_segment() -> None:
    raw = "/api/threads/thread-1/artifacts/preview-token/header.payload.signature/mnt/user-data/outputs/site/_next/static/app.js"

    masked = mask_preview_token_urls(raw)

    assert "header.payload.signature" not in masked
    assert "/api/threads/thread-1/artifacts/preview-token/[redacted]/mnt/user-data/outputs/site/_next/static/app.js" == masked


def test_preview_token_redaction_filter_masks_uvicorn_access_log_args() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:50000",
            "GET",
            "/api/threads/thread-1/artifacts/preview-token/secret-token/mnt/user-data/outputs/site/app.js",
            "1.1",
            200,
        ),
        exc_info=None,
    )

    PreviewTokenRedactionFilter().filter(record)

    assert "secret-token" not in record.getMessage()
    assert "/artifacts/preview-token/[redacted]/mnt/user-data/outputs/site/app.js" in record.getMessage()
