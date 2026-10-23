"""The environment a child process may see (security baseline).

Every place the harness builds a subprocess environment for something an agent
drives (today: the Composio stdio MCP server) starts from :func:`scrubbed_environment`,
never from ``os.environ``. It drops, by NAME, anything that looks like a secret
and, by VALUE, anything that carries credentials (a URL with ``user:pass@``,
a webhook URL). With ``isolate_home=True`` it also points HOME at an empty
temporary directory and drops XDG_* paths, so dotfiles (~/.codex, ~/.claude,
~/.ssh) are not reachable through $HOME.
"""

from __future__ import annotations

import os
import re
import tempfile

#: Secret-looking variable NAMES.
SECRET_ENV_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|PWD$|API_KEY|APIKEY|PRIVATE_KEY|CREDENTIAL|_KEY$|^AUTH_|COOKIE|SESSION|WEBHOOK|_PAT$|^GH_PAT|_DSN$|DATABASE_URL|^PG(PASSWORD|PASS)$)",
    re.IGNORECASE,
)
#: Exact names, for clarity (all also match SECRET_ENV_RE).
SECRET_ENV_NAMES = frozenset({"OMNI_HARNESS_INTERNAL_AUTH_TOKEN", "AUTH_JWT_SECRET", "BETTER_AUTH_SECRET", "DATABASE_URL"})
#: Values that carry credentials whatever the name: scheme://user:pass@ or
#: scheme://token@, and webhook endpoints.
_CREDENTIAL_VALUE_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s@]+@|hooks\.slack\.com/|discord(?:app)?\.com/api/webhooks/|password=", re.IGNORECASE)
_HOME_KEYS = ("HOME", "USERPROFILE")


def scrubbed_environment(source: dict[str, str] | None = None, *, isolate_home: bool = False, home: str | None = None) -> dict[str, str]:
    """``source`` (default: this process's environment) minus every secret."""
    source = dict(os.environ if source is None else source)
    env = {k: v for k, v in source.items() if k not in SECRET_ENV_NAMES and not SECRET_ENV_RE.search(k) and not _CREDENTIAL_VALUE_RE.search(str(v)) and not (isolate_home and k.startswith("XDG_"))}
    if isolate_home and any(k in source for k in _HOME_KEYS):
        safe_home = home or tempfile.mkdtemp(prefix="omni-child-home-")
        for key in _HOME_KEYS:
            if key in source:
                env[key] = safe_home
    return env
