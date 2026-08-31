"""İK-3 T4 — onay + ödeme yolu (spec §5'in 6.-8. satırları).

Mockup otoritesi: BY 56 "Ödemeyi Onayla" · BY 303 "Tümünü Onayla" ·
BY 61 banner ("… bordrosu onay bekliyor").

Bu dosya PARA ÇIKIŞININ KAPISINI ölçer. Üç invariant burada çivilenir:

* **🔴 K2 — çift ödeme yapısal olarak imkânsız.** Taşeron satırı ÜÇ yolun
  üçünden de geçemez: satır onayı **409**, toplu onay **atlar** (ve sayıda
  görünür), `pay` onu **`paid` yapmaz ve ödeme toplamına katmaz**. Üç yol AYRI
  AYRI test edilir çünkü biri kapanıp öteki açık kalırsa taşerona aynı emek için
  hem hakediş (TH) hem bordro ödenirdi.
* **S4 fail-closed** — brütü `null` olan satır onaya GİRMEZ.
* **S8 atlama yok** — `draft` dönem ÖDENEMEZ; her adım komşusuna geçer.

Eşzamanlılık (EŞİK = KİLİT) `test_payroll_approval_concurrency.py`dedir: bu
dosyanın tek bağlantılı istemcisi yarışı ÖLÇEMEZ.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.payroll.models import PayrollLine, PayrollLineStatus, PayrollPeriodStatus

pytestmark = pytest.mark.asyncio

SIRKET_NET = Decimal("7650.00")  # IK3-GV: 9.000 − SGK 1.260 − işsizlik 90
SERBEST_NET = Decimal("10000.00")
STAJYER_NET = Decimal("7500.00")
#: `dort_tip`in ödenebilir üç satırının neti — taşeron (K2) ve ücretsiz (S4) HARİÇ.
ODENEBILIR_TOPLAM = SIRKET_NET + SERBEST_NET + STAJYER_NET


async def _satirlar(client, headers, donem) -> dict[str, dict]:
    """Hesaplanmış dönemin satırlarını PERSONEL ADIYLA anahtarlar."""
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=headers)
    detay = (await client.get(f"/payroll/periods/{donem.id}", headers=headers)).json()
    return {
        satir["personnel_name"]: satir for bolum in detay["sections"] for satir in bolum["lines"]
    }


async def _durum(db_session, line_id) -> PayrollLineStatus:
    return (
        await db_session.execute(select(PayrollLine.status).where(PayrollLine.id == line_id))
    ).scalar_one()


# --- POST /payroll/lines/{id}/approve --------------------------------------


async def test_bekleyen_satir_onaylanir(client, ik_headers, donem, dort_tip):
    """BY satır durumu "Beklemede" → "Onaylandı" (`pending → approved`)."""
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]

    resp = await client.post(f"/payroll/lines/{satir['id']}/approve", headers=ik_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == PayrollLineStatus.approved.value


async def test_K2_taseron_satiri_ONAYLANAMAZ_409(client, ik_headers, donem, dort_tip, db_session):
    """🔴 K2 — ÇİFT ÖDEMENİN BİRİNCİ YOLU kapalı.

    Taşeronun emeği hakediş (TH) üzerinden taşerona ödenir. Bordro satırı da
    onaylanabilseydi aynı emek İKİ KEZ ödenirdi. `excluded` satır geçiş
    tablosunda hiçbir çiftin KAYNAĞI değildir — yapısal terminaldir.
    """
    satir = (await _satirlar(client, ik_headers, donem))["Mehmet Yılmaz"]
    assert satir["status"] == PayrollLineStatus.excluded.value

    resp = await client.post(f"/payroll/lines/{satir['id']}/approve", headers=ik_headers)
    assert resp.status_code == 409, resp.text
    assert await _durum(db_session, satir["id"]) is PayrollLineStatus.excluded


async def test_S4_hesaplanamamis_satir_ONAYLANAMAZ_409(client, ik_headers, donem, dort_tip):
    """🔴 S4 fail-closed — brütü `null` olan satırda onaylanacak bir tutar YOKTUR.

    Onaylanabilseydi "ödenecek bir şey yok" yalanı ödeme listesine damgalanırdı;
    doğru yol brütü elle girmektir (K3 override'ı, `uncomputed → pending`).
    """
    satir = (await _satirlar(client, ik_headers, donem))["Zeynep Ak"]
    assert satir["status"] == PayrollLineStatus.uncomputed.value

    resp = await client.post(f"/payroll/lines/{satir['id']}/approve", headers=ik_headers)
    assert resp.status_code == 409, resp.text


async def test_zaten_ONAYLI_satir_yeniden_onaylanamaz_409(client, ik_headers, donem, dort_tip):
    """`approved → approved` tabloda YOKTUR: ikinci onay yeni bir olgu değildir."""
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    await client.post(f"/payroll/lines/{satir['id']}/approve", headers=ik_headers)

    resp = await client.post(f"/payroll/lines/{satir['id']}/approve", headers=ik_headers)
    assert resp.status_code == 409, resp.text


async def test_ODENMIS_satir_yeniden_onaylanamaz_409(
    client, ik_headers, donem, dort_tip, db_session
):
    """`paid` hiçbir çiftin kaynağı değildir: banka çıkışı geri sarılmaz."""
    satir_json = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    satir = (
        await db_session.execute(select(PayrollLine).where(PayrollLine.id == satir_json["id"]))
    ).scalar_one()
    satir.status = PayrollLineStatus.paid
    await db_session.flush()

    resp = await client.post(f"/payroll/lines/{satir.id}/approve", headers=ik_headers)
    assert resp.status_code == 409, resp.text


async def test_ONAYLI_DONEMDE_satir_onayi_409(client, ik_headers, donem, dort_tip, db_session):
    """S5'in dönem tarafı: onaylanmış dönemin toplamları RAPORLANMIŞTIR.

    İçine sonradan bir satır onaylamak o raporu sessizce yalanlardı — PATCH ile
    AYNI kapı (`LOCKED_PERIOD_STATUSES`).
    """
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    donem.status = PayrollPeriodStatus.approved
    await db_session.flush()

    resp = await client.post(f"/payroll/lines/{satir['id']}/approve", headers=ik_headers)
    assert resp.status_code == 409, resp.text


async def test_olmayan_satir_onayi_404(client, ik_headers, seeded_db):
    resp = await client.post(
        "/payroll/lines/00000000-0000-0000-0000-000000000001/approve", headers=ik_headers
    )
    assert resp.status_code == 404


async def test_yetkisiz_rol_satir_onayi_403(client, ik_headers, yetkisiz_headers, donem, dort_tip):
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    resp = await client.post(f"/payroll/lines/{satir['id']}/approve", headers=yetkisiz_headers)
    assert resp.status_code == 403


# --- POST /payroll/lines/{id}/reject ---------------------------------------


async def test_onayli_satirin_onayi_GERI_ALINIR(client, ik_headers, donem, dort_tip):
    """S5'in düzeltme yolu: `approved → pending` (tablodaki TEK geri geçiş).

    Ayrı bir `rejected` durumu YOKTUR ve icat edilmez: satır durumu kümesi
    T1'de kapanmıştır (`uncomputed/pending/approved/paid/excluded`). "Red",
    onayın geri alınmasıdır ve satırı yeniden DÜZENLENEBİLİR kılar.
    """
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    await client.post(f"/payroll/lines/{satir['id']}/approve", headers=ik_headers)

    resp = await client.post(f"/payroll/lines/{satir['id']}/reject", headers=ik_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == PayrollLineStatus.pending.value

    # Geri alınan satır yeniden düzenlenebilir olmalı (S5 kapısı açıldı).
    duzelt = await client.patch(
        f"/payroll/lines/{satir['id']}", json={"gross_amount": "10000.00"}, headers=ik_headers
    )
    assert duzelt.status_code == 200, duzelt.text


async def test_BEKLEYEN_satir_reddedilemez_409(client, ik_headers, donem, dort_tip):
    """`pending → pending` tabloda yoktur: geri alınacak bir onay YOKTUR."""
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]

    resp = await client.post(f"/payroll/lines/{satir['id']}/reject", headers=ik_headers)
    assert resp.status_code == 409, resp.text


async def test_S4_hesaplanamamis_satir_REDDEDILEMEZ_409(
    client, ik_headers, donem, dort_tip, db_session
):
    """🔴 Geçiş tablosu TEK BAŞINA yetmez — `uncomputed → pending` orada VARDIR.

    O çift K3 override'ının çıkışıdır (elle brüt girilince satır ödenebilir
    olur). Red yolundan kullanılabilseydi brütü `null` bir satır ONAY BEKLEYEN
    hâle gelir ve S4 fail-closed kapısı arkadan dolanılırdı. Kaynak durumu bu
    yüzden AÇIKÇA `approved` olmalıdır.
    """
    satir = (await _satirlar(client, ik_headers, donem))["Zeynep Ak"]
    assert satir["status"] == PayrollLineStatus.uncomputed.value

    resp = await client.post(f"/payroll/lines/{satir['id']}/reject", headers=ik_headers)
    assert resp.status_code == 409, resp.text
    assert await _durum(db_session, satir["id"]) is PayrollLineStatus.uncomputed


async def test_K2_taseron_satiri_REDDEDILEMEZ_409(client, ik_headers, donem, dort_tip):
    """`excluded` hiçbir yoldan durum DEĞİŞTİRMEZ — red de bir yol değildir."""
    satir = (await _satirlar(client, ik_headers, donem))["Mehmet Yılmaz"]

    resp = await client.post(f"/payroll/lines/{satir['id']}/reject", headers=ik_headers)
    assert resp.status_code == 409, resp.text


async def test_ODENMIS_satir_reddedilemez_409(client, ik_headers, donem, dort_tip, db_session):
    satir_json = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    satir = (
        await db_session.execute(select(PayrollLine).where(PayrollLine.id == satir_json["id"]))
    ).scalar_one()
    satir.status = PayrollLineStatus.paid
    await db_session.flush()

    resp = await client.post(f"/payroll/lines/{satir.id}/reject", headers=ik_headers)
    assert resp.status_code == 409, resp.text


async def test_olmayan_satir_reddi_404(client, ik_headers, seeded_db):
    resp = await client.post(
        "/payroll/lines/00000000-0000-0000-0000-000000000001/reject", headers=ik_headers
    )
    assert resp.status_code == 404


async def test_yetkisiz_rol_satir_reddi_403(client, ik_headers, yetkisiz_headers, donem, dort_tip):
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    resp = await client.post(f"/payroll/lines/{satir['id']}/reject", headers=yetkisiz_headers)
    assert resp.status_code == 403


# --- POST /payroll/periods/{id}/approve (BY 303 "Tümünü Onayla") -----------


async def test_toplu_onay_ATLANANLARI_SAYIYLA_raporlar(client, ik_headers, donem, dort_tip):
    """🔴 Sessiz atlama YOKTUR (WORKFLOW §3) — kırılım SEBEBE göredir.

    `dort_tip`: şirket + serbest + stajyer onaylanır (3); taşeron K2 yüzünden,
    ücretsiz S4 yüzünden atlanır. İki sebep AYRI sayılır çünkü kullanıcının
    yapacağı iş farklıdır: biri hakediş modülünün işidir, öteki eksik ücret
    verisidir.
    """
    await _satirlar(client, ik_headers, donem)

    resp = await client.post(f"/payroll/periods/{donem.id}/approve", headers=ik_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["approved"] == 3
    assert govde["skipped_excluded"] == 1
    assert govde["skipped_uncomputed"] == 1
    assert govde["skipped_already_approved"] == 0
    # T6: `compute` dönemi zaten `pending_approval` yaptı → tek onay `approved`.
    assert govde["period_status"] == PayrollPeriodStatus.approved.value


async def test_K2_toplu_onay_taseron_satirini_ATLAR(
    client, ik_headers, donem, dort_tip, db_session
):
    """🔴 K2 — ÇİFT ÖDEMENİN İKİNCİ YOLU kapalı.

    Toplu onay "hepsini onayla" demek DEĞİLDİR: taşeron satırı `excluded`
    KALIR. Kalmasaydı tek tuşla, satır ucunun 409'unu hiç görmeden çift ödeme
    kapısı açılırdı.
    """
    satirlar = await _satirlar(client, ik_headers, donem)
    await client.post(f"/payroll/periods/{donem.id}/approve", headers=ik_headers)

    assert (
        await _durum(db_session, satirlar["Mehmet Yılmaz"]["id"]) is PayrollLineStatus.excluded
    ), "taşeron satırı toplu onayla `approved` oldu — çift ödeme kapısı AÇIK"
    assert await _durum(db_session, satirlar["Ayşe Demir"]["id"]) is PayrollLineStatus.approved


async def test_T6_hesaptan_sonra_TEK_onay_tiki_yeter(client, ik_headers, donem, dort_tip):
    """🔴 T6 YÖNETİM KARARI — kullanıcının TEK tıkı BY 56 "Ödemeyi Onayla"dır.

    `compute` dönemi zaten `pending_approval` yapar (BY 63 banner'ı: "… onay
    bekliyor"), bu yüzden onay ucuna TEK çağrı dönemi `approved` yapar. Eskiden
    iki çağrı gerekiyordu (`draft → pending_approval` ilk tıkla atılıyordu) —
    mockup'ta böyle bir "onaya gönder" tıkı YOK.

    S8 hâlâ atlamıyor: adım zinciri aynı, yalnız ilk adımın tetikleyicisi
    hesaplamadır.
    """
    await _satirlar(client, ik_headers, donem)
    durum = (await client.get(f"/payroll/periods/{donem.id}", headers=ik_headers)).json()["status"]
    assert durum == PayrollPeriodStatus.pending_approval.value

    ilk = await client.post(f"/payroll/periods/{donem.id}/approve", headers=ik_headers)
    assert ilk.status_code == 200, ilk.text
    assert ilk.json()["period_status"] == PayrollPeriodStatus.approved.value
    assert ilk.json()["approved"] == 3

    ikinci = await client.post(f"/payroll/periods/{donem.id}/approve", headers=ik_headers)
    assert ikinci.status_code == 409, ikinci.text


async def test_S8_TASLAK_donemde_onay_yine_KOMSU_adima_gecer(
    client, ik_headers, donem, dort_tip, db_session
):
    """S8 — zincir DEĞİŞMEDİ: `draft`tan çağrılırsa yine BİR adım ilerler.

    Yeni akışta `draft` dönemde onaylanacak satır normalde yoktur (hesaplanmış
    dönem `pending_approval`dır), ama tablo hâlâ `draft → approved` atlamasını
    reddeder — geçiş KÜMESİ T6'da dokunulmamıştır.
    """
    await _satirlar(client, ik_headers, donem)
    donem.status = PayrollPeriodStatus.draft
    await db_session.flush()

    ilk = await client.post(f"/payroll/periods/{donem.id}/approve", headers=ik_headers)
    assert ilk.json()["period_status"] == PayrollPeriodStatus.pending_approval.value

    ikinci = await client.post(f"/payroll/periods/{donem.id}/approve", headers=ik_headers)
    assert ikinci.status_code == 200, ikinci.text
    assert ikinci.json()["period_status"] == PayrollPeriodStatus.approved.value
    # İlk turda satırlar onaylanmıştır; ikincide onaylanacak satır kalmaz.
    assert ikinci.json()["approved"] == 0
    assert ikinci.json()["skipped_already_approved"] == 3


# --- 🔴 KRIT-BORDRO: ödenecek satırı olmayan dönem onaylanamaz --------------
#
# Ölçülen zarar: boş bir dönem İKİ istekte `approved` oluyordu ve o andan sonra
# `compute` 409, satır `PATCH` 409, dönem `DELETE` 405 (uç YOK), aynı ayı
# yeniden açmak 409 (UQ `year, month`) — o ayın bordrosu elle SQL dışında
# kurtarılamaz hâle geliyordu.
#
# Bekçi YENİ DEĞİLDİR: `compute_flow._promote_period_after_compute` bu zararı
# ("geri dönüşü olmayan bir boş onay") zaten tarif edip KENDİ kapısında
# durduruyordu. Kusur, aynı `draft → pending_approval` çiftinin onay ucundan
# ELLE de sürülebilmesiydi. Yüklem artık `core.has_payable_line`de TEK KOPYA.
#
# 🔴 Bu blokta dönem `donem` fixture'ıyla DEĞİL, ÜRÜNÜN KENDİ UCUYLA
# (`POST /payroll/periods`) açılır: fixture dönemi ORM'de elle kurar ve kapı
# o zaman "ürünün ürettiği bir hâli" değil "testin kurduğu bir hâli" ölçmüş
# olurdu.


async def _donem_ac(client, headers, *, month: int) -> str:
    resp = await client.post(
        "/payroll/periods", json={"year": 2026, "month": month}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _donem_durumu(client, headers, period_id: str) -> str:
    resp = await client.get(f"/payroll/periods/{period_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["status"]


async def test_KRIT_HIC_SATIRI_OLMAYAN_donem_ONAYLANAMAZ_409(client, ik_headers, oranlar):
    """🔴 Hesaplanmamış (satırsız) dönem onay zincirine GİRMEZ — İLK tıkta 409.

    Zincire hiç girmemesi ŞARTTIR: `pending_approval`a düşseydi ikinci tık
    dönemi `approved` yapar ve `compute` kapısı o ayın üzerine KALICI kapanırdı.
    """
    period_id = await _donem_ac(client, ik_headers, month=7)

    resp = await client.post(f"/payroll/periods/{period_id}/approve", headers=ik_headers)
    assert resp.status_code == 409, resp.text
    assert "Ödenecek satırı olmayan" in resp.json()["detail"]

    # 🔴 Dönem YAZILMAMIŞ olmalı: 409 yanıtı, "girip çıkmış" bir durumu örtmez.
    assert await _donem_durumu(client, ik_headers, period_id) == PayrollPeriodStatus.draft.value


async def test_KRIT_PUANTAJSIZ_donem_ONAYLANAMAZ_ve_PUANTAJ_GIRILINCE_ONAYLANIR(
    client, ik_headers, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """🔴 Kullanıcının bildirdiği hâl + POZİTİF KONTROL aynı testte.

    Puantaj girilmemişken tüm satırlar `uncomputed`tır (S4): dönemde ödenecek
    hiçbir şey yoktur ve onay **409**dur. `compute` kapısı AÇIK kalır — kapının
    işi kullanıcıyı tıkamak değil, KURTARILABİLİR tarafta tutmaktır.

    🔴 İkinci yarı KARŞIT KANITTIR (K-IKIZ1): puantaj girilip dönem yeniden
    hesaplandığında AYNI dönem AYNI uçtan **200** ile onaylanır. Bu olmadan her
    gövdeye 409 veren bozuk bir uç da testi yeşil geçirirdi.
    """
    kisi = await personel_fabrikasi("Ayşe Demir")
    period_id = await _donem_ac(client, ik_headers, month=7)

    ilk_hesap = await client.post(f"/payroll/periods/{period_id}/compute", headers=ik_headers)
    assert ilk_hesap.status_code == 200, ilk_hesap.text
    assert await _donem_durumu(client, ik_headers, period_id) == PayrollPeriodStatus.draft.value

    reddedilen = await client.post(f"/payroll/periods/{period_id}/approve", headers=ik_headers)
    assert reddedilen.status_code == 409, reddedilen.text
    assert await _donem_durumu(client, ik_headers, period_id) == PayrollPeriodStatus.draft.value

    # --- POZİTİF KONTROL: dolu dönem AYNI uçtan GEÇMELİ ---
    await puantaj_fabrikasi(kisi, [1, 2, 3, 4, 5])
    ikinci_hesap = await client.post(f"/payroll/periods/{period_id}/compute", headers=ik_headers)
    assert ikinci_hesap.status_code == 200, ikinci_hesap.text
    assert (
        await _donem_durumu(client, ik_headers, period_id)
        == PayrollPeriodStatus.pending_approval.value
    )

    gecen = await client.post(f"/payroll/periods/{period_id}/approve", headers=ik_headers)
    assert gecen.status_code == 200, gecen.text
    assert gecen.json()["period_status"] == PayrollPeriodStatus.approved.value
    assert gecen.json()["approved"] == 1


async def test_KRIT_ODENEBILIR_SATIRI_KALMAYAN_PENDING_APPROVAL_donemi_ONAYLANAMAZ_409(
    client, ik_headers, oranlar, personel_fabrikasi, puantaj_fabrikasi, db_session
):
    """🔴 İKİNCİ ADIM da bekçilenir — ve bu hâl ULAŞILABİLİRDİR (ölçüldü).

    Terfi (`_promote_period_after_compute`) yalnız `draft` döneme bakar, yani
    `pending_approval`a çıkmış bir dönem ödenebilir satırını SONRADAN
    kaybedebilir: personelin ücret tanımı kaldırılıp `compute` yeniden koşarsa
    satır `uncomputed`a düşer, dönem `pending_approval` KALIR. Denetim yalnız
    `draft → pending_approval` çiftine konsaydı buradaki TEK tık dönemi yine
    boş boş `approved` yapardı — kapı kurulmuş ama HÂL ATLANMIŞ olurdu.

    Kapının kullanıcıya bıraktığı çıkış onay değil YENİDEN HESAPTIR:
    `pending_approval` kilitli olmadığı için `compute` hâlâ **200**dür.
    """
    kisi = await personel_fabrikasi("Ayşe Demir")
    await puantaj_fabrikasi(kisi, [1, 2, 3, 4, 5])
    period_id = await _donem_ac(client, ik_headers, month=7)
    assert (
        await client.post(f"/payroll/periods/{period_id}/compute", headers=ik_headers)
    ).status_code == 200
    assert (
        await _donem_durumu(client, ik_headers, period_id)
        == PayrollPeriodStatus.pending_approval.value
    )

    # Ücret tanımı kalkar → yeniden hesapta satır `uncomputed`a düşer.
    kisi.wage_type = None
    kisi.wage_amount = None
    await db_session.flush()
    assert (
        await client.post(f"/payroll/periods/{period_id}/compute", headers=ik_headers)
    ).status_code == 200
    assert (
        await _donem_durumu(client, ik_headers, period_id)
        == PayrollPeriodStatus.pending_approval.value
    )

    resp = await client.post(f"/payroll/periods/{period_id}/approve", headers=ik_headers)
    assert resp.status_code == 409, resp.text
    assert (
        await _donem_durumu(client, ik_headers, period_id)
        == PayrollPeriodStatus.pending_approval.value
    )
    # Kurtarma yolu AÇIK: dönem hâlâ hesaplanabilir.
    assert (
        await client.post(f"/payroll/periods/{period_id}/compute", headers=ik_headers)
    ).status_code == 200


async def test_KRIT_TEK_TEK_ONAYLANMIS_satirli_donem_ONAYLANABILIR(
    client, ik_headers, oranlar, personel_fabrikasi, puantaj_fabrikasi
):
    """🔴 Kapı `pending` DEĞİL `PAYABLE` sorar — ve fark ÖLÇÜLEBİLİRDİR.

    `draft` dönem kilitli değildir, yani kullanıcı satırı TEK TEK onaylayıp
    (`approve_line`) dönemi `pending` satırsız bırakabilir. Bekçi yalnız
    `pending` sorsaydı, içinde onaylanmış GERÇEK bir satır bulunan bu dönem
    onaylanamaz olur ve kapı kusursuz bir dönemi TIKARDI.
    """
    kisi = await personel_fabrikasi("Ayşe Demir")
    await puantaj_fabrikasi(kisi, [1, 2, 3, 4, 5])
    period_id = await _donem_ac(client, ik_headers, month=7)
    await client.post(f"/payroll/periods/{period_id}/compute", headers=ik_headers)

    detay = (await client.get(f"/payroll/periods/{period_id}", headers=ik_headers)).json()
    satir = [s for bolum in detay["sections"] for s in bolum["lines"]][0]
    tekil = await client.post(f"/payroll/lines/{satir['id']}/approve", headers=ik_headers)
    assert tekil.status_code == 200, tekil.text

    resp = await client.post(f"/payroll/periods/{period_id}/approve", headers=ik_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["period_status"] == PayrollPeriodStatus.approved.value
    assert resp.json()["skipped_already_approved"] == 1


async def test_ODENMIS_donem_yeniden_onaylanamaz_409(
    client, ik_headers, donem, dort_tip, db_session
):
    donem.status = PayrollPeriodStatus.paid
    await db_session.flush()

    resp = await client.post(f"/payroll/periods/{donem.id}/approve", headers=ik_headers)
    assert resp.status_code == 409, resp.text


async def test_olmayan_donem_onayi_404(client, ik_headers, seeded_db):
    resp = await client.post(
        "/payroll/periods/00000000-0000-0000-0000-000000000001/approve", headers=ik_headers
    )
    assert resp.status_code == 404


async def test_yetkisiz_rol_donem_onayi_403(client, yetkisiz_headers, donem, dort_tip):
    resp = await client.post(f"/payroll/periods/{donem.id}/approve", headers=yetkisiz_headers)
    assert resp.status_code == 403


# --- POST /payroll/periods/{id}/pay (BY 56 sonrası ödeme damgası) ----------


async def _onaya_kadar(client, headers, donem) -> dict[str, dict]:
    """Hesapla + onayla. T6'dan sonra onay TEK çağrıdır: `compute` dönemi zaten
    `pending_approval` bırakır, tek `approve` onu `approved` yapar."""
    satirlar = await _satirlar(client, headers, donem)
    resp = await client.post(f"/payroll/periods/{donem.id}/approve", headers=headers)
    assert resp.json()["period_status"] == PayrollPeriodStatus.approved.value, resp.text
    return satirlar


async def test_odeme_damgasi_donemi_ve_satirlari_paid_yapar(client, ik_headers, donem, dort_tip):
    await _onaya_kadar(client, ik_headers, donem)

    resp = await client.post(f"/payroll/periods/{donem.id}/pay", headers=ik_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["period_status"] == PayrollPeriodStatus.paid.value
    assert govde["paid_at"] is not None
    assert govde["paid"] == 3
    assert Decimal(govde["paid_net_total"]) == ODENEBILIR_TOPLAM


async def test_K2_odeme_taseron_satirini_ODEMEZ_ve_TOPLAMA_KATMAZ(
    client, ik_headers, donem, dort_tip, db_session
):
    """🔴 K2 — ÇİFT ÖDEMENİN ÜÇÜNCÜ YOLU kapalı.

    Taşeron satırı ne `paid` olur ne de ödeme toplamına girer. Toplama girseydi
    banka talimatı taşeron işçisinin netini de taşır ve aynı emek hem hakedişten
    hem bordrodan ödenirdi.
    """
    satirlar = await _onaya_kadar(client, ik_headers, donem)
    taseron = satirlar["Mehmet Yılmaz"]

    resp = await client.post(f"/payroll/periods/{donem.id}/pay", headers=ik_headers)
    govde = resp.json()

    assert await _durum(db_session, taseron["id"]) is PayrollLineStatus.excluded
    assert govde["skipped_excluded"] == 1
    assert Decimal(govde["paid_net_total"]) == ODENEBILIR_TOPLAM
    assert Decimal(govde["paid_net_total"]) < ODENEBILIR_TOPLAM + Decimal(taseron["net_amount"])


async def _satiri_zorla(db_session, line_id, **alanlar) -> None:
    """Uçlardan ERİŞİLEMEYEN bir durumu doğrudan kurar (savunma derinliği testi)."""
    satir = (
        await db_session.execute(select(PayrollLine).where(PayrollLine.id == line_id))
    ).scalar_one()
    for ad, deger in alanlar.items():
        setattr(satir, ad, deger)
    await db_session.flush()


async def test_odeme_ONAYLANMAMIS_satiri_odemez_ve_raporlar(
    client, ik_headers, donem, dort_tip, db_session
):
    """Onaysız satır ÖDENMEZ — ve sessizce atlanmaz.

    ⚠️ Bu durum uçlardan ERİŞİLEMEZ ve bu iyi bir özelliktir: toplu onay TÜM
    `pending` satırları onaylar, dönem onaylandıktan sonra da satır onayı/reddi
    kapanır (`PERIOD_LOCKED_FOR_DECISION`). Yani "dönem onaylı ama satır
    onaysız" hâli bugün doğmaz. Kapı yine de SERVİSTE durur ve burada durum
    ELLE kurularak ölçülür: yarın satırı geri alan ikinci bir yol eklenirse
    (spec S8'in literal okuması buna izin verir) onaysız para ÇIKMAMALIDIR.
    """
    satirlar = await _onaya_kadar(client, ik_headers, donem)
    await _satiri_zorla(db_session, satirlar["Ayşe Demir"]["id"], status=PayrollLineStatus.pending)

    resp = await client.post(f"/payroll/periods/{donem.id}/pay", headers=ik_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["paid"] == 2
    assert govde["skipped_unapproved"] == 1
    assert Decimal(govde["paid_net_total"]) == ODENEBILIR_TOPLAM - SIRKET_NET
    assert await _durum(db_session, satirlar["Ayşe Demir"]["id"]) is PayrollLineStatus.pending


async def test_NETI_BILINMEYEN_onayli_satir_TUM_odemeyi_durdurur_409(
    client, ik_headers, donem, dort_tip, db_session
):
    """🔴 Fail-closed (NULL-EŞİK kanonu) — bilinmeyen tutar 0 SAYILMAZ.

    T1 invariantına göre onaylı satırın neti `null` olamaz (S4 kapısı onayı
    engeller). Yine de olsaydı: 0 sayılıp geçilseydi o kişiye hiç ödeme
    yapılmaz ve eksik ancak banka ekstresinden anlaşılırdı. Ödeme TOPTAN durur.
    """
    satirlar = await _onaya_kadar(client, ik_headers, donem)
    await _satiri_zorla(db_session, satirlar["Ayşe Demir"]["id"], net_amount=None)

    resp = await client.post(f"/payroll/periods/{donem.id}/pay", headers=ik_headers)
    assert resp.status_code == 409, resp.text


@pytest.mark.parametrize("durum", [PayrollPeriodStatus.draft, PayrollPeriodStatus.pending_approval])
async def test_S8_ONAYLANMAMIS_donem_ODENEMEZ_409(
    client, ik_headers, donem, dort_tip, db_session, durum
):
    """🔴 S8 atlama yok — `draft → paid` para çıkışının onay zincirini atlardı."""
    await _satirlar(client, ik_headers, donem)
    donem.status = durum
    await db_session.flush()

    resp = await client.post(f"/payroll/periods/{donem.id}/pay", headers=ik_headers)
    assert resp.status_code == 409, resp.text


async def test_ODENMIS_donem_yeniden_odenemez_409(client, ik_headers, donem, dort_tip):
    """🔴 İkinci `pay` = ikinci para çıkışı. `paid` hiçbir çiftin kaynağı değildir."""
    await _onaya_kadar(client, ik_headers, donem)
    await client.post(f"/payroll/periods/{donem.id}/pay", headers=ik_headers)

    resp = await client.post(f"/payroll/periods/{donem.id}/pay", headers=ik_headers)
    assert resp.status_code == 409, resp.text


async def test_S5_odenmis_donemde_PATCH_409(client, ik_headers, donem, dort_tip):
    """Ödeme sonrası satır DONAR — T3'ün S5 kapısı ödeme yolunda da geçerli."""
    satirlar = await _onaya_kadar(client, ik_headers, donem)
    await client.post(f"/payroll/periods/{donem.id}/pay", headers=ik_headers)

    resp = await client.patch(
        f"/payroll/lines/{satirlar['Ayşe Demir']['id']}",
        json={"gross_amount": "1.00"},
        headers=ik_headers,
    )
    assert resp.status_code == 409, resp.text


async def test_olmayan_donem_odemesi_404(client, ik_headers, seeded_db):
    resp = await client.post(
        "/payroll/periods/00000000-0000-0000-0000-000000000001/pay", headers=ik_headers
    )
    assert resp.status_code == 404


async def test_yetkisiz_rol_odeme_403(client, yetkisiz_headers, donem, dort_tip):
    resp = await client.post(f"/payroll/periods/{donem.id}/pay", headers=yetkisiz_headers)
    assert resp.status_code == 403


# --- Denetim izi -----------------------------------------------------------


async def test_onay_ve_odeme_DENETIM_satiri_yazar(client, ik_headers, donem, dort_tip, db_session):
    """Onay/ödeme PARA olaylarıdır: her biri TEK denetim satırı bırakır (B5 deseni)."""
    from app.modules.audit.models import AuditAction, AuditLog

    satirlar = await _satirlar(client, ik_headers, donem)
    await client.post(f"/payroll/lines/{satirlar['Ayşe Demir']['id']}/approve", headers=ik_headers)
    # T6: dönem onayı TEK çağrıdır (`compute` `pending_approval` bıraktı).
    await client.post(f"/payroll/periods/{donem.id}/approve", headers=ik_headers)
    await client.post(f"/payroll/periods/{donem.id}/pay", headers=ik_headers)

    kayitlar = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == AuditAction.approve)))
        .scalars()
        .all()
    )
    assert len(kayitlar) == 3, [k.detail for k in kayitlar]
    assert any("Ayşe Demir" in k.detail for k in kayitlar)
    assert any("ödendi" in k.detail.lower() for k in kayitlar)
