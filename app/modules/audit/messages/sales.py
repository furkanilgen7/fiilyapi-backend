"""Denetim metinleri — satis ailesi: alici kartoteksi, unite, unite satisi (P8)."""

from decimal import Decimal


def block_created(project_name: str, block_name: str) -> str:
    return f"Yeni blok oluşturuldu: {project_name} · {block_name}"


def block_updated(project_name: str, block_name: str) -> str:
    return f"Blok güncellendi: {project_name} · {block_name}"


def block_deleted(project_name: str, block_name: str) -> str:
    return f"Blok silindi: {project_name} · {block_name}"


def unit_created(project_name: str, block_name: str, unit_no: str) -> str:
    """Unite adlari projeler arasinda tekrar eder ("A Blok · Daire 1" her projede
    olabilir); proje adi olmadan denetim satiri anlamsizlasir (`section_created`
    ile ayni gerekce)."""
    return f"Yeni ünite oluşturuldu: {project_name} · {block_name} · {unit_no}"


def unit_updated(project_name: str, block_name: str, unit_no: str) -> str:
    return f"Ünite güncellendi: {project_name} · {block_name} · {unit_no}"


def unit_deleted(project_name: str, block_name: str, unit_no: str) -> str:
    return f"Ünite silindi: {project_name} · {block_name} · {unit_no}"


def units_bulk_created(project_name: str, block_name: str, count: int) -> str:
    return f"Toplu ünite üretildi: {project_name} · {block_name} · {count} ünite"


def units_imported(project_name: str, created: int, skipped: int = 0) -> str:
    """DEGISTI (P3.1 §6.1, §9): kismi aktarimda ATLANAN satir sayisi da yazilir.

    Yazilmasaydi denetim gunlugu "kac unite geldi" sorusuna yaniltici cevap
    verirdi: 24 satirlik dosyadan 22 unite gelmesi ile 22 satirlik dosyadan 22
    unite gelmesi gunlukte AYNI gorunurdu.
    """
    if skipped:
        return (
            f"Üniteler Excel'den içe aktarıldı: {project_name} · "
            f"{created} ünite ({skipped} satır atlandı)"
        )
    return f"Üniteler Excel'den içe aktarıldı: {project_name} · {created} ünite"


def unit_allocation_updated(project_name: str, count: int, shareholder_count: int) -> str:
    """P9 spec §5: hissedar atamasi MEVCUT dönem-özetine eklenir.

    Yeni bir `AuditAction` ACILMAZ (TB3 T3 emsali): paylasim tek bir eylemdir,
    hissedar atamasi onun bir ayrintisidir. Ek YALNIZ atama varken basilir;
    "(0 hissedar ataması)" her paylasim satirina gurultu eklerdi
    (`units_imported`in `skipped` gerekcesinin aynisi).
    """
    if shareholder_count:
        return (
            f"Ünite paylaşımı güncellendi: {project_name} · "
            f"{count} ünite ({shareholder_count} hissedar ataması)"
        )
    return f"Ünite paylaşımı güncellendi: {project_name} · {count} ünite"


# --- Alici (musteri) kartoteksi (P8 T2) ---
#
# Yeni `AuditAction` GEREKMEDI: kayit acma/duzenleme mevcut `create`/`update`
# aksiyonlarina birebir oturuyor (`subcontractor_created` deseni). Silme metni
# YOK cunku DELETE ucu da yok (spec §4).


def customer_created(name: str) -> str:
    return f"Müşteri oluşturuldu: {name}"


def customer_updated(name: str) -> str:
    return f"Müşteri güncellendi: {name}"


