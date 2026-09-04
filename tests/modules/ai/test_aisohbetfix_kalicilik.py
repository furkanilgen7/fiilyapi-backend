"""AI-SOHBET-FIX — sohbet geçmişi CANLIDA HİÇ kaydedilmiyordu. Bu dosya bekçisidir.

## Kusur (canlıda ölçüldü)

    ai_conversations | 0      ai_messages | 0      ai_tool_calls | 16

`ai_tool_calls` doluydu çünkü `audit.py` **kendi session'ında commit eder**.
`ai_conversations` boştu çünkü `turu_baslat` yalnız `flush()` ediyordu ve
commit'i `get_db`nin çıkışına bırakıyordu. Akış gövdesindeki `cevabi_sakla` ise
AYRI bir session açıyor ve commit edilmemiş sohbeti göremiyordu:

    asyncpg.exceptions.ForeignKeyViolationError:
      "ai_messages" violates constraint "ai_messages_conversation_id_fkey"

İstisna `get_db`ye kaçıp **ROLLBACK** tetikliyor, yani cevabı saklayamayan tur
SORUYU da siliyordu; üstüne Starlette `RuntimeError: Caught handled exception,
but response already started.` fırlatıyordu.

## 🔴 NEDEN DÖRT KAPI DA YEŞİLDİ — ölçüldü

`test_aichat2_sohbet.py::test_cevap_METIN_ADLAR_ve_HALLER_saklar_GOVDE_saklamaz`
sohbet saklamayı sözde bekçiliyordu ama İKİ kanonu birden çiğniyordu:

* **§5-19 — bekçi ölçtüğü yolu KENDİSİ kuruyor.** O test
  `monkeypatch.setattr(conversations, "SessionLocal", lambda: _Sahte())` ile
  `cevabi_sakla`nın "ayrı session"ını **testin kendi session'ına** bağlıyor ve
  `commit`i `flush`a çeviriyor. Böylece kusurun TEK sebebi — *ayrı bir
  transaction commit edilmemiş satırı göremez* — test ortamında **hiç
  gerçekleşmiyor**. FK asla ihlal edilmiyor.
* **§5-20 — çağrı yeri de mutanttır.** O test `cevabi_sakla`yı **doğrudan**
  çağırıyor; `POST /ai/chat`e hiç uğramıyor. `turu_baslat` → commit → akış
  gövdesi sırasının tamamı ölçüm dışında kalıyor.

Ek olarak kök `client` fikstürü `get_db`yi **commit etmeyen** bir override ile
değiştirir; yani gerçek `get_db`nin sıra davranışı hiçbir testte koşmuyordu.

## Bu dosya neyi BAŞKA yapıyor

1. **Tek kullanımlık gerçek veritabanı** (`test_fisno_concurrency.py` emsali).
   Kurulum COMMIT EDİLİR; ayrı session'lar birbirini GERÇEKTEN görür/görmez.
2. **Gerçek `get_db`** — `dependency_overrides` KULLANILMAZ.
3. **Uçtan koşar**: `POST /ai/chat`. Sahte olan tek parça **sağlayıcıdır**
   (ağa çıkılmaz); huni, denetim, izin kapısı, sahiplik kapısı ve saklama
   yolunun tamamı gerçektir.

⚠️ Bu dosya `.env`/`TEST_DATABASE_URL` veritabanına DOKUNMAZ ve canlı
`DATABASE_URL`e hiç ulaşmaz: `get_db`nin, `cevabi_sakla`nın, `audit.py`nin ve
`taze_aktor`un oturum fabrikalarının HEPSİ tek kullanımlık veritabanına
yönlendirilir. Yönlendirilmemiş bir tanesi kalsaydı test canlıya yazardı.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.db as core_db
from app.core.config import settings
from app.core.db import Base, get_db
from app.core.security import create_access_token
from app.main import app as ana_app
from app.modules.ai import audit as ai_audit
from app.modules.ai import conversations as ai_conversations
from app.modules.ai import loop as ai_loop
from app.modules.ai import router as ai_router
from app.modules.ai.models import AiConversation, AiMessage, AiMessageRole
from app.modules.ai.providers.base import (
    AiOlay,
    Kullanim,
    Mesaj,
    MetinParcasi,
    TurBitti,
    TurSebebi,
)
from app.modules.ai.registry import ToolSpec
from app.modules.audit.models import AuditAction, AuditLog
from app.modules.roles.models import Role
from app.modules.roles.seed_data import seed_reference_data
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

#: Turun akıttığı metin. Cevabın **birleştirilerek** saklandığını görmek için
#: bilerek İKİ parçadır: tek parça olsaydı `"".join(...)` mutantı görünmezdi.
CEVAP_PARCALARI = ("Temmuz 2026 hakedişi ", "12.500,00 TL.")
CEVAP = "".join(CEVAP_PARCALARI)
SORU = "Temmuz hakedişi ne kadar?"

#: Sahiplik kapısı ve izin matrisi için kullanılan rol. `MATRIX["ai"]` bu role
#: `view` verir; `ai:full` diye bir seviye YOKTUR (`guards.MIN_LEVEL`).
ROL = "patron"


# --------------------------------------------------------------------------- #
# Sahte sağlayıcı — TEK sahte parça
# --------------------------------------------------------------------------- #


class _SahteSaglayici:
    """Ağa çıkmayan sağlayıcı: iki metin parçası, sonra `bitti`.

    🔴 Araç ÇAĞIRMAZ. Sebep ölçülmüştür: araç çağrısı okuma düzlemini
    uyandırırdı ve o düzlem `AiSessionLocal` üzerinden **canlı** `DATABASE_URL`e
    bağlanırdı. Bu dosyanın ölçtüğü şey saklama sınırıdır, huni değil.
    """

    ad = "sahte"

    def arac_semasi(self, spec: ToolSpec) -> dict[str, Any]:  # pragma: no cover - çağrılmaz
        return {}

    async def tur(
        self, *, sistem: str, gecmis: Sequence[Mesaj], araclar: Sequence[ToolSpec]
    ) -> AsyncIterator[AiOlay]:
        for parca in CEVAP_PARCALARI:
            yield MetinParcasi(metin=parca)
        yield TurBitti(sebep=TurSebebi.bitti, kullanim=Kullanim(girdi=11, cikti=7))


# --------------------------------------------------------------------------- #
# Tek kullanımlık veritabanı (emsal: tests/modules/accounting/test_fisno_concurrency.py)
# --------------------------------------------------------------------------- #


def _asyncpg_dsn(database: str) -> str:
    base = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    return base.rsplit("/", 1)[0] + f"/{database}"


def _sqlalchemy_dsn(database: str) -> str:
    return settings.test_database_url.rsplit("/", 1)[0] + f"/{database}"


async def _admin(sql: str) -> None:
    baglanti = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await baglanti.execute(sql)
    finally:
        await baglanti.close()


class _Ortam:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], bearer: str, user_id: uuid.UUID
    ) -> None:
        self.Session = session_factory
        self.bearer = bearer
        self.user_id = user_id


@asynccontextmanager
async def _gercek_ortam(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Gerçek `get_db` + gerçek ayrı session'lar + tek kullanımlık veritabanı."""
    database = f"aisohbet_{uuid.uuid4().hex[:8]}"
    await _admin(f'CREATE DATABASE "{database}"')
    engine = create_async_engine(_sqlalchemy_dsn(database))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as kurulum:
            await seed_reference_data(kurulum)
            role = (await kurulum.execute(select(Role).where(Role.key == ROL))).scalar_one()
            user = User(
                email="aisohbet@fiil.test",
                password_hash="x",
                full_name="AI Sohbet Bekçisi",
                role_id=role.id,
            )
            kurulum.add(user)
            await kurulum.flush()
            # 🔴 COMMIT ŞART: aşağıdaki HER oturum AYRI bir bağlantıdır.
            await kurulum.commit()
            bearer = create_access_token(user.id, user.token_version)
            ortam = _Ortam(Session, bearer, user.id)

        # 🔴 DÖRT oturum fabrikasının HEPSİ yönlendirilir. Biri atlanırsa test
        # canlı `DATABASE_URL`e yazar — bu yüzden liste aşağıda ADIYLA sayılır.
        monkeypatch.setattr(core_db, "SessionLocal", Session)  # get_db
        monkeypatch.setattr(ai_conversations, "SessionLocal", Session)  # cevabi_sakla
        monkeypatch.setattr(ai_audit, "SessionLocal", Session)  # record_ai_turn
        monkeypatch.setattr(ai_loop, "AiSessionLocal", Session)  # taze_aktor
        monkeypatch.setattr(ai_router, "saglayici_kur", lambda: _SahteSaglayici())

        # 🔴 Gerçek `get_db` koşmalı: kök `client` fikstürünün override'ı
        # commit ETMEZ ve tam olarak ölçülmek istenen davranışı maskelerdi.
        assert get_db not in ana_app.dependency_overrides, (
            "`get_db` override edilmiş: bu dosya GERÇEK `get_db`yi ölçmek zorunda."
        )
        yield ortam
    finally:
        await engine.dispose()
        await _admin(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')


async def _chat(ortam: _Ortam, mesaj: str = SORU) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ana_app), base_url="http://test"
    ) as istemci:
        return await istemci.post(
            "/ai/chat",
            headers={"Authorization": f"Bearer {ortam.bearer}"},
            json={"mesaj": mesaj},
        )


