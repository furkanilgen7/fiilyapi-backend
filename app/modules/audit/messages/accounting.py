"""Denetim metinleri — muhasebe: hesap plani, yevmiye fisi (MU-1) + donem (MU-2)."""

from datetime import date

# --- MU-1 T3a: hesap planı kaydı ---
#
# Kimlik İKİ parçalıdır: KOD (kaydın gerçek kimliği, HP:58) + AD (HP:59). Hesap
# UUID'si metne girmez — denetim tablosunda kimse UUID okumaz; kod ile ad
# birlikte satırı zaten ayırt eder.
#
# 🔴 **BAKİYE metne GİRMEZ.** Bakiye SAKLANMAZ, TÜRETİLİR (MU-1 K3); günlüğe
# donmuş bir kopyası düşseydi ilk fişte ayrışır ve iki sayı yan yana yaşardı
# (`bank_account_*` kanonunun aynısı). Repoda hiçbir denetim metni para taşımaz.
#
# 🔴 YENİ `AuditAction` ÜYESİ AÇILMADI (TB3/T3 kanonu): `create`/`update`/
# `delete` kullanılır, ayrım METİNDEDİR.


def chart_account_label(code: str, name: str) -> str:
    """Üç denetim metninin TEK kimlik kaynağı.

    Ayrı ayrı kurulsalardı biri kodu unutur ve aynı adı taşıyan iki hesap
    (`100 Kasa` / `101 Kasa`) günlükte ayırt edilemezdi.
    """
    return f"{code} · {name}"


def chart_account_created(code: str, name: str) -> str:
    return f"Hesap oluşturuldu: {chart_account_label(code, name)}"


def chart_account_updated(code: str, name: str) -> str:
    """Metin GÜNCELLENMİŞ değerlerle kurulur: kullanıcı adı ya da kodu
    düzelttiyse günlükte yeni değer durmalıdır, yoksa satır neyin ne olduğunu
    anlatmaz."""
    return f"Hesap güncellendi: {chart_account_label(code, name)}"


def chart_account_deleted(code: str, name: str) -> str:
    """Metin `session.delete`ten ÖNCE kurulur — sonra kurulsaydı kod ve ad
    güvenilir okunamazdı (`invoice_deleted` dersi)."""
    return f"Hesap silindi: {chart_account_label(code, name)}"


# --- MU-1 T3b: yevmiye fişi ---
#
# 🔴 Kimlik TARİH + AÇIKLAMADIR — burada, denetim metninde. Fiş artık bir
# `entry_no`ya SAHİPTİR (FIS-NO, kullanıcı kararı 2026-08-21, bkz.
# `accounting/models.JournalEntry` sınıf docstring'i); ama bu dilim denetim
# metnini DEĞİŞTİRMEDİ — kapsam bilinçli olarak `entry_no` + `numbering.py`
# ile SINIRLIDIR. Yani `journal_entry_label` hâlâ tarih + açıklama kurar ve
# numarayı TAŞIMAZ; bu bir unutma değil, açık bir borçtur (numarayı denetim
# metnine eklemek FIS-NO'nun kapsamı dışında ayrı bir karar gerektirir).
# Kimlik teknik olarak `id`dir ama denetim tablosunda kimse UUID okumaz —
# tarih ile açıklama birlikte satırı ayırt eder.
#
# 🔴 **TUTAR METNE GİRMEZ** (HZ-1 kanonu, `bank_account_*`/`chart_account_*` ile
# aynı gerekçe): fişin toplamı bir satır düzeltmesiyle değişir ve günlüğe donmuş
# bir kopyası düşseydi iki sayı yan yana yaşardı. Repoda hiçbir denetim metni
# para taşımaz.
#
# 🔴 YENİ `AuditAction` ÜYESİ AÇILMADI (TB3/T3 kanonu): `action` gerçek bir
# Postgres enum tipidir ve yeni üye MIGRATION ister. `post` mevcut `approve`
# üyesine oturur (kayıtlaştırma bir ONAYDIR: fişi mali ize sokar ve geri
# alınamaz), `reverse` `update`e. Ayrım METİNDEDİR.


