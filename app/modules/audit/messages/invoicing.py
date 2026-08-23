"""Denetim metinleri — fatura cekirdegi ve durum gecisleri (FAT-1 T3/T4)."""

# --- FAT-1 T3: fatura çekirdeği ---
#
# Kimlik UUID DEĞİL kullanıcının GÖRDÜĞÜ değerdir: FATURA NUMARASI (giden'de
# `FIL2026000184`, gelen'de satıcının serisi). **Tutar hiçbir metinde geçmez:**
# toplam TÜREVDİR (`amounts.py`) ve günlüğe donmuş bir kopyası düşerse kalem ya
# da oran değişiminde ayrışır (`purchase_request_*` kanonu).
#
# 🔴 YENİ `AuditAction` ÜYESİ AÇILMADI (TB3/T3 kanonu): `action` gerçek bir
# Postgres enum tipidir ve yeni üye migration ister. Ayrım metindedir.


def invoice_created(invoice_no: str) -> str:
    return f"Fatura oluşturuldu: {invoice_no}"


def invoice_updated(invoice_no: str) -> str:
    return f"Fatura güncellendi: {invoice_no}"


def invoice_lines_replaced(invoice_no: str) -> str:
    """Kalem kümesi TOPTAN yazılır ve günlüğe TEK satır düşer: kullanıcının
    yaptığı tek bir eylemdir ("Kaydet") ve satır başına günlük satırı 40
    kalemlik bir faturada denetimi boğardı (`stock_entry_created` kuralı).

    `invoice_updated`tan AYRI metin: başlık düzeltmesi ile kalem değişimi mali
    olarak farklı ağırlıktadır ve günlükte ayırt edilebilmelidir."""
    return f"Fatura kalemleri güncellendi: {invoice_no}"


def invoice_deleted(invoice_no: str) -> str:
    """Metin `session.delete`ten ÖNCE kurulur — sonra kurulsaydı numara
    güvenilir okunamazdı (`purchase_request_deleted` dersi)."""
    return f"Fatura silindi: {invoice_no}"


# --- FAT-1 T4: durum geçişleri ---
#
# Dördü de mevcut `AuditAction` üyelerine oturur (`update`, `approve`) — 🔴 YENİ
# ÜYE AÇILMADI. Bu yüzden AYIRT EDİCİ olan METİNDİR: dört geçiş dört ayrı cümle
# taşır ve hiçbiri `invoice_updated` ("Fatura güncellendi") ile karışmaz. Tek
# metne indirgenselerdi denetim tablosunda "gönderildi" ile "tahsil edildi"
# birbirinden ayrılamazdı.
#
# Tutar hiçbirinde geçmez (yukarıdaki kural) ve DURUM ADI da yazılmaz: durum
# kaydın kendisinden okunur, günlüğe donmuş bir kopyası düşerse ileride bir
# geçiş yeniden adlandırıldığında iki ad yan yana yaşardı.


def invoice_sent(invoice_no: str) -> str:
    return f"Fatura gönderildi: {invoice_no}"


def invoice_collected(invoice_no: str) -> str:
    return f"Fatura tahsil edildi olarak işaretlendi: {invoice_no}"


def invoice_approved(invoice_no: str) -> str:
    """Gelen faturanın onayı — TEK `AuditAction.approve` kullanan fatura
    geçişidir (üye seed'den beri tanımlıdır, migration GEREKTİRMEZ)."""
    return f"Gelen fatura onaylandı: {invoice_no}"


def invoice_disputed(invoice_no: str) -> str:
    """İtiraz bir REDDETMEDİR ama `AuditAction`da `reject` üyesi YOKTUR ve
    açmak gerçek bir Postgres enum'una migration demektir (TB3 kanonu) —
    `update` üyesiyle yazılır, ayrım bu cümledir."""
    return f"Gelen faturaya itiraz edildi: {invoice_no}"
