"""İK-3 T3 — `PATCH /payroll/lines/{id}` (spec §5 son satırı).

Bu dilimin PARA kapısı burada: **S3 invariantı** (`banka + elden = net`) ve
**S5 değişmezliği** (onaylı satır dokunulmaz). Yanına K3 override izi ve K2'nin
yapısal kapısı eklenir.

Mockup'ta altı satırın altısında da invariant tutar — BY 143/146 (26.538+0) ·
191/194 (10.000+9.336) · 211/214 (0+16.080) · 231/234 (8.000+9.671) ·
259/262 (10.000+0) · 287/290 (7.500+0). Bölüşüm ekranda İKİ AYRI `input`tur
(BY 142-147), yani kullanıcı ikisini bağımsız yazabilir; toplamı NETE eşitleyen
tek şey SUNUCUDUR (spec S3: "istemci hesabına güvenilmez").
"""

from decimal import Decimal

import pytest

from app.modules.payroll.models import PayrollLineStatus, PayrollPeriodStatus

pytestmark = pytest.mark.asyncio

SIRKET_NET = Decimal("6681.69")  # 5 gün × 1.800 = 9.000 brüt, %25,759 kesinti


async def _satirlar(client, headers, donem) -> dict[str, dict]:
    """Hesaplanmış dönemin satırlarını PERSONEL ADIYLA anahtarlar."""
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=headers)
    detay = (await client.get(f"/payroll/periods/{donem.id}", headers=headers)).json()
    return {
        satir["personnel_name"]: satir for bolum in detay["sections"] for satir in bolum["lines"]
    }


# --- S3: banka + elden = net -----------------------------------------------


async def test_S3_bolusum_neti_tutmazsa_422(client, ik_headers, donem, dort_tip):
    """🔴 S3 — 1.000 + 1.000 ≠ 6.681,69: kayıp 4.681,69 ₺ sessizce yazılamaz."""
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]

    resp = await client.patch(
        f"/payroll/lines/{satir['id']}",
        json={"bank_amount": "1000.00", "cash_amount": "1000.00"},
        headers=ik_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_S3_KURUS_kaymasinda_da_422(client, ik_headers, donem, dort_tip):
    """🔴 S3 — tek kuruşluk fark da ihlaldir; `float` yaklaşıklığına düşülmez.

    6.681,68 + 0,02 = 6.681,70 ≠ 6.681,69. `float` ile karşılaştırılsaydı bu
    fark yuvarlama gürültüsünde kaybolabilirdi; `Decimal` ile KESİNDİR.
    """
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]

    resp = await client.patch(
        f"/payroll/lines/{satir['id']}",
        json={"bank_amount": "6681.68", "cash_amount": "0.02"},
        headers=ik_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_S3_tutan_bolusum_kabul_edilir(client, ik_headers, donem, dort_tip):
    """BY 191/194 deseni: kısmi banka + kısmi elden — toplam nete EŞİT."""
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]

    resp = await client.patch(
        f"/payroll/lines/{satir['id']}",
        json={"bank_amount": "6681.68", "cash_amount": "0.01"},
        headers=ik_headers,
    )
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert Decimal(govde["bank_amount"]) + Decimal(govde["cash_amount"]) == SIRKET_NET


async def test_bolusumun_TEK_bacagi_gonderilemez_422(client, ik_headers, donem, dort_tip):
    """Yalnız banka gönderilip elden sunucuya tamamlatılamaz.

    Tamamlatılsaydı S3 bir DOĞRULAMA değil bir HESAP olurdu ve istemcinin ne
    demek istediği ("gerisi elden mi, yoksa yanlış mı yazdım?") kaybolurdu.
    """
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]

    resp = await client.patch(
        f"/payroll/lines/{satir['id']}", json={"bank_amount": "6681.69"}, headers=ik_headers
    )
    assert resp.status_code == 422, resp.text


async def test_hesaplanamayan_satirda_bolusum_yapilamaz_422(client, ik_headers, donem, dort_tip):
    """S4 — neti `null` olan satırda `banka + elden` neye eşit olacaktı?"""
    satir = (await _satirlar(client, ik_headers, donem))["Zeynep Ak"]
    assert satir["status"] == PayrollLineStatus.uncomputed.value

    resp = await client.patch(
        f"/payroll/lines/{satir['id']}",
        json={"bank_amount": "0.00", "cash_amount": "0.00"},
        headers=ik_headers,
    )
    assert resp.status_code == 422, resp.text


# --- S5: onaylı/ödenmiş satır DEĞİŞTİRİLEMEZ -------------------------------


