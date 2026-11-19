import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from drytonic.cli import collect_python_files, collect_source_files, main
from drytonic.templates import render_claude_settings, render_opencode_plugin

RULES = ["TN001", "TN002", "TN003", "TN004", "TN005", "TN006"]

# (extension, code that must be blocked, same code with an auditable ignore)
CASES: dict[str, list[tuple[str, str, str]]] = {
    "TN001": [
        (
            "ts",
            "function f() {\n  try { risky(); } catch (err) {}\n}\n",
            "function f() {\n  try { risky(); } catch (err) {} // tonic-ignore TN001: empty catch is deliberate\n}\n",
        ),
        (
            "js",
            "function f() {\n  try { risky(); } catch {}\n}\n",
            "function f() {\n  try { risky(); } catch {} // tonic-ignore TN001: empty catch is deliberate\n}\n",
        ),
    ],
    "TN002": [
        (
            "ts",
            "function f() {\n  try { risky(); } catch (err) {\n    console.error(err);\n  }\n}\n",
            "function f() {\n  try { risky(); } catch (err) { // tonic-ignore TN002: telemetry only\n    console.error(err);\n  }\n}\n",
        ),
        (
            "js",
            "function f() {\n  try { risky(); } catch (err) {\n    console.warn('oops');\n  }\n}\n",
            "function f() {\n  try { risky(); } catch (err) { // tonic-ignore TN002: telemetry only\n    console.warn('oops');\n  }\n}\n",
        ),
    ],
    "TN003": [
        (
            "ts",
            "function f() {\n  try { risky(); } catch (err) {\n    return null;\n  }\n}\n",
            "function f() {\n  try { risky(); } catch (err) { // tonic-ignore TN003: null is the API contract\n    return null;\n  }\n}\n",
        ),
        (
            "js",
            "function f() {\n  try { risky(); } catch (err) {\n    return [];\n  }\n}\n",
            "function f() {\n  try { risky(); } catch (err) { // tonic-ignore TN003: empty batch is the API contract\n    return [];\n  }\n}\n",
        ),
    ],
    "TN004": [
        (
            "ts",
            "function f() {\n  try { risky(); } catch (err) {\n    throw new Error('boom');\n  }\n}\n",
            "function f() {\n  try { risky(); } catch (err) { // tonic-ignore TN004: root cause is not sensitive\n    throw new Error('boom');\n  }\n}\n",
        ),
        (
            "js",
            "function f() {\n  try { risky(); } catch (err) {\n    throw new TypeError('boom');\n  }\n}\n",
            "function f() {\n  try { risky(); } catch (err) { // tonic-ignore TN004: root cause is not sensitive\n    throw new TypeError('boom');\n  }\n}\n",
        ),
    ],
    # `catch (err: any)` is TypeScript-only by definition.
    "TN005": [
        (
            "ts",
            "function f() {\n  try { risky(); } catch (err: any) {\n    handle(err);\n  }\n}\n",
            "function f() {\n  try { risky(); } catch (err: any) { // tonic-ignore TN005: SDK is untyped at this boundary\n    handle(err);\n  }\n}\n",
        ),
    ],
    "TN006": [
        (
            "ts",
            "function f() {\n  for (const item of items) {\n    try { handle(item); } catch (err) { continue; }\n  }\n}\n",
            "function f() {\n  for (const item of items) {\n    try { handle(item); } catch (err) { continue; } // tonic-ignore TN006: skip known bad rows\n  }\n}\n",
        ),
        (
            "js",
            "function f() {\n  for (const item of items) {\n    try { handle(item); } catch (err) { continue; }\n  }\n}\n",
            "function f() {\n  for (const item of items) {\n    try { handle(item); } catch (err) { continue; } // tonic-ignore TN006: skip known bad rows\n  }\n}\n",
        ),
    ],
}


def write_config(root: Path, rules: list[str], **extra: object) -> None:
    payload: dict[str, Any] = {"rules": rules}
    payload.update(extra)
    config_path = root / ".tonic" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")


def run_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: object
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["tonic", *(str(arg) for arg in args)])
    with pytest.raises(SystemExit) as saida:
        main()
    captured = capsys.readouterr()
    return saida.value.code, captured.out, captured.err


