"""Denetim metinleri — personel: belge alt-kaynagi (IK-1 T3) + izin (IK-2 T2/T3).

Izin ONAYI `APPROVAL_ON_BEHALF_MARK` isaretini onay zinciri ailesiyle
PAYLASIR ve `shared`den okur (OK-1A T5 kullanici karari).
"""

from datetime import date
from decimal import Decimal

from app.modules.audit.messages.shared import APPROVAL_ON_BEHALF_MARK


def personnel_created(full_name: str) -> str:
    """Puantaj T2. Personel kartı ACMAK bir `create` olayidir; puantaj kayitlari
    bu karta baglanacagi icin denetim izi kritiktir."""
    return f"Personel eklendi: {full_name}"


def personnel_updated(full_name: str) -> str:
    """Puantaj T2. PASIFLESTIRME de buraya duser: DELETE ucu yoktur, cikarma
    `is_active=false` PATCH'idir ve ayri bir aksiyon acilmaz (spec §3)."""
    return f"Personel güncellendi: {full_name}"


# --- Personel belgeleri (İK-1 T3 — belge alt-kaynağı) ---
#
# Yeni `AuditAction` GEREKMEDI: belge eklemek `create`, künye/BC bağı güncellemek
# `update`, silmek `delete` aksiyonuna oturur. Kimlik UUID DEĞİL insan-okur
# ikilidir: personel adı · belge adı (tip adı ya da serbest etiket). Tarih/durum
# YAZILMAZ — türevdir ve denetim satırına donmuş bir kopyası düşerse ayrışırdı.


def personnel_document_added(full_name: str, label: str) -> str:
    return f"Personel belgesi eklendi: {full_name} · {label}"


def personnel_document_updated(full_name: str, label: str) -> str:
    return f"Personel belgesi güncellendi: {full_name} · {label}"


def personnel_document_deleted(full_name: str, label: str) -> str:
    """Metin `session.delete`ten ÖNCE kurulur (`site_deleted` dersi) — sonra
    kurulsaydı ad/etiket okunamaz ve silinenin NE OLDUĞU kaybolurdu."""
    return f"Personel belgesi silindi: {full_name} · {label}"


# --- İK-2 T2: izin talebi ---
#
# Kimlik kullanicinin GORDUGU degerdir: personel adi · izin tipi · tarih araligi.
# `days` metne KONMAZ — SUNUCU hesabidir (spec §5 K2) ve gunluge donmus bir
# kopyasi tarih duzeltmesinde ayrisirdi; tarih araligi zaten onu belirler.


def leave_request_created(full_name: str, type_name: str, start: date, end: date) -> str:
    return f"İzin talebi oluşturuldu: {full_name} · {type_name} · {start} - {end}"


def leave_request_self_created(full_name: str, type_name: str, start: date, end: date) -> str:
    """İK-2.1 — personelin KENDİ actigi talep. `AuditAction` uyesi ACILMAZ
    (gercek Postgres enum, migration isterdi); self/İK ayrimi METINDEN okunur."""
    return f"Self-servis izin talebi oluşturuldu: {full_name} · {type_name} · {start} - {end}"


def leave_request_updated(full_name: str, type_name: str, start: date, end: date) -> str:
    return f"İzin talebi güncellendi: {full_name} · {type_name} · {start} - {end}"


def leave_request_deleted(full_name: str, type_name: str, start: date, end: date) -> str:
    """Metin `session.delete`ten ONCE kurulur (`site_deleted` dersi) — sonra
    kurulsaydi silinenin NE OLDUGU kaybolurdu."""
    return f"İzin talebi silindi: {full_name} · {type_name} · {start} - {end}"


# --- İK-2 T3: izin onayı/reddi + bakiye ---
#
# Karar metinleri talebin KİMLİĞİNİ (kim · hangi tip · hangi aralık) taşır; red
# ayrıca GEREKÇEYİ taşır — red kararının denetim değeri gerekçesindedir ve talep
# kaydı silinirse (pending değil, ama bakiye turlarında) gerekçe yalnız burada kalır.


def leave_request_approved(
    full_name: str, type_name: str, start: date, end: date, *, on_behalf: bool
) -> str:
    """İzin talebi onayi. `on_behalf` YALNIZ `admin`in KENDI talebinde True olur
    (OK-1A T5, kullanici karari 2026-08-21).

    Isaret `approval_step_approved` ile AYNI sabittir (`APPROVAL_ON_BEHALF_MARK`)
    ve bu bilinclidir: iki ayri metin yazilsaydi denetimde "vekaleten verilmis
    kararlar" tek bir aramayla bulunamazdi. 🔴 Yeni `AuditAction` uyesi ACILMADI —
    ayrim METINDEDIR (T3 kanonu).

    `on_behalf` KEYWORD-ONLY ve ZORUNLUDUR: varsayilani `False` olsaydi yeni bir
    cagiran isareti sessizce DUSURUR ve istisna gunlukte gorunmez olurdu.
    """
    metin = f"İzin talebi onaylandı: {full_name} · {type_name} · {start} - {end}"
    return f"{metin} · {APPROVAL_ON_BEHALF_MARK}" if on_behalf else metin


def leave_request_rejected(
    full_name: str, type_name: str, start: date, end: date, reason: str
) -> str:
    return f"İzin talebi reddedildi: {full_name} · {type_name} · {start} - {end} · {reason}"


def leave_request_withdrawn(full_name: str, type_name: str, start: date, end: date) -> str:
    """İK-2.2 — talebi ACAN kisinin KENDI vazgecmesi. Kayit SILINMEZ, durumu
    `withdrawn` olur; bu yuzden `leave_request_deleted`ten AYRI bir metindir —
    denetimde "geri cekildi" ile "silindi" ayirt edilebilmelidir.

    🔴 Yeni `AuditAction` uyesi ACILMADI (TB3/T3 kanonu, gercek Postgres enum):
    eylem `update`tir (approve/reject ile ayni — ucu de durum gecisidir), ayrim
    BU METINDEDIR."""
    return f"İzin talebi geri çekildi: {full_name} · {type_name} · {start} - {end}"


def leave_balance_updated(full_name: str, year: int, carried_over: Decimal) -> str:
    """Devreden gün MANUEL girilir (İZ 137) — bakiyeyi doğrudan büyüten tek yazma
    yolu budur, bu yüzden yeni değer metne KONUR (denetim onu geri okuyabilsin)."""
    return f"İzin devreden günü güncellendi: {full_name} · {year} · {carried_over}"
