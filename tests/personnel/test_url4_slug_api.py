"""URL-4 — `GET /personnel/{personnel_id}` ad slug'ıyla açılır.

## 🔴 KVKK — KULLANICI KARARI 2026-09-05: AD SLUG'I, BAŞKA HİÇBİR ŞEY

Bu tablonun TEK tekil anahtarı `tc_no`dur (`uq_personnel_tc_no`) ve URL'ye
**ASLA** konmaz. Slug'a YALNIZ `full_name` girer; telefon, e-posta ve TCKN'nin
HİÇBİR PARÇASI girmez. Aynı adlı ikinci personel `unique_slug` ile `-2` eki
alır — ad zaten listede görünür olduğu için bu YENİ bir sızıntı AÇMAZ.

`test_slug_TCKN_TELEFON_EPOSTA_hicbirini_TASIMAZ` bu kararın bekçisidir ve
yalnız "slug doğru üretiliyor mu" değil, **hangi verinin URL'ye giremeyeceğini**
ölçer.

## 🔴 ÖLÇÜLDÜ: bu modülde PROJE KAPSAMLI görünürlük süzgeci YOKTUR

`app/modules/personnel/service/core.py`de `visible_*` kapısı yoktur ve
`test_personnel.py` modül docstring'i bunu açıkça yazar: *"proje süzgeci
YOKTUR — `personnel` şirket-geneli bir İK varlığıdır"*. Yani slug burada var
OLMAYAN bir süzgeci DELMEZ; korunan sınır MODÜL İZNİDİR ve
`test_yetkisiz_aktor_SLUGLA_da_ayni_kapiya_carpar` onu ölçer. Bu, dürüstçe
kaydedilir: uydurulmuş bir kapsam bekçisi yazmak gerçekte olmayan bir güvenceyi
belgelemek olurdu.
"""

import uuid

_YOL = "/personnel"

ISCI = {"full_name": "Ahmet Yılmaz", "trade": "Kalıpçı", "source": "company"}


async def _olustur(client, headers, **alanlar) -> dict:
    yanit = await client.post(_YOL, json={**ISCI, **alanlar}, headers=headers)
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


# =========================================================================== #
# 1. ÜRETİM + KVKK
# =========================================================================== #


async def test_personel_olustururken_TURKCE_ad_sluglanir(client, ik_headers) -> None:
    kayit = await _olustur(client, ik_headers)
    assert kayit["slug"] == "ahmet-yilmaz"


async def test_slug_TCKN_TELEFON_EPOSTA_hicbirini_TASIMAZ(client, ik_headers) -> None:
    """🔴🔴 KVKK BEKÇİSİ — kullanıcı kararı 2026-09-05.

    Personel TCKN, telefon ve e-posta ile birlikte açılır; slug bunların
    HİÇBİR PARÇASINI taşımaz ve tamamen `full_name`den türer.
    """
    kayit = await _olustur(
        client,
        ik_headers,
        full_name="Zeynep Kaya",
        tc_no="10000000146",
        phone="05321234567",
        email="zeynep.kaya@ornek.co",
    )
    slug = kayit["slug"]
    assert slug == "zeynep-kaya"

    # Hiçbir hassas değerin hiçbir parçası slug'da GEÇMEZ.
    for hassas in ("10000000146", "1000000", "0146", "05321234567", "5321234", "zeynep.kaya@"):
        assert hassas not in slug, f"slug hassas veri taşıyor: {hassas!r}"
    # Ve slug yalnız slug alfabesindedir.
    assert all(ch.isalnum() and ch.isascii() or ch == "-" for ch in slug)


