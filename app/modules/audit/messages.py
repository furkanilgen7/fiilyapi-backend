"""Denetim gunlugu detay metinleri.

Kullaniciya gorunen tum detay metinleri Turkce ve TEK yerde tutulur; router'lara
string gomulmez. Metinlere parola, token veya baska gizli deger YAZILMAZ.
"""

from datetime import date, datetime
from decimal import Decimal

from app.core.access import AccessLevel

LOGIN_DETAIL = "Sisteme giriş yapıldı"
COMPANY_UPDATED = "Şirket bilgileri güncellendi"
COMPANY_LOGO_UPDATED = "Şirket logosu güncellendi"
COMPANY_LOGO_REMOVED = "Şirket logosu kaldırıldı"

# Erisim seviyelerinin insan-okur karsiliklari — izin matrisi ekranindaki etiketlerle
# ayni dil (frontend permission-presets.ts). Denetim gunlugu enum degeri gostermez.
ACCESS_LEVEL_LABELS: dict[AccessLevel, str] = {
    AccessLevel.none: "Yok",
    AccessLevel.view: "Görüntüle",
    AccessLevel.draft: "Taslak",
    AccessLevel.request: "Talep",
    AccessLevel.approve: "Onay",
    AccessLevel.full: "Tam",
    AccessLevel.admin: "Süper",
}


def user_created(name: str, role_name: str) -> str:
    return f"Kullanıcı oluşturuldu: {name} · {role_name}"


def user_updated(name: str) -> str:
    return f"Kullanıcı güncellendi: {name}"


def password_reset(name: str) -> str:
    """Parolanin kendisi ASLA metne girmez — yalnizca islemin yapildigi bildirilir."""
    return f"Kullanıcı parolası sıfırlandı: {name}"


def user_deleted(name: str) -> str:
    return f"Kullanıcı silindi: {name}"


def project_access_updated(name: str) -> str:
    return f"Proje erişimi güncellendi: {name}"


def role_created(name: str) -> str:
    return f"Özel rol oluşturuldu: {name}"


def role_renamed(old_name: str, new_name: str) -> str:
    """Eski ad cagri noktasinda islemden ONCE okunmali; sonra okunursa yeni ad iki kez cikar."""
    return f"Rol yeniden adlandırıldı: {old_name} → {new_name}"


def role_deleted(name: str) -> str:
    return f"Rol silindi: {name}"


def permission_changed(role_name: str, module_name: str, level: AccessLevel) -> str:
    """Modul ADI kullanilir (module_key degil) — denetim gunlugu dili insan-okur."""
    return f"İzin değişti: {role_name} · {module_name} → {ACCESS_LEVEL_LABELS[level]}"


def employer_created(name: str) -> str:
    return f"Yeni işveren oluşturuldu: {name}"


def project_created(name: str) -> str:
    return f"Yeni proje oluşturuldu: {name}"


def project_updated(name: str) -> str:
    return f"Proje güncellendi: {name}"


def site_created(name: str) -> str:
    return f"Yeni şantiye oluşturuldu: {name}"


def site_draft_created(name: str) -> str:
    """Taslak olusturma yayin olusturmadan AYRI metindir (spec §10).

    Denetim ekraninda "gercekten bir santiye acildi mi" sorusu metinden
    cevaplanabilmelidir; tek metin kullanmak yarim kalmis bir taslagi tamamlanmis
    bir acilis gibi gosterirdi.
    """
    return f"Yeni şantiye taslağı oluşturuldu: {name}"


def site_sections_created(site_name: str, count: int) -> str:
    """Bolumlu form icin TEK OZET satir (`units_bulk_created` deseni, spec §10).

    Bolum basina ayri satir yazilmaz: 5 bolumlu bir form 6 denetim satiri
    uretmez, 2 uretir — gunluk okunabilirligi kaydin sayisindan daha degerlidir.
    """
    return f"Şantiye bölümleri oluşturuldu: {site_name} · {count} bölüm"


def site_updated(name: str) -> str:
    return f"Şantiye güncellendi: {name}"


def site_published(name: str) -> str:
    """`is_draft: true -> false` gecisi (spec §5.3, §10) — duz guncellemeden AYRI."""
    return f"Şantiye taslaktan yayına alındı: {name}"


