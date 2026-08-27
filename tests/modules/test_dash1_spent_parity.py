"""DASH-1 — taahhut kartindaki `contracting.spent` PARITE bekcisi.

NICIN DOGDU
-----------
Yonetim canlida `GET /projects` ile `GET /projects/{id}` ayni proje icin FARKLI
"Harcanan" gosterdigini bildirdi. Iz surulunce kodun ayrisamayacagi olculdu:
`service.to_detail` yanitini dogrudan `_to_item(...)`ten kurar, yani DETAY,
LISTE ogesinin alan-alan ustkumesidir ve iki uc da ayni `cost_cards.by_projects`
toplu okumasini cagirir. Canlidaki fark, iki olcum ARASINDA degisen DB
durumundan geliyordu — kod kusuru degil.

Gercek acik BASKAYDI: `contracting.spent` bugune kadar YALNIZ liste ucunde
cakiliydi (`test_projects_cost_bindings.py`). DETAY YUZEYI BEKCISIZDI. Iki yuzey
ileride ayrisirsa (ornegin detay yoluna `cost_cards.EMPTY` sizarsa) bu YESIL
gecerdi. Asagidaki bekciler o acigi kapatir.

NE CAKILIR
----------
1. PARITE — ayni projede LISTE ile DETAY ayni zarfi doner (TUM zarf, tek
   karsilastirmada: kismi eslesme gecemez).
2. KUME — sayi YALNIZ `approved`+`paid` brutudur. "Sahte-yesilin 8. hali"
   (ozet servisin arkasindaki KUME bekcisizdir) yuzunden toplam iddiasi TEK
   basina yetmez: beklenen sayi testte ACIKCA carpilir **ve** ayrica
   `draft`/`pending_approval` eklemenin sayiyi OYNATMADIGI olculur.
3. BOS HAL — hakedissiz taahhutte iki yuzey de `available=true, value="0.00"`
   doner ("bulundu, bos"; `metric(None)` olsaydi `available=false` gelirdi).

Tum iddialar HTTP uclarindan gecer: bekci KULLANICININ gordugunu olcmelidir.
"""

from decimal import Decimal

from app.modules.subcontractor_progress_payments.models import SubcontractorPaymentStatus

from . import _ilr

# Zarf tek fiyatla kurulur ki testteki carpim GOZLE dogrulanabilsin.
_BIRIM = "1000.00"


def _liste_spent(body: dict, project_id) -> dict:
    """LISTE ucundaki projenin `contracting.spent` zarfi (TUM sozluk)."""
    item = next(row for row in body["items"] if row["id"] == str(project_id))
    return item["contracting"]["spent"]


async def _iki_yuzey(client, headers: dict, project_id) -> tuple[dict, dict]:
    """(liste zarfi, detay zarfi) — ayni anda, ayni DB durumundan okunur.

    Canlidaki "fark" iki olcumun ARASINDA degisen veriden dogmustu; bekci bu
    yuzden iki ucu pes pese ve arada YAZMA yapmadan okur.
    """
    liste = (await client.get("/projects", headers=headers)).json()
    detay = (await client.get(f"/projects/{project_id}", headers=headers)).json()
    return _liste_spent(liste, project_id), detay["contracting"]["spent"]


async def test_LISTE_ile_DETAY_ayni_projede_AYNI_spent_doner(
    client, db_session, user_factory, project_factory
):
    """K3 (tek kaynak) YUZEY duzeyinde cakilir: detay ucu bugun listeyle ayni
    toplu okumadan besleniyor, ama bunu HICBIR test olcmuyordu.

    Iddia TUM zarf uzerindedir (`available` + `value` + `pending_module`), tek
    karsilastirmada: yalnizca `value` cakilsaydi, detayin bos zarf donmesi
    (`available=false`) yine yesil gecebilirdi.
    """
    yazan = await _ilr.aktor(db_session, user_factory, "parite@dash1.co")
    project = await project_factory(
        code="D1-PAR", project_type="taahhut", contract_amount="9000000.00"
    )
    # Dort durumun HEPSI ayni projede: parite, ayiklama yapilan bir kumede olculur.
    for durum, miktar in (
        (SubcontractorPaymentStatus.draft, "100"),
        (SubcontractorPaymentStatus.pending_approval, "200"),
        (SubcontractorPaymentStatus.approved, "300"),
        (SubcontractorPaymentStatus.paid, "400"),
    ):
        await _ilr.taseron_hakedisi(
            db_session, project, yazan, quantity=miktar, unit_price=_BIRIM, status=durum
        )
    headers = await _ilr.login(client, db_session, user_factory, "patron", "parite@d1.co")

    liste_spent, detay_spent = await _iki_yuzey(client, headers, project.id)

    assert liste_spent == detay_spent
    # Parite "ikisi de bos" ile de saglanabilirdi — zarfin DOLU oldugu da cakilir.
    assert liste_spent["available"] is True
    assert liste_spent["pending_module"] is None


