"""Phase A remote-eval architecture, privacy, and evaluator-digest guards."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

from my_pa.application.goodnotes_gsqs import (
    evaluator_code_identity,
    evaluator_implementation_digest,
    evaluator_implementation_files,
)

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "src" / "my_pa" / "application"
CLI = ROOT / "apps" / "cli" / "gsqs_b0.py"
GENERATE = ROOT / "ops" / "goodnotes" / "gsqs" / "fixtures" / "remote-eval" / "generate.py"

REMOTE_EVAL_MODULES = (
    APPLICATION / "goodnotes_gsqs_remote_eval_contracts.py",
    APPLICATION / "goodnotes_gsqs_remote_eval.py",
    APPLICATION / "goodnotes_gsqs_remote_eval_storage.py",
    APPLICATION / "goodnotes_gsqs_remote_eval_staging.py",
    APPLICATION / "goodnotes_gsqs_remote_eval_disclosure.py",
)

FORBIDDEN_IMPORT_PREFIXES = (
    "my_pa.adapters.mcp",
    "my_pa.infrastructure.gsqs_routellm_transport",
    "my_pa.application.service",
    "my_pa.infrastructure.persistence",
    "sqlalchemy",
    "urllib",
    "http.client",
    "socket",
    "requests",
    "httpx",
)
FORBIDDEN_NETWORK_MODULES = frozenset(
    {
        "socket",
        "urllib",
        "urllib.request",
        "http",
        "http.client",
        "requests",
        "httpx",
    }
)
FORBIDDEN_CALLS = frozenset({"propose", "submit_proposal"})
CLI_HANDLER_FORBIDDEN_CALLS = frozenset(
    {
        "execute_measured_b0",
        "partition_b_census",
        "post_chat_completion",
        "serve_stdio",
    }
)
CLI_HANDLERS = ("_prepare_remote_eval", "_score_remote_eval")
ASYNC_NODES = (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)
EXPECTED_CODE_IDENTITY = "d2bd088a098f99d31637069fd339a67d665b80eb7aa97b403367cce1011a3fb7"
EXPECTED_IMPLEMENTATION_DIGEST = "a8f26fb28e2bb4cce1a2a3e6745dd01a2bdf5e2deaff63d9d05977bbfc9815ba"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _forbidden_imports(found: set[str]) -> set[str]:
    banned: set[str] = set()
    for name in found:
        if name in FORBIDDEN_NETWORK_MODULES:
            banned.add(name)
            continue
        for prefix in FORBIDDEN_IMPORT_PREFIXES:
            if name == prefix or name.startswith(prefix + "."):
                banned.add(name)
    return banned


def _called_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _load_generate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gsqs_remote_eval_generate", GENERATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase_a_application_modules_do_not_import_forbidden_surfaces() -> None:
    for path in REMOTE_EVAL_MODULES:
        found = _forbidden_imports(_imported_modules(_tree(path)))
        assert not found, f"{path.name} imports forbidden modules: {sorted(found)}"


def test_fixture_generator_does_not_import_network_modules() -> None:
    found = _forbidden_imports(_imported_modules(_tree(GENERATE)))
    assert not found, f"generate.py imports forbidden modules: {sorted(found)}"


def test_phase_a_modules_do_not_call_propose_or_submit_proposal() -> None:
    for path in (*REMOTE_EVAL_MODULES, GENERATE):
        called = _called_names(_tree(path)) & FORBIDDEN_CALLS
        assert not called, f"{path.name} calls {sorted(called)}"


def test_phase_a_application_modules_are_synchronous() -> None:
    for path in REMOTE_EVAL_MODULES:
        found = sorted(
            {type(node).__name__ for node in ast.walk(_tree(path)) if isinstance(node, ASYNC_NODES)}
        )
        assert not found, f"{path.name} contains async syntax {found}"


def test_cli_remote_eval_handlers_do_not_call_live_b0_or_network_entrypoints() -> None:
    tree = _tree(CLI)
    for name in CLI_HANDLERS:
        called = _called_names(_function(tree, name)) & CLI_HANDLER_FORBIDDEN_CALLS
        assert not called, f"{name} calls {sorted(called)}"


def test_evaluator_digests_are_stable_and_exclude_remote_eval_modules() -> None:
    identity = evaluator_code_identity()
    digest = evaluator_implementation_digest()
    assert identity == EXPECTED_CODE_IDENTITY
    assert digest == EXPECTED_IMPLEMENTATION_DIGEST
    names = [path.name for path in evaluator_implementation_files()]
    resolved = {path.resolve() for path in evaluator_implementation_files()}
    assert not any("goodnotes_gsqs_remote_eval" in name for name in names)
    assert "goodnotes_gsqs.py" in names
    prompt = ROOT / "ops" / "goodnotes" / "gsqs" / "b0" / "chatllm-remote-eval-prompt-v1.txt"
    canary_prompt = ROOT / "ops" / "goodnotes" / "gsqs" / "b0"
    canary_prompt = canary_prompt / "chatllm-remote-eval-visual-canary-prompt-v1.txt"
    assert prompt.resolve() not in resolved
    assert canary_prompt.resolve() not in resolved


def test_write_rasters_writes_only_pngs(tmp_path: Path) -> None:
    generate = _load_generate()
    dest = tmp_path / "rasters"
    written = generate.write_rasters(dest)
    files = sorted(path for path in dest.iterdir() if path.is_file())
    assert len(written) == 73
    assert len(files) == 73
    assert {path.suffix.lower() for path in files} == {".png"}
    assert not list(dest.glob("*.json"))
    assert [path.name for path in files] == [f"syn-b-{index:03d}.png" for index in range(1, 74)]
