import json
import sys
from pathlib import Path

import pytest

from drytonic.cli import main
from drytonic.guard import DisputeError, create_dispute, is_protected_test


def test_is_protected_test_usa_globs_do_config(tmp_path: Path) -> None:
    assert is_protected_test(tmp_path / "tests" / "test_config.py", tmp_path) is True
    assert is_protected_test(tmp_path / "pkg" / "user_test.py", tmp_path) is True
    assert is_protected_test(tmp_path / "src" / "drytonic" / "cli.py", tmp_path) is False

    cfg = tmp_path / ".tonic" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"protected_test_globs": ["contracts/*.py"]}), encoding="utf-8")

    assert is_protected_test(tmp_path / "contracts" / "api.py", tmp_path) is True
    assert is_protected_test(tmp_path / "tests" / "test_config.py", tmp_path) is False


def test_create_dispute_gera_markdown_estruturado(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_sample.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_ok(): assert True\n", encoding="utf-8")

    dispute_path = create_dispute(
        test_path=test_file,
        reason="Contrato exige retorno síncrono incompatível com I/O.",
        proposed_change="Alterar assinatura esperada para async.",
        root_dir=tmp_path,
    )

    assert dispute_path.exists()
    assert dispute_path.parent == tmp_path / ".tonic" / "disputes"
    content = dispute_path.read_text(encoding="utf-8")
    assert "test_sample.py" in content
    assert "Contrato exige retorno síncrono" in content
    assert "Alterar assinatura esperada para async." in content


def test_create_dispute_valida_inputs(tmp_path: Path) -> None:
    missing = tmp_path / "tests" / "nao_existe.py"
    with pytest.raises(DisputeError):
        create_dispute(missing, "Motivo válido", "Proposta válida", root_dir=tmp_path)

    existing = tmp_path / "tests" / "test_real.py"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("def test_x(): pass\n", encoding="utf-8")

    with pytest.raises(DisputeError):
        create_dispute(existing, "   ", "Proposta válida", root_dir=tmp_path)

    with pytest.raises(DisputeError):
        create_dispute(existing, "Motivo válido", "", root_dir=tmp_path)


def test_cli_guard_e_dispute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    test_file = tmp_path / "tests" / "test_alvo.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_a(): pass\n", encoding="utf-8")

    src_file = tmp_path / "src" / "app.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("x = 1\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(sys, "argv", ["tonic", "guard", str(test_file)])
    with pytest.raises(SystemExit) as exc_protected:
        main()
    assert exc_protected.value.code == 2

    monkeypatch.setattr(sys, "argv", ["tonic", "guard", str(src_file)])
    with pytest.raises(SystemExit) as exc_open:
        main()
    assert exc_open.value.code == 0

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tonic",
            "dispute",
            str(test_file),
            "--reason",
            "Asserção desatualizada",
            "--proposal",
            "Atualizar expectativa",
        ],
    )
    with pytest.raises(SystemExit) as exc_dispute:
        main()
    assert exc_dispute.value.code == 0
    out = capsys.readouterr().out
    assert "DISPUTE-" in out
