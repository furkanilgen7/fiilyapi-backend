"""Denetim metinleri — TASERON hakedisi (T2/T4, spec §6, §5).

`BILINMIYOR`/`_damga` isveren ailesiyle PAYLASILIR ve `shared`den okunur.
"""

from datetime import datetime
from decimal import Decimal

from app.modules.audit.messages.shared import BILINMIYOR, _damga

# --- Taşeron hakedişi (T2, spec §6) ---
#
# İşveren ailesinin `(project_name, sequence_no)` imzasına TAŞERON ADI eklenir:
# `sequence_no` burada SÖZLEŞME kapsamlıdır (spec §2), dolayısıyla proje adı tek
# başına kaydı adreslemez — "#1" aynı projede birden çok sözleşmede vardır.


def subcontractor_payment_label(
    project_name: str, subcontractor_name: str | None, sequence_no: int
) -> str:
    """Taseron hakedisinin KIMLIGI. 🔴 OK-1A T3'te GORUNUR yapildi (`_` kalkti):

    zincirin ARA ADIM denetim metni evragin kendi cumlesini KULLANAMAZ ("onaylandi"
    demek olurdu, oysa evrak hâlâ onay bekliyor) — ama kimliksiz bir "adim 1/3
    onaylandi" satiri gunlukte HANGI evrak sorusunu yanitsiz birakirdi. Bu yuzden
    ara adim metnine bu ETIKET eklenir.
    """
    return f"{project_name} · {subcontractor_name or 'taşeron seçilmedi'} · #{sequence_no}"


def subcontractor_progress_payment_created(
    project_name: str, subcontractor_name: str | None, sequence_no: int
) -> str:
    label = subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakedişi oluşturuldu: {label}"


def subcontractor_progress_payment_updated(
    project_name: str, subcontractor_name: str | None, sequence_no: int
) -> str:
    label = subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakedişi güncellendi: {label}"


def subcontractor_progress_payment_lines_saved(
    project_name: str, subcontractor_name: str | None, sequence_no: int, count: int
) -> str:
    label = subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakediş satırları kaydedildi: {label} · {count} satır"


def subcontractor_progress_payment_prices_refreshed(
    project_name: str, subcontractor_name: str | None, sequence_no: int, count: int
) -> str:
    label = subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakediş fiyatları tazelendi: {label} · {count} kalem"


def subcontractor_progress_payment_deleted(
    project_name: str,
    subcontractor_name: str | None,
    sequence_no: int,
    status_label: str,
    amount: Decimal,
) -> str:
    """`progress_payment_deleted` ile AYNI zorunluluk: özet `session.delete`

    ÖNCESİNDE çıkarılmalıdır — kayıt gittiğinde durum/tutar bir daha okunamaz.
    """
    label = subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakedişi silindi: {label} · {status_label} · {amount:,.2f} TL"


# --- Taşeron hakedişi durum geçişleri (T4, spec §5) ---


def subcontractor_progress_payment_submitted(
    project_name: str, subcontractor_name: str | None, sequence_no: int
) -> str:
    label = subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakedişi onaya gönderildi: {label}"


def subcontractor_progress_payment_approved(
    project_name: str, subcontractor_name: str | None, sequence_no: int
) -> str:
    label = subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakedişi onaylandı: {label}"


def subcontractor_progress_payment_rejected(
    project_name: str, subcontractor_name: str | None, sequence_no: int, reason: str
) -> str:
    """İşverenin `reason`ı OPSİYONELDİR; burada ZORUNLUDUR (spec §5) — gerekçe
    `rejection_reason` kolonuna da yazılır, günlük onun İKİNCİ değil KALICI
    kopyasıdır (kolon güncellenebilir, günlük satırı değişmez)."""
    label = subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakedişi reddedildi: {label} · Gerekçe: {reason}"


def subcontractor_progress_payment_paid(
    project_name: str, subcontractor_name: str | None, sequence_no: int
) -> str:
    label = subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakedişi ödendi olarak işaretlendi: {label}"


def subcontractor_progress_payment_unapproved(
    project_name: str,
    subcontractor_name: str | None,
    sequence_no: int,
    previous_approver_name: str | None,
    previous_approved_at: datetime | None,
) -> str:
    """`progress_payment_unapproved` ile AYNI ZORUNLULUK: bu iki değer
    `transitions._stamp` onları NULL'lamadan ÖNCE okunmalıdır, sonra okunursa
    `unapprove` sessiz bir tarih silme işlemi olur."""
    label = subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    approver = previous_approver_name or BILINMIYOR
    when = _damga(previous_approved_at)
    return f"Taşeron hakediş onayı geri çekildi: {label} · Önceki onay: {approver} · {when}"
