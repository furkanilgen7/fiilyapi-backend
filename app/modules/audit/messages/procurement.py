"""Denetim metinleri — satinalma (SA T2/T3): talep, onay akisi, teklif, siparis."""

# --- Satınalma (SA T2) ---
#
# Kimlik UUID DEĞİL kullanıcının gördüğü değerdir: tedarikçide AD, talepte
# NUMARA (`SAT-2026-0001`). Talep metinlerinde proje adı ya da tutar VERİLMEZ
# (`SITE_HAS_BLOCKS` dersi): numara künyeyi zaten açar, tutar ise türevdir ve
# günlüğe donmuş bir kopyası düşerse kalem değişiminde ayrışırdı.


def supplier_created(name: str) -> str:
    return f"Tedarikçi oluşturuldu: {name}"


def supplier_updated(name: str) -> str:
    """Pasifleştirme de BU satırı yazar (`is_active: false` bir PATCH'tir);
    ayrı bir metin AÇILMAZ çünkü tedarikçi silinmez, yalnız kullanımdan kalkar
    (`stock_item_updated` deseni)."""
    return f"Tedarikçi güncellendi: {name}"


def purchase_request_created(request_no: str) -> str:
    return f"Satın alma talebi oluşturuldu: {request_no}"


def purchase_request_updated(request_no: str) -> str:
    """Kalem değişimi de BU satırdır: kalemler talebin gövdesinde REPLACE edilir
    ve tek atomik işlemdir — satır başına günlük satırı, 40 kalemlik bir talepte
    günlüğü boğardı (`stock_entry_created` "giriş başına tek olay" kuralı)."""
    return f"Satın alma talebi güncellendi: {request_no}"


def purchase_request_deleted(request_no: str) -> str:
    """Metin `session.delete`ten ÖNCE kurulur — sonra kurulsaydı numara
    güvenilir okunamaz ve silinenin NE OLDUĞU kaybolurdu (`site_deleted` dersi)."""
    return f"Satın alma talebi silindi: {request_no}"


# --- Satınalma T3: onay akışı, teklif, sipariş ---
#
# Kimlik yine kullanıcının GÖRDÜĞÜ değerdir (talep numarası · sipariş numarası ·
# tedarikçi adı). **Tutar hiçbir metinde geçmez:** tahmini toplam TÜREVDİR ve
# günlüğe donmuş bir kopyası düşerse kalem değişiminde ayrışır; ₺500K eşiğinin
# hangi tarafında kalındığı da izin matrisinden okunur, günlükten değil.


def purchase_request_submitted(request_no: str) -> str:
    return f"Satın alma talebi onaya gönderildi: {request_no}"


def purchase_request_approved(request_no: str) -> str:
    """Onay talebi doğrudan `quote_wait`e taşır (§3) — metin bu yüzden "onaylandı"
    der, "teklif bekleniyor" değil: kaydedilen şey KULLANICININ EYLEMİDİR,
    eylemin yan etkisi olan durum değil."""
    return f"Satın alma talebi onaylandı: {request_no}"


def purchase_request_rejected(request_no: str) -> str:
    """Gerekçe metne KONMAZ: `rejection_reason` KOLONDUR (SAT ekranı onu kaydın
    üstünde gösterir) ve günlükte ikinci bir kopyası düzeltmelerde ayrışırdı —
    `sale_cancelled`ın aksine burada gerekçenin kalıcı bir yeri vardır."""
    return f"Satın alma talebi reddedildi: {request_no}"


def purchase_quote_created(request_no: str, supplier_name: str) -> str:
    return f"Teklif eklendi: {request_no} · {supplier_name}"


def purchase_quote_updated(request_no: str, supplier_name: str) -> str:
    return f"Teklif güncellendi: {request_no} · {supplier_name}"


def purchase_quote_deleted(request_no: str, supplier_name: str) -> str:
    """Metin `session.delete`ten ÖNCE kurulur (`purchase_request_deleted` dersi)."""
    return f"Teklif silindi: {request_no} · {supplier_name}"


def purchase_order_created_from_quote(order_no: str, request_no: str) -> str:
    """`select-and-order` ÜÇ şey yapar ama günlüğe TEK satır düşer: kullanıcının
    yaptığı tek bir eylemdir ("Sipariş Ver") ve üç satır denetimi boğardı
    (`stock_entry_created` "giriş başına tek olay" kuralı)."""
    return f"Teklif seçildi ve sipariş oluşturuldu: {order_no} · {request_no}"


def purchase_order_created(order_no: str, supplier_name: str) -> str:
    """Doğrudan (talepsiz) sipariş — SIP 35."""
    return f"Sipariş oluşturuldu: {order_no} · {supplier_name}"


def purchase_order_updated(order_no: str) -> str:
    """Durum geçişi de bu satırdır: `approved → in_transit` tek meşru geçiştir
    ve ayrı bir metin, not düzeltmesiyle karışmayacak kadar az bilgi eklerdi."""
    return f"Sipariş güncellendi: {order_no}"