# --- Unite satisi (P8 T3) ---
#
# Yeni `AuditAction` GEREKMEDI: satis kaydi acma/duzenleme/silme mevcut
# `create`/`update`/`delete` aksiyonlarina birebir oturuyor (`unit_created`
# ailesinin deseni). Durum GECISLERININ metinleri (`activate`/`transfer-deed`/
# `cancel`) T5'in isidir ve `approve` aksiyonu orada degerlendirilecektir.
#
# Ucunun de imzasi AYNIDIR — silme metni ek parametre ALMAZ cunku etiket
# (`A Blok · 12`) ve alici adi zaten kaydin kim oldugunu tam olarak soyler.
# Cagiran (`sales/service.delete_sale`) bu ikisini `session.delete` ONCESINDE
# okur; sonrasinda hicbir sorguyla geri getirilemezler.


def sale_created(project_name: str, unit_label: str, customer_name: str) -> str:
    return f"Ünite satışı oluşturuldu: {project_name} · {unit_label} · {customer_name}"


def sale_updated(project_name: str, unit_label: str, customer_name: str) -> str:
    return f"Ünite satışı güncellendi: {project_name} · {unit_label} · {customer_name}"


def sale_deleted(project_name: str, unit_label: str, customer_name: str) -> str:
    return f"Ünite satışı silindi: {project_name} · {unit_label} · {customer_name}"


# --- Odeme plani (P8 T4) ---
#
# Yeni `AuditAction` GEREKMEDI: plan uretimi satir ACAR (`create`), plan
# duzenlemesi ve tahsilat mevcut satiri DEGISTIRIR (`update`). Tahsilat icin
# ayri bir aksiyon acilmadi cunku denetim ekrani aksiyona degil METNE gore
# okunur ve "Taksit tahsilati" ifadesi olayi tam olarak adlandirir.


def sale_plan_generated(project_name: str, unit_label: str, row_count: int) -> str:
    return f"Ödeme planı oluşturuldu: {project_name} · {unit_label} · {row_count} satır"


def sale_plan_saved(project_name: str, unit_label: str, row_count: int) -> str:
    return f"Ödeme planı güncellendi: {project_name} · {unit_label} · {row_count} satır"


def sale_installment_paid(
    project_name: str, unit_label: str, installment_label: str, amount: Decimal
) -> str:
    return (
        f"Taksit tahsilatı işlendi: {project_name} · {unit_label} · {installment_label} · {amount}"
    )


# --- Durum gecisleri (P8 T5) ---
#
# Yeni `AuditAction` ACILMADI: `AuditAction` bir PostgreSQL enum tipidir ve yeni
# deger MIGRATION gerektirir; ucu de mevcut kaydin durumunu DEGISTIRDIGI icin
# `update` aksiyonuna oturur. Denetim ekrani aksiyona degil METNE gore okunur,
# bu yuzden UC AYRI metin yazilir — tek "guncellendi" metnine dusseydi denetimde
# tapu devri ile fiyat duzeltmesi ayirt edilemezdi.
#
# `approve` aksiyonu BILINCLI OLARAK kullanilmadi: o deger hakedis onay is
# akisina aittir; `activate` bir onay degil ticari bir durum degisikligidir.
#
# IPTAL GEREKCESI: `unit_sales`te gerekce KOLONU YOKTUR (T1) ve acilmaz —
# gerekce kaydin bir NITELIGI degil, bir OLAYIN aciklamasidir ve tam olarak
# denetim gunlugunun tasidigi seydir (`progress_payments` reject gerekcesi K12).


def sale_activated(project_name: str, unit_label: str, customer_name: str) -> str:
    return (
        "Satış kaydı aktifleştirildi (rezervasyon → satış): "
        f"{project_name} · {unit_label} · {customer_name}"
    )


def sale_deed_transferred(project_name: str, unit_label: str, customer_name: str) -> str:
    return f"Tapu devri işlendi: {project_name} · {unit_label} · {customer_name}"


def sale_cancelled(project_name: str, unit_label: str, customer_name: str, reason: str) -> str:
    return (
        f"Ünite satışı iptal edildi: {project_name} · {unit_label} · {customer_name} "
        f"· Gerekçe: {reason}"
    )
