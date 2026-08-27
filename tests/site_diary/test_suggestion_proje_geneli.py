"""TH-PRJGENEL — PROJE-GENELİ (`site_id IS NULL`) taşeron sözleşmesinde günlük köprüsü.

🔴 KULLANICI KARARI 2026-08-27 — spec §7 S5 TERSİNE ÇEVRİLDİ.

ESKİ KURAL: `site_id` NULL olan sözleşme köprünün kapsamı DIŞINDAYDI; öneri ucu
`lines: []` + `reason=SUGGESTION_CONTRACT_WITHOUT_SITE` döner, yazma yolu her
satırı `manual` damgalardı.

YENİ KURAL: proje-geneli sözleşmenin doğru cevabı sözleşmenin PROJESİNİN TÜM
ŞANTİYELERİ üzerindeki toplamdır. Zincir DEĞİŞMEZ
(`SiteDiaryLine → BoqItem.contract_item_id → SubcontractorContractItem.
source_contract_item_id`), gruplama yalnız KALEM kalır (taşeron satırında şantiye
kırılımı yoktur); değişen TEK ŞEY ŞANTİYE süzgecinin PROJE süzgecine dönmesidir.
`contract.site_id` NULL DEĞİLSE davranış AYNEN KORUNUR.

## Bu dosyanın ASIL kabul ölçütü

Öneri ucu ile YAZMA yolunun AYNI sayıyı söylemesi. `bridge.is_diary_quantity`
BİREBİR eşitliktir: öneri projenin toplamını verip damga başka bir yoldan
hesaplarsa, kullanıcı "günlükten doldur"un verdiği gövdeyi HİÇ DEĞİŞTİRMEDEN
kaydettiğinde satır `manual` damgalanır — sessiz ve tam da bu dilimin doğurduğu
kusur sınıfı. `test_ONERI_govdesi_DEGISTIRILMEDEN_yazilinca_HEPSI_diary` bunu
uçtan uca ölçer.

## Sayım DEĞİL KÜME (sahte-yeşilin 8. hâli)

"Kaç satır döndü" iddiası KÜMEYİ bekçilemez. Beklenen toplamlar testin kendi
tohumundan BAĞIMSIZ olarak hesaplanır ve `{kalem: miktar}` eşlemesinin TAMAMI
karşılaştırılır — uydurma bir üye eklenmesi testi kırabilmelidir.
"""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_diary import repository

from ._suggestion import (
    DONEM,
    HAKEDIS_DONEM,
    _damgalar,
    _gun,
    _hakedis,
    _kalem_id,
    _kaydet,
    _taseron_onerisi,
)

pytestmark = pytest.mark.asyncio

_FIYAT = Decimal("100.00")
_BOQ_MIKTAR = Decimal("900.000")


def _specler(*kodlar: str) -> list[tuple[str, Decimal, Decimal]]:
    return [(kod, _BOQ_MIKTAR, _FIYAT) for kod in kodlar]


async def _miktarlar(client: AsyncClient, headers, contract_id, **params) -> dict[str, Decimal]:
    """Öneri yanıtını `{taşeron_kalem_id: miktar}` EŞLEMESİNE çevirir."""
    yanit = await _taseron_onerisi(client, headers, contract_id, **params)
    assert yanit.status_code == 200, yanit.text
    return {s["contract_item_id"]: Decimal(s["quantity"]) for s in yanit.json()["lines"]}