@pytest.mark.parametrize("durum", [PayrollLineStatus.approved, PayrollLineStatus.paid])
async def test_S5_onayli_satirda_PATCH_409(client, ik_headers, donem, dort_tip, db_session, durum):
    """🔴 S5 — ödeme izi: onaylanan tutar geriye dönük değiştirilemez."""
    from sqlalchemy import select

    from app.modules.payroll.models import PayrollLine

    satir_json = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    satir = (
        await db_session.execute(select(PayrollLine).where(PayrollLine.id == satir_json["id"]))
    ).scalar_one()
    satir.status = durum
    await db_session.flush()

    for govde in (
        {"gross_amount": "10000.00"},
        {"bank_amount": "6681.68", "cash_amount": "0.01"},
    ):
        resp = await client.patch(f"/payroll/lines/{satir.id}", json=govde, headers=ik_headers)
        assert resp.status_code == 409, resp.text


async def test_S5_onayli_DONEMDE_de_PATCH_409(client, ik_headers, donem, dort_tip, db_session):
    """Dönem onaylandıysa içindeki `uncomputed` satır da donar (spec S5 gerekçesi).

    Onaylanmış bir dönemin toplamları raporlanmıştır; içine sonradan bir satır
    büyütmek o raporu sessizce yalanlardı.
    """
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    donem.status = PayrollPeriodStatus.approved
    await db_session.flush()

    resp = await client.patch(
        f"/payroll/lines/{satir['id']}", json={"gross_amount": "10000.00"}, headers=ik_headers
    )
    assert resp.status_code == 409, resp.text


# --- K2: taşeron satırı --------------------------------------------------


async def test_K2_taseron_satirinda_PATCH_409(client, ik_headers, donem, dort_tip):
    """🔴 K2 — bölüşüm ÖDEMEYE dairdir; taşeron bordrodan ÖDENMEZ.

    Taşeronun ödemesi hakediş üzerinden yapılır (TH modülü); banka/elden
    alanının doldurulabilmesi, ödenmeyecek bir satır için ödeme talimatı
    hazırlanmasını ve çift ödemeyi mümkün kılardı. Brüt override'ı da aynı
    kapıdan döner: `excluded` satır yapısal bir terminaldir.
    """
    satir = (await _satirlar(client, ik_headers, donem))["Mehmet Yılmaz"]
    assert satir["status"] == PayrollLineStatus.excluded.value

    for govde in (
        {"gross_amount": "10000.00"},
        {"bank_amount": "6681.69", "cash_amount": "0.00"},
    ):
        resp = await client.patch(f"/payroll/lines/{satir['id']}", json=govde, headers=ik_headers)
        assert resp.status_code == 409, resp.text


# --- K3: brüt override izi -------------------------------------------------


async def test_K3_override_IZ_birakir_ve_net_yeniden_TURETILIR(client, ik_headers, donem, dort_tip):
    """🔴 K3 — kim/ne zaman/önceki değer + kesinti ve netin yeniden türetilmesi.

    10.000,00 × %25,759 = 2.575,90 → net 7.424,10. Kesinti ELLE girilmez ve
    eski kesinti KORUNMAZ: korunsaydı brütü büyütmek neti orantısız şişirirdi.
    """
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]

    resp = await client.patch(
        f"/payroll/lines/{satir['id']}", json={"gross_amount": "10000.00"}, headers=ik_headers
    )
    assert resp.status_code == 200, resp.text
    govde = resp.json()

    assert govde["is_overridden"] is True
    assert Decimal(govde["previous_gross_amount"]) == Decimal("9000.00")
    assert govde["overridden_at"] is not None
    assert Decimal(govde["deduction_amount"]) == Decimal("2575.90")
    assert Decimal(govde["net_amount"]) == Decimal("7424.10")
    # Bölüşüm de NETTEN yeniden türer — eski 6.681,69'luk banka tutarı kalsaydı
    # satır S3'ü ihlal eder durumda DB'ye yazılmış olurdu.
    assert Decimal(govde["bank_amount"]) == Decimal("7424.10")
    assert Decimal(govde["cash_amount"]) == Decimal("0.00")