async def _sayim(ortam: _Ortam) -> tuple[int, list[tuple[str, str]]]:
    """TAZE bir bağlantıdan okur: commit edilmemiş hiçbir şey görünmez."""
    async with ortam.Session() as taze:
        sohbet_adedi = await taze.scalar(select(func.count()).select_from(AiConversation))
        satirlar = await taze.execute(
            select(AiMessage.role, AiMessage.content).order_by(AiMessage.created_at, AiMessage.id)
        )
        return int(sohbet_adedi or 0), [(r.value, c) for r, c in satirlar.all()]


async def _denetim_satirlari(ortam: _Ortam) -> list[str]:
    """`audit_log`daki `ai_turn` satırları — TAZE bağlantıdan."""
    async with ortam.Session() as taze:
        satirlar = await taze.scalars(
            select(AuditLog.detail).where(AuditLog.action == AuditAction.ai_turn)
        )
        return list(satirlar)


# --------------------------------------------------------------------------- #
# BEKÇİ 1 — sohbet + İKİ mesaj akıştan sonra KALICIDIR
# --------------------------------------------------------------------------- #


async def test_POST_ai_chat_SOHBETI_ve_IKI_MESAJI_KALICI_yazar(monkeypatch, caplog) -> None:
    """🔴 ASIL BEKÇİ. Mutasyon: `router.py`deki `await session.commit()` silinince
    asistan mesajı FK ihlaliyle yazılamaz ve bu test KIRMIZI olur.

    İddia TAZE bir bağlantıdan okunur — yani "commit edildi mi" sorusunu
    veritabanının kendisi cevaplar, testin elindeki session değil.
    """
    async with _gercek_ortam(monkeypatch) as ortam:
        with caplog.at_level(logging.ERROR, logger="app.modules.ai.router"):
            yanit = await _chat(ortam)

        assert yanit.status_code == 200, yanit.text
        assert "event: tur_bitti" in yanit.text
        # 🔴 AKIŞ parçaları taşır, VERİTABANI birleşmiş metni. İkisi AYNI DEĞİL:
        # birleştirmeyi router yapar (`"".join(...)`). Parçalar akışta ayrı ayrı
        # aranır; birleşmiş hâl aşağıda satırda aranır — bu ayrım, birleştirmeyi
        # düşüren bir mutantı görünür kılar.
        for parca in CEVAP_PARCALARI:
            assert f'"metin": "{parca}"' in yanit.text, parca

        sohbet_adedi, mesajlar = await _sayim(ortam)

        assert sohbet_adedi == 1, (
            "Sohbet KALICI DEĞİL. `turu_baslat`ın yazısı akış başlamadan commit "
            "edilmiyorsa, akış gövdesindeki FK ihlali `get_db`yi ROLLBACK'e "
            "sürükler ve soru da sohbet de kaybolur (canlıda olan buydu)."
        )
        assert mesajlar == [
            (AiMessageRole.kullanici.value, SORU),
            (AiMessageRole.asistan.value, CEVAP),
        ], (
            "Kullanıcı sorusu + asistan cevabı İKİSİ BİRDEN kalıcı olmalı. "
            f"Bulunan: {mesajlar}. Asistan satırı yoksa `cevabi_sakla` ayrı "
            "session'ında commit edilmemiş bir sohbete FK ile bağlanmaya "
            "çalışmıştır (ai_messages_conversation_id_fkey)."
        )
        assert not caplog.records, f"Saklama sessizce patladı: {caplog.text}"

        # 🔴 §5-19 POZİTİF KONTROL: yan etkiler artık izole; izolasyon BOZUK bir
        # denetim yolunu SESSİZCE gizliyor olabilirdi. Denetim satırının
        # GERÇEKTEN yazıldığı burada ölçülür — yoksa `record_ai_turn`ün her
        # zaman patlıyor olması da testi yeşil bırakırdı.
        denetim = await _denetim_satirlari(ortam)
        assert len(denetim) == 1, f"Tur denetim satırı yazılmadı: {denetim}"
        assert "AI turu" in denetim[0]


