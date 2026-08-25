"""Proje maliyet ucu — KY/KK SENARYOLARI · DURUM SÜZGECİ · TAŞERON TABLOSU.

Mockup otoritesi KY 212-249: taşeron tablosunun toplamı SATIRLARIN toplamına
eşittir (tfoot satırlarıyla çelişirse SATIR kazanır). Aynı taşeronun iki
sözleşmesi AYRI satır açar.

⚠️ Dosya 800 satır tavanını aşınca BÖLÜNDÜ (`_journal.py` emsali): ilerleme
sütunu, yetki/IDOR, N+1 ölçümü ve mutasyon denetimi
`test_projects_costs_progress.py`ye taşındı; paylaşılan yardımcılar
`_projects_costs.py`dedir. Hiçbir testin iddiası değişmedi.
"""

from decimal import Decimal

from app.modules.projects.models import ProjectInvestment
from app.modules.sales.models import UnitSaleStatus
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
)
from app.modules.units.models import UnitOwnerSide

from ._projects_costs import (
    _TENTH,
    _auth,
    _contract,
    _customer,
    _login,
    _payment,
    _sale,
    _set_budget_lines,
    _units,
)


async def test_ky_maliyet_kirilimi_ve_kar_projeksiyonu_mockupi_birebir_verir(
    client, db_session, user_factory, project_factory
):
    """KY 113-194: arsa 8,4M · inşaat bütçesi 21,4M · 48,2M − 29,8M = 18,4M · %38,2."""
    kurucu = await user_factory(email="kurucu@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="KY-1", project_type="kendi_yatirim")
    _set_budget_lines(
        project, material="8000000", labor="5000000", sub="7000000", overhead="1400000"
    )
    db_session.add(
        ProjectInvestment(
            project_id=project.id,
            land_cost=Decimal("8400000.00"),
            # S4: satış hedefi kolonu hesapta KULLANILMAZ — çeliştirilmediği burada kanıtlanır.
            sales_target=Decimal("1.00"),
        )
    )
    await db_session.flush()
    await _units(
        db_session,
        project,
        [
            {"list_price": Decimal("24100000.00"), "gross_area_m2": Decimal("100.00")},
            {"list_price": Decimal("24100000.00"), "gross_area_m2": Decimal("100.00")},
        ],
    )
    contract = await _contract(
        db_session, project, kurucu, name="Akın İnşaat", work_category="Betonarme"
    )
    await _payment(db_session, contract, kurucu, SubcontractorPaymentStatus.paid, quantity="5700")
    await _payment(
        db_session,
        contract,
        kurucu,
        SubcontractorPaymentStatus.approved,
        quantity="840",
        sequence_no=2,
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/costs", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    breakdown = body["breakdown"]
    assert Decimal(breakdown["land_cost"]) == Decimal("8400000.00")
    assert Decimal(breakdown["construction_budget"]) == Decimal("21400000.00")
    assert Decimal(breakdown["construction_spent"]) == Decimal("6540000.00")
    # KY 156-159 "Toplam Harcanan" = BİLİNEN kalemler (arsa + inşaat).
    assert Decimal(breakdown["total_spent"]) == Decimal("14940000.00")
    profit = body["profit"]
    assert Decimal(profit["revenue"]) == Decimal("48200000.00")
    assert Decimal(profit["cost"]) == Decimal("29800000.00")
    assert Decimal(profit["profit"]) == Decimal("18400000.00")
    assert Decimal(profit["margin_pct"]).quantize(_TENTH) == Decimal("38.2")


async def test_gerceklesen_satis_ve_kalan_stok_KY_iki_satirini_verir(
    client, db_session, user_factory, project_factory
):
    """KY 173-180 (kullanıcı kararı 2026-08-09): "Gerçekleşen Satış" satış
    BEDELLERİNİN, "Kalan Stok Değeri" satılmamış ünitelerin LİSTE fiyatlarının
    toplamıdır."""
    kurucu = await user_factory(email="stok@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="ST-1", project_type="kendi_yatirim")
    uniteler = await _units(
        db_session,
        project,
        [
            {"list_price": Decimal("20000000.00")},
            {"list_price": Decimal("11420000.00")},
            {"list_price": Decimal("9000000.00")},
            {"list_price": Decimal("7780000.00")},
        ],
    )
    musteri = await _customer(db_session)
    await _sale(
        db_session, uniteler[0], musteri, kurucu, UnitSaleStatus.active, price="20000000.00"
    )
    await _sale(
        db_session,
        uniteler[1],
        musteri,
        kurucu,
        UnitSaleStatus.deed_transferred,
        price="11420000.00",
    )
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    profit = body["profit"]
    assert Decimal(profit["realized_sales"]) == Decimal("31420000.00")
    assert Decimal(profit["remaining_stock_value"]) == Decimal("16780000.00")
    # Gelir (KY 169) LİSTE fiyatları toplamıdır ve iki yeni satırdan BAĞIMSIZDIR.
    assert Decimal(profit["revenue"]) == Decimal("48200000.00")


async def test_iptal_ve_rezerve_satis_gerceklesen_satisa_girmez(
    client, db_session, user_factory, project_factory
):
    """Ölçüt `sales.summary._SOLD_STATUSES`: rezervasyon ciro DEĞİLDİR, iptal
    edilmiş satış ise hiç sayılmaz."""
    kurucu = await user_factory(email="iptal@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="ST-2", project_type="kendi_yatirim")
    uniteler = await _units(
        db_session,
        project,
        [
            {"list_price": Decimal("5000000.00")},
            {"list_price": Decimal("4000000.00")},
            {"list_price": Decimal("3000000.00")},
        ],
    )
    musteri = await _customer(db_session)
    await _sale(db_session, uniteler[0], musteri, kurucu, UnitSaleStatus.active, price="5000000.00")
    await _sale(
        db_session, uniteler[1], musteri, kurucu, UnitSaleStatus.reservation, price="4000000.00"
    )
    await _sale(
        db_session, uniteler[2], musteri, kurucu, UnitSaleStatus.cancelled, price="3000000.00"
    )
    token = await _login(client, user_factory, "system_admin")

    profit = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()[
        "profit"
    ]

    assert Decimal(profit["realized_sales"]) == Decimal("5000000.00")
    # Rezerve ünite "boş" DEĞİLDİR; iptal edilen satışın ünitesi stokta KALIR.
    assert Decimal(profit["remaining_stock_value"]) == Decimal("3000000.00")


async def test_taahhutte_gerceklesen_satis_ve_kalan_stok_YOKTUR(
    client, db_session, user_factory, project_factory
):
    """Taahhütte ünite/satış KAVRAMI yok (`_UNIT_REVENUE_TYPES` süzgeci) — iki
    alan `None` döner, 0 basmak "hiç satılmadı" yalanı olurdu."""
    project = await project_factory(
        code="ST-3", project_type="taahhut", contract_amount="10000000.00"
    )
    token = await _login(client, user_factory, "system_admin")

    profit = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()[
        "profit"
    ]

    assert profit["realized_sales"] is None
    assert profit["remaining_stock_value"] is None


async def test_bekleyen_uc_kalem_zarf_icinde_doner_uydurma_sifir_basmaz(
    client, db_session, user_factory, project_factory
):
    """KY 134-154: Ruhsat & Harçlar · Finansman · Pazarlama kaynağı YOK → pending."""
    project = await project_factory(code="KY-2", project_type="kendi_yatirim")
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    for key in ("permits", "financing", "marketing"):
        kalem = body["breakdown"][key]
        assert kalem["available"] is False, key
        assert kalem["value"] is None, key
        assert kalem["pending_module"], key


# --- KK senaryosu (kat karşılığı) ---


async def test_kk_kar_projeksiyonu_mockupi_birebir_verir(
    client, db_session, user_factory, project_factory
):
    """KK 104-141: arsa ₺0 · inşaat 17,6M · bizim pay 30,4M → 12,8M / %42,1."""
    project = await project_factory(code="KK-1", project_type="kat_karsiligi")
    _set_budget_lines(project, material="17600000")
    await db_session.flush()
    await _units(
        db_session,
        project,
        [
            {
                "appraisal_value": Decimal("30400000.00"),
                "owner_side": UnitOwnerSide.contractor,
            },
            # Arsa sahibinin ünitesi BİZİM PAY değerine girmez.
            {
                "appraisal_value": Decimal("25000000.00"),
                "owner_side": UnitOwnerSide.landowner,
            },
        ],
    )
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    assert Decimal(body["breakdown"]["land_cost"]) == Decimal("0")
    assert Decimal(body["breakdown"]["construction_budget"]) == Decimal("17600000.00")
    profit = body["profit"]
    assert Decimal(profit["revenue"]) == Decimal("30400000.00")
    assert Decimal(profit["cost"]) == Decimal("17600000.00")
    assert Decimal(profit["profit"]) == Decimal("12800000.00")
    assert Decimal(profit["margin_pct"]).quantize(_TENTH) == Decimal("42.1")


async def test_taahhutte_arsa_maliyeti_none_ve_kar_sozlesme_eksi_harcanandir(
    client, db_session, user_factory, project_factory
):
    """E4 180-181: taahhütte arsa KAVRAMI yok (0 basmak "bedava arsa" yalanı olurdu)."""
    kurucu = await user_factory(email="taahhut@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(
        code="TA-1", project_type="taahhut", contract_amount="10000000.00"
    )
    contract = await _contract(db_session, project, kurucu, name="Akın İnşaat")
    await _payment(db_session, contract, kurucu, SubcontractorPaymentStatus.paid, quantity="4000")
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    assert body["breakdown"]["land_cost"] is None
    assert Decimal(body["breakdown"]["construction_spent"]) == Decimal("4000000.00")
    assert Decimal(body["profit"]["revenue"]) == Decimal("10000000.00")
    assert Decimal(body["profit"]["profit"]) == Decimal("6000000.00")


# --- Durum süzgeci ---


async def test_taslak_onay_bekleyen_ve_reddedilmis_hakedis_maliyete_girmez(
    client, db_session, user_factory, project_factory
):
    """S1 süzgeci: yalnız `approved`+`paid`. Reddedilmiş taslak da SIZMAZ."""
    kurucu = await user_factory(email="suzgec@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="SZ-1", project_type="taahhut")
    contract = await _contract(db_session, project, kurucu, name="Akın İnşaat")
    await _payment(db_session, contract, kurucu, SubcontractorPaymentStatus.paid, quantity="100")
    await _payment(
        db_session,
        contract,
        kurucu,
        SubcontractorPaymentStatus.draft,
        quantity="9000",
        sequence_no=2,
    )
    await _payment(
        db_session,
        contract,
        kurucu,
        SubcontractorPaymentStatus.pending_approval,
        quantity="8000",
        sequence_no=3,
    )
    await _payment(
        db_session,
        contract,
        kurucu,
        SubcontractorPaymentStatus.draft,
        quantity="7000",
        sequence_no=4,
        rejected=True,
    )
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    assert Decimal(body["breakdown"]["construction_spent"]) == Decimal("100000.00")
    assert Decimal(body["subcontractor_total"]["paid"]) == Decimal("100000.00")
    assert Decimal(body["subcontractor_total"]["pending"]) == Decimal("0.00")


# --- Taşeron maliyet tablosu (KY 212-249) ---


async def test_taseron_tablosu_toplami_satirlarin_toplamina_esittir(
    client, db_session, user_factory, project_factory
):
    """KY 244-248 tfoot: toplam satırı satırların toplamıdır — iki farklı kaynak YOK.

    Hakedişsiz sözleşme de satır açar (KY 236-243 "Demirci Alüminyum ₺0/₺0").
    """
    kurucu = await user_factory(email="tablo@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="TS-1", project_type="taahhut")
    akin = await _contract(
        db_session,
        project,
        kurucu,
        name="Akın İnşaat",
        work_category="Betonarme",
        item_quantity="8400",
        item_price="1000",
    )
    yilmaz = await _contract(
        db_session,
        project,
        kurucu,
        name="Yılmaz Elektrik",
        work_category="Elektrik",
        item_quantity="2400",
        item_price="1000",
    )
    await _contract(
        db_session,
        project,
        kurucu,
        name="Demirci Alüminyum",
        work_category="Doğrama",
        item_quantity="1800",
        item_price="1000",
    )
    await _payment(db_session, akin, kurucu, SubcontractorPaymentStatus.paid, quantity="5700")
    await _payment(
        db_session, akin, kurucu, SubcontractorPaymentStatus.approved, quantity="840", sequence_no=2
    )
    await _payment(db_session, yilmaz, kurucu, SubcontractorPaymentStatus.paid, quantity="1200")
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    rows = body["subcontractors"]
    assert [row["subcontractor_name"] for row in rows] == [
        "Akın İnşaat",
        "Demirci Alüminyum",
        "Yılmaz Elektrik",
    ]
    by_name = {row["subcontractor_name"]: row for row in rows}
    assert Decimal(by_name["Akın İnşaat"]["contract_amount"]) == Decimal("8400000.00")
    assert Decimal(by_name["Akın İnşaat"]["paid"]) == Decimal("5700000.00")
    assert Decimal(by_name["Akın İnşaat"]["pending"]) == Decimal("840000.00")
    assert by_name["Akın İnşaat"]["work_category"] == "Betonarme"
    # Satır kimliği geri getirilebilir olmalı (mockup "İş Kalemi" sütunu sözleşme düzeyi).
    assert by_name["Akın İnşaat"]["contract_id"] == str(akin.id)
    assert Decimal(by_name["Demirci Alüminyum"]["paid"]) == Decimal("0.00")
    total = body["subcontractor_total"]
    for alan in ("contract_amount", "paid", "pending"):
        assert Decimal(total[alan]) == sum(Decimal(row[alan]) for row in rows), alan
    # İnşaat harcanan tablonun ödenen+bekleyeni ile AYNI kaynaktan gelir.
    assert Decimal(body["breakdown"]["construction_spent"]) == Decimal(total["paid"]) + Decimal(
        total["pending"]
    )


async def test_ayni_taseronun_iki_sozlesmesi_AYRI_satir_acar(
    client, db_session, user_factory, project_factory
):
    """Satır birimi SÖZLEŞMEDİR (KY 205-249): satırdaki "İş Kalemi" metni sözleşme
    düzeyi bir kavramdır, iki iş kapsamı tek satıra EZİLEMEZ.

    Toplam yine satırların toplamıdır — satır birimi değişti, tfoot DEĞİŞMEDİ.
    """
    kurucu = await user_factory(email="ikili@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="TS-2", project_type="taahhut")
    birinci = await _contract(
        db_session,
        project,
        kurucu,
        name="Akın İnşaat",
        work_category="Betonarme",
        item_quantity="1000",
        item_price="1000",
        contract_no="TS-2-01",
    )
    ikinci = await _contract(
        db_session,
        project,
        kurucu,
        name="Akın İnşaat",
        work_category="Doğrama",
        item_quantity="500",
        item_price="1000",
        contract_no="TS-2-02",
    )
    await _payment(db_session, birinci, kurucu, SubcontractorPaymentStatus.paid, quantity="300")
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    rows = body["subcontractors"]
    assert [row["contract_id"] for row in rows] == [str(birinci.id), str(ikinci.id)]
    assert [row["contract_no"] for row in rows] == ["TS-2-01", "TS-2-02"]
    # Kategori artık SÖZLEŞMEDEN gelir: "ayrışırsa None" kuralı KALDIRILDI.
    assert [row["work_category"] for row in rows] == ["Betonarme", "Doğrama"]
    assert [Decimal(row["contract_amount"]) for row in rows] == [
        Decimal("1000000.00"),
        Decimal("500000.00"),
    ]
    assert [Decimal(row["paid"]) for row in rows] == [Decimal("300000.00"), Decimal("0.00")]
    total = body["subcontractor_total"]
    for alan in ("contract_amount", "paid", "pending"):
        assert Decimal(total[alan]) == sum(Decimal(row[alan]) for row in rows), alan
    assert Decimal(body["breakdown"]["construction_spent"]) == Decimal("300000.00")


async def test_kategorisiz_sozlesmenin_is_kalemi_sutunu_BOS_doner(
    client, db_session, user_factory, project_factory
):
    """Kullanıcı kararı 2026-08-09: mockup'ın "İş Kalemi" sütunu `work_category`
    ile beslenir; YENİ KOLON AÇILMAZ. Taslak sözleşmede kategori NULL olabilir ve
    bu MEŞRUDUR — satır yine açılır, sütun boş basılır (uydurma metin YOK).
    """
    kurucu = await user_factory(
        email="kategorisiz@p10.co", password="parola1234", role_key="patron"
    )
    project = await project_factory(code="TS-4", project_type="taahhut")
    taslak = await _contract(
        db_session, project, kurucu, name="Akın İnşaat", item_quantity="100", item_price="1000"
    )
    await _contract(
        db_session,
        project,
        kurucu,
        name="Yılmaz Elektrik",
        work_category="Elektrik",
        item_quantity="50",
        item_price="1000",
    )
    token = await _login(client, user_factory, "system_admin")

    body = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    rows = {row["subcontractor_name"]: row for row in body["subcontractors"]}
    assert rows["Akın İnşaat"]["work_category"] is None
    assert rows["Akın İnşaat"]["contract_id"] == str(taslak.id)
    assert Decimal(rows["Akın İnşaat"]["contract_amount"]) == Decimal("100000.00")
    assert rows["Yılmaz Elektrik"]["work_category"] == "Elektrik"


async def test_sozlesme_nosuz_satirlar_da_deterministik_siralanir(
    client, db_session, user_factory, project_factory
):
    """Taslak sözleşmenin `contract_no`su NULL'dur; sıralama yine kararlı olmalı
    (ad → `contract_no` → `contract_id`), aksi hâlde tablo her istekte oynar."""
    kurucu = await user_factory(email="sirali@p10.co", password="parola1234", role_key="patron")
    project = await project_factory(code="TS-3", project_type="taahhut")
    for _ in range(3):
        await _contract(
            db_session, project, kurucu, name="Akın İnşaat", item_quantity="1", item_price="1000"
        )
    token = await _login(client, user_factory, "system_admin")

    birinci = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()
    ikinci = (await client.get(f"/projects/{project.id}/costs", headers=_auth(token))).json()

    kimlikler = [row["contract_id"] for row in birinci["subcontractors"]]
    assert len(kimlikler) == 3
    assert kimlikler == sorted(kimlikler)
    assert kimlikler == [row["contract_id"] for row in ikinci["subcontractors"]]


# --- İlerleme sütunu (KY 214/222/230 · KK 217/223/229) ---
