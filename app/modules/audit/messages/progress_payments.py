"""Denetim metinleri — ISVEREN hakedisi (P7, spec §11).

`BILINMIYOR`/`_damga` taseron ailesiyle PAYLASILIR ve `shared`den okunur.
"""

from datetime import datetime
from decimal import Decimal

from app.modules.audit.messages.shared import BILINMIYOR, _damga

# --- İşveren hakedişi (P7, spec §11, task H10) ---
#
# `(project_name, sequence_no)` imzası ailenin ortak deseni — tek istisna
# `progress_payment_unapproved` (H6'dan devir) ve `progress_payment_deleted`
# (H8'den devir): ikisi de kaybolacak bilgiyi TAŞIR, bu yüzden ek parametre
# alır (plan H10, iki "devredilen zorunluluk" notu).


def progress_payment_created(project_name: str, sequence_no: int) -> str:
    return f"Hakediş oluşturuldu: {project_name} · #{sequence_no}"


def progress_payment_updated(project_name: str, sequence_no: int) -> str:
    return f"Hakediş güncellendi: {project_name} · #{sequence_no}"


def progress_payment_deleted(
    project_name: str, sequence_no: int, status_label: str, amount: Decimal
) -> str:
    """H8'den devredilen not (plan H10): kayıt SİLİNMEDEN ÖNCE özeti çıkarılmalı.

    Kayıt gittiğinde `sequence_no`/durum/tutar bir daha okunamaz — çağıran
    (`progress_payments/service.py.delete_payment`) bu üçlüyü `session.delete`
    ÖNCESİNDE yakalar.
    """
    return f"Hakediş silindi: {project_name} · #{sequence_no} · {status_label} · {amount:,.2f} TL"


def progress_payment_label(project_name: str, sequence_no: int) -> str:
    """Isveren hakedisinin KIMLIGI (`subcontractor_payment_label` esdegeri).

    OK-1A T3: zincirin ARA ADIM metni evragin cumlesini kullanamaz ama kimliksiz
    de kalamaz — bu etiket oraya eklenir.
    """
    return f"{project_name} · #{sequence_no}"


def progress_payment_submitted(project_name: str, sequence_no: int) -> str:
    return f"Hakediş onaya gönderildi: {progress_payment_label(project_name, sequence_no)}"


def progress_payment_approved(project_name: str, sequence_no: int) -> str:
    return f"Hakediş onaylandı: {progress_payment_label(project_name, sequence_no)}"


def progress_payment_rejected(project_name: str, sequence_no: int, reason: str | None) -> str:
    """K12: `reason` gövdede opsiyoneldir, kolon AÇILMAZ — bu metin TEK kalıcı izdir."""
    base = f"Hakediş reddedildi: {project_name} · #{sequence_no}"
    return f"{base} · Gerekçe: {reason}" if reason else base


def progress_payment_paid(project_name: str, sequence_no: int) -> str:
    return f"Hakediş ödendi olarak işaretlendi: {project_name} · #{sequence_no}"


def progress_payment_unapproved(
    project_name: str,
    sequence_no: int,
    previous_approver_name: str | None,
    previous_approved_at: datetime | None,
) -> str:
    """H6'dan devredilen ZORUNLU not (plan H10, spec §11): `transitions._stamp`

    bu değerleri NULL'lamadan ÖNCE okunmalıdır — sonra okunursa `unapprove`
    sessiz bir tarih silme işlemi olur (H6 denetimi O1, 2026-07-31 bulgusu).
    """
    approver = previous_approver_name or BILINMIYOR
    when = _damga(previous_approved_at)
    return (
        f"Hakediş onayı geri çekildi: {project_name} · #{sequence_no} · "
        f"Önceki onay: {approver} · {when}"
    )


def progress_payment_lines_saved(project_name: str, sequence_no: int, count: int) -> str:
    return f"Hakediş satırları kaydedildi: {project_name} · #{sequence_no} · {count} satır"


def progress_payment_prices_refreshed(project_name: str, sequence_no: int, count: int) -> str:
    return f"Hakediş fiyatları tazelendi: {project_name} · #{sequence_no} · {count} kalem"