@pytest.fixture
async def prj_geneli(
    seeded_db: AsyncSession,
    client: AsyncClient,
    admin_headers,
    santiye_fabrikasi,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
):
    """İKİ şantiyeli bir proje + KARŞI KANIT tohumları (K-IKIZ1).

    "Şantiyesiz sözleşme artık satır döndürüyor" iddiası, HER ŞEYİ döndüren
    bozuk bir sorguda da geçerdi. Bu yüzden kurulum aynı anda DIŞARIDA KALMASI
    gerekenleri de kurar: başka PROJENİN günlüğü (üstelik bu projenin işveren
    kalemine köprülenmiş hâliyle — yalnız PROJE süzgeci onu tutabilir), TASLAK
    kayıt, DÖNEM DIŞI gün, köprüsüz poz, bu sözleşmenin hiçbir kaleminin
    bağlanmadığı işveren kalemi ve SIFIR miktar.
    """
    site_a, proje, pozlar_a = await santiye_fabrikasi(
        "PG-A", item_specs=_specler("A1", "A2", "A3", "A4")
    )
    site_b, _, pozlar_b = await santiye_fabrikasi(
        "PG-B", project=proje, item_specs=_specler("B1", "B2")
    )
    poz = {item.code: item for item in [*pozlar_a, *pozlar_b]}

    # ORTAK işveren kalemi: A1 ve B1 pozları AYNI kaleme köprülü → tek taşeron
    # kaleminde TOPLANMALILAR (gruplama yalnız kalem).
    szl_ortak = await sozlesme_kalemi_fabrikasi(poz["A1"], proje)
    poz["B1"].contract_item_id = szl_ortak.id
    szl_a2 = await sozlesme_kalemi_fabrikasi(poz["A2"], proje)
    szl_a4 = await sozlesme_kalemi_fabrikasi(poz["A4"], proje)
    # Köprülü ama BU sözleşmenin hiçbir kalemi bağlı değil → `skipped` sayılır.
    await sozlesme_kalemi_fabrikasi(poz["B2"], proje)
    # A3 hiç köprülenmedi (`contract_item_id IS NULL`) → `skipped` sayılır.

    contract = await taseron_sozlesmesi_fabrikasi(
        proje,
        site=None,
        kalemler=[("TK-1", szl_ortak), ("TK-2", szl_a2), ("TK-3", szl_a4)],
        code="PG-GENEL",
    )

    # --- KARŞI KANIT: BAŞKA PROJENİN günlüğü ---
    # Q1 bu projenin kalemine KÖPRÜLÜ (öneri SATIRLARININ kapsam bekçisi),
    # Q2 ise KÖPRÜSÜZ (`contract_item_id IS NULL`) — SAYACIN kapsam bekçisi.
    # Q2 olmasaydı yabancı projenin tek günlüğü köprülü olduğu için köprüsüz
    # kümesine HİÇ GİREMEZ, sayacın kapsam süzgeci de bekçisiz kalırdı.
    site_q, proje_q, pozlar_q = await santiye_fabrikasi("PG-Q", item_specs=_specler("Q1", "Q2"))
    poz_q = {item.code: item for item in pozlar_q}
    poz_q["Q1"].contract_item_id = szl_ortak.id
    await seeded_db.flush()

    # --- Günlükler ---
    await _gun(
        client,
        admin_headers,
        site_a.id,
        date(2026, 7, 10),
        [
            {"boq_item_id": str(poz["A1"].id), "quantity": "10"},
            {"boq_item_id": str(poz["A2"].id), "quantity": "3"},
            {"boq_item_id": str(poz["A3"].id), "quantity": "6"},
            {"boq_item_id": str(poz["A4"].id), "quantity": "0"},
        ],
    )
    await _gun(
        client,
        admin_headers,
        site_a.id,
        date(2026, 7, 12),
        [{"boq_item_id": str(poz["A1"].id), "quantity": "2.5"}],
    )
    await _gun(
        client,
        admin_headers,
        site_b.id,
        date(2026, 7, 11),
        [
            {"boq_item_id": str(poz["B1"].id), "quantity": "4"},
            {"boq_item_id": str(poz["B2"].id), "quantity": "7"},
        ],
    )
    # TASLAK (gönderilmemiş) — sayılmaz.
    await _gun(
        client,
        admin_headers,
        site_a.id,
        date(2026, 7, 20),
        [{"boq_item_id": str(poz["A4"].id), "quantity": "99"}],
        gonder=False,
    )
    # DÖNEM DIŞI (haziran) — sayılmaz.
    await _gun(
        client,
        admin_headers,
        site_a.id,
        date(2026, 6, 15),
        [{"boq_item_id": str(poz["A1"].id), "quantity": "100"}],
    )
    # BAŞKA PROJE — sayılmaz.
    await _gun(
        client,
        admin_headers,
        site_q.id,
        date(2026, 7, 10),
        [
            {"boq_item_id": str(poz_q["Q1"].id), "quantity": "50"},
            {"boq_item_id": str(poz_q["Q2"].id), "quantity": "8"},
        ],
    )

    # Beklenen küme testin TOHUMUNDAN BAĞIMSIZ türetilir: sözleşme kalemi →
    # dönem içi, gönderilmiş, BU projenin şantiyelerindeki miktarların toplamı.
    beklenen = {
        "TK-1": Decimal("10") + Decimal("2.5") + Decimal("4"),
        "TK-2": Decimal("3"),
        # TK-3 (A4) YOKTUR: dönemdeki tek gönderilmiş miktarı SIFIR, 99'luk gün
        # TASLAK. `HAVING SUM > 0` onu düşürür.
    }
    return contract, (site_a, site_b), proje, poz, beklenen, (proje_q, poz_q)


