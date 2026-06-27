"""OmniHarness platform primitives.

This package contains shared building blocks that all platform product
objects (Workflows, Triggers, Watchers, etc.) depend on:

- events.py      — PlatformEvent envelope + EventSource discriminator
- writer.py      — emit_platform_event() thin helper (uses existing store)
- idempotency.py — compute_idempotency_key() deterministic helper
"""
