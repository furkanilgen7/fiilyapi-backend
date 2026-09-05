"""URL slug üretimi ve çözümlemesi (URL-2).

KÖK OLAY: `panel.fiilyapi.com/projeler/049e058b-42d9-...` kullanıcıya ham UUID
gösteriyordu. Kullanıcı kararı (2026-08-29): **AD SLUG'I** — `/projeler/kopru-guclendirme`.

## 🔴 `str.lower()` TÜRKÇE İÇİN YANLIŞTIR — bu modülün varlık sebebi

Python'un varsayılan büyük/küçük harf dönüşümü Unicode'un *dilden bağımsız*
kurallarını uygular ve Türkçe'nin noktalı/noktasız `i` ikilisini bozar:

    "İ".lower()  ->  "i̇"   (i + BİRLEŞİK ÜST NOKTA — TEK harf değil, İKİ kod noktası)
    "I".lower()  ->  "i"          (Türkçe'de "ı" olmalıydı)

Birinci satır sinsidir: sonuç *ekranda* "i" gibi görünür ama içinde U+0307
taşır; `[a-z0-9]` süzgecinden geçmez ve slug'da sessizce bir `-` bırakır
(`İstanbul` -> `-stanbul`). Depoda ölçülmüş kardeş tuzak: `find -iname`
Türkçe "İ"de yanıltır.

ÇÖZÜM: `lower()`a HİÇ güvenilmez. Türkçe harfler `lower()`dan **ÖNCE** açık
tabloyla ASCII karşılıklarına çevrilir; tablodan sonra dizede Türkçe'ye özgü
hiçbir harf kalmadığı için `lower()` yalnız ASCII üzerinde çalışır ve zararsızdır.

Tablo (emirde birebir verilen): `ÇĞİÖŞÜçğıöşü` -> `cgiosucgiosu`.
`I` (noktasız BÜYÜK I) tabloda AYRICA vardır ve `i`ye düşer: Türkçe'de küçüğü
`ı`dır, `ı` da zaten `i`ye eşlenir — yani iki yol da aynı ASCII harfe varır.

## 🔴 ÖLÇÜLDÜ: tablonun TEK TAŞIYICI harfi `ı`dır — geri kalanı NFKD MASKELER

Mutasyon ölçümü (tabloyu tamamen kaldır, yalnız NFKD + `lower()` bırak):

    "İstanbul"        -> "istanbul"   ✅ (NFKD `İ`yi `I`+U+0307'ye ayrıştırır)
    "Köprü Güçlendirme" -> "kopru-guclendirme"  ✅
    "IĞDIR"           -> "igdir"      ✅
    "Işıklar"         -> "is-klar"    ❌ <-- TEK GERÇEK KUSUR

`ı` (U+0131) Unicode'da AYRIŞMAZ ve `lower()`da `ı` KALIR; süzgeçten geçemez ve
harf tamamen DÜŞER. Yani `Ç Ğ İ Ö Ş Ü ç ğ ö ş ü` için tablo ile NFKD **aynı**
sonucu verir (iki katman birbirini maskeler); tabloyu ölçüte bağlayan harf
yalnızca `ı`dır — ve `İ` için tablo, NFKD sırasının yanlışlıkla değiştirilmesine
karşı ikinci savunmadır.

Bu ölçüm dürüstçe kaydedilir çünkü aksi hâlde "12 harf için testim var"
sanılırdı; gerçekte 11'i eşdeğer mutant üretir. `test_slug.py` içindeki
`test_i_HARFI_TABLONUN_TEK_TASIYICI_HARFIDIR` bu tek gerçek yükü ölçer.

## Boş slug

Adı tamamen noktalama/ASCII-dışı olan bir kayıt boş slug üretebilir (`"..."`,
`"???"`). Böyle bir kayda slug UYDURULMAZ: `slugify` `None` döner, kolon NULL
kalır ve o kaydın URL'i UUID olarak yaşamaya devam eder (URL-2 kararı 2 zaten
UUID'yi kalıcı olarak desteklenir kılar). Uydurulmuş bir taban (`kayit`) yazmak
çakışma üretir ve kullanıcıya hiçbir okunabilirlik kazandırmaz.

## Çakışan slug

İki farklı ad aynı slug'a düşebilir (`Köprü A` / `Kopru A` -> `kopru-a`).
`unique_slug` SAYI EKİ verir (`kopru-a-2`, `kopru-a-3`). Sessizce çakıştırma
YOKTUR: ek verilemiyorsa (kapsamdaki tüm adaylar dolu) çağıran taraf DB'nin
benzersizlik kısıtına çarpar ve 409 alır — `_next_project_code` / `_next_site_code`
ile BİREBİR aynı yarış kanonu (otomatik yeniden deneme YAPILMAZ).
"""

