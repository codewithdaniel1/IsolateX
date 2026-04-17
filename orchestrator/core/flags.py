import hmac
import hashlib
from orchestrator.config import settings


def derive_flag(team_id: str, challenge_id: str, instance_id: str, salt: str) -> str:
    """
    Derives a deterministic per-team flag so that:
    - each team gets a unique flag
    - leaking one flag does not solve the challenge for anyone else
    - flags are reproducible (useful for verification without storing plaintext)

    Format: flag{<hex>}
    """
    material = f"{team_id}:{challenge_id}:{instance_id}:{salt}"
    digest = hmac.new(
        settings.flag_hmac_secret.encode(),
        material.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{settings.flag_prefix}{{{digest}}}"