async def _beklenen_kimlikli(
    session: AsyncSession, contract_id, beklenen: dict[str, Decimal]
) -> dict[str, Decimal]:
    return {
        str(await _kalem_id(session, contract_id, kod)): miktar for kod, miktar in beklenen.items()
    }


# --- C) KÜME karşılaştırması + D) karşı kanıt ---


async def test_sitesiz_sozlesme_PROJE_TOPLAMI_ve_DISARIDA_KALANLAR(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, prj_geneli
) -> None:
    """Proje-geneli sözleşme projenin TÜM şantiyelerini toplar — ama SADECE onları.

    Eşlemenin TAMAMI karşılaştırılır (satır SAYISI değil): uydurma bir üye
    eklenmesi ya da dışarıda kalması gerekenin sızması testi KIRAR.
    """
    contract, _, _, _, beklenen, _ = prj_geneli

    olculen = await _miktarlar(client, admin_headers, contract.id, **DONEM)
    assert olculen == await _beklenen_kimlikli(seeded_db, contract.id, beklenen)


async def test_sitesiz_sozlesmede_KOPRUSUZ_pozlar_PROJE_GENELINDE_sayilir(
    client: AsyncClient, admin_headers, prj_geneli
) -> None:
    """Bugün `subcontractor_unbridged_item_count` şantiyesiz sözleşmede HİÇ
    KOŞMAZ (sabit 0). Artık proje genelinde koşmalıdır: A şantiyesindeki
    köprüsüz poz (A3) ile B şantiyesindeki "köprülü ama bu sözleşmede karşılığı
    yok" pozu (B2) kullanıcı için AYNI şeydir — "bu miktar öneriye giremedi".

    Başka projenin pozları (köprülü Q1 ve KÖPRÜSÜZ Q2) ile dönem içi toplamı
    SIFIR olan poz (A4) SAYILMAZ.
    """
    contract, _, _, _, _, _ = prj_geneli

    yanit = await _taseron_onerisi(client, admin_headers, contract.id, **DONEM)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["skipped_unbridged_count"] == 2


async def test_KOPRUSUZ_SAYACININ_KAPSAM_bekcisi_BASKA_PROJE_sizdirmaz(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, prj_geneli
) -> None:
    """🔴 MUTASYON BEKÇİSİ — `subcontractor_unbridged_item_count`un KAPSAM süzgeci.

    Bu süzgeç (`_subcontractor_scope_conditions`) SATIR sorgusundan BAĞIMSIZ
    olarak silinebilir; silindiğinde sayaç TÜM projelerin köprüsüz günlüklerini
    sayar. Ölçüldü: yalnız bu koşul kaldırıldığında `tests/site_diary`nin 208
    testinin HEPSİ yeşil kalıyordu, çünkü yabancı projenin tek günlüğü (Q1) bu
    sözleşmenin kalemine KÖPRÜLÜYDÜ ve köprüsüz kümesine hiç giremiyordu.

    Kurulum artık yabancı projede KÖPRÜSÜZ, gönderilmiş, dönem içi, miktarı
    POZİTİF bir poz (Q2 = 8) taşır. Sayaç kendi kapsamında 2'de KALMALIDIR.

    POZİTİF KONTROL önce koşar: tohumun gerçekten sayılabilir olduğu, aynı
    sayacın kapsamı yabancı projeye çevrildiğinde 1 döndürmesiyle kanıtlanır —
    yoksa "2'de kaldı" iddiası boş bir tohumla da geçerdi.
    """
    contract, _, _, _, _, (proje_q, _poz_q) = prj_geneli

    yabanci = await repository.subcontractor_unbridged_item_count(
        seeded_db, contract.id, None, proje_q.id, year=DONEM["year"], month=DONEM["month"]
    )
    assert yabanci == 1, "pozitif kontrol: yabancı projedeki köprüsüz poz sayılabilir olmalı"

    yanit = await _taseron_onerisi(client, admin_headers, contract.id, **DONEM)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["skipped_unbridged_count"] == 2


