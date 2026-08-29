"""AI-0a T3 bekçisi — salt-okunur bağlantı (B3).

Kapı D — YAPISAL: AI hattında yazma reddedilmez, **imkânsızdır**.

🔴 Testin can alıcı satırı `await baglanti.rollback()`tır. Salt-okunurluk
PostgreSQL'de TRANSACTION kapsamlıdır: `SET TRANSACTION READ ONLY` ile kurulsaydı
rollback sonrası açılan YENİ transaction yazılabilir olurdu ve ajan döngüsü bir
araç hatasını yutup devam ettiğinde tam olarak bu olurdu. `server_settings`
bağlantı ömrü boyunca yaşar; test bunu rollback'ten SONRA sınayarak farkı ölçer.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.db import READ_ONLY_MAX_OVERFLOW, READ_ONLY_POOL_SIZE, build_engine
from app.core.db import engine as ana_engine
from app.modules.ai.db import AiSessionLocal, ai_engine, get_ai_readonly_db

#: PostgreSQL `read_only_sql_transaction`. Metin eşleştirmesi yerine SQLSTATE:
#: mesaj yerelleştirilebilir, kod kilittir.
SALT_OKUNUR_SQLSTATE = "25006"

#: Yalnız birincil anahtarı zorunlu olan en yalın tablo (`next_no` sunucu
#: varsayılanı taşır) — INSERT'in kısıt hatasına DEĞİL, salt-okunurluğa düşmesi
#: için bilerek seçildi. Yıl 1900 gerçek veriyle çakışmaz.
YAZMA_SONDASI = "insert into journal_entry_counters (year) values (1900)"


def _test_veritabani_ayarlari() -> Settings:
    """Salt-okunur motoru **xdist işçisinin kendi** veritabanına yöneltir.

    `settings.database_url` taban veritabanını gösterir; şeması `_create_schema`
    fixture'ıyla kurulan veritabanı `test_database_url`dir (işçi son ekiyle).
    """
    return settings.model_copy(update={"database_url": settings.test_database_url})


async def test_B3_salt_okunur_baglanti_INSERTi_ROLLBACKTEN_SONRA_DA_reddeder(
    _create_schema: None,
) -> None:
    motor = build_engine(_test_veritabani_ayarlari(), read_only=True)
    try:
        async with motor.connect() as baglanti:
            # --- pozitif kontrol 1: OKUMA gerçekten çalışıyor -------------
            assert await baglanti.scalar(text("select 1")) == 1
            assert await baglanti.scalar(text("show transaction_read_only")) == "on"

            # --- ilk transaction'da yazma reddedilir ----------------------
            with pytest.raises(DBAPIError) as ilk:
                await baglanti.execute(text(YAZMA_SONDASI))
            assert getattr(ilk.value.orig, "sqlstate", None) == SALT_OKUNUR_SQLSTATE

            # --- 🔴 ROLLBACK SONRASI da reddedilmeli ----------------------
            await baglanti.rollback()
            assert await baglanti.scalar(text("show transaction_read_only")) == "on"
            with pytest.raises(DBAPIError) as ikinci:
                await baglanti.execute(text(YAZMA_SONDASI))
            assert getattr(ikinci.value.orig, "sqlstate", None) == SALT_OKUNUR_SQLSTATE
    finally:
        await motor.dispose()


async def test_B3_pozitif_kontrol_ayni_INSERT_yazilabilir_motorda_GECER(
    _create_schema: None,
) -> None:
    """🔴 Bu ikinci yarı olmadan B3 "yazma engellendi"yi değil "hiçbir şey
    olmuyor"u kanıtlardı.

    Aynı SQL, aynı veritabanı, `read_only=False`: **geçer**. Yani sondanın
    kendisi geçerli bir yazmadır ve yukarıdaki reddin sebebi salt-okunurluktur,
    bozuk bir INSERT değil. Sonunda rollback: işçi veritabanına hiçbir şey sızmaz.
    """
    motor = build_engine(_test_veritabani_ayarlari(), read_only=False)
    try:
        async with motor.connect() as baglanti:
            assert await baglanti.scalar(text("show transaction_read_only")) == "off"
            sonuc = await baglanti.execute(text(YAZMA_SONDASI))
            assert sonuc.rowcount == 1
            await baglanti.rollback()
    finally:
        await motor.dispose()


async def test_B3_mutasyon_server_settings_DUSURULURSE_yazma_gecer(
    _create_schema: None,
) -> None:
    """`connect_args["server_settings"]` satırı silinseydi ne olurdu.

    Mutasyonu elle kurup aynı sondayı koşuyoruz: yazma GEÇER. Yani B3'ün
    ölçtüğü şey gerçekten o satırdır — eşdeğer mutant yok.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    cfg = _test_veritabani_ayarlari()
    mutant = create_async_engine(  # `server_settings` YOK — mutasyon budur
        cfg.database_url,
        pool_pre_ping=True,
        pool_size=READ_ONLY_POOL_SIZE,
        max_overflow=READ_ONLY_MAX_OVERFLOW,
        connect_args={
            "timeout": cfg.db_connect_timeout,
            "command_timeout": cfg.db_command_timeout,
        },
    )
    try:
        async with mutant.connect() as baglanti:
            assert await baglanti.scalar(text("show transaction_read_only")) == "off"
            await baglanti.execute(text(YAZMA_SONDASI))
            await baglanti.rollback()
    finally:
        await mutant.dispose()