def journal_entry_label(entry_date: date, description: str) -> str:
    """Beş denetim metninin TEK kimlik kaynağı.

    Ayrı ayrı kurulsalardı biri tarihi unutur ve aynı açıklamayı taşıyan iki fiş
    (`Kasa tahsilatı`, her ay) günlükte ayırt edilemezdi.

    Tarih `date` nesnesinin kendi ISO gösterimidir (`leave_request_*` emsali):
    `strftime` çağrılmaz — biçim tek yerde, `DISPLAY_TIMESTAMP_FORMAT`ta durur ve
    o yalnız `timestamptz` içindir; `entry_date` zaten TAKVİM günüdür, saat
    dilimi çevirimi GEREKTİRMEZ (K6).
    """
    return f"{entry_date} · {description}"


def journal_entry_created(entry_date: date, description: str) -> str:
    return f"Yevmiye fişi oluşturuldu: {journal_entry_label(entry_date, description)}"


def journal_entry_updated(entry_date: date, description: str) -> str:
    """Metin GÜNCELLENMİŞ değerlerle kurulur: kullanıcı tarihi ya da açıklamayı
    düzelttiyse günlükte yeni değer durmalıdır."""
    return f"Yevmiye fişi güncellendi: {journal_entry_label(entry_date, description)}"


def journal_entry_lines_replaced(entry_date: date, description: str) -> str:
    """Satır kümesi TOPTAN yazılır; kaç satır olduğu metne GİRMEZ — sayı da
    tutar gibi kaydın kendisinden okunur ve günlükte bayatlardı."""
    return f"Yevmiye fişi satırları güncellendi: {journal_entry_label(entry_date, description)}"


def journal_entry_deleted(entry_date: date, description: str) -> str:
    """Metin `session.delete`ten ÖNCE kurulur — sonra kurulsaydı tarih ve
    açıklama güvenilir okunamaz ve silinenin NE OLDUĞU kaybolurdu."""
    return f"Yevmiye fişi silindi: {journal_entry_label(entry_date, description)}"


def journal_entry_posted(entry_date: date, description: str) -> str:
    """`AuditAction.approve` ile yazılır; ayrım BU METİNDEDİR."""
    return f"Yevmiye fişi kayıtlaştırıldı: {journal_entry_label(entry_date, description)}"


def journal_entry_reversed(entry_date: date, description: str) -> str:
    """`AuditAction.update` ile yazılır. Metin ORİJİNAL fişin kimliğinden
    kurulur: denetim satırı "hangi fişe ne oldu" sorusuna yanıt verir, stornonun
    kendi doğuşu orijinalin `reversed` olmasıyla zaten anlatılır."""
    return f"Yevmiye fişi ters kaydedildi: {journal_entry_label(entry_date, description)}"


# --------------------------------------------------------------------------- #
# MU-2 — MUHASEBE DÖNEMİ (kapat / aç)
#
# 🔴 YENİ `AuditAction` ÜYESİ AÇILMADI (TB3/T3 kanonu): `action` gerçek bir
# Postgres enum tipidir ve yeni üye MIGRATION ister. Kapatma mevcut `approve`
# üyesine oturur (bir ONAYDIR: dönemi mali ize kilitler), açma `update`e.
# Ayrım METİNDEDİR — iki eylem günlükte YALNIZCA bu cümlelerle ayrılır.
#
# Dönemin toplamları/mizanı metne GİRMEZ (HZ-1 kanonu, `journal_entry_*` ile
# aynı gerekçe): türev sayılar sonradan değişir ve günlüğe donmuş bir kopyası
# düşseydi iki sayı yan yana yaşardı.
# --------------------------------------------------------------------------- #


def accounting_period_label(year: int, month: int) -> str:
    """İki denetim metninin TEK kimlik kaynağı — biçim `YYYY/AA`.

    Ay SIFIR DOLGULUDUR: `2026/7` ile `2026/12` yan yana sıralandığında metin
    sıralaması takvim sırasından ayrışırdı.
    """
    return f"{year}/{month:02d}"


def accounting_period_closed(year: int, month: int) -> str:
    """`AuditAction.approve` ile yazılır; ayrım BU METİNDEDİR."""
    return f"Muhasebe dönemi kapatıldı: {accounting_period_label(year, month)}"


def accounting_period_reopened(year: int, month: int) -> str:
    """`AuditAction.update` ile yazılır.

    "Yeniden açıldı" AYRI BİR DURUM DEĞİLDİR (`AccountingPeriodStatus` iki
    değerlidir) ve tabloda `reopened_at` kolonu YOKTUR — kim ne zaman açtı
    sorusunun yeri TAM OLARAK burasıdır.
    """
    return f"Muhasebe dönemi yeniden açıldı: {accounting_period_label(year, month)}"