import re
import unicodedata
import uuid
from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

# Türkçe harf -> ASCII. `lower()`dan ÖNCE uygulanır (bkz. modül docstring'i).
# `I` (U+0049) tabloda BİLEREK vardır: Türkçe küçüğü `ı`dır ve `ı` -> `i`dir.
_TURKISH_TO_ASCII = str.maketrans(
    {
        "Ç": "c",
        "Ğ": "g",
        "İ": "i",
        "I": "i",
        "Ö": "o",
        "Ş": "s",
        "Ü": "u",
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
    }
)

_NON_SLUG = re.compile(r"[^a-z0-9]+")

# Slug tabanı için tavan. Kolon `String(160)`tır: 100 taban + `-` + sayı eki
# rahatça sığar.
# 🔴 GEREKÇE DÜZELTİLDİ (URL-4): eski yorum `name`i `String(150)` sanıyordu;
# ÖLÇÜLDÜ — gerçek kolonlar `String(200)`dür (`projects.name`, `equipment.name`,
# `personnel.full_name`). Yani tavanı sağlayan şey KOLON değil BU SABİTTİR:
# 200 karakterlik bir ad burada 100'e KIRPILIR.
MAX_SLUG_LENGTH = 100

# `unique_slug` sayı ekini buradan başlatır: ilk çakışan `-2` alır (`-1` DEĞİL —
# kullanıcı "ikinci Köprü" okur, "birinci"yi zaten eksiz slug taşır).
_FIRST_SUFFIX = 2


