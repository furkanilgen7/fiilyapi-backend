"""İK-3 T3 — dönem uçları (spec §5'in ilk dört satırı).

| Uç | Mockup |
|---|---|
| `GET /payroll/periods` | BG 44-47 + tbody |
| `POST /payroll/periods` | BY 52 ay seçici (yeni ay açma) |
| `GET /payroll/periods/{id}` | BY 69-93 kartlar + 124/172/240/268 bölümler |
| `POST /payroll/periods/{id}/compute` | BY tablosunun doldurulması |

**Bordro şirket geneli bir İK varlığıdır → `visible_projects` süzgeci YOKTUR**
(`personnel`/`timesheet` deseni). Bu BİLİNÇLİDİR ve altta testle kilitlidir —
unutulmuş bir kapsam denetimi ile ayırt edilebilsin diye.
"""

from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio


# --- Kapılar (spec S9: okuma `view`, yazma `full`) --------------------------


async def test_yetkisiz_rol_OKUMADA_bile_403(client, yetkisiz_headers):
    """`site_chief` matriste `payroll=_N` (seed_data.py:182) — bordroyu göremez."""
    resp = await client.get("/payroll/periods", headers=yetkisiz_headers)
    assert resp.status_code == 403


async def test_kimliksiz_istek_401(client):
    assert (await client.get("/payroll/periods")).status_code == 401


# --- POST /payroll/periods --------------------------------------------------


async def test_ay_acilir(client, ik_headers, seeded_db):
    resp = await client.post(
        "/payroll/periods", json={"year": 2026, "month": 8}, headers=ik_headers
    )
    assert resp.status_code == 201, resp.text
    govde = resp.json()
    assert (govde["year"], govde["month"]) == (2026, 8)
    assert govde["status"] == "draft"
    # Yeni ay BOŞTUR: satır yoktur, kartlar sıfırdır — uydurma bir toplam basılmaz.
    assert govde["summary"]["line_count"] == 0
    assert govde["sections"] == []


async def test_ayni_ay_IKINCI_kez_acilamaz_409(client, ik_headers, donem):
    """UQ `(year, month)` — bir ay için TEK bordro (spec §4)."""
    resp = await client.post(
        "/payroll/periods", json={"year": donem.year, "month": donem.month}, headers=ik_headers
    )
    assert resp.status_code == 409


async def test_gecersiz_ay_422(client, ik_headers, seeded_db):
    assert (
        await client.post("/payroll/periods", json={"year": 2026, "month": 13}, headers=ik_headers)
    ).status_code == 422


async def test_govdede_durum_gonderilemez_422(client, ik_headers, seeded_db):
    """`extra="forbid"` — istemci dönemi doğrudan `paid` açamaz (İK-2 `days` emsali)."""
    resp = await client.post(
        "/payroll/periods",
        json={"year": 2026, "month": 9, "status": "paid"},
        headers=ik_headers,
    )
    assert resp.status_code == 422


async def test_acma_ucu_view_ile_gecilmez_403(client, yetkisiz_headers):
    assert (
        await client.post(
            "/payroll/periods", json={"year": 2026, "month": 10}, headers=yetkisiz_headers
        )
    ).status_code == 403


# --- PATCH /payroll/periods/{id} · ödeme tarihi (T4b, YÖNETİM KARARI 2) -----
#
# BY 63 banner'ı "Son ödeme: 20 Temmuz 2026" diye OKUR ama mockup bu alanın
# FORMUNU çizmez; BG'de üç dönemin de ayın 20'sini göstermesi bir İŞ KURALI
# değildir (WORKFLOW §3: mockup'ta olmayan kural uydurulmaz). Bu yüzden alan
# OPSİYONELDİR: sunucu tarih ÜRETMEZ, varsayılan KOYMAZ, yıl/ay tutarlılığı
# DENETLEMEZ — verilmezse `null` kalır ve banner'ın basılıp basılmaması
# frontend'in zarif düşüşüdür.


