"""TB6 T1 — gelir vergisi tarifesi yönetim uçları (IK3-GV'nin ERTELENMİŞ dilimi).

| Uç | Yetki |
|---|---|
| `GET /payroll/tax-brackets` | `payroll:view` |
| `PUT /payroll/tax-brackets/{year}/{income_kind}` | `payroll:admin` |

## 🔴 Niçin `admin`, `full` DEĞİL (WORKFLOW §8: "silme yalnız admin")

Tam küme değiştirme, UQ `(year, income_kind, ordinal)` yüzünden **fiilen bir
SİLME**dir: eski satırlar pasifleştirilerek saklanamaz, çünkü yeni setin aynı
`ordinal`leri aynı anahtara çarpar. `payroll_rates`in `PUT`u satırın ÜSTÜNE
yazar (silmez) ve bu yüzden `full`dur; burada satır GİDER, o hâlde kapı da bir
seviye yukarıdadır.

## 🔴 BU DOSYANIN ASIL İŞİ: GEÇMİŞ DÖNEM DEĞİŞMEZ

`payroll_rates`in kardeş korkuluğudur ama gerekçe AYRIDIR ve ÖLÇÜLMÜŞTÜR:

* gelir vergisi satıra **SNAPSHOT** edilir (`service._apply`:
  `line.income_tax_amount = hesap.income_tax_amount`), oran gibi canlı
  türetilmez — yani tarife değişince HESAPLANMIŞ satır kendiliğinden DEĞİŞMEZ
  (`test_tarife_degisimi_HESAPLANMIS_satiri_DEGISTIRMEZ`);
* **ama** ayın vergisi `T(önceki+bu ay) − T(önceki)`dir ve İKİ çağrı da
  **YÜRÜRLÜKTEKİ** setle yapılır (`income_tax.monthly_income_tax`). Yıl ortasında
  tarife değişirse, ondan sonra hesaplanan İLK ay geçmiş ayların farkını
  **tek başına yutar** (`test_tarife_degisimi_YENIDEN_HESAPTA_satiri_DEGISTIRIR`).

Bu yüzden kapı `payroll_rates` ile AYNI yere kurulur: o yılda `approved`/`paid`
dönem varsa **409**.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.audit.models import AuditLog
from app.modules.payroll.models import IncomeKind, PayrollTaxBracket
from app.modules.payroll.tax_bracket_seed_data import TAX_BRACKETS_2026_WAGE
from app.modules.personnel.models import WageType

from .conftest import YIL

pytestmark = pytest.mark.asyncio

#: Geçerli üç dilimlik set — testlerin ÇOĞUNLUĞUNUN tabanı.
GECERLI = [
    {"ordinal": 1, "upper_bound": "100000.00", "rate_pct": "15.000"},
    {"ordinal": 2, "upper_bound": "500000.00", "rate_pct": "27.000"},
    {"ordinal": 3, "upper_bound": None, "rate_pct": "40.000"},
]


def _govde(brackets=None, **ek) -> dict:
    return {"brackets": GECERLI if brackets is None else brackets, **ek}


async def _put(client, headers, year=2027, kind="wage", **govde):
    return await client.put(
        f"/payroll/tax-brackets/{year}/{kind}", json=_govde(**govde), headers=headers
    )


# --- Kapılar ---------------------------------------------------------------


async def test_yetkisiz_rol_dilimleri_goremez_403(client, yetkisiz_headers, seeded_db):
    assert (await client.get("/payroll/tax-brackets", headers=yetkisiz_headers)).status_code == 403


async def test_yetkisiz_rol_dilim_yazamaz_403(client, yetkisiz_headers, seeded_db):
    assert (await _put(client, yetkisiz_headers)).status_code == 403


async def test_IK_yoneticisi_OKUR_ama_YAZAMAZ_403(client, ik_headers, dilimler):
    """`hr_manager` `payroll=full`tur — okuma serbest, tam küme değiştirme DEĞİL.

    Bu iddia kapının gerçekten `admin` olduğunun TEK kanıtıdır: `full` yazılsaydı
    aşağıdaki `403` `200` olurdu ve kimse fark etmezdi.
    """
    assert (await client.get("/payroll/tax-brackets", headers=ik_headers)).status_code == 200
    assert (await _put(client, ik_headers)).status_code == 403


# --- GET /payroll/tax-brackets ---------------------------------------------


async def test_dilimler_ORDINAL_sirasiyla_listelenir(client, admin_headers, dilimler):
    resp = await client.get("/payroll/tax-brackets", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    govde = resp.json()

    assert govde["total"] == len(TAX_BRACKETS_2026_WAGE)
    assert [s["ordinal"] for s in govde["items"]] == [1, 2, 3, 4, 5]
    assert govde["items"][0]["year"] == YIL
    assert govde["items"][0]["income_kind"] == "wage"
    # `Numeric(6,3)`: oran TAM gelir, iki ondalığa yuvarlanmaz.
    assert Decimal(govde["items"][0]["rate_pct"]) == Decimal("15.000")
    assert Decimal(govde["items"][0]["upper_bound"]) == Decimal("190000.00")
    # 🔴 SON dilimin sınırı `null`dur ("üstü") — 0 ya da eksik DEĞİL.
    assert govde["items"][-1]["upper_bound"] is None
    assert govde["items"][-1]["is_active"] is True


async def test_yila_gore_suzulur(client, admin_headers, dilimler, db_session):
    db_session.add(
        PayrollTaxBracket(
            year=2027, income_kind=IncomeKind.wage, ordinal=1, upper_bound=None, rate_pct="15.000"
        )
    )
    await db_session.flush()

    govde = (await client.get("/payroll/tax-brackets?year=2027", headers=admin_headers)).json()
    assert govde["total"] == 1
    assert govde["items"][0]["year"] == 2027


async def test_gelir_turune_gore_suzulur(client, admin_headers, dilimler, db_session):
    """`income_kind` iki AYRI tarifedir (K5) — süzgeç olmasa ikisi karışırdı."""
    db_session.add(
        PayrollTaxBracket(
            year=YIL,
            income_kind=IncomeKind.non_wage,
            ordinal=1,
            upper_bound=None,
            rate_pct="15.000",
        )
    )
    await db_session.flush()

    hepsi = (await client.get("/payroll/tax-brackets", headers=admin_headers)).json()
    assert hepsi["total"] == len(TAX_BRACKETS_2026_WAGE) + 1

    ucret_disi = (
        await client.get("/payroll/tax-brackets?income_kind=non_wage", headers=admin_headers)
    ).json()
    assert ucret_disi["total"] == 1
    assert ucret_disi["items"][0]["income_kind"] == "non_wage"


async def test_PASIF_dilimler_de_doner(client, admin_headers, db_session):
    """Geçmiş bir bordronun hangi tarifeyle hesaplandığı OKUNABİLİR kalmalıdır."""
    db_session.add(
        PayrollTaxBracket(
            year=2025,
            income_kind=IncomeKind.wage,
            ordinal=1,
            upper_bound=None,
            rate_pct="15.000",
            is_active=False,
        )
    )
    await db_session.flush()

    govde = (await client.get("/payroll/tax-brackets?year=2025", headers=admin_headers)).json()
    assert govde["total"] == 1
    assert govde["items"][0]["is_active"] is False


# --- PUT: tam küme değiştirme ----------------------------------------------


async def test_YENI_YILIN_tarifesi_ACILIR(client, admin_headers, seeded_db, db_session):
    """🔴 Bu ucun VAR OLMA sebebi: 2027'nin tarifesi girilmezse ilk dönem
    `uncomputed` döner (K3 fail-closed) — bordro hesaplanamaz hâle gelir."""
    resp = await _put(client, admin_headers, 2027)
    assert resp.status_code == 200, resp.text
    assert [s["ordinal"] for s in resp.json()["items"]] == [1, 2, 3]

    satirlar = (
        (
            await db_session.execute(
                select(PayrollTaxBracket)
                .where(PayrollTaxBracket.year == 2027)
                .order_by(PayrollTaxBracket.ordinal)
            )
        )
        .scalars()
        .all()
    )
    assert [s.rate_pct for s in satirlar] == [
        Decimal("15.000"),
        Decimal("27.000"),
        Decimal("40.000"),
    ]
    assert satirlar[-1].upper_bound is None


async def test_TAM_KUME_DEGISTIRME_eski_satirlar_KALMAZ(
    client, admin_headers, dilimler, db_session
):
    """🔴 BEŞ dilimlik set ÜÇ dilimle değiştirilince geriye ÜÇ satır kalır.

    Eski satırlar pasifleştirilerek saklanamaz: UQ `(year, income_kind, ordinal)`
    yeni 1/2/3'ü eskilerin üstüne çarpardı. Kısmi güncelleme yolu bırakılsaydı
    4. ve 5. dilim ORTADA KALIR ve `normalize_brackets` seti bozuk sayıp TÜM yılı
    fail-closed'a düşürürdü.
    """
    resp = await _put(client, admin_headers, YIL)
    assert resp.status_code == 200, resp.text

    kalan = (
        (
            await db_session.execute(
                select(PayrollTaxBracket)
                .where(
                    PayrollTaxBracket.year == YIL,
                    PayrollTaxBracket.income_kind == IncomeKind.wage,
                )
                .order_by(PayrollTaxBracket.ordinal)
            )
        )
        .scalars()
        .all()
    )
    assert [s.ordinal for s in kalan] == [1, 2, 3]
    assert kalan[0].upper_bound == Decimal("100000.00")


async def test_OBUR_gelir_turu_ETKILENMEZ(client, admin_headers, dilimler, db_session):
    """Tam küme YILIN değil `(yıl, gelir türü)`nün kümesidir."""
    db_session.add(
        PayrollTaxBracket(
            year=YIL,
            income_kind=IncomeKind.non_wage,
            ordinal=1,
            upper_bound=None,
            rate_pct="15.000",
        )
    )
    await db_session.flush()

    assert (await _put(client, admin_headers, YIL, "wage")).status_code == 200

    sayi = (
        await db_session.execute(
            select(func.count())
            .select_from(PayrollTaxBracket)
            .where(
                PayrollTaxBracket.year == YIL,
                PayrollTaxBracket.income_kind == IncomeKind.non_wage,
            )
        )
    ).scalar_one()
    assert sayi == 1


async def test_pasif_set_yazilabilir(client, admin_headers, seeded_db, db_session):
    """`is_active=false` = o yıl fail-closed (satır `uncomputed`), 0 vergi DEĞİL."""
    resp = await _put(client, admin_headers, 2027, is_active=False)
    assert resp.status_code == 200, resp.text
    assert all(s["is_active"] is False for s in resp.json()["items"])


# --- PUT: setin BÜTÜNLÜĞÜ (income_tax.normalize_brackets) -------------------


async def test_BOS_set_422(client, admin_headers, seeded_db):
    assert (await _put(client, admin_headers, brackets=[])).status_code == 422


async def test_ORDINAL_BOSLUGU_422(client, admin_headers, seeded_db):
    """1,2,4 — eksik bir dilim tarifede DELİKTİR."""
    bozuk = [{**GECERLI[0]}, {**GECERLI[1]}, {**GECERLI[2], "ordinal": 4}]
    assert (await _put(client, admin_headers, brackets=bozuk)).status_code == 422


async def test_ORDINAL_TEKRARI_422(client, admin_headers, seeded_db):
    bozuk = [{**GECERLI[0]}, {**GECERLI[1], "ordinal": 1}, {**GECERLI[2]}]
    assert (await _put(client, admin_headers, brackets=bozuk)).status_code == 422


async def test_SINIRLAR_ARTMAZSA_422(client, admin_headers, seeded_db):
    """Eşit üst sınır = aynı matrah İKİ dilime düşer (örtüşme)."""
    bozuk = [{**GECERLI[0]}, {**GECERLI[1], "upper_bound": "100000.00"}, {**GECERLI[2]}]
    assert (await _put(client, admin_headers, brackets=bozuk)).status_code == 422


async def test_SINIRLAR_AZALIRSA_422(client, admin_headers, seeded_db):
    bozuk = [{**GECERLI[0]}, {**GECERLI[1], "upper_bound": "50000.00"}, {**GECERLI[2]}]
    assert (await _put(client, admin_headers, brackets=bozuk)).status_code == 422


async def test_SON_DILIMIN_SINIRI_VARSA_422(client, admin_headers, seeded_db):
    """Sınırın üstündeki matrah hiçbir dilime düşmez → VERGİSİZ kalırdı."""
    bozuk = [{**GECERLI[0]}, {**GECERLI[1]}, {**GECERLI[2], "upper_bound": "900000.00"}]
    assert (await _put(client, admin_headers, brackets=bozuk)).status_code == 422


async def test_ORTADAKI_DILIM_ACIK_UCLUYSA_422(client, admin_headers, seeded_db):
    """Ortada `null` sınır → sonraki dilimler ERİŞİLEMEZ olurdu."""
    bozuk = [{**GECERLI[0]}, {**GECERLI[1], "upper_bound": None}, {**GECERLI[2]}]
    assert (await _put(client, admin_headers, brackets=bozuk)).status_code == 422


async def test_TEK_DILIMLI_set_GECERLIDIR(client, admin_headers, seeded_db):
    """Düz oranlı bir tarife de bir tarifedir: sınırsız TEK dilim."""
    resp = await _put(
        client, admin_headers, brackets=[{"ordinal": 1, "upper_bound": None, "rate_pct": "20.000"}]
    )
    assert resp.status_code == 200, resp.text


async def test_NEGATIF_ORAN_422(client, admin_headers, seeded_db):
    bozuk = [{**GECERLI[0], "rate_pct": "-1.000"}, {**GECERLI[1]}, {**GECERLI[2]}]
    assert (await _put(client, admin_headers, brackets=bozuk)).status_code == 422


async def test_YUZDEN_BUYUK_ORAN_422(client, admin_headers, seeded_db):
    bozuk = [{**GECERLI[0], "rate_pct": "150.000"}, {**GECERLI[1]}, {**GECERLI[2]}]
    assert (await _put(client, admin_headers, brackets=bozuk)).status_code == 422


async def test_SIFIR_UST_SINIR_422(client, admin_headers, seeded_db):
    """Sıfır/eksi üst sınır hiçbir matrahı kapsamaz: dilim ÖLÜ olurdu (DB CHECK'in eşi)."""
    bozuk = [{**GECERLI[0], "upper_bound": "0.00"}, {**GECERLI[1]}, {**GECERLI[2]}]
    assert (await _put(client, admin_headers, brackets=bozuk)).status_code == 422


async def test_SIFIR_ORDINAL_422(client, admin_headers, seeded_db):
    bozuk = [{**GECERLI[0], "ordinal": 0}, {**GECERLI[1]}, {**GECERLI[2]}]
    assert (await _put(client, admin_headers, brackets=bozuk)).status_code == 422


async def test_gecersiz_gelir_turu_422(client, admin_headers, seeded_db):
    assert (await _put(client, admin_headers, 2027, "yok_boyle_tur")).status_code == 422


async def test_YIL_ARALIGI_DISI_422(client, admin_headers, seeded_db):
    assert (await _put(client, admin_headers, 1999)).status_code == 422


async def test_FAZLA_ALAN_422(client, admin_headers, seeded_db):
    """`extra="forbid"` — sessizce yutulan bir alan yanlış tarife üretirdi."""
    bozuk = [{**GECERLI[0], "lower_bound": "0.00"}, {**GECERLI[1]}, {**GECERLI[2]}]
    assert (await _put(client, admin_headers, brackets=bozuk)).status_code == 422


# --- Denetim ---------------------------------------------------------------


async def test_dilim_yazimi_TEK_denetim_satiri_yazar(client, admin_headers, seeded_db, db_session):
    once = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    await _put(client, admin_headers, 2027)
    sonra = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    assert sonra == once + 1


async def test_okuma_denetim_YAZMAZ(client, admin_headers, dilimler, db_session):
    once = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    await client.get("/payroll/tax-brackets", headers=admin_headers)
    sonra = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    assert sonra == once


# --- 🔴 GEÇMİŞ DÖNEM DEĞİŞMEZ ----------------------------------------------


async def _onayli_donem(client, headers, donem) -> dict:
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=headers)
    await client.post(f"/payroll/periods/{donem.id}/approve", headers=headers)
    await client.post(f"/payroll/periods/{donem.id}/approve", headers=headers)
    detay = (await client.get(f"/payroll/periods/{donem.id}", headers=headers)).json()
    assert detay["status"] == "approved"
    return detay["summary"]


