"""Satinalma korkuluklari ve Turkce hata metinleri (SA spec §2, §3, §4).

`inventory/guards.py` deseninin kardesi: hata SINIFLARI `app/core/errors.py`de,
METINLER burada TEK kopya sabit olarak durur; router'a ya da servise gomulu
string YAZILMAZ.

## Hangi kural hangi koda duser (ST §4b kanonu)

| Durum | Kod | Sinif |
|---|---|---|
| Gorunmeyen ya da var olmayan tedarikci/talep | 404 | `NotFoundError` |
| Govdedeki proje/santiye/bolum/malzeme referansi gorunmuyor ya da yok | 404 | `NotFoundError` |
| Bicim/kural ihlali (XOR, miktar, uzunluk, `limit` tavani) | 422 | Pydantic |
| Taslak DISINDA duzenleme/silme | 409 | `ConflictError` |
| Baskasinin taslagini silme (`can_delete` reddi) | 403 | `DeleteNotAllowedError` |

**Kanon tek cumledir (ST T4-artcisi, 2026-08-11 kullanici karari):**
*gorunmez/yok VARLIK referansi = 404 · bicim/kural ihlali = 422.* Bu modulun
UCLARI o kanona ST ile BIREBIR uyar — emsal ayrismasi birakilmaz.

**Durum cakismasi 409'dur, 403 DEGIL** (`progress_payments.INVALID_STATUS_
TRANSITION` deseni): kullanicinin yetkisi VARDIR, engelleyen sey kaydin
DURUMUDUR. Silme reddi ise 403'tur cunku orada engel YETKIDIR.
"""

__all__ = [
    "DELETE_NOT_ALLOWED",
    "REQUEST_MISSING",
    "REQUEST_NOT_DRAFT",
    "REQUEST_PROJECT_INVALID",
    "REQUEST_SECTION_INVALID",
    "REQUEST_SITE_INVALID",
    "REQUEST_STOCK_ITEM_INVALID",
    "SUPPLIER_MISSING",
]

# 404 — tedarikci katalogunda KAPSAM SUZGECI YOKTUR (tabloda `project_id` kolonu
# bile yoktur, spec §2: ayni "Demirsan A.S." her projede kullanilir). Bu yuzden
# "gorunmeyen tedarikci" diye bir durum da yoktur; tek 404 sebebi kaydin
# gercekten olmamasidir. IDOR unutulmus DEGILDIR — sonraki okuyucu buraya proje
# suzgeci EKLEMESIN. (Kartin PARA turevi ise kapsamlidir; bkz. `repository`.)
SUPPLIER_MISSING = "Tedarikçi bulunamadı"

# 404 — gorunmeyen talep ile var olmayan talep AYNI govdeyi alir. 403 verilseydi
# elinde kimlik olan kullanici kaydin var oldugunu ogrenirdi.
REQUEST_MISSING = "Satın alma talebi bulunamadı"

# 404 — govdedeki `project_id` gorunmuyor ya da hic yok. Iki durum AYNI cumleyi
# alir; ayri cumleler kimligin varligini ele verirdi.
REQUEST_PROJECT_INVALID = "Seçilen proje bulunamadı"

# 404 — `site_id` yok, gorunmuyor YA DA talebin projesine ait degil. Ucuncu dal
# da ayni cumleyi alir: baska projenin santiyesi bu talep icin "yok"tur ve
# ayri bir mesaj hangi santiyenin nerede oldugunu ele verirdi.
REQUEST_SITE_INVALID = "Seçilen şantiye bulunamadı"

# 404 — `section_id` yok ya da SECILEN SANTIYEYE ait degil. Bolum santiyenin ic
# kirilimidir (P2 karari): santiyesiz bolum secimi de bu cumleyi alir, cunku
# bolum ancak santiyesiyle birlikte anlamlidir.
REQUEST_SECTION_INVALID = "Seçilen bölüm bulunamadı"

# 404 — kalemdeki `stock_item_id` katalogda YOK (ST'nin `ENTRY_ITEM_INVALID`
# kardesi). Metin KAC satirin ya da HANGI kimligin hatali oldugunu SOYLEMEZ:
# kimlik sizdirmaz ve eyleme donuktur (`SITE_HAS_BLOCKS` dersi).
REQUEST_STOCK_ITEM_INVALID = "Seçilen malzeme kartı bulunamadı"

# 409 — taslak disinda duzenleme/silme. Onaya gonderilmis bir talebin kalemi
# degistirilebilseydi ONAY EDILEN SEY ile SIPARIS EDILEN SEY ayrisirdi (esik
# atlatmanin da en kisa yolu budur: dusuk tutarla onaylat, sonra sisir).
REQUEST_NOT_DRAFT = "Yalnızca taslak talep düzenlenebilir veya silinebilir"

# 403 — `can_delete` (`app/core/access.py`) reddi: `admin` her seyi siler, aksi
# halde yalniz talebi ACAN aktor kendi TASLAGINI siler. `full` silmeyi
# KAPSAMAZ (spec §5.0), yani satinalma sorumlusu bile bir baskasinin taslagini
# dusuremez.
DELETE_NOT_ALLOWED = "Bu talebi silme yetkiniz yok"