async def test_odeme_tarihi_OPSIYONEL_sunucu_URETMEZ(client, ik_headers, seeded_db):
    """🔴 Alan gönderilmezse `null` KALIR — "her ayın 20'si" uydurulmaz."""
    resp = await client.post(
        "/payroll/periods", json={"year": 2026, "month": 8}, headers=ik_headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["payment_due_date"] is None


async def test_odeme_tarihi_SONRAKI_AYA_sarkabilir(client, ik_headers, seeded_db):
    """Yıl/ay tutarlılığı DENETLENMEZ: Temmuz bordrosu Ağustos'ta ödenebilir.

    Gerçek hayatta olan bir durumu şemayla yasaklamak, kullanıcıyı yanlış tarih
    girmeye zorlardı.
    """
    resp = await client.post(
        "/payroll/periods",
        json={"year": 2026, "month": 8, "payment_due_date": "2026-09-05"},
        headers=ik_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["payment_due_date"] == "2026-09-05"


async def test_PATCH_odeme_tarihini_yazar(client, ik_headers, donem):
    """BY 63'ün beslendiği alan `draft` dönemde yazılabilir."""
    resp = await client.patch(
        f"/payroll/periods/{donem.id}",
        json={"payment_due_date": "2026-07-20"},
        headers=ik_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_due_date"] == "2026-07-20"

    detay = (await client.get(f"/payroll/periods/{donem.id}", headers=ik_headers)).json()
    assert detay["payment_due_date"] == "2026-07-20"


async def test_PATCH_ONAY_BEKLEYEN_donemde_de_acik(client, ik_headers, donem, db_session):
    """Ödeme takvimi onaya girmiş bordroda hâlâ düzeltilebilir — para henüz çıkmadı."""
    from app.modules.payroll.models import PayrollPeriodStatus

    donem.status = PayrollPeriodStatus.pending_approval
    await db_session.flush()

    resp = await client.patch(
        f"/payroll/periods/{donem.id}",
        json={"payment_due_date": "2026-07-25"},
        headers=ik_headers,
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("durum", ["approved", "paid"])
async def test_PATCH_onayli_ve_odenmis_donemde_409(client, ik_headers, donem, db_session, durum):
    """🔴 `approved` ve `paid` KAPALIDIR.

    Ödeme gerçekleştikten sonra "son ödeme tarihi"ni değiştirmek, gerçekleşmiş
    bir olayın kaydını sonradan düzeltmektir ve para izini bozar. `approved`ta
    da kapalıdır: onaylanmış bordronun ödeme takvimi tek taraflı kaymamalıdır —
    değişmesi gerekiyorsa dönem `pending_approval`a geri alınır (S8'in zaten
    izin verdiği yol; YENİ yol icat edilmez).
    """
    from app.modules.payroll.models import PayrollPeriodStatus

    donem.status = PayrollPeriodStatus(durum)
    await db_session.flush()

    resp = await client.patch(
        f"/payroll/periods/{donem.id}",
        json={"payment_due_date": "2026-07-20"},
        headers=ik_headers,
    )
    assert resp.status_code == 409, resp.text


async def test_PATCH_ACIK_null_ile_tarih_SILINIR(client, ik_headers, donem):
    """Açıkça `null` göndermek tarihi TEMİZLER — yanlış girilen tarih geri alınabilir."""
    await client.patch(
        f"/payroll/periods/{donem.id}",
        json={"payment_due_date": "2026-07-20"},
        headers=ik_headers,
    )
    resp = await client.patch(
        f"/payroll/periods/{donem.id}", json={"payment_due_date": None}, headers=ik_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_due_date"] is None


async def test_PATCH_BOS_govde_422(client, ik_headers, donem):
    """Boş gövde bir işlem DEĞİLDİR (satır PATCH'iyle aynı karar).

    `{}` ile `{"payment_due_date": null}` ayrımı `model_fields_set` ile korunur:
    ikisi tek davranışa indirgenseydi ya boş istek sessizce tarihi silerdi ya da
    açık `null` ile silmek imkânsız olurdu.
    """
    resp = await client.patch(f"/payroll/periods/{donem.id}", json={}, headers=ik_headers)
    assert resp.status_code == 422, resp.text


async def test_PATCH_bilinmeyen_alan_422(client, ik_headers, donem):
    """`extra="forbid"` — durum/onay alanları bu uçtan sızamaz."""
    resp = await client.patch(
        f"/payroll/periods/{donem.id}",
        json={"payment_due_date": "2026-07-20", "status": "paid"},
        headers=ik_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_PATCH_olmayan_donem_404(client, ik_headers, seeded_db):
    """Görünmeyen ile var olmayan AYIRT EDİLEMEZ (spec §6.8)."""
    resp = await client.patch(
        "/payroll/periods/00000000-0000-0000-0000-000000000001",
        json={"payment_due_date": "2026-07-20"},
        headers=ik_headers,
    )
    assert resp.status_code == 404


async def test_PATCH_yetkisiz_rol_403(client, yetkisiz_headers, donem):
    """Diğer yazma uçlarıyla AYNI kapı: `payroll:full`."""
    resp = await client.patch(
        f"/payroll/periods/{donem.id}",
        json={"payment_due_date": "2026-07-20"},
        headers=yetkisiz_headers,
    )
    assert resp.status_code == 403


async def test_PATCH_DENETIM_satiri_yazar(client, ik_headers, donem, db_session):
    """Dönem değişikliği iz bırakır (B5 deseni, mevcut yazma uçlarıyla aynı)."""
    from sqlalchemy import select

    from app.modules.audit.models import AuditAction, AuditLog

    await client.patch(
        f"/payroll/periods/{donem.id}",
        json={"payment_due_date": "2026-07-20"},
        headers=ik_headers,
    )

    kayitlar = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == AuditAction.update)))
        .scalars()
        .all()
    )
    assert len(kayitlar) == 1, [k.detail for k in kayitlar]
    assert "2026-07-20" in kayitlar[0].detail


# --- POST /payroll/periods/{id}/compute -------------------------------------


async def test_compute_satirlari_uretir(client, ik_headers, donem, dort_tip):
    resp = await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "created": 5,
        "updated": 0,
        "skipped_overridden": 0,
        "skipped_approved": 0,
    }


async def test_onayli_donem_yeniden_HESAPLANMAZ_409(
    client, ik_headers, donem, dort_tip, db_session
):
    from app.modules.payroll.models import PayrollPeriodStatus

    donem.status = PayrollPeriodStatus.approved
    await db_session.flush()

    resp = await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)
    assert resp.status_code == 409


