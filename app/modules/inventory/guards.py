"""Stok çekirdeği korkulukları ve Türkçe hata metinleri (spec §2, §4, §7 S2).

`documents/guards.py` deseninin kardeşi: hata SINIFLARI `app/core/errors.py`de,
METİNLER burada TEK kopya sabit olarak durur; router'a ya da servise gömülü
string YAZILMAZ.

## Hangi kural hangi koda düşer

| Durum | Kod | Sınıf |
|---|---|---|
| Görünmeyen ya da var olmayan kart/depo | 404 | `NotFoundError` |
| Kayıtlı malzeme kodu / aynı kapsamda aynı depo adı | 409 | `DuplicateError` |
| Hareketi olan depoyu silme | 409 | `RelatedRecordsExistError` |
| Gövdedeki `site_id` görünmüyor ya da yok | 422 | `SiteValidationError` |

**Kapsam uyumsuzluğu 422'dir, 404 DEĞİL** (`documents.SITE_NOT_IN_PROJECT`
gerekçesi): istenen kaynak DEPO KOLEKSİYONUDUR; `site_id` gövdedeki
düzeltilebilir bir ALAN DEĞERİDİR. Var OLMAYAN kimlik ile GÖRÜNMEYEN kimlik AYNI
cümleyi alır — kimlik varlığı sızdırılmaz.

**Hareketi olan depo 409'dur, 403 DEĞİL** (`documents.FOLDER_HAS_DOCUMENTS`
deseni): kullanıcının yetkisi VARDIR, engelleyen şey kaydın DURUMUDUR.
"""

__all__ = [
    "DUPLICATE_STOCK_ITEM_CODE",
    "ENTRY_BOQ_ITEM_INVALID",
    "ENTRY_BOQ_ITEM_SITE_MISMATCH",
    "ENTRY_ITEM_INVALID",
    "ENTRY_RECEIVER_INVALID",
    "ENTRY_SECTION_BOQ_SITE_MISMATCH",
    "ENTRY_SECTION_INVALID",
    "ENTRY_SECTION_SITE_MISMATCH",
    "SECTION_MISSING",
    "SITE_MISSING",
    "DUPLICATE_WAREHOUSE_NAME",
    "STOCK_ITEM_MISSING",
    "WAREHOUSE_HAS_ENTRIES",
    "WAREHOUSE_MISSING",
    "WAREHOUSE_SITE_INVALID",
]

# 404 — var olmayan malzeme kartı. Katalogda kapsam süzgeci YOKTUR (spec §2:
# tabloda `project_id` kolonu bile yok), bu yüzden "görünmeyen kart" diye bir
# durum da yoktur; tek 404 sebebi kaydın gerçekten olmamasıdır.
STOCK_ITEM_MISSING = "Malzeme kartı bulunamadı"

# 409 — `stock_items.code` GLOBAL tekildir (spec §2). Kontrol UYGULAMA
# katmanındadır: DB `UNIQUE`ına düşülseydi kullanıcı alanına özel bir mesaj
# yerine "Veri bütünlüğü hatası" görürdü. DB kısıtı yarış durumu için İKİNCİ
# katman olarak KALIR (`IntegrityError` → 409).
DUPLICATE_STOCK_ITEM_CODE = "Bu malzeme kodu zaten kayıtlı"

# 404 — görünmeyen depo ile var olmayan kimlik AYNI gövdeyi alır.
WAREHOUSE_MISSING = "Depo bulunamadı"

# 409 — aynı kapsamda (şantiye VEYA merkez) aynı ad.
#
# ⚠️ T1'den DEVREDİLEN SINIR: `uq_warehouses_site_name` Postgres'in varsayılan
# `NULLS DISTINCT` semantiği yüzünden `site_id IS NULL` olduğunda (MERKEZ depo)
# FİİLEN ÇALIŞMAZ — `document_folders` ile birebir aynı durum. Yani DB yalnız
# ŞANTİYELİ depoları korur; merkez dalında tek savunma servis korkuluğudur
# (`service._assert_warehouse_name_free`). Korunmayan dalda eşzamanlı iki istek
# çift kayıt üretebilir — bilinen ve kabul edilen sınır; kapatmak kısmi tekil
# indeks açan bir migration gerektirir (T1'de kapsam dışı bırakıldı).
DUPLICATE_WAREHOUSE_NAME = "Bu kapsamda aynı adlı bir depo zaten var"

# 409 — silme korkuluğu. Hedef bacak (`warehouse_id`) ve KAYNAK bacak
# (`source_warehouse_id`) AYNI kuralı paylaşır: yalnız hedefe bakılsaydı bir
# transferin çıktığı depo silinebilir ve hareketin nereden geldiği kaybolurdu.
# Metin ADET VERMEZ (`SITE_HAS_BLOCKS` dersi).
WAREHOUSE_HAS_ENTRIES = "Bu depoda stok hareketi var, hareketi olan depo silinemez"

