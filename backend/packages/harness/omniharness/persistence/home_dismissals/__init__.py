"""What the user dismissed on Home (Feature 006): alerts, and the name prompt.

One row per (user, kind, key). Kept on the server, so a dismissal follows the
user to every browser and device, and the New chat badge can leave dismissed
alerts out of its count.
"""

from omniharness.persistence.home_dismissals.model import HomeDismissalRow
from omniharness.persistence.home_dismissals.sql import DISMISSAL_KINDS, KEY_MAX, HomeDismissalRepository

__all__ = ["DISMISSAL_KINDS", "KEY_MAX", "HomeDismissalRepository", "HomeDismissalRow"]
