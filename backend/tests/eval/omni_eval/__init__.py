"""The eval suite for the lead agent (spec 009 Slice 0): `make eval`."""

import os
from pathlib import Path

# The harness process itself imports the harness package (the checks share its
# working-loop helpers); point it at the tracked example config, never at a
# developer's config.yaml (Article XIV). Each trial's gateway gets its own.
os.environ.setdefault("OMNI_HARNESS_CONFIG_PATH", str(Path(__file__).resolve().parents[4] / "config.example.yaml"))
