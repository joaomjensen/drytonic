import logging

logger = logging.getLogger(__name__)


def fetch_user_profile(api_client, user_id: str):
    try:
        return api_client.get(user_id)
    except ConnectionError:
        return None  # Deve disparar TN003


def parse_payload(raw: str):
    try:
        return int(raw)
    except ValueError as err:
        raise RuntimeError("Payload inválido")  # Deve disparar TN004 (sem 'from err')


def read_optional_cache(cache, key: str):
    try:
        return cache[key]
    # tonic-ignore TN003: cache local opcional, miss segue para busca primária
    except KeyError:
        return None  # Deve PASSAR por ter justificativa válida