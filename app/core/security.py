import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

# 🔴 ARGON2 MALIYET PARAMETRELERI ACIKCA YAZILIR (SEC-ARGON, 2026-08-25).
# `PasswordHasher()` varsayilan parametrelerle kurulursa, kutuphane surumu degistigi
# gun O GUNDEN SONRAKI parolalar BASKA maliyetle hash'lenir. Argon2 ozeti kendi
# parametrelerini metninde tasidigi icin eskiler dogrulanmaya devam eder → hicbir test
# kirilmaz, hicbir uyari cikmaz ve veritabaninda IKI FARKLI guvenlik seviyesinde parola
# birikir. `ruff==0.15.22` / `pydantic==2.13.4` pinlerinin gerekcesiyle ayni sinif:
# uretilen artefakt (burada: ozetin maliyeti) aracin surumune baglidir, koda degil.
#
# 🔑 Degerler ICAT EDILMEDI: canlida bugun fiilen kosan argon2-cffi 25.1.0'in
# VARSAYILANLARI olculup yazildi (`PasswordHasher()` → t=3, m=65536, p=4, hash_len=32,
# salt_len=16; RFC 9106 "low memory" profili). 23.1.0 da ayni varsayilanlari tasiyor
# (olculdu) → mevcut hicbir parolanin maliyeti bu dilimle DEGISMEZ, kimse gereksiz
# yeniden hash'lenmez. Yukseltme AYRI bir karardir.
# Bekcisi: tests/core/test_argon2_parametreleri.py (iddia URETILEN OZET DIZESINDEN okunur)
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST = 65536
ARGON2_PARALLELISM = 4
ARGON2_HASH_LEN = 32
ARGON2_SALT_LEN = 16

_hasher = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_COST,
    parallelism=ARGON2_PARALLELISM,
    hash_len=ARGON2_HASH_LEN,
    salt_len=ARGON2_SALT_LEN,
)


class TokenError(Exception):
    """Token geçersiz, süresi geçmiş veya beklenen tipte değil."""


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    """Ozet GUNCEL parametrelerle uretilmemisse True.

    Yalnizca DOGRULAMASI BASARILI bir ozet icin cagrilmalidir — cagiran sozlesmesi.
    Bozuk/taninmayan ozet, "yeniden hash'lenecek bir sey yok" demektir (False):
    burada True donmek, dogrulanmamis bir girdiyle yazma tetiklerdi.
    """
    try:
        return _hasher.check_needs_rehash(hashed)
    except (InvalidHashError, ValueError):
        return False


@dataclass(frozen=True)
class DecodedToken:
    """Bir token'dan çözülen kimlik + iptal sürümü."""

    user_id: uuid.UUID
    token_version: int


def _create_token(
    user_id: uuid.UUID, token_version: int, token_type: str, expires_delta: timedelta
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, token_version: int) -> str:
    return _create_token(
        user_id, token_version, "access", timedelta(minutes=settings.access_token_expire_minutes)
    )


def create_refresh_token(user_id: uuid.UUID, token_version: int) -> str:
    return _create_token(
        user_id, token_version, "refresh", timedelta(days=settings.refresh_token_expire_days)
    )


def decode_token(token: str, expected_type: str) -> DecodedToken:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError("Token geçersiz veya süresi dolmuş") from exc

    if payload.get("type") != expected_type:
        raise TokenError("Token tipi beklenenden farklı")

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise TokenError("Token içeriği bozuk") from exc

    # Eski (ver'siz) token'lar 0 sayılır — geriye dönük uyumluluk (yeni sütun default 0).
    token_version = int(payload.get("ver", 0))
    return DecodedToken(user_id=user_id, token_version=token_version)
