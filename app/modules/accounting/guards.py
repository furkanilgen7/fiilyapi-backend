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
    "ENTRY_ALREADY_REVERSED",
    "INVALID_TRANSITION",
    "JOURNAL_ENTRY_MISSING",
    "JOURNAL_ENTRY_NOT_DELETABLE",
    "JOURNAL_ENTRY_NOT_EDITABLE",
    "LINE_ACCOUNT_MISSING",
    "LINE_SINGLE_SIDE",
    "PARENT_HAS_JOURNAL_LINES",
    "PERIOD_ALREADY_CLOSED",
    "PERIOD_ALREADY_OPEN",
    "PERIOD_CLOSED",
    "PERIOD_HAS_DRAFT_ENTRIES",
    "PERIOD_MOVED",
    "PERIOD_PREVIOUS_OPEN",
    "PERMISSION_MODULE",
    "REVERSAL_NOT_REVERSIBLE",
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

# 404 — var olmayan fiş. Hesap planı gibi yevmiye de ŞİRKET GENELİDİR (spec §3):
# üç tabloda da `project_id`/`site_id` yoktur, dolayısıyla "görünmeyen fiş" hâli
# yapısal olarak yoktur; 404 yalnız var OLMAYAN kimlik içindir.
JOURNAL_ENTRY_MISSING = "Fiş bulunamadı"

# 404 — 🔴 ST kanonu: GÖVDE İÇİ varlık referansı 404'tür, 422 DEĞİL. Satırdaki
# `account_id` bir biçim hatası değil, var olmayan bir KAYDA işaret eder.
LINE_ACCOUNT_MISSING = "Fiş satırındaki hesap bulunamadı"

# 409 — K2 matrisinde olmayan her çift. 🔴 403 DEĞİL: kullanıcının yetkisi
# VARDIR, engelleyen şey kaydın DURUMUDUR. "Tanımlı olanı say, gerisini reddet":
# ileride yeni bir durum eklenirse varsayılan davranış REDDETMEKTİR.
INVALID_TRANSITION = "Fiş bu işlem için uygun durumda değil"

# 409 — `posted`/`reversed` fişte PATCH ya da `PUT lines`. Mali iz kanonu:
# kayıtlaştırılmış fiş DEĞİŞMEZ, yalnız ters kaydıyla nötrlenir.
# 🔴 R5: "posted fişin satırı UPDATE edilemez" DB'de ZORLANAMAZ (repo hiçbir
# yerde trigger kullanmıyor); iddia yalnız bu kapı ayakta durduğu sürece doğrudur.
JOURNAL_ENTRY_NOT_EDITABLE = "Kayıtlı fiş düzenlenemez"

# 409 — silinebilir tek durum `draft`tır. YETKİ kapısı (`admin`) AYRIDIR ve
# router'dadır: tek yerde toplansalardı "yetkiniz yok" cümlesi bir DURUM
# engelinden dönerdi.
JOURNAL_ENTRY_NOT_DELETABLE = "Yalnızca taslak fiş silinebilir"

# 409 — `uq_journal_entries_reversal_of`un SERVİS karşılığı. Kapı UNIQUE'e
# DÜŞMEDEN önce koşar ki kullanıcı ayrımsız bir "Veri bütünlüğü hatası" yerine
# ne olduğunu söyleyen bir cümle alsın. UQ yarış durumu emniyet ağı olarak KALIR.
ENTRY_ALREADY_REVERSED = "Bu fişin ters kaydı zaten var"

# 409 — stornonun stornosu. Sonsuz bir zincir açardı ve mali anlamı yoktur:
# bir ters kaydı iptal etmenin yolu orijinali yeniden girmektir.
REVERSAL_NOT_REVERSIBLE = "Ters kayıt fişi terslenemez"

# 422 — `ck_journal_lines_single_side`in ŞEMA karşılığı (`code` deseninin DB
# CHECK'i ile şemada birlikte durmasının aynısı). E8'in her satırının boş tarafı
# HEP `—`dir. Şemada yakalanmasaydı `(0,0)` satırı `len(lines) >= 2` engelini
# SAHTE biçimde geçirir, çift dolu satır ise DB CHECK'ine düşüp kullanıcıya
# ayrımsız bir 409 gösterirdi. DB kısıtı SON savunma olarak yerinde KALIR.
LINE_SINGLE_SIDE = "Fiş satırı ya borç ya alacak taşır; ikisi birden ya da ikisi de boş olamaz"

