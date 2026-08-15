"""Task H10 — denetim günlüğü (spec §11, plan H10, H6/H8'den devredilen notlar).

`app/modules/audit/` altyapısı (`record_audit`/`messages.py`) `contracts/test_audit.py`
deseninin BİREBİRİDİR — çağrı noktaları burada yeniden yazılmaz, YALNIZ çağrılır.

İki devir zorunluluğu ÖZELLİKLE ölçülür:

1. H6'dan devir: `progress_payment_unapproved` eski `approved_by`/`approved_at`
   damgalarını taşımalı — bunlar `_stamp` tarafından NULL'lanmadan ÖNCE okunmak
   ZORUNDADIR. `test_unapprove_denetim_kaydi_eski_onay_damgalarini_tasir` bunu
   pozitif yönde, aşağıdaki mutasyon notu ise NEGATİF yönde (sıra bozulursa
   testin kırmızıya dönmesi) doğrular — mutasyon adımı elle uygulanıp geri
   alınır (task talimatı), test dosyasına GÖMÜLMEZ.
2. H8'den devir: `progress_payment_deleted` silinen kaydın sequence_no/durum/
   tutar özetini taşımalı — `session.delete` ÖNCESİNDE çıkarılmış olmalı.
"""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import DISPLAY_TIMESTAMP_FORMAT, to_display
from app.modules.audit import messages
from app.modules.audit.models import AuditLog
from app.modules.progress_payments import service as pp_service
from app.modules.progress_payments.models import ProgressPayment, ProgressPaymentStatus
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _audit_sayisi(db_session: AsyncSession) -> int:
    return await db_session.scalar(select(func.count()).select_from(AuditLog))


async def _mevcut_kimlikler(db_session: AsyncSession) -> set[uuid.UUID]:
    rows = await db_session.scalars(select(AuditLog.id))
    return set(rows)


async def _yeni_kaydin_metni(db_session: AsyncSession, onceki_kimlikler: set[uuid.UUID]) -> str:
    """`contracts/test_audit.py._yeni_kaydin_metni` deseninin birebiri —
    `occurred_at` aynı transaction içindeki tüm INSERT'lerde aynı olduğu için
    sıralama için GÜVENİLMEZ, bu yüzden kimlik farkı kullanılır."""
    rows = await db_session.scalars(select(AuditLog))
    yeni = [row for row in rows if row.id not in onceki_kimlikler]
    assert len(yeni) == 1, f"tam bir yeni satır beklenirdi, {len(yeni)} bulundu"
    return yeni[0].detail


# --- 1. Okuma uçları yazmaz ---


async def test_okuma_denetim_yazmaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    sozlesmeli_proje: uuid.UUID,
    gecerli_taslak: uuid.UUID,
) -> None:
    once = await _audit_sayisi(db_session)
    await client.get("/progress-payments", headers=admin_headers)
    await client.get(f"/progress-payments/{gecerli_taslak}", headers=admin_headers)
    await client.get(
        f"/projects/{sozlesmeli_proje}/progress-payments/summary", headers=admin_headers
    )
    assert await _audit_sayisi(db_session) == once


# --- 2. Oluşturma / güncelleme ---


async def test_olusturma_denetime_yazar(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    sozlesmeli_proje: uuid.UUID,
) -> None:
    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.post(
        f"/projects/{sozlesmeli_proje}/progress-payments", json={}, headers=admin_headers
    )
    assert yanit.status_code == 201, yanit.text
    detay = await _yeni_kaydin_metni(db_session, onceki)
    assert detay == messages.progress_payment_created("Hakedişli Proje", 1)