async def test_ayni_adli_ikinci_personel_SAYI_EKI_alir(client, ik_headers) -> None:
    """Sessizce çakışma YOKTUR — `unique_slug` `-2` verir."""
    ilk = await _olustur(client, ik_headers, full_name="Mehmet Demir")
    ikinci = await _olustur(client, ik_headers, full_name="Mehmet Demir")

    assert ilk["slug"] == "mehmet-demir"
    assert ikinci["slug"] == "mehmet-demir-2"
    assert ilk["id"] != ikinci["id"]

    # İKİSİ DE kendi slug'ıyla açılır (karşıt kanıt).
    for kayit in (ilk, ikinci):
        resp = await client.get(f"{_YOL}/{kayit['slug']}", headers=ik_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == kayit["id"]


async def test_sluglanamayan_ad_slugu_NULL_birakir_ama_kayit_ACILIR(client, ik_headers) -> None:
    kayit = await _olustur(client, ik_headers, full_name="???")
    assert kayit["slug"] is None
    assert (await client.get(f"{_YOL}/{kayit['id']}", headers=ik_headers)).status_code == 200


# =========================================================================== #
# 2. ÇÖZÜMLEME + DEĞİŞMEZLİK
# =========================================================================== #


async def test_uuid_ve_slug_AYNI_govdeyi_doner(client, ik_headers) -> None:
    kayit = await _olustur(client, ik_headers, full_name="Ayşe Şahin")

    by_uuid = await client.get(f"{_YOL}/{kayit['id']}", headers=ik_headers)
    by_slug = await client.get(f"{_YOL}/ayse-sahin", headers=ik_headers)

    assert by_uuid.status_code == by_slug.status_code == 200, by_slug.text
    assert by_uuid.json() == by_slug.json()


async def test_ad_degisince_slug_DEGISMEZ(client, ik_headers) -> None:
    """🔴 URL-2 kararı 4: paylaşılmış bağlantı yeniden adlandırmayla ÖLMEZ."""
    kayit = await _olustur(client, ik_headers, full_name="Hasan Yıldız")

    patch = await client.patch(
        f"{_YOL}/{kayit['id']}", json={"full_name": "Hasan Yıldızhan"}, headers=ik_headers
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["full_name"] == "Hasan Yıldızhan"
    assert patch.json()["slug"] == "hasan-yildiz"

    # ESKİ slug HÂLÂ açar — kararın asıl ölçütü budur.
    eski = await client.get(f"{_YOL}/hasan-yildiz", headers=ik_headers)
    assert eski.status_code == 200
    assert eski.json()["id"] == kayit["id"]

    # YENİ ada göre türeyecek slug HİÇBİR ŞEY açmaz (yönlendirme tablosu yok).
    assert (await client.get(f"{_YOL}/hasan-yildizhan", headers=ik_headers)).status_code == 404


async def test_slug_LISTEDE_de_bulunur(client, ik_headers) -> None:
    """Liste ucu `personel/[id]` bağlantısını üretir."""
    kayit = await _olustur(client, ik_headers, full_name="Liste Personeli")

    liste = await client.get(_YOL, headers=ik_headers)
    assert liste.status_code == 200, liste.text
    satir = next(k for k in liste.json()["items"] if k["id"] == kayit["id"])
    assert satir["slug"] == "liste-personeli"


# =========================================================================== #
# 3. 🔴 KAPI: MODÜL İZNİ (bu modülde kapsam süzgeci YOK — bkz. docstring)
# =========================================================================== #


async def test_yetkisiz_aktor_SLUGLA_da_ayni_kapiya_carpar(
    client, ik_headers, yetkisiz_headers
) -> None:
    """🔴 Slug var OLMAYAN bir kapsam süzgecini DELMEZ; korunan sınır MODÜL İZNİDİR.

    `personnel:none` taşıyan aktör slug'la da UUID'yle de AYNI cevabı alır ve
    o cevap 200 DEĞİLDİR — yani okunabilir anahtar yetki kapısını AÇMAZ.
    """
    kayit = await _olustur(client, ik_headers, full_name="Gizli Personel")

    slugla = await client.get(f"{_YOL}/gizli-personel", headers=yetkisiz_headers)
    uuid_ile = await client.get(f"{_YOL}/{kayit['id']}", headers=yetkisiz_headers)

    assert slugla.status_code == uuid_ile.status_code
    assert slugla.status_code != 200
    assert slugla.json() == uuid_ile.json()

    # 🔴 POZİTİF KONTROL (K-IKIZ1): YETKİLİ aktör AYNI slug'la 200 alır —
    # yukarıdaki eşitlik "slug hiç çalışmıyor" yüzünden değil, KAPI yüzünden.
    yetkili = await client.get(f"{_YOL}/gizli-personel", headers=ik_headers)
    assert yetkili.status_code == 200, yetkili.text
    assert yetkili.json()["id"] == kayit["id"]


# =========================================================================== #
# 4. YAZMA UCU SLUG KABUL ETMEZ
# =========================================================================== #


async def test_PATCH_slug_kabul_ETMEZ_422(client, ik_headers) -> None:
    kayit = await _olustur(client, ik_headers, full_name="Yazma Personeli")

    resp = await client.patch(
        f"{_YOL}/yazma-personeli", json={"trade": "Demirci"}, headers=ik_headers
    )
    assert resp.status_code == 422, resp.text

    # POZİTİF KONTROL: UUID ile AYNI uç çalışır.
    assert (
        await client.patch(f"{_YOL}/{kayit['id']}", json={"trade": "Demirci"}, headers=ik_headers)
    ).status_code == 200


async def test_bozuk_deger_artik_422_DEGIL_404(client, ik_headers) -> None:
    assert (await client.get(f"{_YOL}/hic-boyle-biri-yok", headers=ik_headers)).status_code == 404
    assert (await client.get(f"{_YOL}/{uuid.uuid4()}", headers=ik_headers)).status_code == 404