# --------------------------------------------------------------------------- #
# MU-2 T3 (dönem kilidi) metinleri
# --------------------------------------------------------------------------- #

# 409 — 🔴 KAPALI DÖNEM YAZMAYA KAPALIDIR. Bu cümle ALTI giriş noktasının
# HEPSİNDE aynı yerden okunur (`periods_service.assert_periods_open`); altıya
# kopyalansaydı biri bir gün güncellenmez ve o yol kapıyı SESSİZCE atlardı
# (BC dersi: "alanın TÜM giriş noktaları aynı sabitten okur").
# 403 DEĞİL: kullanıcının yetkisi VARDIR, engelleyen şey DÖNEMİN durumudur.
PERIOD_CLOSED = "Bu dönem kapalı; fiş eklenemez, değiştirilemez, silinemez"

# 409 — zaten kapalı bir dönemi kapatmak. Sessizce başarı dönseydi kullanıcı
# `closed_at` damgasının GÜNCELLENDİĞİNİ sanırdı; damga İLK kapanışındır.
PERIOD_ALREADY_CLOSED = "Bu dönem zaten kapalı"

# 409 — zaten açık (ya da hiç kaydı olmayan) bir dönemi açmak. Kayıt YOKSA
# dönem AÇIK sayılır (proaktif 12 ay satırı açılmaz — YAGNI), dolayısıyla
# "aç" isteği aynı 409'a düşer.
PERIOD_ALREADY_OPEN = "Bu dönem zaten açık"

# 409 — dönemde `draft` fiş varken kapanış. Dengesiz/eksik kayıt kapanışa
# GİRMEZ: kapatılırsa taslak ne kayıtlaştırılabilir ne silinebilir hâle gelir
# (ikisi de yasağın kapsamındadır) ve dönem sonsuza dek yarım kalırdı.
# 🔴 `posted`/`reversed` fiş ENGEL DEĞİLDİR — kapanışın amacı tam olarak onları
# DONDURMAKTIR; engel sayılsalardı hiçbir dönem asla kapanamazdı.
PERIOD_HAS_DRAFT_ENTRIES = "Bu dönemde taslak fiş var; dönem kapatılamaz"

# 409 — yarış emniyet ağı: fişin dönemi, kilitsiz bakış ile kilitli okuma
# ARASINDA değişti (eşzamanlı bir `PATCH entry_date`). Kilit sırası gereği
# dönem satırı fişten ÖNCE kilitlenir, dolayısıyla bakıştaki dönem kilitlenmiş
# olur; buna rağmen fiş başka bir döneme kaymışsa elimizdeki kilit YANLIŞ
# satırdadır ve karar veremeyiz. Kullanıcı isteği yineler.
PERIOD_MOVED = "Fişin dönemi değişti; lütfen tekrar deneyin"

# 409 — SIRA-B: kapanışın ÜÇÜNCÜ ön koşulu, KRONOLOJİK SIRA. `PERIOD_ALREADY_CLOSED`
# ve `PERIOD_HAS_DRAFT_ENTRIES` ile AYNI SINIFTIR (409, `ConflictError`): kullanıcının
# yetkisi vardır, biçimi de doğrudur — engelleyen şey DEFTERİN DURUMUDUR. 422 olsaydı
# istemci onu bir alan hatası sanır ve forma iliştirecek bir alan arardı.
#
# 🔴 Metin ENGELLEYEN DÖNEMİ ADIYLA söyler. Genel bir "dönemler sırayla kapatılır"
# cümlesi, kullanıcıyı on iki dönemlik listede hangi ayın açık kaldığını aramaya
# zorlardı; engel her zaman TEK ve BİLİNEN bir aydır, söylememek için sebep yok.
PERIOD_PREVIOUS_OPEN = (
    "Önceki dönem ({yil}/{ay:02d}) hâlâ açık; dönemler kronolojik sırayla kapatılır"
)


def period_previous_open(year: int, month: int) -> str:
    """`PERIOD_PREVIOUS_OPEN`u ENGELLEYEN dönemle doldurur — TEK kurulum noktası.

    Şablon iki yerde (servis + test) ayrı ayrı `format` edilseydi biri gün gelip
    `{ay}`ı sıfır dolgusuz basar ve aynı kuralın iki farklı yüzü doğardı; bu
    dosyanın modül docstring'indeki "METİNLER TEK kopya" kuralının aynısıdır.
    """
    return PERIOD_PREVIOUS_OPEN.format(yil=year, ay=month)
