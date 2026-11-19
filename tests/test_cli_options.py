import json
import sys
from pathlib import Path

import pytest

from drytonic.cli import main
from drytonic.config import (
    DEFAULT_ALLOW_AGENT_IGNORE,
    ConfigError,
    load_config,
)


def write_config(root: Path, payload: object) -> Path:
    config_path = root / ".tonic" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def run_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: object
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["tonic", *(str(arg) for arg in args)])
    with pytest.raises(SystemExit) as saida:
        main()
    capturado = capsys.readouterr()
    return saida.value.code, capturado.out, capturado.err


CODIGO_COM_IGNORE = """def fetch():
    try:
        return 1
    except Exception:  # tonic-ignore TN003: contrato legado
        return None
"""

CODIGO_COM_VIOLACAO = """def fetch():
    try:
        return 1
    except Exception:
        return None
"""


@pytest.mark.parametrize("valor", [True, False])
def test_allow_agent_ignore_valores_booleanos(tmp_path: Path, valor: bool) -> None:
    write_config(tmp_path, {"allow_agent_ignore": valor})

    config = load_config(tmp_path)

    assert config["allow_agent_ignore"] is valor


@pytest.mark.parametrize("payload", [{}, {"rules": ["TN003"]}])
def test_allow_agent_ignore_ausente_usa_default(
    tmp_path: Path, payload: dict
) -> None:
    write_config(tmp_path, payload)

    assert load_config(tmp_path)["allow_agent_ignore"] is DEFAULT_ALLOW_AGENT_IGNORE


def test_allow_agent_ignore_sem_arquivo_usa_default(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config["allow_agent_ignore"] is True
    assert config["allow_agent_ignore"] is DEFAULT_ALLOW_AGENT_IGNORE


@pytest.mark.parametrize("valor_invalido", ["false", "true", 1, 0, None, [], {}])
def test_allow_agent_ignore_rejeita_tipos_invalidos(
    tmp_path: Path, valor_invalido: object
) -> None:
    write_config(tmp_path, {"allow_agent_ignore": valor_invalido})

    with pytest.raises(ConfigError, match="allow_agent_ignore"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    ("valor_config", "status_esperado"),
    [(False, 2), (True, 0), ("__ausente__", 0)],
)
def test_check_ignora_comentario_segundo_allow_agent_ignore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    valor_config: object,
    status_esperado: int,
) -> None:
    payload: dict = {"rules": ["TN003"]}
    if valor_config != "__ausente__":
        payload["allow_agent_ignore"] = valor_config
    write_config(tmp_path, payload)

    alvo = tmp_path / "sample.py"
    alvo.write_text(CODIGO_COM_IGNORE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    status, stdout, stderr = run_cli(monkeypatch, capsys, "check", alvo)

    assert status == status_esperado
    if status_esperado == 2:
        assert "[TN003]" in stderr
        assert "allow_agent_ignore: false exige revisão humana para exceções" in stderr
        assert "OK:" not in stdout
    else:
        assert stderr == ""
        assert "OK: 1 arquivo(s) passou(ram) nas regras ativas." in stdout


def test_check_multiplos_arquivos_reporta_contagem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_config(tmp_path, {"rules": ["TN003"], "allow_agent_ignore": True})
    primeiro = tmp_path / "primeiro.py"
    segundo = tmp_path / "segundo.py"
    primeiro.write_text(CODIGO_COM_VIOLACAO, encoding="utf-8")
    segundo.write_text(CODIGO_COM_VIOLACAO, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    status, stdout, stderr = run_cli(
        monkeypatch, capsys, "check", primeiro, segundo, primeiro
    )

    assert status == 2
    assert "primeiro.py" in stderr
    assert "segundo.py" in stderr
    assert stderr.count("[TN003]") == 2
    assert "2 violação(ões) em 2 arquivo(s) verificado(s)." in stderr
    assert stdout == ""


def test_check_multiplos_alvos_sem_duplicatas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_config(tmp_path, {"rules": ["TN003"], "allow_agent_ignore": True})
    primeiro = tmp_path / "src" / "primeiro.py"
    segundo = tmp_path / "src" / "segundo.py"
    primeiro.parent.mkdir(parents=True, exist_ok=True)
    primeiro.write_text("x = 1\n", encoding="utf-8")
    segundo.write_text("y = 2\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    status, stdout, stderr = run_cli(
        monkeypatch, capsys, "check", tmp_path / "src", primeiro, primeiro
    )

    assert status == 0
    assert stderr == ""
    assert "OK: 2 arquivo(s) passou(ram) nas regras ativas." in stdout


def test_init_gera_config_com_allow_agent_ignore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    status, _, _ = run_cli(monkeypatch, capsys, "init")

    assert status == 0
    config = json.loads((tmp_path / ".tonic" / "config.json").read_text(encoding="utf-8"))
    assert config["allow_agent_ignore"] is True
