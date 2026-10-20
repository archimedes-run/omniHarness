"""The production-built gateway (create_app + lifespan), the ledger suite's own
fixture loaded by path: tests/ has no __init__.py, so it is not importable."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_ledger_gateway_conftest", Path(__file__).parents[1] / "ledger" / "conftest.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
gateway = _module.gateway