async def test_ONAYLI_DONEMIN_YILINDA_dilim_yazilamaz_409(
    client, admin_headers, ik_headers, donem, dort_tip
):
    """🔴 PARA KORKULUĞU — gerekçe `payroll_rates`inkiyle AYNI DEĞİLDİR.

    Vergi satıra snapshot edilir, yani onaylı dönemin RAPORLANMIŞ sayısı bu
    yazıyla kendiliğinden değişmez. Kapı, `monthly_income_tax`in fark formülü
    yüzünden gereklidir: aynı yılın SONRAKİ ayı yeni tarifeyle hesaplanınca
    `T(önceki)` de yeni tarifeyle bulunur ve geçmiş ayların TÜM farkı o aya
    yüklenir. Onaylı dönemi olan bir yılda tarife değiştirmek, ödenmiş ayların
    vergisini bir sonraki bordroya taşımaktır.
    """
    once = await _onayli_donem(client, ik_headers, donem)

    resp = await _put(client, admin_headers, YIL)
    assert resp.status_code == 409, resp.text

    sonra = (await client.get(f"/payroll/periods/{donem.id}", headers=ik_headers)).json()["summary"]
    assert sonra == once


async def test_TASLAK_donemin_yilinda_dilim_yazilabilir(
    client, admin_headers, ik_headers, donem, dort_tip
):
    """Kural bordroyu TIKAMAZ: kilit yalnız `approved`/`paid` dönemle gelir."""
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)
    assert (await _put(client, admin_headers, YIL)).status_code == 200


