"""🔴 Kolon sınırını aşan sayı 500 döndürüyordu — veri hatası 422 olmalı (kayıt 465).

## Kusur

`app/core/exception_handlers.py` `sqlalchemy.exc`ten YALNIZ `IntegrityError`
kaydeder; `app/main.py`de genel bir `Exception` işleyicisi de yoktur. Kolon
sınırını aşan bir sayı hiçbir işleyiciye düşmez ve Starlette düz **500** döner.

Ulaşılabilir yol (ölçüldü): `subcontractor_progress_payments/schemas.py:53`
`default_coefficient` yalnız `gt=0` doğrular, kolonu `Numeric(8,3)`tür
(`models.py:135-137`). Bir rakam fazla yazan kullanıcı `numeric field overflow`
alır ve hangi alanın hatalı olduğunu ÖĞRENEMEZ.

## 🔴 TRİYAJ ÖNERİSİ ÖLÇÜLDÜ VE ÇÜRÜTÜLDÜ — `DataError` KAYDI ÖLÜ BİR İŞLEYİCİ OLURDU

Öneri "`sqlalchemy.exc.DataError` kaydet" idi. Bu sürücüde `DataError` HİÇ
DOĞMAZ. `sqlalchemy/dialects/postgresql/asyncpg.py:1010-1021`
`_asyncpg_error_translate` yalnız altı asyncpg sınıfını eşler;
`NumericValueOutOfRangeError` bunların hiçbiri değildir, MRO'da yalnız
`PostgresError`e uyar ve o da düz `self.Error`a eşlenir. Sonuç: SQLAlchemy
**`sqlalchemy.exc.DBAPIError`** fırlatır (ölçüm aşağıdaki ilk testtedir).
`DataError`e kaydedilmiş bir işleyici ASLA çağrılmazdı — sahte-yeşilin bir hâli.

Ayırt edici işaret **SQLSTATE**tir: çeviri `pgcode`/`sqlstate`i korur
(asyncpg.py:794-796). 422'ye yalnız "değer alanın sınırını aşıyor" sınıfı
çevrilir (`22003` sayısal taşma · `22001` metin taşması); `22012` (sıfıra
bölme) gibi sunucu hataları ve altyapı hataları 500 KALIR.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DataError, DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exception_handlers import register_exception_handlers

#: Kolon sınırını aşan değer (`numeric(8,3)` en fazla 5 tam hane taşır).
TASAN_SQL = "SELECT CAST(100000 AS numeric(8,3))"
#: Sunucu hatası — 422'ye ÇEVRİLMEMELİ (SQLSTATE 22012).
SIFIRA_BOLME_SQL = "SELECT 1/0"


async def test_asyncpg_DataError_DEGIL_DBAPIError_firlatir(db_session: AsyncSession) -> None:
    """🔴 ÖNERİLEN ONARIMIN ÇÜRÜTÜLMESİ — işleyici hangi sınıfa kaydedilmeli.

    Mutasyon anlamı: bu test yeşilse `add_exception_handler(DataError, …)`
    yazmak ÖLÜ bir işleyici demektir.
    """
    with pytest.raises(DBAPIError) as hata:
        await db_session.execute(text(TASAN_SQL))

    assert not isinstance(hata.value, DataError), (
        "asyncpg'de `DataError` doğmuyor; işleyici ona kaydedilirse hiç çağrılmaz."
    )
    assert type(hata.value) is DBAPIError
    assert hata.value.orig.sqlstate == "22003"
    assert "numeric field overflow" in str(hata.value)


def _tasma_uygulamasi(db_session: AsyncSession, sql: str) -> FastAPI:
    """İstisnayı ELLE KURMAZ: ucun gövdesi PostgreSQL'e taşan değeri yazdırır.

    Sadakatli: `numeric field overflow` gerçek hayatta da INSERT/`flush()`
    anında, yani handler'ın İÇİNDE doğar (ertelenmiş kısıtların aksine).
    """
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/tasma")
    async def tasma() -> None:
        await db_session.execute(text(sql))

    return app


async def _cagir(app: FastAPI) -> tuple[int, object]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as istemci:
        yanit = await istemci.get("/tasma")
    return yanit.status_code, yanit.text


async def test_numeric_overflow_500_DEGIL_422_doner(db_session: AsyncSession) -> None:
    """🔴 ASIL BEKÇİ. Mutasyon: `add_exception_handler(DBAPIError, …)` satırı
    silinince Starlette düz 500 döner ve bu test KIRMIZI olur."""
    kod, govde = await _cagir(_tasma_uygulamasi(db_session, TASAN_SQL))

    assert kod == 422, (
        f"Kolon sınırını aşan sayı {kod} döndü. asyncpg bunu düz `DBAPIError` "
        f"olarak fırlatır ve hiçbir işleyiciye düşmez. Gövde: {govde}"
    )
    assert "Gönderilen değer alanın sınırını aşıyor" in govde


async def test_sunucu_hatasi_422_YE_CEVRILMEZ(db_session: AsyncSession) -> None:
    """🔴 KAPININ DAR OLDUĞUNUN AYNASI (pozitif kontrol).

    Sıfıra bölme de bir `DBAPIError`dır ama SQLSTATE'i `22012`dir: kullanıcının
    düzeltebileceği bir ALAN değil, sunucu tarafı bir hatadır. `DBAPIError`in
    TAMAMINI 422'ye çeviren bir mutant bu testi KIRMIZI yapar.
    """
    kod, _ = await _cagir(_tasma_uygulamasi(db_session, SIFIRA_BOLME_SQL))

    assert kod == 500, f"Sunucu hatası 422'ye çevrildi ({kod}) — kapı fazla geniş."
