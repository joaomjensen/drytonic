import sys
from pathlib import Path

import pytest

from drytonic.cli import main
from drytonic.guard import (
    GOVERNANCE_GLOBS,
    evaluate_guard,
    is_governance_path,
)


def test_is_governance_path_usar_globs_recursivos(tmp_path: Path) -> None:
    assert GOVERNANCE_GLOBS == [".opencode/**", ".tonic/**", "rules/**"]

    protegidos = [
        tmp_path / ".opencode" / "plugins" / "drytonic.js",
        tmp_path / ".opencode" / "config.json",
        tmp_path / ".tonic" / "config.json",
        tmp_path / ".tonic" / "disputes" / "DISPUTE-teste.md",
        tmp_path / "rules" / "python" / "tn001_to_tn006.yml",
    ]
    for caminho in protegidos:
        assert is_governance_path(caminho, tmp_path) is True, caminho

    # A proteção vale para arquivos novos, que ainda não existem no disco.
    assert not protegidos[0].exists()
    assert is_governance_path(protegidos[0], tmp_path) is True

    for caminho in (
        tmp_path / "src" / "app.py",
        tmp_path / "tests" / "test_app.py",
        tmp_path / "README.md",
    ):
        assert is_governance_path(caminho, tmp_path) is False, caminho


def test_evaluate_guard_categorias_e_precedencia(tmp_path: Path) -> None:
    governanca = tmp_path / ".opencode" / "plugins" / "novo.js"
    bloqueado, categoria, motivo = evaluate_guard(governanca, tmp_path)
    assert (bloqueado, categoria) == (True, "governance")
    assert "Arquivo de governança" in motivo
    assert ".opencode/**" in motivo

    teste = tmp_path / "tests" / "test_contrato.py"
    bloqueado, categoria, motivo = evaluate_guard(teste, tmp_path)
    assert (bloqueado, categoria) == (True, "test")
    assert "test_contrato.py" in motivo

    codigo = tmp_path / "src" / "app.py"
    bloqueado, categoria, motivo = evaluate_guard(codigo, tmp_path)
    assert bloqueado is False
    assert categoria == "open"
    assert isinstance(motivo, str) and motivo

    # Governança tem precedência quando o caminho também parece um teste.
    ambos = tmp_path / ".tonic" / "test_config.py"
    bloqueado, categoria, _ = evaluate_guard(ambos, tmp_path)
    assert (bloqueado, categoria) == (True, "governance")


def _executar_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: object
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["tonic", *(str(arg) for arg in args)])
    with pytest.raises(SystemExit) as saida:
        main()
    capturado = capsys.readouterr()
    return saida.value.code, capturado.out, capturado.err


def test_cli_guard_saida_e_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    governanca = tmp_path / ".opencode" / "plugins" / "novo.js"
    codigo, stdout, stderr = _executar_cli(monkeypatch, capsys, "guard", governanca)
    assert codigo == 2
    assert "[DRYTONIC GUARD:governance]" in stderr
    assert stdout == ""

    teste = tmp_path / "tests" / "test_alvo.py"
    teste.parent.mkdir(parents=True, exist_ok=True)
    teste.write_text("def test_alvo(): pass\n", encoding="utf-8")
    codigo, stdout, stderr = _executar_cli(monkeypatch, capsys, "guard", teste)
    assert codigo == 2
    assert "[DRYTONIC GUARD:test]" in stderr
    assert stdout == ""

    codigo = tmp_path / "src" / "app.py"
    codigo.parent.mkdir(parents=True, exist_ok=True)
    codigo.write_text("x = 1\n", encoding="utf-8")
    status, stdout, stderr = _executar_cli(monkeypatch, capsys, "guard", codigo)
    assert status == 0
    assert stdout.strip() == "OK"
    assert stderr == ""


def test_plugin_nao_duplica_regra_de_guard() -> None:
    plugin = Path(__file__).resolve().parents[1] / ".opencode" / "plugins" / "drytonic.js"
    fonte = plugin.read_text(encoding="utf-8")

    assert "isProtectedTest" not in fonte
    assert '["guard", absPath]' in fonte
    assert 'includes("GUARD:governance")' in fonte
    assert 'includes("GUARD:test")' in fonte
    assert "[drytonic] OK:" in fonte