@pytest.mark.parametrize("rule", RULES)
def test_regra_typescript_bloqueia_e_ignore_e_auditavel(
    rule: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_config(tmp_path, [rule])
    monkeypatch.chdir(tmp_path)

    for extension, violating, ignored in CASES[rule]:
        target = tmp_path / f"sample.{extension}"
        target.write_text(violating, encoding="utf-8")

        status, _, stderr = run_cli(monkeypatch, capsys, "check", target)
        assert status == 2, f"{rule} ({extension}): {stderr}"
        assert f"[{rule}]" in stderr

        target.write_text(ignored, encoding="utf-8")
        status, stdout, stderr = run_cli(monkeypatch, capsys, "check", target)
        assert status == 0, f"{rule} ({extension}) com ignore: {stderr}"
        assert stderr == ""
        assert "OK: 1 arquivo(s) passou(ram) nas regras ativas." in stdout


def test_cause_encadeado_nao_dispara_tn004(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_config(tmp_path, ["TN004"])
    target = tmp_path / "sample.ts"
    target.write_text(
        "function f() {\n"
        "  try { risky(); } catch (err) {\n"
        "    throw new Error('boom', { cause: err });\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    status, _, stderr = run_cli(monkeypatch, capsys, "check", target)

    assert status == 0
    assert stderr == ""


def test_allow_agent_ignore_false_rejeita_commentario_ts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_config(tmp_path, ["TN003"], allow_agent_ignore=False)
    target = tmp_path / "sample.ts"
    target.write_text(CASES["TN003"][0][2], encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    status, _, stderr = run_cli(monkeypatch, capsys, "check", target)

    assert status == 2
    assert "[TN003]" in stderr
    assert "allow_agent_ignore: false exige revisão humana para exceções" in stderr


def test_check_varre_todas_as_extensoes_e_ignora_diretorios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_config(tmp_path, ["TN003"])
    sources = {
        "src/a.py": "def f():\n    try: risky()\n    except Exception:\n        return None\n",
        "src/b.ts": "function f() { try { risky(); } catch (e) { return null; } }\n",
        "src/c.tsx": "function f() { try { risky(); } catch (e) { return undefined; } }\n",
        "src/d.js": "function f() { try { risky(); } catch (e) { return false; } }\n",
        "src/e.jsx": "function f() { try { risky(); } catch (e) { return ''; } }\n",
        "node_modules/lib.ts": "function f() { try { risky(); } catch (e) { return null; } }\n",
        "dist/out.js": "function f() { try { risky(); } catch (e) { return null; } }\n",
        ".next/build.ts": "function f() { try { risky(); } catch (e) { return null; } }\n",
        ".venv/lib.py": "x = 1\n",
        "__pycache__/x.py": "x = 1\n",
    }
    for relative, content in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    status, _, stderr = run_cli(monkeypatch, capsys, "check", tmp_path)

    assert status == 2
    assert stderr.count("[TN003]") == 5
    assert "violação(ões) em 5 arquivo(s) verificado(s)." in stderr
    assert "node_modules" not in stderr
    assert "dist" not in stderr
    assert ".next" not in stderr


def test_collect_source_files_mantem_alias_python(tmp_path: Path) -> None:
    expected = {
        tmp_path / "a.py",
        tmp_path / "b.ts",
        tmp_path / "c.tsx",
        tmp_path / "d.js",
        tmp_path / "e.jsx",
    }
    for path in (*expected, tmp_path / "node_modules" / "ignored.ts"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    assert set(collect_source_files(tmp_path)) == expected
    assert collect_python_files is collect_source_files
    assert collect_python_files(tmp_path / "b.ts") == [tmp_path / "b.ts"]
    assert collect_python_files(tmp_path / "notes.md") == []


def test_guard_protege_testes_typescript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "src" / "api.test.ts"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("test('ok', () => {});\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    status, _, stderr = run_cli(monkeypatch, capsys, "guard", target)

    assert status == 2
    assert "[DRYTONIC GUARD:test]" in stderr


def test_init_cria_gates_para_opencode_e_claude(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    status, _, _ = run_cli(monkeypatch, capsys, "init")

    assert status == 0
    config = json.loads((tmp_path / ".tonic" / "config.json").read_text(encoding="utf-8"))
    assert config["rules"] == RULES
    assert config["allow_agent_ignore"] is True
    assert "**/*.test.ts" in config["protected_test_globs"]
    assert "**/*.spec.tsx" in config["protected_test_globs"]
    assert "**/*.spec.jsx" in config["protected_test_globs"]

    plugin_path = tmp_path / ".opencode" / "plugins" / "drytonic.js"
    plugin = plugin_path.read_text(encoding="utf-8")
    for token in (
        "callID",
        "tool.execute.before",
        "tool.execute.after",
        '["guard", absPath]',
        '["check", absPath]',
        ".venv",
        '"tonic"',
        '".py"',
        '".ts"',
        '".tsx"',
        '".js"',
        '".jsx"',
    ):
        assert token in plugin, token

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]
    assert hooks["PreToolUse"][0]["matcher"] == "Edit|Write"
    assert hooks["PreToolUse"][0]["hooks"][0]["command"] == 'tonic guard "$CLAUDE_FILE_PATHS"'
    assert hooks["PostToolUse"][0]["matcher"] == "Edit|Write"
    assert hooks["PostToolUse"][0]["hooks"][0]["command"] == 'tonic check "$CLAUDE_FILE_PATHS"'

    node = shutil.which("node")
    if node:
        result = subprocess.run(
            [node, "--check", str(plugin_path)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr


def test_templates_sao_isolados_e_reutilizaveis() -> None:
    first = render_claude_settings()
    first["hooks"]["PreToolUse"].clear()

    second = render_claude_settings()
    assert len(second["hooks"]["PreToolUse"]) == 1
    assert len(second["hooks"]["PostToolUse"]) == 1
    assert render_opencode_plugin() == render_opencode_plugin()
