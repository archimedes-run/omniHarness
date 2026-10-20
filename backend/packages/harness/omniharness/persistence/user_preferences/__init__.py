"""Per-user preferences (Feature 006): appearance and an optional display name.

One row per user. Stored server-side so the choice follows the user to every
browser and device; the frontend caches it in localStorage only to paint it
before the first request returns.
"""

from omniharness.persistence.user_preferences.model import UserPreferenceRow
from omniharness.persistence.user_preferences.sql import APPEARANCES, DISPLAY_NAME_MAX, UserPreferenceRepository, effective_display_name

__all__ = ["APPEARANCES", "DISPLAY_NAME_MAX", "UserPreferenceRepository", "UserPreferenceRow", "effective_display_name"]
