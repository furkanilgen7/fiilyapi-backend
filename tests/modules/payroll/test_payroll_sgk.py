"""İK-3 T5 — SGK prim özeti + "gönderildi" damgası (spec §5, SGK **55-95**).

Mockup otoritesi: `projedesign/SGK Bildirimi.dc.html` (SGK).

## 🔴🔴 MOCKUP TUTARLARI TEST BEKLENTİSİ DEĞİLDİR (spec S1)

SGK mockup'ı KENDİ ARİTMETİĞİNE uymuyor. Matrah 743.200 üzerinden işçi tarafı
birebir tutuyor (SGK 69-73: %14→104.048 · %1→7.432 · %10→74.320 ·
%0,759→5.641 · toplam 191.441) **ama işveren tarafı TUTMUYOR**: aynı matrahtan
%20,5→152.356 · %2→14.864 · %1→7.432 = **174.652** çıkarken SGK 82 **148.800**
yazıyor. KPI'lar da uymuyor (SGK 57 → 253.048; oranlardan 256.404 · SGK 91 →
275.344; oranlardan 278.700).

Spec S1'in kuralı: **açıkça yazılı ORAN kazanır, tutarlar temsilîdir.** Bu
yüzden bu dosyadaki her beklenti ORANLARDAN türetilmiştir ve bizim sayımız
mockup'takinden BÜYÜKTÜR — bu bir hata değil, kararın kendisidir. Mockup
toplamına "uyduran" bir düzeltme, işveren primini sistematik olarak eksik
gösterirdi (para sınıfı hata).

## SGK 96-118 KAPSAM DIŞIDIR

Çalışan listesi ("SGK No" + 4a/4b rozeti) bu uçtan DÖNMEZ: spec §5
`sgk-summary`'yi açıkça **55-95**'e bağlar ve `sgk_no` diye bir kolon İK-1'de
yoktur — uydurulmaz.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.audit.models import AuditLog
from app.modules.payroll.models import PayrollPeriod
from app.modules.site_diary.models import WorkerSource

pytestmark = pytest.mark.asyncio


# --- `dort_tip` senaryosunun ORANLARDAN türeyen beklentileri ---------------
#
#   şirket  Ayşe Demir    5 gün × 1.800 = brüt  9.000,00 · SGK 4a oranları
#   taşeron Mehmet Yılmaz 5 gün × 1.800 = brüt  9.000,00 · SGK 4a (satır EXCLUDED)
#   serbest Kemal Tunç              aylık 12.500,00 · yalnız %20 stopaj
#   stajyer Burak Aydın             aylık  7.500,00 · TÜM oranlar 0
#   ücretsiz Zeynep Ak    ücret tanımsız → brüt `null` (S4, matraha GİRMEZ)

MATRAH = Decimal("38000.00")  # 9.000 + 9.000 + 12.500 + 7.500

SGK_ISCI = Decimal("2520.00")  # 2 × 9.000 × %14
ISSIZLIK_ISCI = Decimal("180.00")  # 2 × 9.000 × %1
# 🔴 IK3-GV: gelir vergisi ve damga artık ORANDAN DEĞİL SATIRDAN gelir (K6).
#   şirket + taşeron → 0,00: 9.000 brüt, 2026 brüt asgari ücretinin (33.030,00)
#     ALTINDADIR, KK-7 istisnası hesaplanan verginin tamamını karşılar;
#   serbest → 12.500 × %20 = 2.500,00 (düz oran rejimi, GVK m.94);
#   stajyer → 0 (tüm oranları 0).
# Eski 4.300,00 içindeki 2 × 900, mevzuata dayanmayan düz %10'dan geliyordu.
GELIR_VERGISI = Decimal("2500.00")
# Damga da istisnayı GÖRÜR: 9.000 × %0,759 = 68,31 < istisna 250,70 → 0,00.
DAMGA = Decimal("0.00")
ISCI_KESINTI = Decimal("5200.00")

SGK_ISVEREN = Decimal("3690.00")  # 2 × 9.000 × %20,5
ISSIZLIK_ISVEREN = Decimal("360.00")  # 2 × 9.000 × %2
KISA_CALISMA = Decimal("180.00")  # 2 × 9.000 × %1
ISVEREN_YUKU = Decimal("4230.00")

SGK_PRIMI_TOPLAM = Decimal("6210.00")  # SGK 57 "İşçi + İşveren"
ISSIZLIK_TOPLAM = Decimal("540.00")  # SGK 58
SGK_ODENECEK = Decimal("6750.00")  # SGK 86-91 "İşçi + İşveren SGK + İşsizlik"


async def _ozet(client, headers, donem, *, hesapla: bool = True) -> dict:
    if hesapla:
        await client.post(f"/payroll/periods/{donem.id}/compute", headers=headers)
    resp = await client.get(f"/payroll/periods/{donem.id}/sgk-summary", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _para(govde: dict, alan: str) -> Decimal:
    return Decimal(govde[alan])


# --- Kapılar ---------------------------------------------------------------


async def test_yetkisiz_rol_sgk_ozetini_goremez_403(client, yetkisiz_headers, donem):
    resp = await client.get(f"/payroll/periods/{donem.id}/sgk-summary", headers=yetkisiz_headers)
    assert resp.status_code == 403


async def test_olmayan_donem_404(client, ik_headers, seeded_db):
    import uuid

    resp = await client.get(f"/payroll/periods/{uuid.uuid4()}/sgk-summary", headers=ik_headers)
    assert resp.status_code == 404


# --- SGK 55-58 KPI'ları ----------------------------------------------------


async def test_KPI_dortlusu_oranlardan_turer(client, ik_headers, donem, dort_tip):
    """SGK 55-58: bildirilen çalışan · matrah · SGK primi · işsizlik.

    Dördü de ORANDAN türer (S1); mockup'ın 48/743.200/253.048/22.296 dörtlüsü
    TEMSİLÎDİR ve beklenti değildir.
    """
    govde = await _ozet(client, ik_headers, donem)

    assert govde["declared_personnel_count"] == 4  # SGK 55 (ücretsiz satır HARİÇ)
    assert _para(govde, "sgk_base_total") == MATRAH  # SGK 56
    assert _para(govde, "sgk_premium_total") == SGK_PRIMI_TOPLAM  # SGK 57
    assert _para(govde, "unemployment_total") == ISSIZLIK_TOPLAM  # SGK 58


async def test_isci_paylari_SGK_69_73(client, ik_headers, donem, dort_tip):
    """SGK 69-73 — dört kalem + toplamları. Kalemler toplamlarına EŞİTTİR."""
    govde = await _ozet(client, ik_headers, donem)

    assert _para(govde, "sgk_employee_total") == SGK_ISCI  # SGK 69
    assert _para(govde, "unemployment_employee_total") == ISSIZLIK_ISCI  # SGK 70
    assert _para(govde, "income_tax_total") == GELIR_VERGISI  # SGK 71
    assert _para(govde, "stamp_tax_total") == DAMGA  # SGK 72
    assert _para(govde, "employee_deduction_total") == ISCI_KESINTI  # SGK 73
    assert _para(govde, "sgk_employee_total") + _para(govde, "unemployment_employee_total") + _para(
        govde, "income_tax_total"
    ) + _para(govde, "stamp_tax_total") == _para(govde, "employee_deduction_total")


async def test_isveren_paylari_SGK_79_82_MOCKUP_TOPLAMINDAN_BUYUKTUR(
    client, ik_headers, donem, dort_tip
):
    """🔴 SGK 79-82 — ÜÇ kalem (spec §7) ve toplamı üçünün TAMAMIDIR.

    Mockup SGK 82'de işveren toplamını kendi üç kaleminin altında yazar
    (148.800 < 174.652). Bizim toplamımız üç kalemin tamamıdır ve bu KASITLIDIR:
    biri düşseydi işveren maliyeti sistematik olarak eksik çıkardı.
    """
    govde = await _ozet(client, ik_headers, donem)

    assert _para(govde, "sgk_employer_total") == SGK_ISVEREN  # SGK 79
    assert _para(govde, "unemployment_employer_total") == ISSIZLIK_ISVEREN  # SGK 80
    assert _para(govde, "short_work_total") == KISA_CALISMA  # SGK 81
    assert _para(govde, "employer_burden_total") == ISVEREN_YUKU  # SGK 82
    assert _para(govde, "sgk_employer_total") + _para(govde, "unemployment_employer_total") + _para(
        govde, "short_work_total"
    ) == _para(govde, "employer_burden_total")


async def test_odenecek_toplam_prim_SGK_86_91(client, ik_headers, donem, dort_tip):
    """SGK 86-91 — etiket AÇIKÇA "İşçi + İşveren SGK + İşsizlik" (SGK 89).

    Gelir vergisi ve damga BU TOPLAMA GİRMEZ (vergi dairesine gider, SGK'ya
    değil) ve kısa çalışma da etikette SAYILMAZ; ikisi de yanıtta AYRI AYRI
    döner, hiçbiri gizlenmez.
    """
    govde = await _ozet(client, ik_headers, donem)
    assert _para(govde, "sgk_payable_total") == SGK_ODENECEK
    assert _para(govde, "sgk_employee_total") + _para(govde, "unemployment_employee_total") + _para(
        govde, "sgk_employer_total"
    ) + _para(govde, "unemployment_employer_total") == _para(govde, "sgk_payable_total")


# --- Matrah TABANI: hangi satır girer? -------------------------------------


async def test_TASERON_satiri_MATRAHA_GIRER(client, ik_headers, donem, dort_tip):
    """🔴 Taban kararı — SGK bildirimi bir ÖDEME değil BİLDİRİMDİR.

    K2 taşeronu ÖDEMEDEN çıkarır (`excluded`), SGK tabanından DEĞİL: SGK 112-113
    taşeron satırlarını (Mehmet Yılmaz 26.400 / 22 gün · Ali Kaya 22.000 /
    20 gün — BY 194/214'ün AYNI satırları) bildirilecek çalışan listesinde
    gösterir ve SGK 55'in "48"i BY tfoot 298'in 48'idir (12+29+5+2, taşeron
    DAHİL). Taban `summary.py`nin MALİYET tabanıyla aynıdır, ÖDEME tabanıyla
    değil — T3'te iki tabanın ayrı tutulması bu yüzden yapıldı.
    """
    govde = await _ozet(client, ik_headers, donem)
    taseron_brut = Decimal("9000.00")

    assert _para(govde, "sgk_base_total") == MATRAH
    assert _para(govde, "sgk_base_total") - taseron_brut == MATRAH - taseron_brut
    # Taşeron çıkarılsaydı matrah 29.000 olurdu; 38.000 olması onun İÇERİDE
    # olduğunun kanıtıdır.
    assert _para(govde, "sgk_base_total") == Decimal("29000.00") + taseron_brut
    assert govde["declared_personnel_count"] == 4


async def test_S4_hesaplanamamis_satir_matraha_GIRMEZ_ve_AYRI_SAYILIR(
    client, ik_headers, donem, dort_tip
):
    """🔴 S4 fail-closed + sessiz atlama YOK (WORKFLOW §3).

    Brütü `null` olan satır 0 SAYILMAZ (matrahı sessizce küçültürdü) ve
    kaybolmaz: `uncomputed_count` onu GÖRÜNÜR kılar.
    """
    govde = await _ozet(client, ik_headers, donem)
    assert govde["uncomputed_count"] == 1
    assert _para(govde, "sgk_base_total") == MATRAH


async def test_orani_KAYBOLAN_satir_matraha_GIRMEZ_ve_AYRI_SAYILIR(
    client, ik_headers, donem, dort_tip, oranlar, db_session
):
    """🔴 Brütü BİLİNEN ama primi BİLİNMEYEN satır — fail-closed.

    Bu durum `compute` yolundan doğmaz (oran yoksa satır zaten `uncomputed`
    kalır, ŞEF KARARI 2); SONRADAN doğar: bir oran seti pasifleştirilirse
    (`is_active=false` — eski setler SİLİNMEZ, models.py) hesaplanmış brüt
    yerinde durur ama işveren/işçi primi artık türetilemez.

    Satırı matraha koymak tablonun kendi içinde çelişmesine (matrah var, prim
    yok) yol açardı; primini 0 saymak ise SGK'ya EKSİK bildirim olurdu. İkisi de
    yapılmaz: satır tabandan düşer ve `unknown_rate_count`ta GÖRÜNÜR
    (`summary.unknown_cost_count` kardeşi).
    """
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)
    sirket_orani = next(o for o in oranlar if o.personnel_source is WorkerSource.company)
    sirket_orani.is_active = False
    await db_session.flush()

    resp = await client.get(f"/payroll/periods/{donem.id}/sgk-summary", headers=ik_headers)
    govde = resp.json()

    assert govde["unknown_rate_count"] == 1  # Ayşe Demir (brüt 9.000 duruyor)
    assert _para(govde, "sgk_base_total") == MATRAH - Decimal("9000.00")
    assert govde["declared_personnel_count"] == 3


async def test_bos_donemde_toplamlar_SIFIR_sayaclar_sifir(client, ik_headers, donem):
    """Satırsız dönem GEÇERLİ bir özet döner — uydurma bir sayı basılmaz."""
    govde = await _ozet(client, ik_headers, donem, hesapla=False)
    assert govde["declared_personnel_count"] == 0
    assert _para(govde, "sgk_base_total") == Decimal("0.00")
    assert _para(govde, "sgk_payable_total") == Decimal("0.00")
    assert govde["uncomputed_count"] == 0


async def test_sgk_ozeti_denetim_YAZMAZ(client, ik_headers, donem, dort_tip, db_session):
    """Okuma ucudur (WORKFLOW): `record_audit` çağırmaz."""
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)
    once = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    await client.get(f"/payroll/periods/{donem.id}/sgk-summary", headers=ik_headers)
    sonra = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    assert sonra == once


# --- POST /payroll/periods/{id}/sgk-submit ---------------------------------


async def test_sgk_damgasi_basilir(client, ik_headers, donem, db_session):
    """SGK 44 "SGK'ya Gönder" — YALNIZ `sgk_submitted_at` damgası (spec §1).

    Dış sistem entegrasyonu YOKTUR: ne HTTP isteği, ne kuyruk, ne dosya.
    """
    resp = await client.post(f"/payroll/periods/{donem.id}/sgk-submit", headers=ik_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["sgk_submitted_at"] is not None

    damga = (
        await db_session.execute(
            select(PayrollPeriod.sgk_submitted_at).where(PayrollPeriod.id == donem.id)
        )
    ).scalar_one()
    assert damga is not None


async def test_IKINCI_damga_409(client, ik_headers, donem):
    """🔴 Tekrar damgalama YASAK — idempotent DEĞİL, 409.

    Damga bir OLAYIN zamanıdır (SGK 46'daki "son bildirim tarihi" ile
    karşılaştırılır). Sessizce yeniden yazılsaydı geç kalınmış bir bildirim
    ikinci bir tıklamayla zamanında yapılmış gibi görünürdü — uyum izi.
    """
    assert (
        await client.post(f"/payroll/periods/{donem.id}/sgk-submit", headers=ik_headers)
    ).status_code == 200
    tekrar = await client.post(f"/payroll/periods/{donem.id}/sgk-submit", headers=ik_headers)
    assert tekrar.status_code == 409, tekrar.text


async def test_damga_TASLAK_donemde_de_basilabilir(client, ik_headers, donem):
    """Dönem DURUMU ön koşul DEĞİLDİR — icat edilmez (WORKFLOW §3).

    SGK 44-47 banner'ı bildirimin "gönderilmediğini" ve son tarihin 6 gün sonra
    olduğunu söylerken BY 61 aynı dönemin bordrosunun HÂLÂ onay beklediğini
    yazar: mockup bildirimin ödeme onayından ÖNCE yapılabildiğini gösteriyor.
    Onay şartı koymak mockup'ın çizdiği durumu imkânsız kılardı.
    """
    assert donem.status.value == "draft"
    resp = await client.post(f"/payroll/periods/{donem.id}/sgk-submit", headers=ik_headers)
    assert resp.status_code == 200, resp.text


async def test_damga_yetki_ister_403(client, yetkisiz_headers, donem):
    resp = await client.post(f"/payroll/periods/{donem.id}/sgk-submit", headers=yetkisiz_headers)
    assert resp.status_code == 403


async def test_damga_olmayan_donem_404(client, ik_headers, seeded_db):
    import uuid

    resp = await client.post(f"/payroll/periods/{uuid.uuid4()}/sgk-submit", headers=ik_headers)
    assert resp.status_code == 404


async def test_damga_TEK_denetim_satiri_yazar(client, ik_headers, donem, db_session):
    once = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    await client.post(f"/payroll/periods/{donem.id}/sgk-submit", headers=ik_headers)
    sonra = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    assert sonra == once + 1