async def test_K3_override_ve_bolusum_AYNI_govdede_verilebilir(client, ik_headers, donem, dort_tip):
    """Brüt + bölüşüm tek istekte: bölüşüm YENİ nete göre doğrulanır."""
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]

    resp = await client.patch(
        f"/payroll/lines/{satir['id']}",
        json={"gross_amount": "10000.00", "bank_amount": "5000.00", "cash_amount": "2424.10"},
        headers=ik_headers,
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["cash_amount"]) == Decimal("2424.10")

    # Eski nete (6.681,69) göre doğru olan bir bölüşüm YENİ nette 422'dir.
    satir2 = (await _satirlar(client, ik_headers, donem))["Kemal Tunç"]
    hatali = await client.patch(
        f"/payroll/lines/{satir2['id']}",
        json={"gross_amount": "20000.00", "bank_amount": "10000.00", "cash_amount": "0.00"},
        headers=ik_headers,
    )
    assert hatali.status_code == 422, hatali.text


async def test_K3_override_UNCOMPUTED_satiri_odenebilir_yapar(client, ik_headers, donem, dort_tip):
    """S4'ün çıkış kapısı: ücreti tanımsız kişiye elle brüt girilebilir.

    5.000,00 × %25,759 = 1.287,95 → net 3.712,05; satır `uncomputed` → `pending`.
    """
    satir = (await _satirlar(client, ik_headers, donem))["Zeynep Ak"]

    resp = await client.patch(
        f"/payroll/lines/{satir['id']}", json={"gross_amount": "5000.00"}, headers=ik_headers
    )
    assert resp.status_code == 200, resp.text
    govde = resp.json()
    assert govde["status"] == PayrollLineStatus.pending.value
    assert Decimal(govde["net_amount"]) == Decimal("3712.05")
    assert govde["previous_gross_amount"] is None  # önceki değer YOKTU — 0 uydurulmaz


async def test_K3_override_sonrasi_COMPUTE_satiri_ezmez(client, ik_headers, donem, dort_tip):
    """S6 — yeniden hesap kullanıcının düzeltmesini sessizce ezemez (T2 kanonu)."""
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    await client.patch(
        f"/payroll/lines/{satir['id']}", json={"gross_amount": "10000.00"}, headers=ik_headers
    )

    resp = await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)
    assert resp.json()["skipped_overridden"] == 1

    yeni = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    assert Decimal(yeni["gross_amount"]) == Decimal("10000.00")


async def test_orani_olmayan_satirda_override_422(client, ik_headers, donem, dort_tip, db_session):
    """ŞEF KARARI 2 (T2) — kesintisi bilinmeyen brütten net türetilmez."""
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    from sqlalchemy import select

    from app.modules.payroll.models import PayrollRate

    for rate in (await db_session.execute(select(PayrollRate))).scalars().all():
        rate.is_active = False
    await db_session.flush()

    resp = await client.patch(
        f"/payroll/lines/{satir['id']}", json={"gross_amount": "10000.00"}, headers=ik_headers
    )
    assert resp.status_code == 422, resp.text


# --- Gövde ve kapı korkulukları --------------------------------------------


async def test_BOS_govde_422(client, ik_headers, donem, dort_tip):
    """Hiçbir alan göndermemek bir "işlem" değildir; 200 dönmek yanıltıcı olurdu."""
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    assert (
        await client.patch(f"/payroll/lines/{satir['id']}", json={}, headers=ik_headers)
    ).status_code == 422


async def test_bilinmeyen_alan_422(client, ik_headers, donem, dort_tip):
    """`extra="forbid"` — istemci `net_amount`/`status` gönderip SUNUCU hesabını ezemez."""
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    for govde in ({"net_amount": "1.00"}, {"status": "approved"}, {"is_overridden": True}):
        resp = await client.patch(f"/payroll/lines/{satir['id']}", json=govde, headers=ik_headers)
        assert resp.status_code == 422, (govde, resp.text)


async def test_negatif_tutar_422(client, ik_headers, donem, dort_tip):
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    resp = await client.patch(
        f"/payroll/lines/{satir['id']}", json={"gross_amount": "-1.00"}, headers=ik_headers
    )
    assert resp.status_code == 422


async def test_olmayan_satir_404(client, ik_headers, seeded_db):
    resp = await client.patch(
        "/payroll/lines/00000000-0000-0000-0000-000000000001",
        json={"gross_amount": "1.00"},
        headers=ik_headers,
    )
    assert resp.status_code == 404


async def test_yetkisiz_rol_PATCH_403(client, ik_headers, yetkisiz_headers, donem, dort_tip):
    satir = (await _satirlar(client, ik_headers, donem))["Ayşe Demir"]
    resp = await client.patch(
        f"/payroll/lines/{satir['id']}", json={"gross_amount": "1.00"}, headers=yetkisiz_headers
    )
    assert resp.status_code == 403
