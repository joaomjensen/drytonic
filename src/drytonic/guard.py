"""Proteção de testes contratuais e registro formal de disputas."""

from datetime import datetime
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path

from drytonic.config import load_config

GOVERNANCE_GLOBS: list[str] = [".opencode/**", ".tonic/**", "rules/**"]


class DisputeError(Exception):
    """Dados inválidos ou falha ao registrar uma disputa."""


def _padrao_relativo_a_raiz(path: Path, root_dir: Path) -> Path:
    """Retorna ``path`` relativo à raiz, mantendo-o intacto se estiver fora dela."""
    try:
        return path.relative_to(root_dir)
    except ValueError:
        return path


def _segmentos(texto: str) -> tuple[str, ...]:
    """Normaliza separadores e devolve os componentes relevantes do caminho."""
    return tuple(
        parte
        for parte in texto.replace("\\", "/").split("/")
        if parte not in ("", ".")
    )


def _corresponde_glob(caminho_relativo: str, pattern: str) -> bool:
    """Compara um caminho com um glob, onde ``**`` cruza zero ou mais diretórios.

    ``PurePath.match`` trata ``**`` de forma inconsistente (por exemplo,
    ``.opencode/**`` não alcança arquivos em subdiretórios), então a
    correspondência é feita segmento a segmento com ``fnmatchcase``.
    """
    partes_caminho = _segmentos(caminho_relativo)
    partes_glob = _segmentos(pattern)

    @lru_cache(maxsize=None)
    def casa(indice_glob: int, indice_caminho: int) -> bool:
        if indice_glob == len(partes_glob):
            return indice_caminho == len(partes_caminho)

        parte = partes_glob[indice_glob]
        if parte == "**":
            return casa(indice_glob + 1, indice_caminho) or (
                indice_caminho < len(partes_caminho)
                and casa(indice_glob, indice_caminho + 1)
            )
        if indice_caminho >= len(partes_caminho):
            return False
        if not fnmatchcase(partes_caminho[indice_caminho], parte):
            return False
        return casa(indice_glob + 1, indice_caminho + 1)

    return casa(0, 0)


def _glob_correspondente(
    path: Path, patterns: list[str], root_dir: Path | None = None
) -> str | None:
    """Retorna o primeiro glob que casa com ``path`` relativo à raiz."""
    root = Path.cwd() if root_dir is None else Path(root_dir)
    relativo = _padrao_relativo_a_raiz(Path(path), root).as_posix()
    for pattern in patterns:
        if _corresponde_glob(relativo, pattern):
            return pattern
    return None


def matched_protected_glob(path: Path, root_dir: Path | None = None) -> str | None:
    """Retorna o glob que protege ``path``, ou ``None`` se não houver proteção."""
    root = Path.cwd() if root_dir is None else Path(root_dir)
    return _glob_correspondente(path, load_config(root)["protected_test_globs"], root)


def is_protected_test(path: Path, root_dir: Path | None = None) -> bool:
    """Indica se ``path`` corresponde a um teste protegido pela configuração."""
    return matched_protected_glob(path, root_dir) is not None


def matched_governance_glob(path: Path, root_dir: Path | None = None) -> str | None:
    """Retorna o glob de governança que casa com ``path``, se houver."""
    return _glob_correspondente(path, GOVERNANCE_GLOBS, root_dir)


def is_governance_path(path: Path, root_dir: Path | None = None) -> bool:
    """Indica se ``path`` pertence à governança do projeto (raiz relativa)."""
    return matched_governance_glob(path, root_dir) is not None


def evaluate_guard(path: Path, root_dir: Path | None = None) -> tuple[bool, str, str]:
    """Avalia um caminho e devolve ``(bloqueado, categoria, motivo)``.

    Governança é sempre bloqueada, inclusive para arquivos ainda não criados,
    e tem precedência sobre testes protegidos.
    """
    governance = matched_governance_glob(path, root_dir)
    if governance is not None:
        return (
            True,
            "governance",
            f"Arquivo de governança protegido por '{governance}': {path}. "
            "Alterações exigem aprovação explícita fora do fluxo automático.",
        )

    teste = matched_protected_glob(path, root_dir)
    if teste is not None:
        return (
            True,
            "test",
            f"Teste protegido por '{teste}': {path}. "
            "Abra uma disputa com 'tonic dispute' para propor alterações.",
        )

    return False, "open", f"{path} não é teste protegido nem arquivo de governança."


def create_dispute(
    test_path: Path,
    reason: str,
    proposed_change: str,
    root_dir: Path | None = None,
) -> Path:
    """Grava uma disputa estruturada sobre um teste protegido.

    Raises:
        DisputeError: se o teste não existir, os campos estiverem vazios ou
            não for possível gravar o documento.
    """
    test_file = Path(test_path)
    if not test_file.is_file():
        raise DisputeError(f"Arquivo de teste não encontrado: {test_file}")

    motivo = reason.strip() if isinstance(reason, str) else ""
    proposta = proposed_change.strip() if isinstance(proposed_change, str) else ""
    if not motivo:
        raise DisputeError("O motivo da disputa não pode ser vazio.")
    if not proposta:
        raise DisputeError("A proposta de alteração não pode ser vazia.")

    root = Path.cwd() if root_dir is None else Path(root_dir)
    try:
        teste_exibido = test_file.relative_to(root).as_posix()
    except ValueError:
        teste_exibido = test_file.as_posix()

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    disputes_dir = root / ".tonic" / "disputes"
    dispute_path = disputes_dir / f"DISPUTE-{timestamp}-{test_file.stem}.md"

    conteudo = (
        f"# Disputa: {test_file.name}\n\n"
        f"- **Status:** aberta\n"
        f"- **Teste protegido:** `{teste_exibido}`\n"
        f"- **Criada em:** {datetime.now().astimezone().isoformat(timespec='seconds')}\n\n"
        "## Motivo\n\n"
        f"{motivo}\n\n"
        "## Alteração proposta\n\n"
        f"{proposta}\n\n"
        "## Próximos passos\n\n"
        "1. Revisar o contrato e a proposta com o mantenedor responsável.\n"
        "2. Atualizar o teste protegido (ou o código) somente após aprovação.\n"
        "3. Registrar a decisão final neste documento e fechar a disputa.\n"
    )

    try:
        disputes_dir.mkdir(parents=True, exist_ok=True)
        dispute_path.write_text(conteudo, encoding="utf-8")
    except OSError as err:
        raise DisputeError(f"Não foi possível gravar a disputa em {dispute_path}: {err}") from err

    return dispute_path
