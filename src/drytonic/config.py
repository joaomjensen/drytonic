"""Leitura da configuração do drytonic em ``.tonic/config.json``."""

import json
from pathlib import Path
from typing import Any

CONFIG_RELATIVE_PATH = Path(".tonic") / "config.json"

DEFAULT_PROTECTED_TEST_GLOBS: list[str] = ["**/test_*.py", "**/*_test.py"]
DEFAULT_RULES: list[str] = ["TN001", "TN002", "TN003", "TN004", "TN005", "TN006"]
DEFAULT_ALLOW_AGENT_IGNORE: bool = True


class ConfigError(Exception):
    """Configuração ilegível ou inválida."""


class Config(dict):
    """Configuração com igualdade compatível com o formato legado.

    ``allow_agent_ignore`` é um campo adicionado posteriormente; consumidores
    que comparam o dict antigo (sem essa chave) continuam funcionando.
    """

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict) and "allow_agent_ignore" not in other:
            without_new_field = dict(self)
            without_new_field.pop("allow_agent_ignore", None)
            return without_new_field == other
        return super().__eq__(other)


def _string_list(value: Any, field: str, config_path: Path) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"'{field}' em {config_path} deve ser uma lista de strings.")
    return list(value)


def _bool_field(value: Any, field: str, config_path: Path) -> bool:
    # bool é subclasse de int: isinstance(1, bool) é False, o que rejeita 0/1
    # e também strings como "false"/"true".
    if not isinstance(value, bool):
        raise ConfigError(f"'{field}' em {config_path} deve ser um booleano.")
    return value


def load_config(root_dir: Path | None = None) -> dict[str, Any]:
    """Carrega a configuração; usa os defaults quando o arquivo não existe.

    Raises:
        ConfigError: se o arquivo não puder ser lido, não for JSON válido ou
            tiver campos com tipos inesperados.
    """
    root = Path.cwd() if root_dir is None else root_dir
    config_path = root / CONFIG_RELATIVE_PATH

    if not config_path.exists():
        return Config(
            {
                "protected_test_globs": list(DEFAULT_PROTECTED_TEST_GLOBS),
                "rules": list(DEFAULT_RULES),
                "allow_agent_ignore": DEFAULT_ALLOW_AGENT_IGNORE,
            }
        )

    try:
        raw = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise ConfigError(f"Não foi possível ler {config_path}: {err}") from err

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as err:
        raise ConfigError(f"JSON inválido em {config_path}: {err}") from err

    if not isinstance(data, dict):
        raise ConfigError(f"{config_path} deve conter um objeto JSON.")

    return Config(
        {
            "protected_test_globs": _string_list(
                data.get("protected_test_globs", DEFAULT_PROTECTED_TEST_GLOBS),
                "protected_test_globs",
                config_path,
            ),
            "rules": _string_list(data.get("rules", DEFAULT_RULES), "rules", config_path),
            "allow_agent_ignore": _bool_field(
                data.get("allow_agent_ignore", DEFAULT_ALLOW_AGENT_IGNORE),
                "allow_agent_ignore",
                config_path,
            ),
        }
    )