async def test_KOPRUSUZ_SAYACININ_KAPSAM_bekcisi_KARDES_SANTIYE_sizdirmaz(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye_fabrikasi,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    """Yukarıdaki bekçinin ŞANTİYEYE BAĞLI ikizi.

    Kapsam koşulu silindiğinde şantiyeye bağlı sözleşmenin sayacı da AYNI
    PROJENİN kardeş şantiyesindeki köprüsüz miktarla dolar — proje süzgeci
    doğru olsa bile bu hâl kaçardı. Sözleşme B'ye bağlıdır: B'nin köprüsüz
    pozu (B2 = 5) sayılır, A'nınki (A2 = 9) SAYILMAZ → sayaç 1.
    """
    site_a, proje, pozlar_a = await santiye_fabrikasi("KS-A", item_specs=_specler("A1", "A2"))
    site_b, _, pozlar_b = await santiye_fabrikasi(
        "KS-B", project=proje, item_specs=_specler("B1", "B2")
    )
    poz = {item.code: item for item in [*pozlar_a, *pozlar_b]}
    szl = await sozlesme_kalemi_fabrikasi(poz["A1"], proje)
    poz["B1"].contract_item_id = szl.id
    await seeded_db.flush()
    # A2 ve B2 KÖPRÜSÜZ kalır (`contract_item_id IS NULL`).

    contract = await taseron_sozlesmesi_fabrikasi(
        proje, site=site_b, kalemler=[("TK-1", szl)], code="KS-BAGLI"
    )
    await _gun(
        client,
        admin_headers,
        site_a.id,
        date(2026, 7, 10),
        [
            {"boq_item_id": str(poz["A1"].id), "quantity": "12"},
            {"boq_item_id": str(poz["A2"].id), "quantity": "9"},
        ],
    )
    await _gun(
        client,
        admin_headers,
        site_b.id,
        date(2026, 7, 10),
        [
            {"boq_item_id": str(poz["B1"].id), "quantity": "4"},
            {"boq_item_id": str(poz["B2"].id), "quantity": "5"},
        ],
    )

    # POZİTİF KONTROL: kardeş şantiyenin köprüsüz pozu gerçekten sayılabilir —
    # kapsam A'ya çevrildiğinde sayaç 1 döner.
    kardes = await repository.subcontractor_unbridged_item_count(
        seeded_db, contract.id, site_a.id, proje.id, year=DONEM["year"], month=DONEM["month"]
    )
    assert kardes == 1, "pozitif kontrol: A şantiyesindeki köprüsüz poz sayılabilir olmalı"

    yanit = await _taseron_onerisi(client, admin_headers, contract.id, **DONEM)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["skipped_unbridged_count"] == 1


async def test_sitesiz_sozlesmede_yanit_alanlari_site_id_NULL_reason_NULL(
    client: AsyncClient, admin_headers, prj_geneli
) -> None:
    """`site_id` yanıtta NULL KALIR (sözleşme gerçekten şantiyesizdir) ama artık
    liste DOLUDUR → gerekçe ÜRETİLMEZ. Eski `SUGGESTION_CONTRACT_WITHOUT_SITE`
    metni bu dilimde SİLİNİR."""
    contract, _, _, _, _, _ = prj_geneli

    govde = (await _taseron_onerisi(client, admin_headers, contract.id, **DONEM)).json()
    assert govde["site_id"] is None
    assert govde["reason"] is None
    assert govde["contract_id"] == str(contract.id)


# --- B) ASIL KABUL ÖLÇÜTÜ: iki yol AYNI sayıyı söyler ---


async def test_ONERI_govdesi_DEGISTIRILMEDEN_yazilinca_HEPSI_diary(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, prj_geneli
) -> None:
    """🔴 Bu dilimin ASIL kabul testi.

    Öneri ucu ile yazma yolunun damga kuralı BİREBİR eşitliktir; ikisi farklı
    yoldan hesaplarsa kullanıcı "günlükten doldur"un verdiği gövdeyi HİÇ
    DEĞİŞTİRMEDEN kaydeder ve satır sessizce `manual` damgalanır. Gövde olduğu
    gibi `PUT …/lines`a gönderilir ve YAZILAN HER SATIRIN `diary` olması istenir.
    """
    contract, _, _, _, beklenen, _ = prj_geneli

    oneri = await _taseron_onerisi(client, admin_headers, contract.id, **DONEM)
    assert oneri.status_code == 200, oneri.text
    satirlar = oneri.json()["lines"]
    assert satirlar, "öneri boş döndü — kabul testi ölçemez hâle gelirdi"

    hakedis = await _hakedis(client, admin_headers, contract.id, **HAKEDIS_DONEM)
    yazma = await _kaydet(client, admin_headers, hakedis["id"], satirlar)
    assert yazma.status_code == 200, yazma.text

    kimlikli = await _beklenen_kimlikli(seeded_db, contract.id, beklenen)
    assert _damgalar(yazma.json()) == dict.fromkeys(kimlikli, "diary")


async def test_sitesiz_sozlesmede_PATCH_donem_tazelemesi_PROJE_TOPLAMINI_kullanir(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers, prj_geneli
) -> None:
    """`restamp_for_period` ikizi: dönemi taşınan hakediş de proje toplamıyla
    yeniden sınanır. Haziran döneminde açılan satır temmuza taşınınca proje
    toplamıyla (16.5) eşleşir ve `diary` OLUR."""
    contract, _, _, _, beklenen, _ = prj_geneli
    tk1 = str(await _kalem_id(seeded_db, contract.id, "TK-1"))

    hakedis = await _hakedis(client, admin_headers, contract.id, period_year=2026, period_month=6)
    yanit = await _kaydet(
        client, admin_headers, hakedis["id"], [{"contract_item_id": tk1, "quantity": "16.5"}]
    )
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {tk1: "manual"}
    assert beklenen["TK-1"] == Decimal("16.5")

    yama = await client.patch(
        f"/subcontractor-progress-payments/{hakedis['id']}",
        json={"period_month": 7},
        headers=admin_headers,
    )
    assert yama.status_code == 200, yama.text
    assert _damgalar(yama.json()) == {tk1: "diary"}


# --- E) GERİLEME: ŞANTİYEYE BAĞLI sözleşme DEĞİŞMEZ (yazma yolu ikizi) ---


async def test_SANTIYEYE_BAGLI_sozlesmede_baska_santiyenin_gunlugu_manual_KALIR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye_fabrikasi,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    """`test_taseron_baska_santiyenin_gunlugu_KARISMAZ`ın YAZMA YOLU ikizi.

    Değişiklik "hepsini projeye çevir"e dejenere olursa ŞANTİYEYE BAĞLI
    sözleşmenin damgası da komşu şantiyenin günlüğüyle dolar. B'ye bağlı
    sözleşmede A'nın miktarı (12) `manual` KALMALI, B'nin kendi miktarı (4)
    `diary` olmalıdır.
    """
    site_a, proje, pozlar_a = await santiye_fabrikasi("SB-A", item_specs=_specler("A1"))
    site_b, _, pozlar_b = await santiye_fabrikasi("SB-B", project=proje, item_specs=_specler("B1"))
    szl = await sozlesme_kalemi_fabrikasi(pozlar_a[0], proje)
    pozlar_b[0].contract_item_id = szl.id
    await seeded_db.flush()

    contract = await taseron_sozlesmesi_fabrikasi(
        proje, site=site_b, kalemler=[("TK-1", szl)], code="SB-BAGLI"
    )
    await _gun(
        client,
        admin_headers,
        site_a.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(pozlar_a[0].id), "quantity": "12"}],
    )
    await _gun(
        client,
        admin_headers,
        site_b.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(pozlar_b[0].id), "quantity": "4"}],
    )
    tk1 = str(await _kalem_id(seeded_db, contract.id, "TK-1"))
    hakedis = await _hakedis(client, admin_headers, contract.id, **HAKEDIS_DONEM)

    # Proje toplamı 16, A'nınki 12 — ikisi de sözleşmenin şantiyesi DEĞİL.
    for miktar in ("12", "16"):
        yanit = await _kaydet(
            client, admin_headers, hakedis["id"], [{"contract_item_id": tk1, "quantity": miktar}]
        )
        assert yanit.status_code == 200, yanit.text
        assert _damgalar(yanit.json()) == {tk1: "manual"}, miktar

    yanit = await _kaydet(
        client, admin_headers, hakedis["id"], [{"contract_item_id": tk1, "quantity": "4"}]
    )
    assert yanit.status_code == 200, yanit.text
    assert _damgalar(yanit.json()) == {tk1: "diary"}


