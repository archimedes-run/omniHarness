"""Per-user preferences (Feature 006): the appearance a user chose.

One row per user. Stored server-side so the choice follows the user to every
browser and device; the frontend caches it in localStorage only to paint it
before the first request returns.
"""

from omniharness.persistence.user_preferences.model import UserPreferenceRow
from omniharness.persistence.user_preferences.sql import APPEARANCES, UserPreferenceRepository

__all__ = ["APPEARANCES", "UserPreferenceRepository", "UserPreferenceRow"]
