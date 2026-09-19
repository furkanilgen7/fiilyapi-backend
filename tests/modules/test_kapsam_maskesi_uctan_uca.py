"""Kapsam maskesi UÇTAN UCA — gerçek rol, gerçek uç, gerçek yanıt.

## Neden bu dosya şart

`tests/core/` altındaki bekçiler zincirin PARÇALARINI ölçer (maske doğru mu,
rota bağlı mı, sınıflandırma tam mı). Hiçbiri *"`site_chief` gerçekten BOQ
ekranında birim fiyatı göremiyor mu"* sorusunu sormaz. Parçaların üçü de yeşilken
zincirin kopuk olması mümkündür — bu dosya o boşluğu kapatır.

## Ölçülen roller (matristen)

* `site_chief` → `boq = view/limited` → PARA gizli, metraj görünür
* `accounting` → `boq = view/finance` → metraj gizli, PARA görünür

İkisi birbirinin AYNASIDIR; tek yönlü bir test "her şeyi gizle" hâlini
yakalayamazdı.
"""

from decimal import Decimal

from ._boq import _auth, _group, _item, _login_with_access, _site


async def _boq_yaniti(client, db_session, user_factory, project_factory, rol: str, eposta: str):
    project = await project_factory(f"KAPSAM-{rol}")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    await _item(db_session, site, group, quantity=Decimal("1240.000"), unit_price=Decimal("280.00"))
    token = await _login_with_access(client, db_session, user_factory, rol, eposta)

    resp = await client.get(f"/sites/{site.id}/boq", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _kalem(govde: dict) -> dict:
    return govde["groups"][0]["items"][0]


async def test_ADMIN_hem_parayi_hem_metraji_GORUR(
    client, db_session, user_factory, project_factory
):
    """🔴 POZİTİF KONTROL — maske "herkesten gizle" hâline gelirse burası kırmızı."""
    govde = await _boq_yaniti(
        client, db_session, user_factory, project_factory, "system_admin", "adm@kapsam.co"
    )
    kalem = _kalem(govde)

    assert kalem["unit_price"] == "280.00"
    assert kalem["amount"] == "347200.00"
    assert kalem["quantity"] == "1240.000"
    assert govde["groups"][0]["group_total"] == "347200.00"


async def test_SITE_CHIEF_limited_PARAYI_goremez_METRAJI_gorur(
    client, db_session, user_factory, project_factory
):
    """`boq = view/limited`. 🔴 `amount` ve `group_total` TÜREVDİR: maskelenmeselerdi
    birim fiyat `amount / quantity` ile geri hesaplanırdı."""
    govde = await _boq_yaniti(
        client, db_session, user_factory, project_factory, "site_chief", "sc@kapsam.co"
    )
    kalem = _kalem(govde)

    assert kalem["unit_price"] is None, "BİRİM FİYAT SIZDI"
    assert kalem["amount"] is None, "TÜREV TUTAR SIZDI"
    assert govde["groups"][0]["group_total"] is None, "GRUP TOPLAMI SIZDI"
    assert govde["totals"]["grand_total"] is None, "GENEL TOPLAM SIZDI"
    # metraj ve kimlik DURUR — ekran kullanılabilir kalmalıdır
    assert kalem["quantity"] == "1240.000"
    assert kalem["code"] == "01.001"
    assert kalem["description"] == "Kazı (Makine ile)"


async def test_ACCOUNTING_finance_METRAJI_goremez_PARAYI_gorur(
    client, db_session, user_factory, project_factory
):
    """`boq = view/finance` — `limited`in AYNASI.

    🔴 KİMLİK alanları DURUR: birebir "yalnız para" uygulansaydı muhasebe pozun
    ADINI bile göremez ve ekran kullanılamaz olurdu (kullanıcı kararı)."""
    govde = await _boq_yaniti(
        client, db_session, user_factory, project_factory, "accounting", "acc@kapsam.co"
    )
    kalem = _kalem(govde)

    assert kalem["quantity"] is None, "METRAJ SIZDI"
    assert kalem["allocated_quantity"] is None
    assert kalem["unit_price"] == "280.00", "PARA YANLIŞLIKLA GİZLENDİ"
    assert kalem["code"] == "01.001", "KİMLİK GİZLENDİ"
    assert kalem["description"] == "Kazı (Makine ile)"

    # 🔴 TUTAR TUTARLILIĞI (kullanıcı kararı 2026-09-19) — bu bölüm bir KÖR
    #    BEKÇİNİN onarımıdır. Test eskiden YALNIZ `unit_price`ı ölçüyordu ve
    #    tutarlar hakkında TEK İDDİASI YOKTU; o yüzden şu tutarsızlığı hiç
    #    görmedi: metraj gizlenince satır tutarları türev olarak düşerken
    #    `grand_total` DÜZ bir alan olduğu için GERÇEK kalıyordu. Muhasebenin
    #    ekranında hiçbir satır tutara katkı vermezken altta gerçek bir genel
    #    toplam yazılıydı — ve gizlenen metraj `tutar / birim fiyat` ile GERİ
    #    HESAPLANABİLİYORDU.
    assert kalem["amount"] is None, "metraj gizliyken SATIR TUTARI sızdı"
    assert govde["groups"][0]["group_total"] is None, "metraj gizliyken GRUP TOPLAMI sızdı"
    assert govde["totals"]["grand_total"] is None, (
        "GENEL TOPLAM sızdı: metraj gizliyken toplam hayatta kalırsa ekran "
        "TUTARSIZDIR ve metraj `tutar / birim fiyat` ile geri hesaplanır"
    )