# --- G) ÖLÇÜM: ÇİFT SAYIM (bilinen, RAPORLANMIŞ davranış) ---


async def test_CIFT_SAYIM_ayni_kaynak_kalemi_iki_sozlesmeye_onerilir_OLCUM(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers,
    santiye_fabrikasi,
    sozlesme_kalemi_fabrikasi,
    taseron_sozlesmesi_fabrikasi,
) -> None:
    """🔴 ÖLÇÜLMÜŞ ve RAPORLANMIŞ davranış — YÖNETİM KARARI BEKLİYOR, bu dilimin
    KAPSAMI DIŞINDA. Bu test bir kısıt EKLEMEZ, bir engel KOYMAZ; yalnız fiilî
    davranışı ÇİVİLER ki değişirse sessiz kalmasın.

    `SubcontractorContractItem`ta UNIQUE yalnız `(contract_id, code)`tur: aynı
    projenin İKİ sözleşmesinin (biri proje-geneli, biri şantiyeye bağlı)
    `source_contract_item_id`i AYNI işveren kalemini gösterebilir. Bu değişiklikten
    sonra AYNI günlük miktarı İKİSİNE BİRDEN önerilir ve ikisi de `diary`
    damgalanabilir — yani aynı iş iki kez ödenebilir.

    Ölçülen sayılar: A=12, B=4 → proje-geneli sözleşmeye 16, A'ya bağlı
    sözleşmeye 12 önerilir; 16 birimlik iş için TOPLAM 28 birim önerilmiş olur.
    """
    site_a, proje, pozlar_a = await santiye_fabrikasi("CS-A", item_specs=_specler("A1"))
    site_b, _, pozlar_b = await santiye_fabrikasi("CS-B", project=proje, item_specs=_specler("B1"))
    szl = await sozlesme_kalemi_fabrikasi(pozlar_a[0], proje)
    pozlar_b[0].contract_item_id = szl.id
    await seeded_db.flush()

    genel = await taseron_sozlesmesi_fabrikasi(
        proje, site=None, kalemler=[("TK-G", szl)], code="CS-GENEL"
    )
    bagli = await taseron_sozlesmesi_fabrikasi(
        proje, site=site_a, kalemler=[("TK-A", szl)], code="CS-BAGLI"
    )
    await _gun(
        client,
        admin_headers,
        site_a.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(pozlar_a[0].id), "quantity": "12"}],
    )
    await _gun(
        client,
        admin_headers,
        site_b.id,
        date(2026, 7, 10),
        [{"boq_item_id": str(pozlar_b[0].id), "quantity": "4"}],
    )

    tkg = str(await _kalem_id(seeded_db, genel.id, "TK-G"))
    tka = str(await _kalem_id(seeded_db, bagli.id, "TK-A"))

    assert await _miktarlar(client, admin_headers, genel.id, **DONEM) == {tkg: Decimal("16")}
    assert await _miktarlar(client, admin_headers, bagli.id, **DONEM) == {tka: Decimal("12")}

    for contract_id, kalem, miktar in ((genel.id, tkg, "16"), (bagli.id, tka, "12")):
        hakedis = await _hakedis(client, admin_headers, contract_id, **HAKEDIS_DONEM)
        yanit = await _kaydet(
            client, admin_headers, hakedis["id"], [{"contract_item_id": kalem, "quantity": miktar}]
        )
        assert yanit.status_code == 200, yanit.text
        assert _damgalar(yanit.json()) == {kalem: "diary"}
