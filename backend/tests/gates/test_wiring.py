"""T079 — the wiring gate, for every feature module (Feature 004 FR-039, FR-043).

Gate 4 (formerly tests/trigger_engine/test_wiring.py) scanned only
app/trigger_engine, so it could not see `recognise`, `DisclosureLedger.apply` or
`limits.describe_*` — built, unit-tested, called by nothing. This scans every
module under app/ and packages/, and asks a stricter question:

  is each public function, method, class and UPPERCASE constant REACHED from
  production — referenced by code that is itself reached?

FR-043: "referenced inside its own module" is not enough. A helper called only
by an unwired sibling is unwired. So wiring is a fixpoint from ROOTS:

  * module-level code (it runs on import);
  * handlers registered by decorator (routes, validators, tools, MCP handlers);
  * framework hooks on AgentMiddleware subclasses (langchain calls them);
  * dunders, and overrides of a base-class method that is itself wired;
  * string entry points in the shipped config (`use:` paths, langgraph.json).

References keep where they point when that is knowable (`from m import x as y`
marks m.x — BOTH the alias and the original are recorded, the bug Gate 4 had;
`mod.attr` through an imported module resolves to that module), and fall back
to matching by name only for an attribute on an unknown receiver.

Anything unreached must be wired or whitelisted WITH A REASON. A whitelist entry
for something that is in fact reached fails as stale.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
ROOTS = (BACKEND / "app", BACKEND / "packages")
WHITELIST = Path(__file__).with_name("wiring-whitelist.txt")

#: langchain AgentMiddleware hooks — invoked by the framework, never by us.
AGENT_HOOKS = frozenset({"wrap_tool_call", "awrap_tool_call", "wrap_model_call", "awrap_model_call", "before_model", "abefore_model", "after_model", "aafter_model", "before_agent", "abefore_agent", "after_agent", "aafter_agent"})
#: Decorators that REGISTER the function with something that will call it.
REGISTERING_BASES = frozenset({"router", "app", "server", "mcp"})
REGISTERING_NAMES = frozenset({"tool", "field_validator", "model_validator", "validator", "root_validator", "computed_field", "field_serializer", "model_serializer", "hookimpl", "asynccontextmanager", "contextmanager"})
#: Bases that do not call a subclass's methods back, so subclassing them makes
#: no method a framework callback.
NOT_FRAMEWORK_BASES = frozenset({"object", "Protocol", "ABC", "Generic", "BaseModel", "Enum", "StrEnum", "IntEnum", "TypedDict", "NamedTuple", "Exception", "RuntimeError", "ValueError"})
#: Files whose strings name entry points (module.path:attr).
ENTRY_POINT_FILES = ("config.example.yaml", "extensions_config.example.json", "backend/langgraph.json", "backend/pyproject.toml", "backend/packages/harness/pyproject.toml", "backend/packages/session_watcher/pyproject.toml")


def _base_name(node) -> str:
    """`AgentMiddleware[State]` -> AgentMiddleware; `mod.Base` -> Base."""
    while isinstance(node, ast.Subscript):
        node = node.value
    return node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", "")


def _module_name(path: Path, base: Path = BACKEND) -> str:
    rel = path.relative_to(base)
    parts = list(rel.with_suffix("").parts)
    if parts[0] == "packages":
        parts = parts[2:]  # packages/<dist>/<pkg>/... -> <pkg>/...
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _production_files(roots=ROOTS) -> list[Path]:
    out = []
    for root in roots:
        for path in root.rglob("*.py"):
            if "tests" in path.parts or ".venv" in path.parts or "node_modules" in path.parts:
                continue
            out.append(path)
    return sorted(out)


@dataclass
class Definition:
    qid: str  # module:Class.name
    module: str
    name: str
    kind: str
    owner: str | None = None  # class name, for methods
    root_reason: str | None = None
    refs: set[tuple[str | None, str]] = field(default_factory=set)  # (module or None, name)
    override_of: list[str] = field(default_factory=list)  # base class names


class _Collector(ast.NodeVisitor):
    """Per file: definitions, and the references each definition (or the module
    body) makes."""

    def __init__(self, module: str, modules: set[str], *, is_package: bool):
        self.module = module
        self.is_package = is_package
        self.modules = modules
        self.defs: list[Definition] = []
        self.module_refs: set[tuple[str | None, str]] = set()
        self.stack: list[Definition] = []
        self.class_stack: list[ast.ClassDef] = []
        self.alias_to_target: dict[str, tuple[str | None, str]] = {}  # local name -> (module, name)
        self.module_alias: dict[str, str] = {}  # local name -> module

    # -- references -------------------------------------------------------
    def _ref(self, target: tuple[str | None, str]) -> None:
        (self.stack[-1].refs if self.stack else self.module_refs).add(target)

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            local = a.asname or a.name.split(".")[0]
            self.module_alias[local] = a.name if a.asname else a.name.split(".")[0]
            self._ref((None, a.name.split(".")[-1]))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        if node.level:
            # From a module, level 1 is its package; from a package's __init__,
            # level 1 is the package itself.
            parts = self.module.split(".")
            keep = len(parts) - node.level + (1 if self.is_package else 0)
            pkg = parts[:keep]
            base = ".".join([*pkg, base] if base else pkg)
        for a in node.names:
            full = f"{base}.{a.name}"
            if full in self.modules:
                self.module_alias[a.asname or a.name] = full
                self._ref((full, "<module>"))
            else:
                # BOTH names: the original is what is defined, the alias is what is used.
                self.alias_to_target[a.asname or a.name] = (base, a.name)
                self._ref((base, a.name))

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self.alias_to_target:
            self._ref(self.alias_to_target[node.id])
        else:
            self._ref((None, node.id))

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and node.value.id in self.module_alias:
            self._ref((self.module_alias[node.value.id], node.attr))
        else:
            self._ref((None, node.attr))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        # getattr(obj, "name") and "pkg.mod:attr" strings.
        if isinstance(node.value, str):
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.value):
                self._ref((None, node.value))
            for mod, attr in re.findall(r"([A-Za-z_][\w.]*):([A-Za-z_]\w*)", node.value):
                self._ref((mod, attr))  # "app.channels.telegram:TelegramChannel" style loading

    # -- definitions --------------------------------------------------------
    def _root_reason(self, node, owner: ast.ClassDef | None) -> str | None:
        name = node.name
        if name.startswith("__") and name.endswith("__"):
            return "dunder"
        for dec in getattr(node, "decorator_list", []):
            target = dec.func if isinstance(dec, ast.Call) else dec
            base = target
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name) and base.id in REGISTERING_BASES and isinstance(target, ast.Attribute):
                return f"registered by @{base.id}.{target.attr}"
            tail = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
            if tail in REGISTERING_NAMES:
                return f"registered by @{tail}"
        if owner is not None and name in AGENT_HOOKS and owner.bases:
            # The hook names are langchain's and distinctive; a base computed
            # at runtime (policy_hook's _middleware_base()) has no static name.
            return "AgentMiddleware hook"
        if owner is None and name in {"upgrade", "downgrade"} and "migrations" in self.module:
            return "Alembic migration entry point"
        return None

    def _define(self, node, kind: str) -> Definition:
        owner = self.class_stack[-1] if self.class_stack else None
        qual = f"{owner.name}.{node.name}" if owner is not None and kind != "class" else node.name
        d = Definition(qid=f"{self.module}:{qual}", module=self.module, name=node.name, kind=kind, owner=owner.name if owner is not None else None, root_reason=self._root_reason(node, owner))
        if owner is not None and kind == "method":
            d.override_of = [_base_name(b) for b in owner.bases]
        self.defs.append(d)
        return d

    def _function(self, node) -> None:
        if self.stack and self.stack[-1].kind in ("function", "method"):
            # A nested function is part of its parent.
            self.generic_visit(node)
            return
        for dec in node.decorator_list:
            self.visit(dec)
        d = self._define(node, "method" if self.class_stack else "function")
        self.stack.append(d)
        for child in node.body:
            self.visit(child)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        # Annotations are references: a request model used only as a route
        # parameter's type is used — FastAPI builds it from the body.
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs, node.args.vararg, node.args.kwarg]:
            if arg is not None and arg.annotation is not None:
                self.visit(arg.annotation)
        if node.returns is not None:
            self.visit(node.returns)
        self.stack.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expr in [*node.bases, *node.decorator_list, *[k.value for k in node.keywords]]:
            self.visit(expr)
        d = self._define(node, "class")
        self.class_stack.append(node)
        self.stack.append(d)
        for child in node.body:
            self.visit(child)
        self.stack.pop()
        self.class_stack.pop()

    def _constant(self, target, value) -> None:
        in_enum = bool(self.class_stack) and any(_base_name(b) in {"Enum", "StrEnum", "IntEnum", "IntFlag", "Flag"} for b in self.class_stack[-1].bases)
        if in_enum:
            # An enum member is vocabulary, matched by VALUE from stored data;
            # an unreferenced member is not unwired code.
            if value is not None:
                self.visit(value)
            return
        if isinstance(target, ast.Name) and target.id.isupper() and len(target.id) > 1 and (not self.stack or self.stack[-1].kind == "class"):
            owner = self.class_stack[-1] if self.class_stack else None
            qual = f"{owner.name}.{target.id}" if owner is not None else target.id
            self.defs.append(Definition(qid=f"{self.module}:{qual}", module=self.module, name=target.id, kind="constant", owner=owner.name if owner else None))
        if value is not None:
            self.visit(value)

    def visit_Assign(self, node: ast.Assign) -> None:
        for t in node.targets:
            if isinstance(t, ast.Name):
                self._constant(t, None)
            else:
                self.visit(t)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._constant(node.target, node.value)
        self.visit(node.annotation)


def _entry_points() -> set[tuple[str, str]]:
    found = set()
    for rel in ENTRY_POINT_FILES:
        path = REPO / rel
        if not path.exists():
            continue
        for mod, attr in re.findall(r"([A-Za-z_][\w.]*\.[\w]+|[A-Za-z_]\w*):([A-Za-z_]\w*)", path.read_text()):
            found.add((mod, attr))
            # ./path/file.py:attr in langgraph.json
        for file_path, attr in re.findall(r"\./([\w/]+)\.py:([A-Za-z_]\w*)", path.read_text()):
            found.add((file_path.replace("/", "."), attr))
    return found


def analyse(roots=ROOTS, base: Path = BACKEND, entry_points: bool = True) -> tuple[dict[str, Definition], set[str]]:
    """All definitions, and the qids reached from production."""
    files = _production_files(roots)
    modules = {_module_name(p, base) for p in files}
    defs: dict[str, Definition] = {}
    module_refs: list[set[tuple[str | None, str]]] = []
    for path in files:
        c = _Collector(_module_name(path, base), modules, is_package=path.name == "__init__.py")
        c.visit(ast.parse(path.read_text(encoding="utf-8")))
        for d in c.defs:
            defs.setdefault(d.qid, d)
        module_refs.append(c.module_refs)

    by_name: dict[str, list[Definition]] = {}
    for d in defs.values():
        by_name.setdefault(d.name, []).append(d)
    entry = _entry_points() if entry_points else set()

    def resolve(ref: tuple[str | None, str], source: Definition | None) -> list[Definition]:
        mod, name = ref
        candidates = [d for d in by_name.get(name, []) if d is not source]
        if mod is not None:
            exact = [d for d in candidates if d.module == mod or d.module.startswith(mod + ".")]
            if exact:
                return exact
        return candidates if mod is None else candidates  # unknown module: fall back by name

    wired: set[str] = set()
    frontier: list[Definition] = []

    def mark(d: Definition) -> None:
        if d.qid not in wired:
            wired.add(d.qid)
            frontier.append(d)

    for d in defs.values():
        if d.root_reason or any((d.module.endswith(m) or m.endswith(d.module)) and d.name == a for m, a in entry):
            mark(d)
    for refs in module_refs:
        for ref in refs:
            for d in resolve(ref, None):
                mark(d)
    while frontier:
        d = frontier.pop()
        for ref in d.refs:
            for target in resolve(ref, d):
                mark(target)
        # A wired class makes its methods' overrides elsewhere wired, and an
        # override of a wired base method is called polymorphically.
    class_names = {d.name for d in defs.values() if d.kind == "class"}
    for d in defs.values():
        # A method of a class whose base is a FRAMEWORK class we do not scan
        # (Starlette's BaseHTTPMiddleware.dispatch, logging.Filter.filter,
        # pydantic BaseModel hooks) is called by that framework, polymorphically.
        if d.kind == "method" and d.owner and f"{d.module}:{d.owner}" in wired and any(b and b not in class_names and b not in NOT_FRAMEWORK_BASES for b in d.override_of):
            mark(d)
    while frontier:
        d = frontier.pop()
        for ref in d.refs:
            for target in resolve(ref, d):
                mark(target)
    changed = True
    while changed:
        changed = False
        for d in defs.values():
            if d.qid in wired or d.kind != "method":
                continue
            for base in d.override_of:
                for b in by_name.get(base, []):
                    if b.kind == "class" and f"{b.module}:{base}.{d.name}" in wired:
                        mark(d)
                        changed = True
        while frontier:
            d = frontier.pop()
            for ref in d.refs:
                for target in resolve(ref, d):
                    mark(target)
    return defs, wired


def _whitelist() -> dict[str, str]:
    entries = {}
    for raw in WHITELIST.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        qid, _, reason = line.partition("#")
        entries[qid.strip()] = reason.strip()
    return entries


def _public(d: Definition) -> bool:
    return not d.name.startswith("_") or (d.name.startswith("__") and d.name.endswith("__"))


def unwired(**kw) -> list[str]:
    defs, wired = analyse(**kw)
    return sorted(q for q, d in defs.items() if q not in wired and _public(d))


def test_every_whitelist_entry_has_a_reason() -> None:
    missing = [q for q, reason in _whitelist().items() if not reason]
    assert not missing, f"whitelist entries without a reason: {missing}"


def test_nothing_is_built_and_never_called() -> None:
    orphans = set(unwired())
    allowed = _whitelist()
    unexplained = sorted(orphans - set(allowed))
    stale = sorted(set(allowed) - orphans)
    assert not unexplained, "defined and never reached from production — wire it, or whitelist it with a reason:\n" + "\n".join(unexplained)
    assert not stale, "whitelisted but actually reached (or gone) — remove the entry:\n" + "\n".join(stale)


#: Feature 005 modules: written under "wiring gate from day one" (FR-070).
#: Nothing in them may be whitelisted as unwired; a definition there is wired
#: or it is deleted. (Reasons like "public API" remain possible.)
FEATURE_005_MODULES = ("app.ledger", "omniharness.persistence.ledger", "omniharness.runtime.ledger", "omniharness.tools.builtins.ledger_tool", "session_watcher.adapters.codex", "session_watcher.todos")


def test_feature_005_code_carries_no_unwired_entries() -> None:
    offending = [q for q, reason in _whitelist().items() if q.split(":")[0].startswith(FEATURE_005_MODULES) and "UNWIRED" in reason.upper()]
    assert not offending, "Feature 005 code is wired from day one (FR-070); these are whitelisted as unwired:\n" + "\n".join(offending)


def test_the_gate_is_green_only_because_of_its_whitelist() -> None:
    """SC-022 / T081: on today's tree the gate FINDS things. A gate that finds
    nothing on a real codebase is more likely blind than the codebase clean."""
    assert unwired(), "the gate found no orphans at all — it is probably not looking"


# -- the gate must be able to fail (T078a, T078b's fixture form, T081) --------


def _fixture(tmp_path: Path) -> list[str]:
    """A tiny production tree with each shape the gate exists for."""
    pkg = tmp_path / "app" / "demo"
    pkg.mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "ledger.py").write_text(
        "class Ledger:\n"
        "    def apply(self, text):\n"  # FR-043: only an unwired sibling calls it
        "        return text\n"
        "    def unused_sibling(self):\n"
        "        return self.apply('x')\n"
        "def never_called():\n"
        "    return 1\n"
        "def install():\n"  # imported under an alias, and called through it
        "    return 2\n"
    )
    (pkg / "main.py").write_text("from app.demo.ledger import Ledger, install as install_policy\nLEDGER = Ledger()\ninstall_policy()\n")
    return unwired(roots=(tmp_path / "app",), base=tmp_path, entry_points=False)


def test_the_gate_names_a_helper_reached_only_through_an_unwired_sibling(tmp_path) -> None:
    """T078a. DisclosureLedger.apply's shape: the gate must NOT count a call
    from a sibling that is itself unreached."""
    found = _fixture(tmp_path)
    assert "app.demo.ledger:Ledger.apply" in found
    assert "app.demo.ledger:Ledger.unused_sibling" in found


def test_the_gate_names_a_function_nothing_calls(tmp_path) -> None:
    """T081, fixture form: a function nothing calls is named."""
    assert "app.demo.ledger:never_called" in _fixture(tmp_path)


def test_an_aliased_import_counts_as_a_reference(tmp_path) -> None:
    """Gate 4 recorded only the alias of `import X as Y`, so `install`
    imported as `install_policy` read as unreferenced."""
    assert "app.demo.ledger:install" not in _fixture(tmp_path)