async def test_harcanan_YALNIZ_approved_ve_paid_kumesini_toplar_iki_yuzeyde_de(
    client, db_session, user_factory, project_factory
):
    """KUME bekcisi (sahte-yesilin 8. hali): "toplam X cikti" iddiasi TEK basina
    yetmez — durum suzgeci genisletilse de dar tutulsa da bir sayi yine cikar.

    Iki yarim birlikte cakilir:
    * beklenen sayi testte ACIKCA carpilir (bagimsiz aritmetik),
    * ve `draft`/`pending_approval` EKLEMEK sayiyi OYNATMAZ (S1: harcanan =
      `approved` + `paid`; kesintiler S2 geregi brute dokunmaz).
    """
    yazan = await _ilr.aktor(db_session, user_factory, "kume@dash1.co")
    project = await project_factory(
        code="D1-KUM", project_type="taahhut", contract_amount="9000000.00"
    )
    await _ilr.taseron_hakedisi(
        db_session,
        project,
        yazan,
        quantity="300",
        unit_price=_BIRIM,
        status=SubcontractorPaymentStatus.approved,
    )
    await _ilr.taseron_hakedisi(
        db_session,
        project,
        yazan,
        quantity="400",
        unit_price=_BIRIM,
        status=SubcontractorPaymentStatus.paid,
    )
    headers = await _ilr.login(client, db_session, user_factory, "patron", "kume@d1.co")

    liste_spent, detay_spent = await _iki_yuzey(client, headers, project.id)

    # Aritmetik cakilmadan ONCE parite: yuzeyler ayrisirsa hata net okunsun.
    assert liste_spent == detay_spent
    # 300 × 1000.00 (approved) + 400 × 1000.00 (paid) = 700000.00
    beklenen = Decimal("700000.00")
    assert Decimal(liste_spent["value"]) == beklenen
    assert Decimal(detay_spent["value"]) == beklenen

    # Ikinci yarim: maliyete GIRMEYEN iki durum eklenir, sayi KIMILDAMAMALIDIR.
    await _ilr.taseron_hakedisi(
        db_session,
        project,
        yazan,
        quantity="5000",
        unit_price=_BIRIM,
        status=SubcontractorPaymentStatus.draft,
    )
    await _ilr.taseron_hakedisi(
        db_session,
        project,
        yazan,
        quantity="6000",
        unit_price=_BIRIM,
        status=SubcontractorPaymentStatus.pending_approval,
    )

    liste_sonra, detay_sonra = await _iki_yuzey(client, headers, project.id)

    assert liste_sonra == detay_sonra
    assert Decimal(liste_sonra["value"]) == beklenen
    assert Decimal(detay_sonra["value"]) == beklenen


async def test_hakedissiz_taahhutte_iki_yuzey_de_BULUNDU_SIFIR_doner(
    client, db_session, user_factory, project_factory
):
    """ "Bulundu, bos" ile "bilinmiyor" AYRI hallerdir: kaynak modul CANLI oldugu
    icin hakedissiz taahhut `available=true, value="0.00"` dondurur.

    `metric(None)` sizsaydi `available=false` gelirdi ve ekran "modul yok" derdi
    — ayrimin butun anlami budur. Detay yuzeyi bunu da bugune dek cakmiyordu.
    """
    project = await project_factory(
        code="D1-BOS", project_type="taahhut", contract_amount="5100000.00"
    )
    await db_session.flush()
    headers = await _ilr.login(client, db_session, user_factory, "patron", "bos@d1.co")

    liste_spent, detay_spent = await _iki_yuzey(client, headers, project.id)

    bulundu_sifir = {"available": True, "value": "0.00", "pending_module": None}
    assert liste_spent == bulundu_sifir
    assert detay_spent == bulundu_sifir