# --- 🔴 SNAPSHOT MI, CANLI MI — ÖLÇÜM ---------------------------------------


@pytest.fixture
async def yuksek_kazanc(donem, oranlar, personel_fabrikasi, puantaj_fabrikasi):
    """Vergisi SIFIR OLMAYAN tek kişilik dönem.

    `dort_tip` fixture'ı KULLANILAMAZ: oradaki brütler (9.000) asgari ücretin
    ALTINDADIR ve KK-7 istisnası vergiyi 0'a indirir — 0 ile 0'ı karşılaştıran
    bir snapshot testi HİÇBİR ŞEY kanıtlamazdı ("ayrışma noktası" kanonu).
    """
    kisi = await personel_fabrikasi(
        "Yüksek Kazanç", wage_type=WageType.monthly, wage_amount=Decimal("300000.00")
    )
    await puantaj_fabrikasi(kisi, [1, 2, 3, 4, 5])
    return kisi


async def _vergi(client, headers, donem, kisi) -> Decimal:
    detay = (await client.get(f"/payroll/periods/{donem.id}", headers=headers)).json()
    satirlar = [satir for bolum in detay["sections"] for satir in bolum["lines"]]
    satir = next(s for s in satirlar if s["personnel_id"] == str(kisi.id))
    assert satir["income_tax_amount"] is not None
    return Decimal(satir["income_tax_amount"])


