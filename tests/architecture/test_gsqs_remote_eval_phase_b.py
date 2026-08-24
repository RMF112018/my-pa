"""Phase B remote-eval isolation: import graph, published names, logs, origins."""

from __future__ import annotations

import ast
from pathlib import Path

from my_pa.application.goodnotes_gsqs import (
    evaluator_code_identity,
    evaluator_implementation_digest,
    evaluator_implementation_files,
)

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "src" / "my_pa" / "application"
ADAPTER = ROOT / "src" / "my_pa" / "adapters" / "gsqs_remote_eval_mcp.py"
ENTRYPOINT = ROOT / "apps" / "gsqs_remote_eval.py"
SETTINGS = ROOT / "src" / "my_pa" / "bootstrap" / "settings.py"
TOOLS = ROOT / "src" / "my_pa" / "adapters" / "mcp" / "tools.py"
AUTH = ROOT / "src" / "my_pa" / "infrastructure" / "security" / "gsqs_remote_eval_authentication.py"
MCP_INIT = ROOT / "src" / "my_pa" / "adapters" / "mcp" / "__init__.py"

REMOTE_EVAL_APPLICATION = (
    APPLICATION / "goodnotes_gsqs_remote_eval_contracts.py",
    APPLICATION / "goodnotes_gsqs_remote_eval.py",
    APPLICATION / "goodnotes_gsqs_remote_eval_storage.py",
    APPLICATION / "goodnotes_gsqs_remote_eval_staging.py",
    APPLICATION / "goodnotes_gsqs_remote_eval_disclosure.py",
)
ISOLATED_PROCESS_FILES = (ADAPTER, ENTRYPOINT)
LOG_SCAN_FILES = (*ISOLATED_PROCESS_FILES, *REMOTE_EVAL_APPLICATION)

