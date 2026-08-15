"""Muhasebe korkulukları ve Türkçe hata metinleri (MU-1 spec §5, §7).

`invoicing/guards.py` deseninin kardeşi: hata SINIFLARI `app/core/errors.py`de,
METİNLER burada **TEK kopya** sabit olarak durur; router'a ya da servise gömülü
string YAZILMAZ. Aynı cümle iki yerde kurulsaydı biri düzeltilir, öteki kalır ve
kullanıcı aynı kuralın iki farklı adını görürdü.

## Hangi kural hangi koda düşer (ST §4b kanonu)

| Durum | Kod | Sınıf |
|---|---|---|
| Görünmeyen ya da var olmayan hesap/fiş | 404 | `NotFoundError` |
| Gövdedeki hesap referansı yok | 404 | `NotFoundError` |
| Biçim ihlali (kod deseni, uzunluk, `limit` tavanı, türev alan) | 422 | Pydantic |
| Alanlar-arası kural (denge, yaprak hesap) | 422 | T3b `validation.py` |
| Aynı hesap kodu | 409 | `DuplicateError` |
| Düzenlemeye kapalı DURUM / geçmişi kaydıracak değişiklik | 409 | `ConflictError` |
| Bağlı yevmiye satırı ya da alt hesap | 409 | `RelatedRecordsExistError` |

**Kanon tek cümledir:** *görünmez/yok VARLIK referansı = 404 · biçim/kural
ihlali = 422.* Durum çakışması 409'dur, 403 DEĞİL: kullanıcının yetkisi VARDIR,
engelleyen şey kaydın DURUMU ya da geçmişidir.
"""

__all__ = [
    "ACCOUNT_CODE_LOCKED",
    "ACCOUNT_DUPLICATE_CODE",
    "ACCOUNT_HAS_CHILDREN",
    "ACCOUNT_HAS_JOURNAL_LINES",
    "ACCOUNT_MISSING",
    "PARENT_HAS_JOURNAL_LINES",
    "PERMISSION_MODULE",
    "REVERSAL_PREFIX",
]

PERMISSION_MODULE = "accounting"
"""Spec §2/K8: izin anahtarı seed'de ZATEN vardı ("Muhasebe", grup MALI,
`sort_order: 12`, `roles/seed_data.py:99`) — 🔴 **yeni izin modülü AÇILMAZ,
matris satırına DOKUNULMAZ, izin migration'ı YOKTUR.**

Matris satırı `"accounting": [_A, _F, _N, _N, _N, _F, _V, _N]`, yani kapılar:
* okuma (`view`)  → PM · muhasebe · patron · sysadmin
* yazma (`full`)  → muhasebe · patron · sysadmin (**PM yazamaz**)
* silme (`admin`) → YALNIZ sysadmin — `full` silmeyi KAPSAMAZ (repo kanonu)

Sabit `service`te DEĞİL burada durur (`invoicing.guards` emsali): hem router hem
servis hem testler ona ihtiyaç duyar ve `repository → service` ithalatı ileride
döngüye girebilirdi.
"""

# 404 — var olmayan hesap. Hesap planı ŞİRKET GENELİDİR (spec §3), dolayısıyla
# "görünmeyen hesap" hâli yoktur: izni olan herkes hepsini görür.
ACCOUNT_MISSING = "Hesap bulunamadı"

# 409 — `uq_chart_of_accounts_code`. Servis IntegrityError'a düşmeden ÖNCE açık
# bir SELECT ile bunu fırlatır ki kullanıcı alanına özel Türkçe mesaj alsın
# (R16); UQ yarış durumu emniyet ağı olarak KALIR. Aynı kod iki kez açılsaydı
# yevmiye satırları iki karta bölünür ve bakiye (K3) ikiye ayrılırdı.
ACCOUNT_DUPLICATE_CODE = "Bu hesap kodu zaten kayıtlı"

# 409 — 🔴 K-Ş3 (spec §11): fiş satırı OLAN bir hesabın altına çocuk hesap
# açılamaz. Açılabilseydi `120`e satır atıp sonra `120.01` açmak yaprak kuralını
# (§4c) GEÇMİŞE DÖNÜK deler ve MU-2 mizanı üst hesabın bakiyesini ÇİFT SAYARDI.
# Kural POST ve PATCH yollarının İKİSİNDE de koşar: yalnız POST'ta olsaydı aynı
# delik bir `code` düzeltmesiyle açılırdı.
PARENT_HAS_JOURNAL_LINES = "Üst hesabın yevmiye kaydı var; altına hesap açılamaz"

# 409 — fiş satırı olan hesabın KODU değiştirilemez. Satırlar `account_id` ile
# bağlıdır ama defter, mizan ve tüm raporlar KODU basar; kod değişseydi geçmiş
# yevmiye sessizce başka bir hesaba kaymış gibi görünürdü.
ACCOUNT_CODE_LOCKED = "Yevmiye kaydı olan hesabın kodu değiştirilemez"

# 409 — `journal_lines.account_id` FK RESTRICT'inin servis karşılığı. Sayım FK
# ihlaline DÜŞMEDEN önce koşar: düşseydi kullanıcıya ya ham bir 500 ya da
# `IntegrityError` handler'ının ayrımsız "Veri bütünlüğü hatası" 409'u giderdi.
# CASCADE'e de KAYILMAZ — hesabın silinmesi yevmiye satırlarını yok eder ve
# türetilmiş bakiye KAYDIĞI FARK EDİLMEDEN kayardı. Kaldırma yolu `is_active`tir.
ACCOUNT_HAS_JOURNAL_LINES = "Bu hesaba bağlı yevmiye kayıtları var; hesap silinemez"

# 409 — alt hesabı (ya da torunu) olan hesap silinemez. Hiyerarşi kodun içinde
# taşındığı için (K4) DB'de bir FK yoktur; ebeveyn silinseydi `120.01` sahipsiz
# kalır ve zincir sessizce kopardı.
ACCOUNT_HAS_CHILDREN = "Bu hesabın alt hesapları var; hesap silinemez"

# --------------------------------------------------------------------------- #
# T3b (yevmiye) metinleri
# --------------------------------------------------------------------------- #

REVERSAL_PREFIX = "Ters kayıt: "
"""Storno fişinin açıklamasının öneki (spec §5).

🔴 T3a'da KULLANILMAZ ama BURADA durur: T3b'nin `state_service`i storno
açıklamasını `f"{REVERSAL_PREFIX}{orijinal.description}"` diye kurar. İki yerde
kurulsaydı (ör. bir de arama süzgecinde) ayrışır ve stornolar bir gün ekranda
tanınamaz hâle gelirdi.
"""