async def test_SAHIPLIK_KAPISI_hala_kapali_ve_404_iz_BIRAKMAZ(monkeypatch) -> None:
    """🔴 §5-19 POZİTİF KONTROLÜN AYNASI: yeni commit kapıyı GEVŞETMEDİ.

    Commit'in yeri bir kısıttır: sahiplik kapısından SONRA gelir. Başkasının
    sohbetine yazma denemesi 404 alır **ve** geride bir satır bırakmaz — commit
    kapıdan ÖNCE koşsaydı bu test kırmızı olurdu.
    """
    async with _gercek_ortam(monkeypatch) as ortam:
        yabanci = uuid.uuid4()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=ana_app), base_url="http://test"
        ) as istemci:
            yanit = await istemci.post(
                "/ai/chat",
                headers={"Authorization": f"Bearer {ortam.bearer}"},
                json={"mesaj": "başkasının sohbetine yazayım", "conversation_id": str(yabanci)},
            )
        assert yanit.status_code == 404, yanit.text
        assert await _sayim(ortam) == (0, [])


# --------------------------------------------------------------------------- #
# BEKÇİ 2 — saklama patlarsa YANIT ÇÖKMEZ, ama hata GÖRÜNÜR
# --------------------------------------------------------------------------- #


async def test_cevabi_sakla_PATLARSA_yanit_COKMEZ_soru_KALIR_hata_GORUNUR(
    monkeypatch, caplog
) -> None:
    """🔴 Saklama bir YAN ETKİDİR (§ router yorumu).

    Mutasyon: `router.py`deki `try/except` kaldırılınca istisna ASGI katmanına
    kaçar; bu test `httpx`in `raise_app_exceptions` yolundan KIRMIZI döner.
    İkinci mutasyon: `logger.exception` silinirse `caplog` iddiası kırmızı olur
    (hiçbir hata SESSİZCE yutulmaz).
    """
    async with _gercek_ortam(monkeypatch) as ortam:

        async def _patla(**_: object) -> None:
            raise RuntimeError("saklama katmanı simüle edilmiş arıza")

        monkeypatch.setattr(ai_conversations, "cevabi_sakla", _patla)

        with caplog.at_level(logging.ERROR, logger="app.modules.ai.router"):
            yanit = await _chat(ortam, mesaj="cevap saklanamasa da akmalı")

        # 1. Kullanıcı cevabını EKSİKSİZ aldı.
        assert yanit.status_code == 200, yanit.text
        assert "event: tur_bitti" in yanit.text
        for parca in CEVAP_PARCALARI:
            assert f'"metin": "{parca}"' in yanit.text, parca

        # 2. Soru ve sohbet KAYBOLMADI — saklama arızası `get_db`yi ROLLBACK'e
        #    sürüklememeli (canlıda tam olarak bu oluyordu).
        sohbet_adedi, mesajlar = await _sayim(ortam)
        assert sohbet_adedi == 1
        assert mesajlar == [(AiMessageRole.kullanici.value, "cevap saklanamasa da akmalı")]

        # 3. Hata SESSİZCE YUTULMADI: traceback ve kimlik günlüğe düştü.
        assert caplog.records, "Saklama arızası hiçbir yere yazılmadı — sessiz yutma."
        kayit = caplog.records[-1]
        assert kayit.exc_info is not None, "`logger.error` değil `logger.exception` olmalı"
        assert "asistan cevabı" in kayit.getMessage()


