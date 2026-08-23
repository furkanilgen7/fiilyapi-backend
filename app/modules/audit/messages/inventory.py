"""Denetim metinleri — stok cekirdegi ve stok hareketi (ST T2/T3)."""

# --- Stok çekirdeği (ST T2 — malzeme kartı + depo) ---
#
# Kimlik UUID DEĞİL kullanıcının ekranda gördüğü değerdir: kartta KOD + AD
# (E3 tablosu ikisini üst üste basar), depoda AD. Kategori/birim/eşik
# YAZILMAZ — künye ekranda zaten görünür ve günlük satırını gürültüye boğardı.


def _warehouse_scope(site_name: str | None) -> str:
    """Merkez depo (`site_id IS NULL`) şantiyesizdir ve günlükte de öyle görünür.

    Şantiye adı olmadan "D-1 Ambar silindi" satırı anlamsızdır: aynı ad her
    şantiyede olabilir (`section_created` gerekçesi).
    """
    return "Merkez" if site_name is None else site_name


def stock_item_created(code: str, name: str) -> str:
    return f"Malzeme kartı oluşturuldu: {code} · {name}"


def stock_item_updated(code: str, name: str) -> str:
    """Pasifleştirme de BU satırı yazar (`is_active: false` bir PATCH'tir);
    ayrı bir metin AÇILMAZ çünkü kart silinmez, yalnız kullanımdan kalkar."""
    return f"Malzeme kartı güncellendi: {code} · {name}"


def warehouse_created(site_name: str | None, name: str) -> str:
    return f"Depo oluşturuldu: {_warehouse_scope(site_name)} · {name}"


def warehouse_renamed(site_name: str | None, old_name: str, new_name: str) -> str:
    """Eski ad çağrı noktasında değişiklikten ÖNCE okunmalı (`role_renamed`
    dersi); sonra okunursa günlükte yeni ad iki kez çıkar."""
    return f"Depo yeniden adlandırıldı: {_warehouse_scope(site_name)} · {old_name} → {new_name}"


def warehouse_deleted(site_name: str | None, name: str) -> str:
    """Metin `session.delete`ten ÖNCE kurulur — sonra kurulsaydı ad güvenilir
    okunamaz ve silinenin NE OLDUĞU kaybolurdu (`site_deleted` dersi)."""
    return f"Depo silindi: {_warehouse_scope(site_name)} · {name}"


# --- Stok hareketi (ST T3) ---
#
# GİRİŞ BAŞINA TEK SATIR yazılır, satır başına DEĞİL (spec §4): 40 kalemlik bir
# irsaliye günlüğü boğardı ve kullanıcının aradığı olay "şu irsaliye girildi"dir.

_ENTRY_TYPE_LABELS = {
    "purchase": "Satınalma girişi",
    "transfer": "Şantiye transferi",
    "adjustment": "Manuel düzeltme",
}
"""SG 53-76'nın Türkçe etiketleri — günlükte ham enum değeri görünmez."""


def stock_entry_created(
    entry_type: str,
    warehouse_name: str,
    source_warehouse_name: str | None,
    delivery_note_no: str | None,
) -> str:
    """Kimlik UUID DEĞİL kullanıcının gördüğü değerdir: tip · depo(lar) · irsaliye.

    Transferde KAYNAK depo da yazılır — yalnız hedef yazılsaydı "stok nereden
    çıktı" sorusu günlükten cevaplanamazdı (çift bacağın günlükteki karşılığı).

    Kalem SAYISI verilmez (`SITE_HAS_BLOCKS` dersi): satır adedi künyeden okunur.
    """
    tip = _ENTRY_TYPE_LABELS.get(entry_type, entry_type)
    depo = (
        warehouse_name
        if source_warehouse_name is None
        else (f"{source_warehouse_name} → {warehouse_name}")
    )
    irsaliye = "" if not delivery_note_no else f" · {delivery_note_no}"
    return f"Stok hareketi kaydedildi: {tip} · {depo}{irsaliye}"
