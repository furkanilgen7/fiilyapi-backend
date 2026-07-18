import uuid

import pytest

from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_password_does_not_return_plaintext():
    hashed = hash_password("gizli-parola")
    assert hashed != "gizli-parola"
    assert hashed.startswith("$argon2")


def test_verify_password_accepts_correct_and_rejects_wrong():
    hashed = hash_password("gizli-parola")
    assert verify_password("gizli-parola", hashed) is True
    assert verify_password("yanlis-parola", hashed) is False


def test_same_password_hashes_differently_each_time():
    """Tuz (salt) kullanıldığını doğrular — aynı parola iki farklı özet üretmeli."""
    assert hash_password("ayni") != hash_password("ayni")


def test_verify_password_on_corrupt_hash_returns_false():
    """Bozuk özet çökmeye değil, False'a dönüşmeli."""
    assert verify_password("herhangi", "bu-bir-argon2-ozeti-degil") is False


def test_access_token_roundtrips_user_id_and_version():
    user_id = uuid.uuid4()
    token = create_access_token(user_id, 3)
    decoded = decode_token(token, expected_type="access")
    assert decoded.user_id == user_id
    assert decoded.token_version == 3


def test_token_without_version_claim_defaults_to_zero():
    """Eski (ver'siz) token'lar geriye dönük uyumlu olsun diye 0 sayılır."""
    import jwt

    from app.core.config import settings

    payload = {"sub": str(uuid.uuid4()), "type": "access"}
    legacy = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    assert decode_token(legacy, expected_type="access").token_version == 0


def test_refresh_token_is_not_accepted_as_access_token():
    """Token tipi karıştırılamaz — refresh ile korumalı uca girilemez."""
    token = create_refresh_token(uuid.uuid4(), 0)
    with pytest.raises(TokenError):
        decode_token(token, expected_type="access")


def test_garbage_token_raises():
    with pytest.raises(TokenError):
        decode_token("bu-bir-token-degil", expected_type="access")
