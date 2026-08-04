"""Belge arşivi korkulukları ve Türkçe hata metinleri (spec §2, §3).

`site_planning/guards.py` deseninin kardeşi: metinler TEK yerde durur, router'a
ya da servise gömülü string YAZILMAZ.

`sites` modülünün "bulunamadı" cümleleri KOPYALANMAZ, İMPORT edilir: belge ucu
görünmeyen bir proje/şantiye için `sites` ucundan FARKLI bir cümle dönerse,
elinde bir UUID olan kullanıcı iki uç arasındaki farktan kaydın var olduğunu
çıkarabilir.

## Hangi kural hangi koda düşer

| Durum | Kod | Sınıf |
|---|---|---|
| Görünmeyen ya da var olmayan proje/klasör | 404 | `NotFoundError` |
| Aynı kapsamda aynı ad | 409 | `DuplicateError` |
| Dolu klasörü silme | 409 | `RelatedRecordsExistError` |
| `site_id`/`parent_id` kapsam dışı | 422 | `DocumentValidationError` |

**Dolu klasör 409'dur, 403 DEĞİL** (`sites.SITE_HAS_SECTIONS` deseninin
birebiri): kullanıcının yetkisi VARDIR, engelleyen şey kaydın DURUMUDUR. 403
verilseydi ekran "yetkin yok" der ve kullanıcı içeriği boşaltarak sorunu
çözebileceğini asla anlayamazdı. Metin bu yüzden EYLEME DÖNÜKTÜR ve ADET
VERMEZ (`SITE_HAS_BLOCKS` dersi: sayıyı kullanıcı zaten listede görüyor).

**Kapsam uyumsuzluğu 422'dir, 404 DEĞİL:** istenen kaynak PROJEDİR; `site_id` ve
`parent_id` gövdedeki düzeltilebilir ALAN DEĞERLERİDİR (`sites.USER_NOT_FOUND`
gerekçesi). Var OLMAYAN kimlik ile BAŞKA kapsamın kimliği AYNI cümleyi alır —
kimlik varlığı sızdırılmaz.
"""

from app.modules.sites.guards import PROJECT_MISSING, SITE_MISSING

__all__ = [
    "FOLDER_HAS_CHILDREN",
    "FOLDER_HAS_DOCUMENTS",
    "FOLDER_MISSING",
    "PARENT_SCOPE_MISMATCH",
    "PROJECT_MISSING",
    "SITE_MISSING",
    "SITE_NOT_IN_PROJECT",
    "DUPLICATE_FOLDER_NAME",
]

# 404 — görünmeyen klasör ile var olmayan kimlik AYNI gövdeyi alır.
FOLDER_MISSING = "Klasör bulunamadı"

# 409 — aynı kapsamda (proje + şantiye + üst klasör) aynı ad.
#
# ⚠️ T1'den DEVREDİLEN SINIR (T2'de ÖLÇÜLDÜ): `uq_document_folder_scope_name`
# Postgres'in varsayılan `NULLS DISTINCT` semantiği yüzünden `site_id` VEYA
# `parent_id`den HERHANGİ BİRİ NULL olduğunda FİİLEN ÇALIŞMAZ. Yani kısıt yalnız
# ŞANTİYE KAPSAMLI ALT KLASÖRLERDE (ikisi de dolu) koruma sağlar; proje düzeyi
# klasörler, şantiye kök klasörleri ve proje düzeyi alt klasörler KORUMASIZDIR.
# Tekilliği bu dallarda DB değil yazma ucundaki açık kontrol tutar; DB kısıtı
# yalnız dört alanın da dolu olduğu dalda yarış durumu için ikinci katmandır
# (`IntegrityError` → 409).
DUPLICATE_FOLDER_NAME = "Bu kapsamda aynı adlı bir klasör zaten var"

# 422 — gövdedeki `site_id` bu projenin şantiyesi değil (ya da hiç yok).
SITE_NOT_IN_PROJECT = "Seçilen şantiye bu projeye ait değil"

# 422 — üst klasör başka bir kapsamda (başka proje ya da başka şantiye/düzey).
# Kabul edilseydi şantiye klasörü proje düzeyi bir ağaca asılır ve E12 kökü ile
# şantiye sekmesi AYNI kaydı iki farklı yerde gösterirdi.
PARENT_SCOPE_MISMATCH = "Üst klasör bu kapsamda değil"

# 409 — silme korkulukları. Sıra sabittir ve İLK ENGELDE DURUR.
FOLDER_HAS_DOCUMENTS = "Bu klasörde belge var, önce belgeleri silin"
FOLDER_HAS_CHILDREN = "Bu klasörde alt klasör var, önce alt klasörleri silin"