def test_B3_ai_motoru_ANA_motordan_AYRIDIR_ve_havuzu_TASMASIZDIR() -> None:
    assert ai_engine is not ana_engine
    assert ai_engine.pool.size() == READ_ONLY_POOL_SIZE
    assert ai_engine.pool._max_overflow == READ_ONLY_MAX_OVERFLOW
    # Ana motor SQLAlchemy varsayılanında kalır — AI'ın sınırı ana hattı kısmadı.
    assert ana_engine.pool.size() != READ_ONLY_POOL_SIZE or ana_engine is ai_engine


def test_B3_ai_oturumu_ai_motoruna_BAGLIDIR() -> None:
    oturum: AsyncSession = AiSessionLocal()
    try:
        assert oturum.bind is ai_engine
    finally:
        # Hiç bağlanmadı; kapatmak bir bağlantı açmaz.
        oturum.sync_session.close()


async def test_B3_get_ai_readonly_db_COMMIT_ETMEZ() -> None:
    """🔴 `get_db`nin aksine bu üretici temiz çıkışta da commit ETMEZ.

    `get_db` kopyalanıp `commit()` satırı taşınırsa dosyanın tüm anlamı sessizce
    silinir; bu test o kopya-yapıştırı yakalar. Session hiç bağlanmadığı için
    gerçek bir DB turu yoktur — ölçülen çağrı kümesidir.
    """
    cagrilar: list[str] = []

    class SahteOturum:
        async def rollback(self) -> None:
            cagrilar.append("rollback")

        async def commit(self) -> None:
            cagrilar.append("commit")

        async def close(self) -> None:
            cagrilar.append("close")

        async def __aenter__(self) -> "SahteOturum":
            return self

        async def __aexit__(self, *_: object) -> None:
            await self.close()

    import app.modules.ai.db as ai_db

    gercek = ai_db.AiSessionLocal
    ai_db.AiSessionLocal = SahteOturum  # type: ignore[assignment]
    try:
        uretici = get_ai_readonly_db()
        oturum = await uretici.__anext__()
        assert isinstance(oturum, SahteOturum)
        with pytest.raises(StopAsyncIteration):
            await uretici.__anext__()
    finally:
        ai_db.AiSessionLocal = gercek  # type: ignore[assignment]

    assert "commit" not in cagrilar
    assert cagrilar == ["rollback", "close"]