async def test_tarife_degisimi_HESAPLANMIS_satiri_DEGISTIRMEZ(
    client, admin_headers, ik_headers, donem, yuksek_kazanc
):
    """🔴 ÖLÇÜM: gelir vergisi satıra SNAPSHOT edilir (`service._apply`).

    Tarife değişince hesaplanmış satır YENİDEN HESAPLANMAZ; `sgk.py` de
    toplamları saklanan `income_tax_amount` kolonundan SUM'lar, canlı tarifeden
    değil. `payroll_rates`in aksine bu alan CANLI türemez.
    """
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)
    once = await _vergi(client, ik_headers, donem, yuksek_kazanc)
    assert once > Decimal("0")

    assert (
        await _put(
            client,
            admin_headers,
            YIL,
            brackets=[{"ordinal": 1, "upper_bound": None, "rate_pct": "40.000"}],
        )
    ).status_code == 200

    assert await _vergi(client, ik_headers, donem, yuksek_kazanc) == once


async def test_tarife_degisimi_YENIDEN_HESAPTA_satiri_DEGISTIRIR(
    client, admin_headers, ik_headers, donem, yuksek_kazanc
):
    """🔴 ÖLÇÜMÜN İKİNCİ YARISI: snapshot YENİDEN HESABA kadar sürer.

    409 korkuluğunun gerekçesi budur — `approved`/`paid` dönemi olan bir yılda
    tarife değiştirilebilseydi, o yılın sonraki (taslak) dönemi `T(önceki)`yi de
    YENİ tarifeyle bulur ve ödenmiş ayların farkını yutardı.
    """
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)
    once = await _vergi(client, ik_headers, donem, yuksek_kazanc)

    assert (
        await _put(
            client,
            admin_headers,
            YIL,
            brackets=[{"ordinal": 1, "upper_bound": None, "rate_pct": "40.000"}],
        )
    ).status_code == 200
    await client.post(f"/payroll/periods/{donem.id}/compute", headers=ik_headers)

    assert await _vergi(client, ik_headers, donem, yuksek_kazanc) != once
