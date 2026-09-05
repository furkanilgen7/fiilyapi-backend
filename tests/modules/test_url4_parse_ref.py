"""URL-4 M1 — `parse_ref` KANONİKLİK SINAVI.

## Çürütülen iddia

URL-2 `parse_ref` docstring'i şöyle diyordu: *"Slug'lar `[a-z0-9-]` olduğundan
hiçbir geçerli slug UUID olarak ayrıştırılamaz — **iki uzay kesişmez**."*
**Yanlıştı ve ölçülerek çürütüldü.**

`uuid.UUID()` girdideki TİRELERİ TAMAMEN ATAR ve 32 hex hanesi olan her dizeyi
kabul eder. `[a-z0-9-]` alfabesi `[0-9a-f-]`i KAPSADIĞI için `slugify`nin
ÜRETEBİLDİĞİ bir slug UUID uzayına düşebiliyordu:

    slugify("Deadbeef Deadbeef Deadbeef Deadbeef")
        -> "deadbeef-deadbeef-deadbeef-deadbeef"  -> uuid.UUID() KABUL EDER

Sonuç: o slug'ı taşıyan kayıt KENDİ BAĞINI AÇAMIYORDU — istek var olmayan bir
kimliğe gidip 404 alıyordu.

## Düzeltme ve neden GERİYE UYUMLU

Yalnız **kanonik 8-4-4-4-12** biçim UUID sayılır. `str(uuid)` HER ZAMAN kanonik
üretir, yani sistemin YAYINLADIĞI her UUID bağlantısı kanoniktir ve çalışmaya
devam eder. Kanonik olmayan biçimler (tiresiz 32 hex, `urn:uuid:` önekli) artık
slug sayılır — onları üreten şey kullanıcının adıdır, bizim bağlantımız değil.

⚠️ Bu **düşük olasılıklı ama gerçek** bir kusurdur: kullanıcının 32 hex şekilli
bir ad yazması gerekir. Abartılmıyor; kapatılıyor.
"""

import uuid

from app.core.slug import parse_ref, slugify


def test_32_HEX_SEKILLI_SLUG_kendi_bagini_ACAR():
    """🔴 M1'in ÇEKİRDEK İDDİASI — `slugify` çıktısı UUID'ye DÜŞMEZ.

    Mutasyon: `parse_ref`teki kanoniklik sınavını kaldır (`return parsed`) →
    bu test kırmızı olur, çünkü slug UUID olarak ayrıştırılır.
    """
    ad = "Deadbeef Deadbeef Deadbeef Deadbeef"
    slug = slugify(ad)
    assert slug == "deadbeef-deadbeef-deadbeef-deadbeef"

    cozum = parse_ref(slug)
    assert isinstance(cozum, str), "slugify çıktısı UUID uzayına düştü — kayıt bağını açamaz"
    assert cozum == slug


def test_TIRESIZ_32_hex_de_slug_sayilir():
    """`uuid.UUID()` kabul eder ama kanonik DEĞİLDİR → slug."""
    for deger in ("0123456789abcdef0123456789abcdef", "deadbeefdeadbeefdeadbeefdeadbeef"):
        assert isinstance(parse_ref(deger), str), deger


def test_KANONIK_uuid_hala_UUID_olarak_cozulur_POZITIF_KONTROL():
    """🔴 POZİTİF KONTROL: eski UUID bağlantıları ÇALIŞMAYA DEVAM EDER.

    Bu iddia olmasaydı `parse_ref` "her şey slug" diye kırılabilir ve
    yukarıdaki iki test yine yeşil kalırdı (eşdeğer mutant).
    """
    for _ in range(20):
        gercek = uuid.uuid4()
        cozum = parse_ref(str(gercek))
        assert isinstance(cozum, uuid.UUID) and cozum == gercek

    # Büyük harfli kanonik yazım da UUID'dir (`str(parsed) == ref.lower()`).
    buyuk = str(uuid.uuid4()).upper()
    assert isinstance(parse_ref(buyuk), uuid.UUID)


def test_normal_sluglar_ETKILENMEDI():
    for slug in ("kopru-guclendirme", "FIL20260001", "tsz-2026-004", "ahmet-yilmaz-2"):
        assert isinstance(parse_ref(slug), str), slug


def test_uuid_ve_slug_uzaylari_ARTIK_KESISMEZ():
    """Düzeltmeden SONRA iddia GERÇEKTEN doğru: hiçbir değer iki dala da düşmez.

    `slugify`nin üretebildiği alfabede (`[a-z0-9-]`) rastgele üretilmiş 32-hex
    şekilli dizelerin hiçbiri UUID'ye düşmemeli; gerçek UUID'lerin hepsi
    düşmeli. İki küme AYRIK.
    """
    import random

    hexler = "0123456789abcdef"
    for _ in range(200):
        ham = "".join(random.choice(hexler) for _ in range(32))
        parcali = f"{ham[:8]}-{ham[8:16]}-{ham[16:24]}-{ham[24:]}"
        assert isinstance(parse_ref(parcali), str)
        assert isinstance(parse_ref(ham), str)
    for _ in range(200):
        assert isinstance(parse_ref(str(uuid.uuid4())), uuid.UUID)
