import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    """Gera hash seguro da senha usando PBKDF2 (HMAC-SHA256) com salt aleatório."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verifica a senha contra o hash armazenado."""
    try:
        algo, salt_hex, dk_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            100_000,
        )
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def new_session_token() -> str:
    """Gera um token de sessão forte e aleatório."""
    return secrets.token_urlsafe(48)