# --------------------------------------------------------------------------- #
# BEKÇİ 3 — YAN ETKİLER BİRBİRİNİ DÜŞÜREMEZ (kusur sınıfının ikinci yarısı)
# --------------------------------------------------------------------------- #


async def test_record_ai_turn_PATLARSA_cevap_YINE_SAKLANIR(monkeypatch, caplog) -> None:
    """🔴 Kusur sınıfının İKİNCİ YARISI.

    `record_ai_turn` aynı `finally`de ve `cevabi_sakla`dan **ÖNCE** koşar.
    İzole edilmeseydi arızası iki şeyi birden yapardı: yanıtı çökertir **ve**
    `cevabi_sakla`yı hiç koşturmazdı — yani sohbet geçmişi yine boş kalır,
    düzeltilen kusurun kullanıcıya görünen semptomu AYNEN geri gelirdi.

    🔴 Bağımsızlık koddan ölçüldü: `record_ai_turn` → `audit_log`,
    `cevabi_sakla` → `ai_messages`/`ai_conversations`. Ayrık tablolar, ayrı
    session'lar, paylaşılan durum YOK. Bu test o bağımsızlığın **davranışta**
    da tuttuğunu çakar.

    Mutasyon: `record_ai_turn` çağrısının izolasyonu kaldırılınca bu test
    KIRMIZI olur — hem 200 iddiası hem de asistan satırı iddiası düşer.
    """
    async with _gercek_ortam(monkeypatch) as ortam:

        async def _patla(**_: object) -> None:
            raise RuntimeError("denetim katmanı simüle edilmiş arıza")

        monkeypatch.setattr(ai_router, "record_ai_turn", _patla)

        with caplog.at_level(logging.ERROR, logger="app.modules.ai.router"):
            yanit = await _chat(ortam)

        # (a) Kullanıcı cevabını EKSİKSİZ aldı.
        assert yanit.status_code == 200, yanit.text
        assert "event: tur_bitti" in yanit.text
        for parca in CEVAP_PARCALARI:
            assert f'"metin": "{parca}"' in yanit.text, parca

        # (b) 🔴 ASIL İDDİA: denetim patlasa da SOHBET GEÇMİŞİ YAZILDI.
        sohbet_adedi, mesajlar = await _sayim(ortam)
        assert sohbet_adedi == 1
        assert mesajlar == [
            (AiMessageRole.kullanici.value, SORU),
            (AiMessageRole.asistan.value, CEVAP),
        ], (
            "Denetim satırının arızası sohbet saklamayı DÜŞÜRDÜ. İki yan etki "
            f"birbirinden bağımsız olmalıydı. Bulunan: {mesajlar}"
        )

        # (c) Hata SESSİZCE YUTULMADI.
        assert caplog.records, "Denetim arızası hiçbir yere yazılmadı — sessiz yutma."
        kayit = caplog.records[-1]
        assert kayit.exc_info is not None, "`logger.error` değil `logger.exception` olmalı"
        assert "tur denetim satırı" in kayit.getMessage()

        # Ve denetim satırı gerçekten YAZILAMADI (test bir arızayı ölçüyor,
        # kendi kurduğu bir yolu değil).
        assert await _denetim_satirlari(ortam) == []


