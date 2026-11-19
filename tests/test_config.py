import json
from pathlib import Path

import pytest

from drytonic.config import (
    DEFAULT_PROTECTED_TEST_GLOBS,
    DEFAULT_RULES,
    ConfigError,
    load_config,
)


def write_config(root: Path, payload: object) -> Path:
    config_path = root / ".tonic" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def test_load_config_valida(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        {
            "rules": ["TN001", "TN003"],
            "protected_test_globs": ["**/spec_*.py"],
        },
    )

    config = load_config(tmp_path)

    assert config["rules"] == ["TN001", "TN003"]
    assert config["protected_test_globs"] == ["**/spec_*.py"]


def test_load_config_ausente_usa_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config == {
        "protected_test_globs": DEFAULT_PROTECTED_TEST_GLOBS,
        "rules": DEFAULT_RULES,
    }

    config["rules"].append("TN999")
    assert load_config(tmp_path)["rules"] == DEFAULT_RULES


def test_load_config_parcial_mantem_defaults(tmp_path: Path) -> None:
    write_config(tmp_path, {"rules": ["TN002"]})

    config = load_config(tmp_path)

    assert config["rules"] == ["TN002"]
    assert config["protected_test_globs"] == DEFAULT_PROTECTED_TEST_GLOBS


def test_load_config_json_corrompido(tmp_path: Path) -> None:
    config_path = tmp_path / ".tonic" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text('{"rules": ["TN001", ', encoding="utf-8")

    with pytest.raises(ConfigError, match="JSON inválido"):
        load_config(tmp_path)


def test_load_config_tipos_invalidos(tmp_path: Path) -> None:
    write_config(tmp_path, {"rules": "TN001"})

    with pytest.raises(ConfigError, match="'rules'"):
        load_config(tmp_path)