# 404 — gövdedeki `site_id` görünmüyor ya da hiç yok. İki durum AYNI cümleyi
# alır; ayrı cümleler kimliğin varlığını ele verirdi.
#
# ⚠️ T4-artçı (2026-08-11, kullanıcı kararı — spec'e EK): bu sabit önce 422
# üretiyordu. Repo kuralı tek cümleye bağlandı:
#     görünmez/yok VARLIK referansı = 404 · biçim/kural ihlali = 422.
# Böylece `POST /warehouses`in `site_id`i ile `POST /stock/entries`in
# `warehouse_id`i AYNI kodu döndürür (emsal ayrışması bırakılmadı).
WAREHOUSE_SITE_INVALID = "Seçilen şantiye bulunamadı"


# --- Hareket uçları (T3) ---

# 404 — satırdaki `item_id` kataloğda YOK. Kart kataloğunda kapsam süzgeci
# olmadığı için (spec §2) "görünmeyen kart" durumu yoktur: tek sebep kaydın
# gerçekten olmamasıdır.
#
# ⚠️ T4-artçı (2026-08-11, kullanıcı kararı — spec'e EK): önce 422'ydi.
# `WAREHOUSE_SITE_INVALID` ile AYNI gerekçeyi paylaşmaya devam eder, ama artık
# ortak kural şudur: **gövde içi VARLIK referansı = 404 · biçim/kural ihlali =
# 422.** Satır içinde durması bunu değiştirmez — referans yine bir varlığadır.
#
# Metin KAÇ satırın ya da HANGİ kimliğin hatalı olduğunu SÖYLEMEZ: kimlik
# sızdırmaz ve eyleme dönüktür (`SITE_HAS_BLOCKS` dersi).
ENTRY_ITEM_INVALID = "Seçilen malzeme kartı bulunamadı"

# 404 — SG 88 "Teslim Alan" kullanıcısı yok (aynı kural, T4-artçı).
ENTRY_RECEIVER_INVALID = "Seçilen teslim alan kullanıcı bulunamadı"

# 404 — `GET /sites/{id}/stock`: görünmeyen şantiye ile var olmayan şantiye AYNI
# gövdeyi alır (`sites` modülünün tek cümlesiyle aynı metin).
SITE_MISSING = "Şantiye bulunamadı"


# --- Bolum / poz atfi (STOK-BOLUM) ---

# 404 — satirdaki `section_id` yok ya da GORUNMUYOR. Ayni cumle: kimlik
# varligi sizdirilmaz (T4-artci kurali: govde ici VARLIK referansi = 404).
ENTRY_SECTION_INVALID = "Seçilen bölüm bulunamadı"

# 404 — satirdaki `boq_item_id` yok ya da gorunmuyor (ayni kural).
ENTRY_BOQ_ITEM_INVALID = "Seçilen iş kalemi bulunamadı"

# 🔴 422 — TUTARLILIK KAPISI: bolum, hareketin deposunun SANTIYESINE ait degil.
#
# Neden 404 DEGIL: bolum VARDIR ve gorunurdur; ihlal edilen sey iki alan
# ARASINDAKI ILISKIDIR, yani govdenin duzeltilebilir bir KURAL ihlalidir
# (`WAREHOUSE_SITE_INVALID`in tersi durum: orada referans EDILEN varlik
# bulunamiyordu, burada bulunuyor ama yanlis yere baglaniyor).
#
# Neden DB CHECK DEGIL: kural `warehouses.site_id` ile `sections.site_id`yi
# karsilastirir — IKI AYRI TABLO. Postgres CHECK'i baska tabloyu okuyamaz;
# kanon "sozlesme kisiti tipte yasamaz"in kardesi: cok tablolu kisit da
# SEMADA yasamaz, SERVIS katmanindadir.
#
# FAIL-CLOSED: eslesmeyen bolum REDDEDILIR. Gecirmek, A1'e baska santiyenin
# deposundan sarf yazilmasi demekti — veri bozuklugu.
ENTRY_SECTION_SITE_MISMATCH = "Seçilen bölüm, hareketin deposunun şantiyesine ait değil"

# 422 — poz, hareketin deposunun santiyesine ait degil (ayni gerekce).
ENTRY_BOQ_ITEM_SITE_MISMATCH = "Seçilen iş kalemi, hareketin deposunun şantiyesine ait değil"

# 🔴 422 — bolum ile poz AYNI santiyede degil.
#
# Bu kapi MERKEZ DEPO icin TEK savunmadir: merkez deponun `site_id`si NULL'dur,
# yani yukaridaki iki kapinin karsilastiracagi bir capa yoktur. Ikisi birden
# verildiginde birbirlerine capa olurlar.
ENTRY_SECTION_BOQ_SITE_MISMATCH = "Seçilen bölüm ile iş kalemi aynı şantiyeye ait değil"

# 404 — `GET /sections/{id}/stock`: gorunmeyen bolum ile var olmayan bolum AYNI
# govdeyi alir.
SECTION_MISSING = "Bölüm bulunamadı"