async def test_istemci_kapatma_PATLARSA_iki_yazi_da_KOSAR(monkeypatch, caplog) -> None:
    """🔴 `finally`nin İLK adımı da bir yan etkidir.

    Okuma düzlemi istemcisinin `aclose()`u çıplak bırakılsaydı, oradaki bir
    arıza HEM denetim satırını HEM sohbet geçmişini düşürürdü — üstelik ikisi
    de tamamen sağlamken. Bu test o ilk adımın da izole olduğunu çakar.
    """
    async with _gercek_ortam(monkeypatch) as ortam:
        gercek_kur = httpx.AsyncClient.aclose

        async def _patla(self) -> None:
            raise RuntimeError("istemci kapatma simüle edilmiş arıza")

        monkeypatch.setattr(httpx.AsyncClient, "aclose", _patla)
        assert httpx.AsyncClient.aclose is not gercek_kur

        with caplog.at_level(logging.ERROR, logger="app.modules.ai.router"):
            yanit = await _chat(ortam)

        assert yanit.status_code == 200, yanit.text
        sohbet_adedi, mesajlar = await _sayim(ortam)
        assert sohbet_adedi == 1
        assert [r for r, _ in mesajlar] == [
            AiMessageRole.kullanici.value,
            AiMessageRole.asistan.value,
        ], f"Kapatma arızası yazıları düşürdü: {mesajlar}"
        assert len(await _denetim_satirlari(ortam)) == 1
        assert caplog.records, "Kapatma arızası sessizce yutuldu."
        assert "kapatılması" in caplog.records[0].getMessage()