def site_deleted(project_name: str, name: str) -> str:
    """Metin santiye satiri SILINMEDEN ONCE kurulmalidir (spec §10).

    Sonra kurulursa `project.name` ve `site.name` guvenilir okunamaz ve satir bos
    adla yazilir — yani silinen kaydin NE OLDUGU tamamen kaybolur.
    """
    return f"Şantiye silindi: {project_name} · {name}"


def section_created(site_name: str, name: str) -> str:
    """Bolum adlari santiyeden bagimsiz tekrar edebilir ("Kat 6-10" her blokta
    olabilir); santiye adi olmadan denetim satiri anlamsizlasir."""
    return f"Yeni bölüm oluşturuldu: {site_name} · {name}"


def section_updated(site_name: str, name: str) -> str:
    return f"Bölüm güncellendi: {site_name} · {name}"


def section_published(site_name: str, name: str) -> str:
    """`site_published` deseninin birebiri: `is_draft: true -> false` gecisi
    (spec §5.3) duz guncellemeden AYRI metindir. YENI `AuditAction` ACILMAZ —
    ayrim METINDEDIR, aksiyon `update` olarak kalir."""
    return f"Bölüm taslaktan yayına alındı: {site_name} · {name}"


def section_deleted(site_name: str, name: str) -> str:
    """`site_deleted` ile ayni kural: metin `session.delete`ten ONCE kurulur."""
    return f"Bölüm silindi: {site_name} · {name}"


def boq_group_created(name: str) -> str:
    return f"İş kalemi grubu oluşturuldu: {name}"


def boq_group_updated(name: str) -> str:
    return f"İş kalemi grubu güncellendi: {name}"


def boq_item_created(code: str, description: str) -> str:
    return f"İş kalemi oluşturuldu: {code} — {description}"


def boq_item_updated(code: str, description: str) -> str:
    return f"İş kalemi güncellendi: {code} — {description}"


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


def unit_allocation_updated(project_name: str, count: int) -> str:
    return f"Ünite paylaşımı güncellendi: {project_name} · {count} ünite"


def boq_item_deleted(code: str, description: str) -> str:
    return f"İş kalemi silindi: {code} — {description}"


# --- Sözleşmeler (P5, spec §8, task C13) ---
#
# C6-C12 bu aileleri `contracts/router.py`de geçici, modül-içi yardımcılar
# olarak yazdı (task brief kararı — henüz burada yoklardı). C13 onları TEK
# yere taşır; metinler değişmedi, yalnız yerleri değişti.


def employer_contract_group_created(project_name: str, name: str) -> str:
    return f"Sözleşme poz grubu oluşturuldu: {project_name} · {name}"


def employer_contract_group_updated(project_name: str, name: str) -> str:
    return f"Sözleşme poz grubu güncellendi: {project_name} · {name}"


def employer_contract_group_deleted(project_name: str, name: str) -> str:
    return f"Sözleşme poz grubu silindi: {project_name} · {name}"


def employer_contract_item_created(project_name: str, code: str, description: str) -> str:
    """`boq_item_created` deseninin aynısı: kod TEK BAŞINA anlamsız, açıklama

    olmadan denetim satırı hangi kalemin oluştuğunu göstermez (spec §8'in
    kısaltılmış imzası `(project_name, code)` yalnız özet listedir — gerçek
    metin `boq_item_*` ailesinin deseni izlenerek `description` de taşır).
    """
    return f"Sözleşme poz kalemi oluşturuldu: {project_name} · {code} — {description}"


def employer_contract_item_updated(project_name: str, code: str, description: str) -> str:
    return f"Sözleşme poz kalemi güncellendi: {project_name} · {code} — {description}"


def employer_contract_item_deleted(project_name: str, code: str, description: str) -> str:
    return f"Sözleşme poz kalemi silindi: {project_name} · {code} — {description}"


def contract_distribution_saved(project_name: str, count: int) -> str:
    return f"Poz dağılımı kaydedildi: {project_name} · {count} eşleştirme"


def subcontractor_created(name: str) -> str:
    return f"Taşeron oluşturuldu: {name}"


def subcontractor_updated(name: str) -> str:
    return f"Taşeron güncellendi: {name}"


def subcontractor_deleted(name: str) -> str:
    return f"Taşeron silindi: {name}"


