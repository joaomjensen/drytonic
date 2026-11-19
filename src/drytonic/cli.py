import json
import re
import sys
from pathlib import Path

import yaml
from ast_grep_py import SgRoot

from drytonic.config import (
    CONFIG_RELATIVE_PATH,
    DEFAULT_PROTECTED_TEST_GLOBS,
    DEFAULT_RULES,
    ConfigError,
    load_config,
)
from drytonic.guard import (
    DisputeError,
    create_dispute,
    evaluate_guard,
)

IGNORE_PATTERN = re.compile(r"#\s*tonic-ignore\s+(TN\d{3})\s*:\s*(.{5,})")
IGNORED_DIRS = {".venv", "__pycache__"}


def load_rules(rules_path: Path) -> list[dict]:
    with rules_path.open("r", encoding="utf-8") as f:
        return [doc for doc in yaml.safe_load_all(f) if doc]


def has_valid_ignore(lines: list[str], line_idx: int, rule_id: str) -> bool:
    candidates = [lines[line_idx]]
    if line_idx > 0:
        candidates.append(lines[line_idx - 1])
    for line in candidates:
        match = IGNORE_PATTERN.search(line)
        if match and match.group(1) == rule_id:
            return True
    return False


def check_file(target: Path, rules: list[dict]) -> list[str]:
    source = target.read_text(encoding="utf-8")
    lines = source.splitlines()
    root = SgRoot(source, "python").root()
    diagnostics: list[str] = []

    for rule_doc in rules:
        config: dict = {"rule": rule_doc["rule"]}
        if "constraints" in rule_doc:
            config["constraints"] = rule_doc["constraints"]

        for node in root.find_all(config):
            start = node.range().start
            if has_valid_ignore(lines, start.line, rule_doc["id"]):
                continue

            snippet = "\n│  ".join(node.text().splitlines()[:4])
            remediation = "\n│  ".join(rule_doc["remediation"].strip().splitlines())
            diagnostics.append(
                f"[{rule_doc['id']}] {rule_doc['name']} em {target}:{start.line + 1}:{start.column + 1}\n"
                f"├─ Trecho bloqueado:\n│  {snippet}\n"
                f"├─ Motivo:\n│  {rule_doc['message']}\n"
                f"└─ Como corrigir:\n│  {remediation}"
            )
    return diagnostics


def collect_python_files(target: Path) -> list[Path]:
    """Lista arquivos .py de um arquivo ou de um diretório, recursivamente."""
    if target.is_file():
        return [target] if target.suffix == ".py" else []

    return sorted(
        path
        for path in target.rglob("*.py")
        if not any(part in IGNORED_DIRS for part in path.parts)
    )


def config_root_for(target: Path) -> Path:
    """Retorna a raiz com .tonic/config.json mais próxima do alvo, ou o cwd."""
    start = target if target.is_dir() else target.parent
    for candidate in (start, *start.parents):
        if (candidate / CONFIG_RELATIVE_PATH).exists():
            return candidate
    return Path.cwd()


def cmd_init(root_dir: Path) -> int:
    tonic_dir = root_dir / ".tonic"
    tonic_dir.mkdir(exist_ok=True)
    config_file = tonic_dir / "config.json"
    if not config_file.exists():
        config_file.write_text(
            json.dumps(
                {
                    "protected_test_globs": list(DEFAULT_PROTECTED_TEST_GLOBS),
                    "rules": list(DEFAULT_RULES),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    claude_dir = root_dir / ".claude"
    claude_dir.mkdir(exist_ok=True)
    settings_file = claude_dir / "settings.json"
    settings = {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "Edit|Write",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "tonic check \"$CLAUDE_FILE_PATHS\"",
                        }
                    ],
                }
            ]
        }
    }
    settings_file.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print("drytonic inicializado em .tonic/config.json e .claude/settings.json")
    return 0