async def test_olmayan_donemde_compute_404(client, ik_headers, seeded_db):
    resp = await client.post(
        "/payroll/periods/00000000-0000-0000-0000-000000000001/compute", headers=ik_headers
    )
    assert resp.status_code == 404


# --- GET /payroll/periods/{id} ---------------------------------------------


async def test_detay_dort_karti_ve_bolumleri_dondurur(client, ik_headers, donem, dort_tip):
    """BY 69-93 dört kart + BY 124/172/240/268 tip bazında gruplama."""
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)
    resp = await client.get(f"/payroll/periods/{donem.id}", headers=ik_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()

    ozet = govde["summary"]
    assert Decimal(ozet["net_total"]) == Decimal("24181.69")  # 1. kart (BY 69-71)
    assert Decimal(ozet["bank_total"]) == Decimal("24181.69")  # 2. kart (BY 76-79)
    assert Decimal(ozet["cash_total"]) == Decimal("0.00")  # 3. kart (BY 84-87)
    assert Decimal(ozet["total_employer_cost"]) == Decimal("42230.00")  # 4. kart (BY 90-92)
    assert ozet["uncomputed_count"] == 1

    bolumler = {b["personnel_source"]: b for b in govde["sections"]}
    assert set(bolumler) == {"company", "subcontractor", "freelance", "intern"}
    # BY 124 → 172 → 240 → 268 sırası KORUNUR (ekran bölümleri bu sırayla basar).
    assert [b["personnel_source"] for b in govde["sections"]] == [
        "company",
        "subcontractor",
        "freelance",
        "intern",
    ]
    assert bolumler["company"]["line_count"] == 2  # şirket + ücretsiz (ikisi de `company`)
    taseron = bolumler["subcontractor"]["lines"][0]
    assert taseron["status"] == "excluded"
    assert taseron["excluded_reason"]  # K2: sessiz atlama yok, gerekçe YAZILI


async def test_detayda_personel_adi_bulunur(client, ik_headers, donem, dort_tip):
    """BY 137 satırı adı basıyor — istemci ikinci bir istek atmak zorunda kalmaz."""
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)
    govde = (await client.get(f"/payroll/periods/{donem.id}", headers=ik_headers)).json()
    adlar = {satir["personnel_name"] for bolum in govde["sections"] for satir in bolum["lines"]}
    assert "Ayşe Demir" in adlar