async def test_guncelleme_denetime_yazar(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    gecerli_taslak: uuid.UUID,
) -> None:
    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.patch(
        f"/progress-payments/{gecerli_taslak}",
        json={"description": "Güncellenmiş açıklama"},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    detay = await _yeni_kaydin_metni(db_session, onceki)
    assert detay == messages.progress_payment_updated("Hakedişli Proje", 1)


# --- 3. Satır kaydetme (count taşınır) ---


async def test_lines_kaydi_count_ile_yazar(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    taslak_hakedis: uuid.UUID,
    hakedis_santiyesi,
    hakedis_kalemi,
) -> None:
    item, _ = hakedis_kalemi
    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.put(
        f"/progress-payments/{taslak_hakedis}/lines",
        json={
            "lines": [
                {
                    "contract_item_id": str(item.id),
                    "site_id": str(hakedis_santiyesi.id),
                    "quantity": "100",
                }
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    detay = await _yeni_kaydin_metni(db_session, onceki)
    assert detay == messages.progress_payment_lines_saved("Hakedişli Proje", 1, 1)
    # H10 denetimi Y1: `messages.progress_payment_lines_saved`'ın KENDİ İÇİNDEKİ
    # `count` kullanımını (örn. sabit `0` yazması) `messages.<fn>(...)` eşitliği
    # tek başına YAKALAMAZ — çağrılan `count` gerçekten metne girdi mi, fonksiyondan
    # BAĞIMSIZ bir literal ile ayrıca doğrulanır (mutasyon kanıtı raporda).
    assert "· 1 satır" in detay


# --- 4. Fiyat tazeleme ---


async def test_refresh_prices_yazar(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    hakedis_fabrikasi,
    hakedis_kalemi,
) -> None:
    item, _ = hakedis_kalemi
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.draft)
    item.unit_price = Decimal("1900")
    await db_session.flush()

    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.post(
        f"/progress-payments/{payment_id}/refresh-prices", headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["refreshed_count"] == 1
    detay = await _yeni_kaydin_metni(db_session, onceki)
    assert detay == messages.progress_payment_prices_refreshed("Hakedişli Proje", 1, 1)
    # H10 denetimi Y1: `count`'un mesaja GERÇEKTEN girdiğinin bağımsız kanıtı
    # (fonksiyon kendi içinde sabit değere düşerse bu satır kırmızıya döner).
    assert "· 1 kalem" in detay


# --- 5. Beş durum geçişi ---


async def test_her_durum_gecisi_yazar(
    client: AsyncClient,
    admin_headers: dict[str, str],
    muhasebe_headers: dict[str, str],
    db_session: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """submit/approve/reject/mark-paid/unapprove — HER biri TAM BİR kayıt üretir.

    Zincir: draft →(submit) pending →(approve) approved →(unapprove) pending
    →(reject) draft →(submit) pending →(approve) approved →(mark-paid) paid.
    `reject` yalnız `pending_approval`dan çalıştığı için `unapprove` ARADA
    çağrılır (spec §7 tablosu — `approved → draft` doğrudan yol YOKTUR).
    """
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.draft)

    async def _adim(uc: str, headers: dict[str, str]) -> None:
        onceki = await _mevcut_kimlikler(db_session)
        yanit = await client.post(f"/progress-payments/{payment_id}/{uc}", headers=headers)
        assert yanit.status_code == 200, yanit.text
        await _yeni_kaydin_metni(db_session, onceki)

    await _adim("submit", admin_headers)
    await _adim("approve", muhasebe_headers)
    await _adim("unapprove", admin_headers)
    await _adim("reject", muhasebe_headers)
    await _adim("submit", admin_headers)
    await _adim("approve", muhasebe_headers)
    await _adim("mark-paid", muhasebe_headers)


async def test_submit_mesaji_dogru_metni_tasir(
    client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession, gecerli_taslak
) -> None:
    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.post(f"/progress-payments/{gecerli_taslak}/submit", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    detay = await _yeni_kaydin_metni(db_session, onceki)
    assert detay == messages.progress_payment_submitted("Hakedişli Proje", 1)


async def test_approve_mesaji_dogru_metni_tasir(
    client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession, gecerli_taslak
) -> None:
    submit = await client.post(f"/progress-payments/{gecerli_taslak}/submit", headers=admin_headers)
    assert submit.status_code == 200, submit.text
    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.post(f"/progress-payments/{gecerli_taslak}/approve", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    detay = await _yeni_kaydin_metni(db_session, onceki)
    assert detay == messages.progress_payment_approved("Hakedişli Proje", 1)


async def test_mark_paid_mesaji_dogru_metni_tasir(
    client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession, gecerli_taslak
) -> None:
    await client.post(f"/progress-payments/{gecerli_taslak}/submit", headers=admin_headers)
    await client.post(f"/progress-payments/{gecerli_taslak}/approve", headers=admin_headers)
    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.post(
        f"/progress-payments/{gecerli_taslak}/mark-paid", headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    detay = await _yeni_kaydin_metni(db_session, onceki)
    assert detay == messages.progress_payment_paid("Hakedişli Proje", 1)


# --- 6. Reject gerekçesi (K12) ---


async def test_reject_reason_mesaja_girer(
    client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession, gecerli_taslak
) -> None:
    """K12: `reason` kolonu YOK — TEK kalıcı iz denetim metnidir."""
    await client.post(f"/progress-payments/{gecerli_taslak}/submit", headers=admin_headers)
    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.post(
        f"/progress-payments/{gecerli_taslak}/reject",
        json={"reason": "Eksik metraj"},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    detay = await _yeni_kaydin_metni(db_session, onceki)
    assert detay == messages.progress_payment_rejected("Hakedişli Proje", 1, "Eksik metraj")
    assert "Eksik metraj" in detay


async def test_reject_gerekcesiz_de_yazar(
    client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession, gecerli_taslak
) -> None:
    await client.post(f"/progress-payments/{gecerli_taslak}/submit", headers=admin_headers)
    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.post(f"/progress-payments/{gecerli_taslak}/reject", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    detay = await _yeni_kaydin_metni(db_session, onceki)
    assert detay == messages.progress_payment_rejected("Hakedişli Proje", 1, None)


# --- 7. H6'dan devredilen ZORUNLULUK: unapprove eski damgaları taşır ---


async def test_unapprove_denetim_kaydi_eski_onay_damgalarini_tasir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    gecerli_taslak: uuid.UUID,
) -> None:
    """H6 devir notu (plan H10, spec §11): `unapprove` bugün geriye HİÇBİR iz
    bırakmıyordu — bu test onun kapandığını kanıtlar. Onaylayanın adı VE eski
    onay tarihi günlük metninde GEÇMELİDİR; `_stamp` bunları NULL'ladıktan
    SONRA okunsaydı mesaj "Bilinmiyor" ile giderdi (aşağıdaki sıra testi bunu
    ayrıca doğrular)."""
    await client.post(f"/progress-payments/{gecerli_taslak}/submit", headers=admin_headers)
    onay = await client.post(f"/progress-payments/{gecerli_taslak}/approve", headers=admin_headers)
    assert onay.status_code == 200, onay.text
    eski_approved_at = onay.json()["approved_at"]
    assert eski_approved_at is not None

    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.post(
        f"/progress-payments/{gecerli_taslak}/unapprove", headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    detay = await _yeni_kaydin_metni(db_session, onceki)

    assert "Bilinmiyor" not in detay
    # Onaylayanın gerçek adı fixture'da sabitlenmediği için tam metin yerine
    # `messages.progress_payment_unapproved` (TEK doğruluk kaynağı) ile
    # üretilen SONUÇ karşılaştırılır.
    admin = (
        await db_session.execute(select(User).where(User.email == "admin@pp-crud.co"))
    ).scalar_one()
    eski_dt = datetime.fromisoformat(eski_approved_at)
    assert detay == messages.progress_payment_unapproved(
        "Hakedişli Proje", 1, admin.full_name, eski_dt
    )
    # H10 denetimi Y1: `messages.<fn>(...)` eşitliği fonksiyonun KENDİ İÇİNDEKİ
    # bir mutasyonu (örn. `previous_approver_name` sabit metne çevrilmesi)
    # YAKALAMAZ — gerçek onaylayan adı ve gerçek eski onay tarihi fonksiyondan
    # BAĞIMSIZ literal'lerle ayrıca doğrulanır (mutasyon kanıtı raporda).
    assert admin.full_name in detay
    # TB5 T4: damga TR saatiyle basilir. `eski_approved_at` teldeki UTC anidir;
    # ham `strftime` UTC'yi iddia ederdi ve TR ile UTC 3 saat ayrildigi icin
    # metinle ASLA eslesmezdi. Iddianin BAGIMSIZLIGI korunuyor — cevirim
    # `messages` fonksiyonundan degil, `core.timezone`dan geliyor.
    assert to_display(eski_dt).strftime(DISPLAY_TIMESTAMP_FORMAT) in detay


# --- 8. H8'den devredilen: silme özet taşır ---


async def test_silme_yazar(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """H8 devir notu (plan H10, spec §11): `progress_payment_deleted` kaydın
    sequence_no/durum/tutarını taşımalı — kayıt gittiğinde bunlar bir daha
    okunamaz, `session.delete` ÖNCESİNDE çıkarılmış olmalıdır."""
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.draft)

    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.delete(f"/progress-payments/{payment_id}", headers=admin_headers)
    assert yanit.status_code == 204, yanit.text
    detay = await _yeni_kaydin_metni(db_session, onceki)
    # `hakedis_fabrikasi` varsayılanı: 100 birim × 1850 = 185000.00 brüt.
    assert detay == messages.progress_payment_deleted(
        "Hakedişli Proje", 1, "Taslak", Decimal("185000.00")
    )
    # H10 denetimi Y1: `sequence_no`/`status_label`/`amount` gerçekten metne
    # girdiğinin fonksiyondan BAĞIMSIZ kanıtı — `messages.<fn>(...)` eşitliği
    # bu üç değerin fonksiyon içi kullanımını bozan bir mutasyonu YAKALAMAZ.
    assert "#1" in detay
    assert "· Taslak ·" in detay
    assert "185,000.00 TL" in detay


async def test_silme_ozeti_delete_dan_once_uretilir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    hakedis_fabrikasi,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H10 denetimi Y2 (spec §11, plan H10): `delete_payment` özeti (`DeletedPaymentSummary`)
    `session.delete`'ten ÖNCE kurulmalı — bugüne kadar bu sıra YALNIZ disiplinle
    korunuyordu: `SessionLocal(expire_on_commit=False)` + bellekte kalan
    öznitelikler yüzünden özet SONRAYA taşınsa bile (flush commit edilene kadar)
    testler farkı GÖRMÜYORDU (13/13 yeşil kalıyordu).

    Bu test sırayı GERÇEKTEN zorlar: ORM'in satırı fiilen veritabanından
    sildiği an (`ProgressPayment` mapper'ının `after_delete` olayı, flush
    sırasında senkron tetiklenir) bir bayrakla işaretlenir. `DeletedPaymentSummary`
    inşası (`pp_service` modülünde monkeypatch'lenir) bu bayrağın HENÜZ
    `False` olduğunu doğrular — özet üretimi `session.delete`/`flush`
    SONRASINA taşınan bir mutasyonda bayrak zaten `True` olacağı için bu
    assert kırmızıya döner (mutasyon kanıtı task raporunda).
    """
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.draft)

    delete_fired = False

    def _mark_deleted(mapper, connection, target) -> None:
        nonlocal delete_fired
        delete_fired = True

    event.listen(ProgressPayment, "after_delete", _mark_deleted)

    original_summary_cls = pp_service.DeletedPaymentSummary

    def _guarded_summary(*args: object, **kwargs: object) -> pp_service.DeletedPaymentSummary:
        assert not delete_fired, (
            "DeletedPaymentSummary, session.delete/flush SONRASINDA üretildi — "
            "H8'den devredilen sıra kuralı (spec §11) bozuldu"
        )
        return original_summary_cls(*args, **kwargs)

    monkeypatch.setattr(pp_service, "DeletedPaymentSummary", _guarded_summary)

    try:
        yanit = await client.delete(f"/progress-payments/{payment_id}", headers=admin_headers)
        assert yanit.status_code == 204, yanit.text
        assert delete_fired, "after_delete olayı hiç tetiklenmedi — test kurulumu geçersiz"
    finally:
        event.remove(ProgressPayment, "after_delete", _mark_deleted)