def cmd_guard(target: Path) -> int:
    """Bloqueia governança e testes protegidos usando a regra centralizada."""
    try:
        bloqueado, categoria, motivo = evaluate_guard(target, config_root_for(target))
    except ConfigError as err:
        print(f"Erro de configuração: {err}", file=sys.stderr)
        return 1

    if bloqueado:
        print(f"[DRYTONIC GUARD:{categoria}] {motivo}", file=sys.stderr)
        return 2

    print("OK")
    return 0


DISPUTE_OPTIONS = {
    "--reason": "motivo",
    "--motivo": "motivo",
    "--proposal": "proposta",
    "--proposta": "proposta",
}


def parse_dispute_args(args: list[str]) -> tuple[Path, str, str]:
    """Extrai arquivo de teste, motivo e proposta dos argumentos da CLI."""
    if not args:
        raise ValueError("informe o caminho do arquivo de teste.")

    test_path = Path(args[0])
    values: dict[str, str] = {}
    index = 1
    while index < len(args):
        flag = args[index]
        field = DISPUTE_OPTIONS.get(flag)
        if field is None:
            raise ValueError(f"opção desconhecida: {flag}")
        if index + 1 >= len(args):
            raise ValueError(f"falta o valor da opção {flag}")
        values[field] = args[index + 1]
        index += 2

    for field, flag in (("motivo", "--reason"), ("proposta", "--proposal")):
        if field not in values:
            raise ValueError(f"falta a opção obrigatória {flag}")

    return test_path, values["motivo"], values["proposta"]


def cmd_dispute(args: list[str]) -> int:
    """Cria um documento de disputa para um teste protegido."""
    try:
        test_path, reason, proposal = parse_dispute_args(args)
    except ValueError as err:
        print(f"Erro: {err}", file=sys.stderr)
        print(
            'Uso: tonic dispute <arquivo_teste> --reason "<motivo>" --proposal "<proposta>"',
            file=sys.stderr,
        )
        return 1

    try:
        dispute_path = create_dispute(test_path, reason, proposal, config_root_for(test_path))
    except (DisputeError, ConfigError) as err:
        print(f"Erro ao criar disputa: {err}", file=sys.stderr)
        return 1

    print(dispute_path)
    return 0


def main() -> None:
    if len(sys.argv) < 2:
        print(
            'Uso: tonic <init|check|guard|dispute> [arquivo.py|diretorio]',
            file=sys.stderr,
        )
        sys.exit(1)

    command = sys.argv[1]
    if command == "init":
        sys.exit(cmd_init(Path.cwd()))

    if command == "check":
        if len(sys.argv) < 3:
            print("Erro: informe o caminho de um arquivo ou diretório Python.", file=sys.stderr)
            sys.exit(1)

        target = Path(sys.argv[2])
        try:
            config = load_config(config_root_for(target))
        except ConfigError as err:
            sys.exit(f"Erro de configuração: {err}")

        enabled_rules = set(config["rules"])
        rules_file = Path(__file__).resolve().parents[2] / "rules/python/tn001_to_tn006.yml"
        rules = [
            rule_doc
            for rule_doc in load_rules(rules_file)
            if rule_doc["id"] in enabled_rules
        ]

        files = collect_python_files(target)
        errors: list[str] = []
        for file_path in files:
            errors.extend(check_file(file_path, rules))

        if errors:
            print("\n\n".join(errors), file=sys.stderr)
            sys.exit(2)

        if files:
            print(f"OK: {len(files)} arquivo(s) passou(ram) nas regras ativas.")
        sys.exit(0)

    if command == "guard":
        if len(sys.argv) < 3:
            print("Erro: informe o caminho do arquivo a ser verificado.", file=sys.stderr)
            sys.exit(1)
        sys.exit(cmd_guard(Path(sys.argv[2])))

    if command == "dispute":
        sys.exit(cmd_dispute(sys.argv[2:]))

    print(f"Comando desconhecido: {command}", file=sys.stderr)
    sys.exit(1)