def subcontract_label(contract_no: str | None, subcontractor_name: str | None) -> str:
    """Sözleşme no yoksa taşeron adı, o da yoksa "taslak" — taslak aşamasında

    henüz doldurulmamış alanlar için anlamlı bir denetim etiketi üretir.
    """
    return contract_no or subcontractor_name or "taslak"


def subcontract_created(project_name: str, label: str) -> str:
    return f"Taşeron sözleşmesi oluşturuldu: {project_name} · {label}"


def subcontract_updated(project_name: str, label: str) -> str:
    return f"Taşeron sözleşmesi güncellendi: {project_name} · {label}"


def subcontract_published(project_name: str, label: str) -> str:
    """`site_published` deseninin aynısı: `is_draft: true -> false` geçişi

    (spec §5.3/§8, §10) — düz güncellemeden AYRI metindir.
    """
    return f"Taşeron sözleşmesi taslaktan yayına alındı: {project_name} · {label}"


def subcontract_deleted(project_name: str, label: str) -> str:
    return f"Taşeron sözleşmesi silindi: {project_name} · {label}"


def subcontract_item_created(contract_no: str | None, code: str) -> str:
    return f"Taşeron sözleşmesi kalemi oluşturuldu: {contract_no or 'taslak'} · {code}"


def subcontract_item_updated(contract_no: str | None, code: str) -> str:
    return f"Taşeron sözleşmesi kalemi güncellendi: {contract_no or 'taslak'} · {code}"


def subcontract_item_deleted(contract_no: str | None, code: str) -> str:
    return f"Taşeron sözleşmesi kalemi silindi: {contract_no or 'taslak'} · {code}"


def subcontract_items_loaded(contract_no: str | None, count: int) -> str:
    label = contract_no or "taslak"
    return f"Taşeron sözleşmesi kalemleri işverenden yüklendi: {label} · {count} kalem"


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


def progress_payment_submitted(project_name: str, sequence_no: int) -> str:
    return f"Hakediş onaya gönderildi: {project_name} · #{sequence_no}"


def progress_payment_approved(project_name: str, sequence_no: int) -> str:
    return f"Hakediş onaylandı: {project_name} · #{sequence_no}"


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
    approver = previous_approver_name or "Bilinmiyor"
    when = previous_approved_at.strftime("%d.%m.%Y %H:%M") if previous_approved_at else "Bilinmiyor"
    return (
        f"Hakediş onayı geri çekildi: {project_name} · #{sequence_no} · "
        f"Önceki onay: {approver} · {when}"
    )


def progress_payment_lines_saved(project_name: str, sequence_no: int, count: int) -> str:
    return f"Hakediş satırları kaydedildi: {project_name} · #{sequence_no} · {count} satır"


def progress_payment_prices_refreshed(project_name: str, sequence_no: int, count: int) -> str:
    return f"Hakediş fiyatları tazelendi: {project_name} · #{sequence_no} · {count} kalem"


# --- Taşeron hakedişi (T2, spec §6) ---
#
# İşveren ailesinin `(project_name, sequence_no)` imzasına TAŞERON ADI eklenir:
# `sequence_no` burada SÖZLEŞME kapsamlıdır (spec §2), dolayısıyla proje adı tek
# başına kaydı adreslemez — "#1" aynı projede birden çok sözleşmede vardır.


def _subcontractor_payment_label(
    project_name: str, subcontractor_name: str | None, sequence_no: int
) -> str:
    return f"{project_name} · {subcontractor_name or 'taşeron seçilmedi'} · #{sequence_no}"


def subcontractor_progress_payment_created(
    project_name: str, subcontractor_name: str | None, sequence_no: int
) -> str:
    label = _subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakedişi oluşturuldu: {label}"


def subcontractor_progress_payment_updated(
    project_name: str, subcontractor_name: str | None, sequence_no: int
) -> str:
    label = _subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakedişi güncellendi: {label}"


def subcontractor_progress_payment_lines_saved(
    project_name: str, subcontractor_name: str | None, sequence_no: int, count: int
) -> str:
    label = _subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakediş satırları kaydedildi: {label} · {count} satır"


def subcontractor_progress_payment_prices_refreshed(
    project_name: str, subcontractor_name: str | None, sequence_no: int, count: int
) -> str:
    label = _subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
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
    label = _subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakedişi silindi: {label} · {status_label} · {amount:,.2f} TL"


