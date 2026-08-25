"""SEC-ARGON: başarılı girişte eski parametreli parola özetinin yeniden yazılması.

Parametreler yükseltildiğinde eski özetler DOĞRULANMAYA DEVAM EDER (argon2 özeti
parametrelerini metninde taşır) — yani hiçbir şey kırılmaz ve eski/zayıf maliyetli
parolalar veritabanında SONSUZA KADAR kalır. Tek düzeltme anı, düz parolanın elde
olduğu tek an olan BAŞARILI GİRİŞTİR. (Toplu dönüştürme imkânsızdır: düz parolalar yok.)
"""

import logging

from argon2 import PasswordHasher
from sqlalchemy import select

from app.core.security import verify_password
from app.modules.auth import service as auth_service
from app.modules.users.models import User

# Kasten ZAYIF parametreler: "eski nesil" özeti temsil eder. Gerçek bir profil değildir.
_ESKI_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, hash_len=16, salt_len=8)

# Test fikstürü — gerçek bir parola DEĞİLDİR, hiçbir ortamda kullanılmaz.
_FIKSTUR_PAROLA = "sec-argon-fikstur-girdisi"


async def _eski_parametreli_kullanici(seeded_db, user_factory, email: str) -> tuple[User, str]:
    user = await user_factory(email=email, password=_FIKSTUR_PAROLA, role_key="patron")
    user.password_hash = _ESKI_HASHER.hash(_FIKSTUR_PAROLA)
    await seeded_db.flush()
    assert "$m=8,t=1,p=1$" in user.password_hash, "kurulum bozuk: eski özet üretilemedi"
    return user, user.password_hash


async def _saklanan_hash(seeded_db, user: User) -> str:
    """Özeti kimlik haritasından değil, VERİTABANI SATIRINDAN okur."""
    return (
        await seeded_db.execute(select(User.password_hash).where(User.id == user.id))
    ).scalar_one()


async def test_giris_ESKI_parametreli_ozeti_YENI_parametrelerle_YENIDEN_YAZAR(
    client, seeded_db, user_factory
):
    user, eski_hash = await _eski_parametreli_kullanici(seeded_db, user_factory, "eski@fiil.com")

    yanit = await client.post(
        "/auth/login", json={"email": "eski@fiil.com", "password": _FIKSTUR_PAROLA}
    )
    assert yanit.status_code == 200

    yeni_hash = await _saklanan_hash(seeded_db, user)
    assert yeni_hash != eski_hash, "satır güncellenmedi — check_needs_rehash çalışmıyor"
    assert "$m=65536,t=3,p=4$" in yeni_hash, (
        f"satır güncel parametrelerle yazılmamış: {yeni_hash.split('$')[:4]}"
    )
    assert verify_password(_FIKSTUR_PAROLA, yeni_hash) is True, (
        "yeniden yazılan özet aynı parolayı doğrulamıyor — kullanıcı kilitlenirdi"
    )


async def test_GUNCEL_parametreli_ozet_giriste_YENIDEN_YAZILMAZ(client, seeded_db, user_factory):
    """Pozitif kontrolün aynası: rehash körü körüne değil, yalnız GEREKTİĞİNDE olur.

    Aksi hâlde her giriş gereksiz bir yazma üretir ve testin ilk yarısı hiçbir şey
    kanıtlamaz (her koşulda değişen bir satır 'güncellendi' iddiasını boşa çıkarır).
    """
    user = await user_factory(email="guncel@fiil.com", password=_FIKSTUR_PAROLA, role_key="patron")
    onceki = await _saklanan_hash(seeded_db, user)

    yanit = await client.post(
        "/auth/login", json={"email": "guncel@fiil.com", "password": _FIKSTUR_PAROLA}
    )
    assert yanit.status_code == 200
    assert await _saklanan_hash(seeded_db, user) == onceki


async def test_YANLIS_parolayla_giriste_ozet_ASLA_yeniden_yazilmaz(client, seeded_db, user_factory):
    """Rehash yalnız DOĞRULAMA BAŞARILIYSA yapılır.

    Doğrulanmamış bir girdiyle rehash yapmak, saldırganın kendi parolasını kurbanın
    satırına yazması demektir — hesap devralma.
    """
    user, eski_hash = await _eski_parametreli_kullanici(seeded_db, user_factory, "yanlis@fiil.com")

    yanit = await client.post(
        "/auth/login", json={"email": "yanlis@fiil.com", "password": "bu-parola-yanlis"}
    )
    assert yanit.status_code == 401
    assert await _saklanan_hash(seeded_db, user) == eski_hash


async def test_rehash_PATLASA_BILE_giris_BASARILI_olur(
    client, seeded_db, user_factory, monkeypatch, caplog
):
    """🔴 POZİTİF KONTROL: rehash bir kolaylıktır, giriş yolunun bekası değil.

    Yeniden hash'leme herhangi bir sebeple patlarsa (bellek, kütüphane, DB) kullanıcı
    hesabına giremez hâle GELMEMELİDİR. Hata loglanır, giriş sürer.
    """
    user, eski_hash = await _eski_parametreli_kullanici(seeded_db, user_factory, "patlak@fiil.com")

    def _patla(*_args, **_kwargs):
        raise RuntimeError("olculmus ariza: yeniden hash'leme basarisiz")

    monkeypatch.setattr(auth_service, "hash_password", _patla)

    with caplog.at_level(logging.ERROR):
        yanit = await client.post(
            "/auth/login", json={"email": "patlak@fiil.com", "password": _FIKSTUR_PAROLA}
        )

    assert yanit.status_code == 200, "rehash arızası girişi düşürdü — kullanıcı kilitlendi"
    assert await _saklanan_hash(seeded_db, user) == eski_hash

    kayitlar = [k for k in caplog.records if k.levelno >= logging.ERROR]
    assert kayitlar, "rehash arızası sessizce yutuldu — hiçbir hata loglanmadı"
    log_metni = caplog.text
    assert _FIKSTUR_PAROLA not in log_metni, "🔴 düz parola loga sızdı"
    assert eski_hash not in log_metni, "🔴 parola özeti loga sızdı"