async def test_gorunmeyen_donem_404(client, ik_headers, seeded_db):
    resp = await client.get(
        "/payroll/periods/00000000-0000-0000-0000-000000000001", headers=ik_headers
    )
    assert resp.status_code == 404


# --- GET /payroll/periods ---------------------------------------------------


async def test_liste_BG_sutunlarini_dondurur(client, ik_headers, donem, dort_tip):
    """BG 44-47: dönem · çalışan · brüt · SGK işveren · net · toplam maliyet."""
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)
    resp = await client.get("/payroll/periods", headers=ik_headers)
    assert resp.status_code == 200, resp.text
    satir = resp.json()["items"][0]

    assert (satir["year"], satir["month"]) == (donem.year, donem.month)
    # BG "Çalışan" sütunu DÖNEMİN TÜM satırlarını sayar (BY tfoot 48 = 12+29+5+2);
    # 1. kartın "çalışan" sayısı ise ÖDENEBİLİR satırlardır — ikisi aynı değildir.
    assert satir["personnel_count"] == 5
    assert Decimal(satir["gross_total"]) == Decimal("38000.00")
    assert Decimal(satir["sgk_employer_total"]) == Decimal("3690.00")
    assert Decimal(satir["net_total"]) == Decimal("24181.69")
    assert Decimal(satir["total_cost"]) == Decimal("42230.00")


async def test_liste_toplam_maliyeti_KART_ile_ayni_kaynaktan_gelir(
    client, ik_headers, donem, dort_tip
):
    """Tek kaynak: BG sütunu ile BY 4. kartı aynı formülü çağırır, kopyalanmaz."""
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)
    liste = (await client.get("/payroll/periods", headers=ik_headers)).json()["items"][0]
    detay = (await client.get(f"/payroll/periods/{donem.id}", headers=ik_headers)).json()

    assert liste["total_cost"] == detay["summary"]["total_employer_cost"]
    assert liste["net_total"] == detay["summary"]["net_total"]


async def test_liste_yeniden_ESKIYE_siralanir(client, ik_headers, donem, seeded_db):
    """BG tbody: Temmuz · Haziran · Mayıs — en yeni dönem başta."""
    await client.post("/payroll/periods", json={"year": 2026, "month": 6}, headers=ik_headers)
    await client.post("/payroll/periods", json={"year": 2026, "month": 9}, headers=ik_headers)

    aylar = [
        (s["year"], s["month"])
        for s in (await client.get("/payroll/periods", headers=ik_headers)).json()["items"]
    ]
    assert aylar == [(2026, 9), (2026, 7), (2026, 6)]


async def test_sayfalama_TB3_deseni(client, ik_headers, donem, seeded_db):
    resp = await client.get("/payroll/periods?limit=1&offset=0", headers=ik_headers)
    assert resp.status_code == 200
    govde = resp.json()
    assert len(govde["items"]) == 1
    assert govde["total"] == 1
    assert (govde["limit"], govde["offset"]) == (1, 0)


async def test_limit_tavani_ASIMI_422(client, ik_headers, seeded_db):
    """TB3 kanonu: tavan 200 — aşım sessizce KIRPILMAZ, 422 döner."""
    assert (await client.get("/payroll/periods?limit=201", headers=ik_headers)).status_code == 422


async def test_liste_proje_kapsamiyla_SUZULMEZ(client, ik_headers, donem, dort_tip):
    """🔴 BİLİNÇLİ: bordro şirket genelidir, `visible_projects` süzgeci YOKTUR.

    `ik_headers` kullanıcısının hiçbir projeye açık erişimi yoktur
    (`user_project_access` boş) ve `payroll` matris satırında kapsam sütunu da
    `all`dır. Buna rağmen dönem ve TÜM satırları görünür — `personnel`/
    `timesheet` deseninin aynısı. Bu test, süzgecin sonradan "unutulmuş" diye
    eklenmesini engeller.
    """
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)
    assert (await client.get("/payroll/periods", headers=ik_headers)).json()["total"] == 1
    detay = (await client.get(f"/payroll/periods/{donem.id}", headers=ik_headers)).json()
    assert sum(b["line_count"] for b in detay["sections"]) == 5