# --- Taşeron hakedişi durum geçişleri (T4, spec §5) ---


def subcontractor_progress_payment_submitted(
    project_name: str, subcontractor_name: str | None, sequence_no: int
) -> str:
    label = _subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakedişi onaya gönderildi: {label}"


def subcontractor_progress_payment_approved(
    project_name: str, subcontractor_name: str | None, sequence_no: int
) -> str:
    label = _subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakedişi onaylandı: {label}"


def subcontractor_progress_payment_rejected(
    project_name: str, subcontractor_name: str | None, sequence_no: int, reason: str
) -> str:
    """İşverenin `reason`ı OPSİYONELDİR; burada ZORUNLUDUR (spec §5) — gerekçe
    `rejection_reason` kolonuna da yazılır, günlük onun İKİNCİ değil KALICI
    kopyasıdır (kolon güncellenebilir, günlük satırı değişmez)."""
    label = _subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    return f"Taşeron hakedişi reddedildi: {label} · Gerekçe: {reason}"


def subcontractor_progress_payment_paid(
    project_name: str, subcontractor_name: str | None, sequence_no: int
) -> str:
    label = _subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
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
    label = _subcontractor_payment_label(project_name, subcontractor_name, sequence_no)
    approver = previous_approver_name or "Bilinmiyor"
    when = previous_approved_at.strftime("%d.%m.%Y %H:%M") if previous_approved_at else "Bilinmiyor"
    return f"Taşeron hakediş onayı geri çekildi: {label} · Önceki onay: {approver} · {when}"


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


# --- Santiye gunlugu (site_diary T2) ---
#
# Yeni `AuditAction` GEREKMEDI: gunluk kayit acmak `create`, basligini
# duzenlemek `update`, silmek `delete` aksiyonuna oturur. Denetim ekrani
# aksiyona degil METNE gore okunur.
#
# Kaydin kimligi UUID degil INSAN-OKUR uclusudur (proje · santiye · gun):
# denetim satirini okuyan kisi hangi gunun kaydinin silindigini gormek ister,
# bir kimlik dizisini degil.


def site_diary_entry_created(
    project_name: str, site_name: str, entry_date: date, line_count: int
) -> str:
    return (
        f"Günlük kayıt oluşturuldu: {project_name} · {site_name} · {entry_date.isoformat()} "
        f"· {line_count} poz"
    )


def site_diary_entry_updated(project_name: str, site_name: str, entry_date: date) -> str:
    return f"Günlük kayıt güncellendi: {project_name} · {site_name} · {entry_date.isoformat()}"


def site_diary_lines_saved(
    project_name: str, site_name: str, entry_date: date, line_count: int
) -> str:
    """T3 `PUT …/lines`. `update` aksiyonuna oturur: satir kaydetmek kaydin
    ICERIGINI degistirir, yeni bir kayit ACMAZ."""
    return (
        f"Günlük kayıt poz satırları kaydedildi: {project_name} · {site_name} "
        f"· {entry_date.isoformat()} · {line_count} poz"
    )


def site_diary_entry_submitted(project_name: str, site_name: str, entry_date: date) -> str:
    """T4 `POST …/submit`. `update` aksiyonuna oturur: `AuditAction.approve` HAKEDIS
    onayina ayrilmistir — gunluk gonderimi bir onay DEGILDIR (iki durumlu akis)."""
    return f"Günlük kayıt gönderildi: {project_name} · {site_name} · {entry_date.isoformat()}"


def site_diary_entry_reopened(project_name: str, site_name: str, entry_date: date) -> str:
    """T4 `POST …/reopen` — YALNIZ admin. Denetim satiri kritiktir: gonderilmis bir
    kaydin yeniden yazilabilir hale gelmesi hakedise giden veriyi degistirir."""
    return (
        f"Günlük kayıt taslağa geri alındı: {project_name} · {site_name} · {entry_date.isoformat()}"
    )


def site_diary_entry_deleted(
    project_name: str, site_name: str, entry_date: date, status_label: str, line_count: int
) -> str:
    return (
        f"Günlük kayıt silindi: {project_name} · {site_name} · {entry_date.isoformat()} "
        f"· {status_label} · {line_count} poz"
    )
