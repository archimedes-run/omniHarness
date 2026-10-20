"""Files baked into the built-MCP-server runtime image (Feature 006, #59).

Nothing here is imported by the gateway: ``launch.py`` runs inside the
container, and ``assemble_packages.py`` runs wherever the runtime packages
are read from (the gateway itself, or a throwaway container). The gateway
reads them as files.
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
LAUNCHER = HERE / "launch.py"
ASSEMBLER = HERE / "assemble_packages.py"