EXPECTED_CODE_IDENTITY = "d2bd088a098f99d31637069fd339a67d665b80eb7aa97b403367cce1011a3fb7"
EXPECTED_IMPLEMENTATION_DIGEST = "a8f26fb28e2bb4cce1a2a3e6745dd01a2bdf5e2deaff63d9d05977bbfc9815ba"
EVAL_TOOL_NAMES = frozenset(
    {
        "goodnotes.eval.status",
        "goodnotes.eval.next",
        "goodnotes.eval.submit",
    }
)
PRODUCTION_TOOL_NAMES = frozenset(
    {
        "goodnotes.propose",
        "goodnotes.work",
        "goodnotes.content",
    }
)
FORBIDDEN_IMPORT_MODULES = frozenset(
    {
        "my_pa.application.service",
        "my_pa.adapters.mcp",
    }
)
FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "ApplicationService",
        "published_tools",
        "create_mcp_server",
        "TOOLS",
    }
)
FORBIDDEN_PACKAGE_IMPORT_NAMES = frozenset(
    {
        "tools",
        "TOOLS",
        "published_tools",
        "create_mcp_server",
        "create_remote_mcp_app",
        "ApplicationService",
    }
)
FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "gold",
        "gold_path",
        "handwriting_path",
        "label",
        "path",
        "private_gold",
        "private_label",
        "raster_path",
        "source_path",
    }
)
FORBIDDEN_LOG_TOKENS = (
    "source_path",
    "gold_path",
    "handwriting_path",
    "raster_path",
    "authorization",
    "Authorization",
    "Bearer",
    "base64",
    "png_image_content",
    "image bytes",
)
LOG_CALL_NAMES = frozenset({"print", "debug", "info", "warning", "error", "exception", "critical"})


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported(path: Path) -> tuple[set[str], set[str], set[str]]:
    modules: set[str] = set()
    names: set[str] = set()
    package_names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
                names.add(alias.asname or alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            bound = {alias.asname or alias.name for alias in node.names}
            names |= bound
            if node.module == "my_pa.adapters.mcp":
                package_names |= bound
    return modules, names, package_names


def _leaked_modules(found: set[str]) -> set[str]:
    leaked: set[str] = set()
    for name in found:
        for banned in FORBIDDEN_IMPORT_MODULES:
            if name == banned or name.startswith(banned + "."):
                leaked.add(name)
    return leaked


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _string_constants(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            constants[target.id] = value.value
    return constants


def _dict_string_keys(tree: ast.AST) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
    return keys


def _keyword_constant(call: ast.Call, name: str) -> object:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    raise AssertionError(f"missing keyword {name}")


def _uvicorn_run_calls(tree: ast.AST) -> list[ast.Call]:
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "run"
            and isinstance(func.value, ast.Name)
            and func.value.id == "uvicorn"
        ):
            found.append(node)
    return found


def _log_like_calls(tree: ast.AST) -> list[ast.Call]:
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in LOG_CALL_NAMES:
            found.append(node)
        elif isinstance(func, ast.Attribute) and func.attr in LOG_CALL_NAMES:
            root = func.value
            if (isinstance(root, ast.Name) and root.id in {"logging", "logger", "log"}) or (
                isinstance(root, ast.Attribute) and root.attr == "logging"
            ):
                found.append(node)
    return found


def _ann_assign_default(tree: ast.Module, class_name: str, field: str) -> object:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    if item.target.id != field:
                        continue
                    value = item.value
                    if isinstance(value, ast.Constant):
                        return value.value
                    if isinstance(value, ast.Call):
                        for keyword in value.keywords:
                            if keyword.arg == "default" and isinstance(keyword.value, ast.Constant):
                                return keyword.value.value
                    raise AssertionError(f"{class_name}.{field} default is not a constant")
    raise AssertionError(f"missing {class_name}.{field}")


def _published_tool_names(tree: ast.Module) -> set[str]:
    constants = _module_string_constants(tree)
    published: set[str] = set()
    for node in ast.walk(_function(tree, "gsqs_eval_tools")):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != "Tool":
            continue
        for keyword in node.keywords:
            if keyword.arg != "name":
                continue
            value = keyword.value
            if isinstance(value, ast.Name) and value.id in constants:
                published.add(constants[value.id])
            elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                published.add(value.value)
    return published


def test_evaluator_digests_are_stable_and_exclude_remote_eval_modules() -> None:
    identity = evaluator_code_identity()
    digest = evaluator_implementation_digest()
    files = evaluator_implementation_files()
    names = [path.name for path in files]
    resolved = {path.resolve() for path in files}
    assert identity == EXPECTED_CODE_IDENTITY
    assert digest == EXPECTED_IMPLEMENTATION_DIGEST
    assert "goodnotes_gsqs.py" in names
    assert not any("goodnotes_gsqs_remote_eval" in name for name in names)
    assert "gsqs_remote_eval.py" not in names
    assert "gsqs_remote_eval_mcp.py" not in names
    assert "gsqs_remote_eval_authentication.py" not in names
    assert ADAPTER.resolve() not in resolved
    assert ENTRYPOINT.resolve() not in resolved
    assert AUTH.resolve() not in resolved
    assert SETTINGS.resolve() not in resolved
    prompt = ROOT / "ops" / "goodnotes" / "gsqs" / "b0" / "chatllm-remote-eval-prompt-v1.txt"
    assert prompt.resolve() not in resolved
    for path in REMOTE_EVAL_APPLICATION:
        assert path.resolve() not in resolved


def test_isolated_process_and_adapter_do_not_import_production_mcp_or_application_service() -> None:
    for path in ISOLATED_PROCESS_FILES:
        modules, names, package_names = _imported(path)
        leaked = _leaked_modules(modules)
        leaked_names = names & FORBIDDEN_IMPORT_NAMES
        leaked_package = package_names & FORBIDDEN_PACKAGE_IMPORT_NAMES
        assert not leaked, f"{path.name} imports {sorted(leaked)}"
        assert not leaked_names, f"{path.name} binds {sorted(leaked_names)}"
        assert not leaked_package, f"{path.name} imports {sorted(leaked_package)} from adapters.mcp"
        source = path.read_text(encoding="utf-8")
        assert "from my_pa.application.service" not in source
        assert "import my_pa.application.service" not in source
        assert "from my_pa.adapters.mcp.tools" not in source
        assert "import my_pa.adapters.mcp.tools" not in source
        assert "published_tools" not in source
        assert "create_mcp_server" not in source
        assert "ApplicationService" not in source


def test_eval_tools_do_not_publish_production_goodnotes_capabilities() -> None:
    tree = _tree(ADAPTER)
    published = _published_tool_names(tree)
    assert published == EVAL_TOOL_NAMES
    assert published.isdisjoint(PRODUCTION_TOOL_NAMES)
    assert _string_constants(tree).isdisjoint(PRODUCTION_TOOL_NAMES)
    constants = set(_module_string_constants(tree).values())
    assert constants >= EVAL_TOOL_NAMES


def test_status_payload_and_logs_omit_gold_and_source_paths() -> None:
    adapter = _tree(ADAPTER)
    status_keys = _dict_string_keys(_function(adapter, "_status_payload"))
    next_keys = _dict_string_keys(_function(adapter, "_next_result"))
    submit_keys = _dict_string_keys(_function(adapter, "_submit_result"))
    leaked = (status_keys | next_keys | submit_keys) & FORBIDDEN_PAYLOAD_KEYS
    assert not leaked, f"payload construction includes {sorted(leaked)}"
    assert "source_path" not in status_keys
    assert "path" not in status_keys
    application_status = _function(_tree(REMOTE_EVAL_APPLICATION[1]), "status")
    status_keywords = {
        keyword.arg
        for node in ast.walk(application_status)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "SessionStatus"
        for keyword in node.keywords
        if keyword.arg is not None
    }
    assert not (status_keywords & FORBIDDEN_PAYLOAD_KEYS)
    for path in LOG_SCAN_FILES:
        source = path.read_text(encoding="utf-8")
        tree = _tree(path)
        for call in _log_like_calls(tree):
            snippet = ast.get_source_segment(source, call) or ""
            for token in FORBIDDEN_LOG_TOKENS:
                assert token not in snippet, f"{path.name} log-like call leaks {token}: {snippet}"


def test_production_default_allowed_origins_are_empty_and_not_wildcard() -> None:
    settings = _tree(SETTINGS)
    default = _ann_assign_default(settings, "Settings", "gsqs_remote_eval_allowed_origins")
    assert default == ""
    assert default != "*"
    checker = _function(settings, "_check_gsqs_remote_eval")
    assert "*" in _string_constants(checker)
    factory = _function(_tree(ADAPTER), "create_gsqs_remote_eval_app")
    assert "*" in _string_constants(factory)


def test_entrypoint_disables_access_log_and_does_not_log_secrets() -> None:
    tree = _tree(ENTRYPOINT)
    runs = _uvicorn_run_calls(tree)
    assert runs, "entrypoint does not call uvicorn.run"
    for call in runs:
        assert _keyword_constant(call, "access_log") is False
    for path in ISOLATED_PROCESS_FILES:
        modules, _names, _package = _imported(path)
        assert "logging" not in modules
        source = path.read_text(encoding="utf-8")
        for call in _log_like_calls(_tree(path)):
            snippet = ast.get_source_segment(source, call) or ""
            for token in FORBIDDEN_LOG_TOKENS:
                assert token not in snippet, f"{path.name} leaks {token} in {snippet}"


def test_tools_py_does_not_publish_eval_tool_names() -> None:
    source = TOOLS.read_text(encoding="utf-8")
    literals = _string_constants(_tree(TOOLS))
    leaked = EVAL_TOOL_NAMES & literals
    assert not leaked, f"tools.py contains eval tool names {sorted(leaked)}"
    for name in EVAL_TOOL_NAMES:
        assert name not in source
    assert "goodnotes.eval." not in source


def test_production_mcp_package_init_does_not_import_remote_eval_adapter() -> None:
    modules, names, _package = _imported(MCP_INIT)
    assert "my_pa.adapters.mcp.gsqs_remote_eval" not in modules
    assert "gsqs_remote_eval" not in names
    source = MCP_INIT.read_text(encoding="utf-8")
    assert "gsqs_remote_eval" not in source
    for name in EVAL_TOOL_NAMES:
        assert name not in source