def slugify(value: str | None) -> str | None:
    """Serbest metni URL slug'ına çevirir; slug'lanamıyorsa `None`.

    Sıra ÖNEMLİDİR ve değiştirilemez:
      1. Türkçe harfler açık tabloyla ASCII'ye (`lower()`dan ÖNCE),
      2. NFKD ayrıştırma + birleşik işaretleri düşürme (`é` -> `e`),
      3. `lower()` (artık yalnız ASCII üzerinde),
      4. `[a-z0-9]` dışı her dizi tek `-`,
      5. baştaki/sondaki `-` kırpılır, tavan uygulanır.

    2. adım 1.'den SONRA gelmek zorundadır: `İ` NFKD'de `I` + U+0307'ye ayrışır
    ve birleşik işaret düşünce geriye `I` kalırdı — Türkçe kaybı 1. adımda
    zaten önlenmiş olduğu için bu sıra güvenlidir.
    """
    if value is None:
        return None
    ascii_text = value.translate(_TURKISH_TO_ASCII)
    decomposed = unicodedata.normalize("NFKD", ascii_text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    slug = _NON_SLUG.sub("-", stripped.lower()).strip("-")
    if not slug:
        return None
    return slug[:MAX_SLUG_LENGTH].strip("-") or None


def unique_slug(base: str | None, taken: Iterable[str]) -> str | None:
    """Kapsamda kullanılmayan bir slug döndürür; taban `None` ise `None`.

    `taken` KAPSAM İÇİ mevcut slug kümesidir — kapsam çağırana aittir
    (proje: şirket geneli, şantiye: proje içi, bölüm: şantiye içi).
    """
    if base is None:
        return None
    used = {s for s in taken if s}
    if base not in used:
        return base
    suffix = _FIRST_SUFFIX
    while f"{base}-{suffix}" in used:
        suffix += 1
    return f"{base}-{suffix}"


def parse_ref(ref: str) -> uuid.UUID | str:
    """Yol parametresini UUID'ye VEYA slug metnine çözer (URL-2 kararı 2).

    Eski UUID bağlantıları ÇALIŞMAYA DEVAM ETMELİDİR: kullanıcının yer imleri
    proje yeniden adlandırıldı diye de, slug açıldı diye de bozulmaz.

    ## 🔴 "İKİ UZAY KESİŞMEZ" İDDİASI YANLIŞTI — ÖLÇÜLDÜ VE DÜZELTİLDİ (URL-4)

    URL-2 bu fonksiyonun docstring'ine *"slug'lar `[a-z0-9-]` olduğundan hiçbir
    geçerli slug UUID olarak ayrıştırılamaz"* yazmıştı. **Yanlıştı.**
    `uuid.UUID()` girdideki TİRELERİ TAMAMEN ATAR ve 32 hex hanesi olan HER
    dizeyi kabul eder; `[a-z0-9-]` alfabesi `[0-9a-f-]`i KAPSAR:

        slugify("Deadbeef Deadbeef Deadbeef Deadbeef")
            -> "deadbeef-deadbeef-deadbeef-deadbeef"  -> uuid.UUID() KABUL EDER
        "0123456789abcdef0123456789abcdef"            -> uuid.UUID() KABUL EDER

    Yani `slugify`nin ÜRETEBİLDİĞİ bir slug, UUID uzayına düşüp kendi kaydını
    açamaz hâle gelebiliyordu (istek var olmayan bir kimliğe gidip 404 alırdı).

    ## Çözüm: YALNIZ KANONİK BİÇİM UUID sayılır

    Kanonik biçim 8-4-4-4-12'dir ve `str(uuid)` HER ZAMAN onu üretir — yani
    sistemin YAYINLADIĞI her UUID bağlantısı kanoniktir ve çalışmaya devam
    eder. Kanonik olmayan ama `uuid.UUID()`nin kabul ettiği biçimler (tiresiz
    32 hex, yanlış yerde tireli, `urn:uuid:` önekli) artık SLUG sayılır —
    çünkü onları üreten şey kullanıcının adı, bizim bağlantımız değildir.

    Bu ayrım ÖLÇÜLDÜ: `deadbeef-deadbeef-deadbeef-deadbeef` ve
    `0123456789abcdef0123456789abcdef` kanonik DEĞİLDİR (slug'a düşer), gerçek
    `uuid4()` çıktıları kanoniktir (UUID'ye düşer).

    Bekçisi: `test_url4_parse_ref.py::test_32_HEX_SEKILLI_SLUG_kendi_bagini_ACAR`.
    """
    try:
        parsed = uuid.UUID(ref)
    except (ValueError, AttributeError, TypeError):
        return ref
    # 🔴 Kanoniklik SINAVI: `uuid.UUID()` kabul etti diye UUID DEĞİLDİR.
    # `str(parsed)` her zaman kanonik 8-4-4-4-12 küçük harf üretir; girdi ona
    # birebir eşit değilse bu bir UUID bağlantısı değil, slug'dır.
    return parsed if str(parsed) == ref.lower() else ref


async def allocate_slug(
    session: AsyncSession,
    name: str | None,
    column: InstrumentedAttribute[str | None],
    *scope_filters: ColumnElement[bool],
) -> str | None:
    """Kapsamda benzersiz bir slug ayirir; ad slug'lanamiyorsa `None`.

    `scope_filters` TEKILLIK KAPSAMINI tasir ve kolonun kisitiyla BIREBIR
    ortusmek ZORUNDADIR — aksi hâlde ayirici bir cakismayi goremez ve DB
    kisitina carpar:

        Project.slug  -> kapsam YOK          (global, `uq_projects_slug`)
        Site.slug     -> Site.project_id ==  (`uq_sites_project_slug`)
        Section.slug  -> Section.site_id ==  (`uq_sections_site_slug`)

    `LIKE` deseni GUVENLIDIR: `base` yalniz `[a-z0-9-]` icerir (`slugify`
    ciktisi), yani `%`/`_` joker karakteri tasiyamaz — kacis gerekmez.

    🔴 YARIS: iki es zamanli olusturma ayni sayi ekini secebilir; kismi
    benzersiz indeks ihlali mevcut IntegrityError -> 409 isleyicisine duser ve
    OTOMATIK YENIDEN DENEME YAPILMAZ. `_next_project_code` / `_next_site_code`
    ile BIREBIR ayni kanon (spec §8.3) — slug icin ayri bir yaris cozumu icat
    edilmez.

    ## 🔴 KARAR (URL-4): GLOBAL TEKILLIK BIR SIZINTI TASIR — KABUL EDILDI

    URL-4'un alti kolonu GLOBAL tekildir (`scope_filters` VERILMEZ). Sonuc:
    goremedigi bir "Kopru Guclendirme" varken ikinci bir tane olusturan
    kullanici `kopru-guclendirme-2` alir ve bundan **ayni adli baska bir
    kaydin VAR OLDUGUNU** cikarabilir. Sizan sey adin KENDISI degildir
    (kullanici onu zaten yazdi), yalnizca **varlik** bilgisidir.

    Kapsam suzgeci gecmek (`allocate_slug`a `Model.project_id == …` vermek) bu
    sizintiyi kapatirdi ama URL'i BOZARDI: kapsam ici tekil bir slug, kapsami
    URL'de TASIMAYAN bir yolda (`/makine/beko-loder`) coklu esleme uretir ve
    cozumleyici hangi kaydi acacagini bilemez — URL-2'nin `sites` icin
    `?project=` parametresiyle cozdugu problem, burada cozecek bir segment
    YOKTUR.

    Bu yuzden GLOBAL TEKILLIK SECILDI ve sizinti KABUL EDILDI. Gerekce:
    ad zaten kullanicinin YAZDIGI seydir, kayit govdesi/kimligi hicbir sekilde
    sizmaz, ve alternatifi calismayan bir URL'dir. Karar burada YAZILIDIR ki
    ileride "farkinda degildik" denmesin.
    """
    base = slugify(name)
    if base is None:
        return None
    stmt = select(column).where(
        or_(column == base, column.like(f"{base}-%")),
        *scope_filters,
    )
    taken = (await session.execute(stmt)).scalars().all()
    return unique_slug(base, taken)


def matches_ref(entity_id: uuid.UUID, entity_slug: str | None, ref: uuid.UUID | str) -> bool:
    """URL-4: bir kayit YA kimligiyle YA slug'iyla eslesir.

    `projects/service.py::project_matches_ref`in TURDEN BAGIMSIZ ikizidir.

    🔴 SAYIM DUZELTILDI: bu docstring once *"URL-4'un dokuz rotasinin HEPSI
    bunu kullanir"* diyordu — YANLIS. Olculdu, GERCEK CAGIRAN TEKTIR:
    `contracts/service.py:328` (`_visible_project`, isveren sozlesmesi ucu).
    Kalan sekiz rota kaydi GORUNUR KUMEDE degil DOGRUDAN SORGUDA cozer
    (`ref_filter` + repository) ve bu fonksiyona hic ugramaz.

    Neden yine de burada duruyor: isveren sozlesmesi ucu kaydi gorunur kumenin
    ICINDE eslestirmek ZORUNDA (kapsam suzgeci yapisal olarak atlanamaz olsun
    diye), ve o esleştirme kosulunu `Project` tipine baglamadan ifade eden tek
    yer burasi. Tek cagiranli olmasi onu olu kod YAPMAZ; ama "dokuz rota"
    iddiasi bir sayim yalaniydi ve kaldirildi.

    `project_matches_ref` BILEREK YERINDE BIRAKILDI: `Project` tipine bagli
    imzasi ve mutasyon olcumunu anlatan docstring'i URL-2'nin kaydidir; onu
    silmek bu dilimin isi degildir (kapsam disi).

    Slug'i NULL olan kayit HICBIR slug'la eslesmez — yalniz UUID'siyle
    erisilebilir (URL-2 karar 5).
    """
    if isinstance(ref, uuid.UUID):
        return entity_id == ref
    return entity_slug is not None and entity_slug == ref


# Yol segmentine GUVENLE girebilen dogal anahtar. `/` EN TEHLIKELISIDIR:
# `invoice_no` GELEN faturada SERBEST METINDIR (kullanici girer) ve `2026/0001`
# gibi bir numara `/faturalar/2026/0001` uretirdi — Next.js dinamik segmenti
# bunu ESLESTIREMEZ, kullanici 404 gorurdu. Yuzde-kodlama (`%2F`) BFF ile
# FastAPI arasindaki iki katmanda guvenilir DEGILDIR (proxy'ler cozer/yeniden
# kodlar), bu yuzden kodlama DEGIL ELEME secildi.
_URL_SAFE_KEY = re.compile(r"[A-Za-z0-9._~-]+")


def url_safe_key(value: str | None) -> str | None:
    """Dogal anahtari URL'ye KOYULABILIYORSA dondurur, aksi hâlde `None`.

    URL-4: `purchase_requests.request_no` ve `invoices.invoice_no` KENDI
    degerleriyle cozulur (slug kolonu YOKTUR) — yani sozlesmede yayinlanan
    anahtar ile cozumleyicinin aradigi deger BIREBIR AYNI OLMAK ZORUNDADIR.
    Bu yuzden anahtar SLUG'LANMAZ: `slugify("2026/0001")` -> `2026-0001` olurdu
    ve o deger veritabaninda HIC YOKTUR; uc kendi yayinladigi bagi acamazdi.

    Guvenli olmayan numara tasiyan kayit `None` doner ve URL'i UUID olarak
    yasar — URL-2 karar 5'in (`slug ?? id`) tam olarak ongordugu dusus.

    ## 🔴 KARAR (URL-4): BUYUK/KUCUK HARF ASIMETRISI — KABUL EDILDI

    URL-4'te IKI anahtar ailesi var ve harf davranislari FARKLI:

      * `slug` KOLONU olan alti tablo -> `slugify` ciktisi, HEP KUCUK HARF
        (`/makine/beko-loder`).
      * DOGAL ANAHTARLI iki uc (`request_no`, `invoice_no`) -> deger OLDUGU
        GIBI yayinlanir (`/faturalar/FIL20260001`).

    Sonuc olculdu: `/faturalar/fil20260001` **404**, `/faturalar/FIL20260001`
    **200**. Bu bir tutarsizliktir ve BILEREK kabul edilmistir.

    Gerekce: cozumleyici `invoice_no = :ref` ile EXACT arar ve o kolonun
    benzersiz indeksi de exact'tir. Kucuk harfe indirgemek (`lower(invoice_no)
    = lower(:ref)`) indeksi kullanilamaz hale getirir; slug'lamak ise
    yayinlanan anahtar ile aranan degeri AYIRIR (`url_safe_key` docstring'inin
    ust kismi) — yani uc kendi yayinladigi bagi acamaz olurdu.

    Kullaniciya gorunen yuzde bu asimetri ZARARSIZDIR: iki uc de bagi KENDISI
    uretir (`slug ?? id`), yani kullanici anahtari elle YAZMAZ; kopyaladigi
    baglanti her zaman dogru harflerle gelir. Elle harf degistirerek gelen
    istek 404 alir — var olmayan bir anahtarla ayni cevap.

    🔴 NOKTA SEGMENTLERI DE ELENIR (`.` ve `..`). Alfabede `.` VAR (`A-2026.0001`
    mesru bir fatura numarasidir), ama TAMAMI noktadan olusan bir segment yol
    ANLAMI tasir: tarayici ve proxy'ler `..`yi istek GONDERILMEDEN normalize
    eder, kullanici sessizce baska bir sayfaya duser ve sunucu bunu hicbir
    zaman GORMEZ. `/` icin verilen ELEME kararinin birebir aynisi.
    """
    if value is None:
        return None
    if not _URL_SAFE_KEY.fullmatch(value):
        return None
    return None if set(value) == {"."} else value


def ref_filter(
    id_column: InstrumentedAttribute[uuid.UUID],
    key_column: InstrumentedAttribute[str | None],
    ref: uuid.UUID | str,
) -> ColumnElement[bool]:
    """`parse_ref` ciktisini SQL suzgecine cevirir (UUID -> kimlik, metin -> anahtar).

    🔴 `or_` DEGIL, SECIM: iki kolonu `OR` ile birlestirmek UUID metnini anahtar
    kolonuyla da karsilastirirdi; anahtar `String` oldugu icin Postgres bunu
    kabul eder ve indeks kullanilamaz hale gelirdi.

    🔴 Secimin MESRULUGU `parse_ref`in KANONIKLIK SINAVINDAN gelir, "iki uzay
    kesismez"den DEGIL — o iddia olculerek CURUTULDU (bkz. `parse_ref`).
    `parse_ref` yalnizca kanonik 8-4-4-4-12 biciminde UUID dondurdugu icin,
    UUID dalina dusen bir deger ASLA bir slug olamaz; tersi de gecerlidir.
    """
    if isinstance(ref, uuid.UUID):
        return id_column == ref
    return key_column == ref


def composite_slug(parent_slug: str | None, suffix: object) -> str | None:
    """Bilesik slug tabani: `<ust-slug>-<ek>` — EK HER ZAMAN HAYATTA KALIR.

    URL-4'un uc bilesik anahtarli rotasi (isveren hakedisi, taseron hakedisi)
    slug'ini `<ust-slug>-<sira>` olarak URETIP SAKLAR. Naif kurulum
    (`f"{parent}-{seq}"` -> `slugify`) bir tuzak tasir ve OLCULDU:

        slugify("a"*120 + " 48")  ->  "aaa…a"  (100 karakter, `-48` YOK)

    `MAX_SLUG_LENGTH` kirpmasi SONDAN kirptigi icin SIRA NUMARASI SESSIZCE
    DUSER — ve o an ayni projenin 1., 2., 48. hakedisi AYNI tabana coker.
    Cakisma `unique_slug` tarafindan `-2`/`-3` ile "cozulur", yani kullanici
    `/hakedisler/aaa…a-2` gibi SIRAYI HIC TASIMAYAN bir URL gorur; kusur
    hicbir yerde patlamaz, yalnizca adres anlamsizlasir.

    Bu yuzden ek once ayrilir, UST SLUG ona gore kirpilir:
    taban = ust[: MAX - len("-" + ek)] + "-" + ek.

    Ust slug `None` ise (adi sluglanamayan proje/sozlesme) sonuc da `None`dur:
    uydurma taban YAZILMAZ (URL-2 karar 5).
    """
    if parent_slug is None:
        return None
    ek = str(suffix)
    tavan = MAX_SLUG_LENGTH - len(ek) - 1
    if tavan <= 0:
        # Ek tek basina tavani dolduruyorsa ust slug'a yer YOKTUR; sessizce
        # ek'siz bir taban dondurmek sirayi kaybetmenin ta kendisi olurdu.
        return slugify(ek)
    return slugify(f"{parent_slug[:tavan].rstrip('-')}-{ek}")
