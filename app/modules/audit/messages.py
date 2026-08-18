"""Denetim gunlugu detay metinleri.

Kullaniciya gorunen tum detay metinleri Turkce ve TEK yerde tutulur; router'lara
string gomulmez. Metinlere parola, token veya baska gizli deger YAZILMAZ.
"""

from datetime import date, datetime
from decimal import Decimal

from app.core.access import AccessLevel
from app.core.timezone import DISPLAY_TIMESTAMP_FORMAT, to_display

BILINMIYOR = "Bilinmiyor"


def _damga(value: datetime | None) -> str:
    """Denetim metnindeki, kullanıcıya görünen tarih-saat damgası.

    `approved_at` bir `timestamptz`tir; ham `strftime` sunucunun UTC saatini
    basar ve TR gecesi 21:00-24:00 arasında BİR ÖNCEKİ GÜNÜ gösterir (TB5 §1
    kusur sınıfı — denetim metni onay saatini yanlış anlatırdı). Çeviri TEK
    kaynaktan (`core.timezone.to_display`) yapılır.
    """
    return to_display(value).strftime(DISPLAY_TIMESTAMP_FORMAT) if value else BILINMIYOR


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


def boq_item_allocations_replaced(code: str, section_count: int) -> str:
    """BOQ-SEC: pozun bölüm tahsisleri değiştirildi.

    Adet VERİLİR (silme mesajlarının "adet verilmez" kuralının tersi): burada
    sayı bir uyarı değil DEĞİŞİKLİĞİN KENDİSİDİR — `0` "tüm tahsisler
    kaldırıldı" demektir ve denetim kaydında bu ayırt edilebilmelidir.
    """
    return f"İş kalemi bölüm tahsisleri güncellendi: {code} — {section_count} bölüm"


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


def boq_item_deleted(code: str, description: str) -> str:
    return f"İş kalemi silindi: {code} — {description}"


def boq_group_deleted(name: str) -> str:
    """`boq_group_updated` ailesinin devami. YENI `AuditAction` ACILMAZ —
    aksiyon `delete`tir (`boq_item_deleted` ile ayni), ayrim METINDEDIR."""
    return f"İş kalemi grubu silindi: {name}"


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


def employer_contract_item_updated(
    project_name: str, code: str, description: str, refreshed_boq_count: int = 0
) -> str:
    """TB4/B3+S7: kalemin AYNA ALAN KÜMESİ (`code`/`description`/`unit`/
    `unit_price` — `contracts.service.MIRRORED_ITEM_FIELDS`) değişimi ayna BOQ
    satırlarını da

    tazeler. Bu yan etki MEVCUT `update` olayının detayına eklenir — yeni bir
    `AuditAction` üyesi açmak gerçek Postgres enum'una migration isterdi
    (TB3-C emsali). Tazeleme olmadıysa metin BİREBİR eskisi gibi kalır.
    """
    detail = f"Sözleşme poz kalemi güncellendi: {project_name} · {code} — {description}"
    if refreshed_boq_count > 0:
        detail += f" · {refreshed_boq_count} BOQ satırı tazelendi"
    return detail


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
    approver = previous_approver_name or BILINMIYOR
    when = _damga(previous_approved_at)
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


def timesheet_saved(
    project_name: str, site_name: str, year: int, month: int, cell_count: int
) -> str:
    """Puantaj T3 `PUT …/timesheet`. TEK donem-ozeti olayidir: hucre basina olay
    yazmak 31 gun x 48 isci'lik bir kaydetmede 1488 satir uretir ve denetim
    gunlugunu kullanilamaz hale getirirdi (spec §3).

    `update` aksiyonuna oturur: kaydetme donemin ICERIGINI degistirir, yeni bir
    kayit ACMAZ (`AuditAction.approve` hakedis onayina ayrilmistir — puantajda
    onay akisi YOKTUR, spec §7 S3).
    """
    return (
        f"Puantaj kaydedildi: {project_name} · {site_name} · {year}-{month:02d} "
        f"· {cell_count} hücre"
    )


# --- Santiye planlama (site_planning T3) ---
#
# Dort ucun dordu de `AuditAction.update`tir: kaydetme planin ICERIGINI
# degistirir, yeni bir kayit ACMAZ. Her uc TEK ozet olayi yazar — satir/hucre/
# hedef basina olay yazmak 7 gun x N satirlik bir kaydetmede denetim gunlugunu
# kullanilamaz hale getirirdi (planlama spec §3, puantajin `timesheet_saved`
# gerekcesinin aynisi).
#
# Kaydin kimligi UUID degil INSAN-OKUR ucludur (proje · santiye · hafta).


def site_plan_rows_saved(project_name: str, site_name: str, row_count: int) -> str:
    """`PUT …/plan/rows`. Hafta YOKTUR: satir listesi haftadan bagimsizdir."""
    return f"Şantiye planı satırları kaydedildi: {project_name} · {site_name} · {row_count} satır"


def site_plan_cells_saved(
    project_name: str, site_name: str, week_start: date, cell_count: int
) -> str:
    return (
        f"Şantiye planı hücreleri kaydedildi: {project_name} · {site_name} "
        f"· {week_start.isoformat()} haftası · {cell_count} hücre"
    )


def site_plan_goals_saved(
    project_name: str, site_name: str, week_start: date, goal_count: int
) -> str:
    return (
        f"Şantiye planı haftalık hedefleri kaydedildi: {project_name} · {site_name} "
        f"· {week_start.isoformat()} haftası · {goal_count} hedef"
    )


def site_plan_sprint_saved(project_name: str, site_name: str, name: str | None) -> str:
    """Sprint ADI degistirildi ya da (ad bossa) aktif sprint kapatildi."""
    if name is None:
        return f"Şantiye planı aktif sprinti kaldırıldı: {project_name} · {site_name}"
    return f"Şantiye planı aktif sprinti kaydedildi: {project_name} · {site_name} · {name}"


# --- Belge arşivi (documents T2 — klasör uçları) ---
#
# Kaydın kimliği UUID değil İNSAN-OKUR kapsamdır: proje · (varsa) şantiye · ad.
# Şantiyesiz klasör PROJE DÜZEYİDİR (spec §2) ve metinde şantiye parçası hiç
# görünmez — "—" gibi bir yer tutucu koymak günlüğü gürültüye boğardı.


def _document_scope(project_name: str, site_name: str | None) -> str:
    if site_name is None:
        return project_name
    return f"{project_name} · {site_name}"


def document_folder_created(project_name: str, site_name: str | None, folder_name: str) -> str:
    return f"Belge klasörü oluşturuldu: {_document_scope(project_name, site_name)} · {folder_name}"


def document_folder_renamed(
    project_name: str, site_name: str | None, old_name: str, new_name: str
) -> str:
    """Eski ad çağrı noktasında değişiklikten ÖNCE okunmalı (`role_renamed` dersi);
    sonra okunursa günlükte yeni ad iki kez çıkar."""
    return (
        f"Belge klasörü yeniden adlandırıldı: {_document_scope(project_name, site_name)} "
        f"· {old_name} → {new_name}"
    )


def document_folder_deleted(project_name: str, site_name: str | None, folder_name: str) -> str:
    """Metin `session.delete`ten ÖNCE kurulur — sonra kurulsaydı proje/şantiye
    adları güvenilir okunamaz ve silinenin NE OLDUĞU kaybolurdu."""
    return f"Belge klasörü silindi: {_document_scope(project_name, site_name)} · {folder_name}"


# --- Belge künyeleri (documents T3 — yükleme/güncelleme/silme) ---
#
# Kimlik yine UUID değil DOSYA ADIDIR: denetim günlüğünü okuyan kişi arşivde
# hangi dosyanın konuşulduğunu adından tanır. Boyut/uzantı YAZILMAZ — künye
# ekranda zaten görünür ve günlük satırını gürültüye boğardı.


def document_uploaded(project_name: str, site_name: str | None, filename: str) -> str:
    return f"Belge yüklendi: {_document_scope(project_name, site_name)} · {filename}"


def document_updated(project_name: str, site_name: str | None, filename: str) -> str:
    """Ad değiştiyse metin YENİ adı taşır (kayıt o addan aranır); klasör
    taşımasında da aynı satır düşer — hangi alanın değiştiği künyenin kendisinden
    okunur, günlük NE OLDUĞUNU değil NEYE DOKUNULDUĞUNU kaydeder."""
    return f"Belge güncellendi: {_document_scope(project_name, site_name)} · {filename}"


def document_deleted(project_name: str, site_name: str | None, filename: str) -> str:
    """Metin `session.delete`ten ÖNCE kurulur (klasör silme dersiyle aynı)."""
    return f"Belge silindi: {_document_scope(project_name, site_name)} · {filename}"


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


# --- İK-2 T2: izin talebi ---
#
# Kimlik kullanicinin GORDUGU degerdir: personel adi · izin tipi · tarih araligi.
# `days` metne KONMAZ — SUNUCU hesabidir (spec §5 K2) ve gunluge donmus bir
# kopyasi tarih duzeltmesinde ayrisirdi; tarih araligi zaten onu belirler.


def leave_request_created(full_name: str, type_name: str, start: date, end: date) -> str:
    return f"İzin talebi oluşturuldu: {full_name} · {type_name} · {start} - {end}"


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


def leave_request_approved(full_name: str, type_name: str, start: date, end: date) -> str:
    return f"İzin talebi onaylandı: {full_name} · {type_name} · {start} - {end}"


def leave_request_rejected(
    full_name: str, type_name: str, start: date, end: date, reason: str
) -> str:
    return f"İzin talebi reddedildi: {full_name} · {type_name} · {start} - {end} · {reason}"


def leave_balance_updated(full_name: str, year: int, carried_over: Decimal) -> str:
    """Devreden gün MANUEL girilir (İZ 137) — bakiyeyi doğrudan büyüten tek yazma
    yolu budur, bu yüzden yeni değer metne KONUR (denetim onu geri okuyabilsin)."""
    return f"İzin devreden günü güncellendi: {full_name} · {year} · {carried_over}"


# --- İK-3 T3: bordro dönemi + satırı ---
#
# Kimlik kullanicinin GORDUGU degerdir: donem (yil/ay) ve personel ADI.
# TUTARLAR metne KONMAZ ve bu bilinclidir (`leave_request` `days` dersi): tutar
# SUNUCU hesabidir, gunluge donmus bir kopyasi brut duzeltmesinde ayrisir ve
# hangi sayinin dogru oldugu anlasilamazdi. Denetim satiri "neyin degistigini"
# degil "kimin neye dokundugunu" tasir; tutar izi `previous_gross_amount`
# kolonundadir (K3).


def payroll_period_created(year: int, month: int) -> str:
    return f"Bordro dönemi açıldı: {year}/{month:02d}"


def payroll_period_updated(year: int, month: int, payment_due_date: object) -> str:
    """Odeme tarihi degisikligi — TARIH metne KONUR ve bu bir ISTISNA DEGILDIR.

    Yukaridaki "tutar konmaz" kurali SUNUCU HESAPLARI icindir; son odeme tarihi
    kullanicinin KENDI GIRDISIDIR ve turemez. Denetimi okuyan kisi takvimin ne
    yapildigini gormelidir; tarih silindiginde de bu acikca yazilir.
    """
    return f"Bordro dönemi güncellendi: {year}/{month:02d} · son ödeme {payment_due_date or '—'}"


def payroll_period_computed(year: int, month: int) -> str:
    return f"Bordro dönemi hesaplandı: {year}/{month:02d}"


def payroll_line_updated(full_name: str, year: int, month: int) -> str:
    return f"Bordro satırı güncellendi: {full_name} · {year}/{month:02d}"


# --- İK-3 T4: onay + ödeme (PARA olaylari) ---
#
# Onay/red satirinda tutar YOKTUR (yukaridaki gerekce): tutar sunucu hesabidir.
# ODEME satiri ise ISTISNADIR ve tutar TASIR: odenen toplam, o anda gerceklesen
# para cikisinin kendisidir; sonradan degisebilecek bir turev degil, olayin
# BUYUKLUGUDUR. Denetimi okuyan kisi "ne kadar odendi"yi baska bir ekrana
# bakmadan gormelidir.


def payroll_line_approved(full_name: str, year: int, month: int) -> str:
    return f"Bordro satırı onaylandı: {full_name} · {year}/{month:02d}"


def payroll_line_rejected(full_name: str, year: int, month: int) -> str:
    return f"Bordro satırı onayı geri alındı: {full_name} · {year}/{month:02d}"


def payroll_period_approved(year: int, month: int, status: str) -> str:
    return f"Bordro dönemi onaylandı: {year}/{month:02d} · durum {status}"


def payroll_period_paid(year: int, month: int, count: int, total: object) -> str:
    return f"Bordro dönemi ödendi: {year}/{month:02d} · {count} satır · {total} ₺"


# --- İK-3 T5: SGK damgasi + oran tablosu ---
#
# SGK damgasinin denetim satirinda TUTAR YOKTUR (yukaridaki kural): prim sunucu
# hesabidir ve oran degisiminde ayrisirdi. ORAN satirinda ise DEGERLER YAZILIR
# ve bu bir ISTISNA DEGILDIR: oranlar kullanicinin KENDI GIRDISIDIR, turemez ve
# neyin ne yapildigini denetimden okuyabilmek K1'in ("oranlar veridir") tek
# geriye donuk izidir — tabloda yalnizca SON hali durur.


def payroll_sgk_submitted(year: int, month: int) -> str:
    return f"SGK bildirimi gönderildi olarak işaretlendi: {year}/{month:02d}"


def payroll_rate_updated(year: int, source: str, rates: dict[str, object]) -> str:
    degerler = " · ".join(f"{alan}={deger}" for alan, deger in sorted(rates.items()))
    return f"Bordro kesinti oranları güncellendi: {year}/{source} · {degerler}"


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


# --- HZ-1 T3: banka/kasa hesabı ---
#
# Kimlik UUID DEĞİL kullanıcının GÖRDÜĞÜ değerdir: E9 kartında basılan ad, yani
# Kasa'da `display_name` ("Merkez Kasa"), vadesizde banka adı ("Ziraat Bank").
#
# 🔴 **IBAN metne GİRMEZ.** Denetim günlüğü geniş bir okur kitlesine açıktır ve
# hesap numarasını oraya kopyalamak, kaydı gereğinden fazla hassas kılardı;
# ayırt etmek için ad zaten yeterlidir.
#
# 🔴 **BAKİYE de girmez** — bakiye SAKLANMAZ, TÜRETİLİR (K2). Günlüğe donmuş bir
# kopyası düşseydi ilk ödemede ayrışır ve iki sayı yan yana yaşardı
# (`invoice_*` kanonunun aynısı).
#
# 🔴 YENİ `AuditAction` ÜYESİ AÇILMADI (TB3/T3 kanonu): `action` gerçek bir
# Postgres enum tipidir ve yeni üye migration ister. Ayrım metindedir.


def bank_account_label(bank_name: str, display_name: str | None) -> str:
    """Denetim metinlerinin TEK ad kaynağı.

    Üç metin de buradan geçer: ayrı ayrı kurulsalardı biri `display_name`i
    unutur ve aynı bankada açılmış iki kasa günlükte ayırt edilemezdi.
    """
    return f"{bank_name} · {display_name}" if display_name else bank_name


def bank_account_created(bank_name: str, display_name: str | None) -> str:
    return f"Banka hesabı oluşturuldu: {bank_account_label(bank_name, display_name)}"


def bank_account_updated(bank_name: str, display_name: str | None) -> str:
    """Metin GÜNCELLENMİŞ değerlerle kurulur: kullanıcı adı düzelttiyse günlükte
    yeni ad durmalıdır, yoksa satır neyin ne olduğunu anlatmaz."""
    return f"Banka hesabı güncellendi: {bank_account_label(bank_name, display_name)}"


def bank_account_deleted(bank_name: str, display_name: str | None) -> str:
    """Metin `session.delete`ten ÖNCE kurulur — sonra kurulsaydı ad güvenilir
    okunamazdı (`invoice_deleted` dersi)."""
    return f"Banka hesabı silindi: {bank_account_label(bank_name, display_name)}"


# --- HZ-1 T4: ödeme (tahsilat/ödeme) kaydı ---
#
# Kimlik İKİ parçalıdır: FATURA NUMARASI (kaydın sahibi) + HESAP ADI (paranın
# gittiği/geldiği yer). Ödeme UUID'si metne girmez — denetim tablosunda kimse
# UUID okumaz; numara ile hesap birlikte satırı zaten ayırt eder.
#
# 🔴 **TUTAR metne GİRMEZ.** Repoda hiçbir denetim metni para taşımaz
# (`bank_account_*` kanonu: bakiye de girmez). Tutar ödemenin KENDİ satırında
# durur ve günlüğe donmuş bir kopyası düşseydi satır silindiğinde günlükte
# yaşamaya devam eden ikinci bir gerçek olurdu.
#
# 🔴 YENİ `AuditAction` ÜYESİ AÇILMADI (TB3/T3 kanonu): `create`/`delete`
# kullanılır, ayrım METİNDEDİR — "Ödeme kaydı" ile "Fatura" satırları aynı
# `create` altında bile karışmaz.


def payment_label(invoice_no: str, bank_name: str, display_name: str | None) -> str:
    """İki denetim metninin TEK kimlik kaynağı.

    Ayrı ayrı kurulsalardı biri hesap adını unutur ve aynı faturaya iki farklı
    hesaptan girilmiş tahsilatlar günlükte ayırt edilemezdi.
    """
    return f"{invoice_no} · {bank_account_label(bank_name, display_name)}"


def payment_created(invoice_no: str, bank_name: str, display_name: str | None) -> str:
    return f"Ödeme kaydı eklendi: {payment_label(invoice_no, bank_name, display_name)}"


def payment_deleted(invoice_no: str, bank_name: str, display_name: str | None) -> str:
    """Metin `session.delete`ten ÖNCE kurulur: sonra kurulsaydı hem hesap hem
    fatura güvenilir okunamaz ve silinenin NE OLDUĞU kaybolurdu."""
    return f"Ödeme kaydı silindi: {payment_label(invoice_no, bank_name, display_name)}"


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
# 🔴 Kimlik TARİH + AÇIKLAMADIR. Fiş NUMARASI YOKTUR (spec §3b): ne HP'de ne
# E8'de fiş numarası sütunu çizilmiştir, `numbering.py` AÇILMADI. Kimlik teknik
# olarak `id`dir ama denetim tablosunda kimse UUID okumaz — tarih ile açıklama
# birlikte satırı ayırt eder.
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


# --- FIN-1: cek & senet portfoyu ---
#
# Kimlik IKI parcalidir: CEK NO (E10:104, kaydin gorunen kimligi) + KESIDECI
# (E10:105). 🔴 Cek numarasi TEKIL DEGILDIR (K3) — tek basina yazilsaydi ayni
# numarali iki kayit gunlukte AYIRT EDILEMEZDI.
#
# 🔴 **TUTAR metne GIRMEZ.** Repoda hicbir denetim metni para tasimaz
# (`bank_account_*` / `payment_*` kanonu): gunluge donmus bir kopya duserse
# kayit degistiginde ikinci bir gercek olarak yasamaya devam eder.
#
# 🔴 YENI `AuditAction` UYESI ACILMADI (TB3/T3 kanonu): durum gecisi de
# `update`tir, ayrim METINDEDIR — "Durumu degistirildi" cumlesi hedef durumu
# TURKCE etiketiyle tasir, enum degeriyle degil (gunlugu okuyan kullanicidir).


#: Durum etiketleri E10 rozetlerinden BIREBIR (E10:130 `Portfoyde` ·
#: E10:157 `Tahsil Edildi` · E10:86 `Iade / Iptal` karti). `paid` mockup'ta
#: cizilmemistir (E10 yalniz "Alinan Cekler" sekmesini gosterir) — "Odendi"
#: karsi yonun dogal karsiligidir ve K2'de bu adla tanimlidir.
FINANCIAL_INSTRUMENT_STATUS_LABELS: dict[str, str] = {
    "portfolio": "Portföyde",
    "collected": "Tahsil Edildi",
    "paid": "Ödendi",
    "returned": "İade",
    "cancelled": "İptal",
}


def financial_instrument_label(serial_no: str, drawer_name: str) -> str:
    """Dort denetim metninin TEK kimlik kaynagi.

    Ayri ayri kurulsalardi biri kesideciyi unutur ve ayni numarali iki cek
    (farkli banka, farkli yon — K3) gunlukte ayirt edilemezdi.
    """
    return f"{serial_no} · {drawer_name}"


def financial_instrument_created(serial_no: str, drawer_name: str) -> str:
    return f"Çek/senet kaydı oluşturuldu: {financial_instrument_label(serial_no, drawer_name)}"


def financial_instrument_updated(serial_no: str, drawer_name: str) -> str:
    """Metin GUNCELLENMIS degerlerle kurulur: kullanici numarayi duzelttiyse
    gunlukte yeni numara durmalidir, yoksa satir neyin ne oldugunu anlatmaz."""
    return f"Çek/senet kaydı güncellendi: {financial_instrument_label(serial_no, drawer_name)}"


def financial_instrument_status_changed(serial_no: str, drawer_name: str, status: str) -> str:
    """Hedef durum TURKCE etiketiyle yazilir (gunlugu okuyan kullanicidir).

    Bilinmeyen bir enum degeri ham hâliyle basilir: sozlukte bulunamayan bir uye
    metni PATLATMAMALI, ama gorunur de olmalidir — sessizce bosluk basmak yeni
    bir durum eklendiginde gunlugu ANLAMSIZ kilardi.
    """
    etiket = FINANCIAL_INSTRUMENT_STATUS_LABELS.get(status, status)
    kimlik = financial_instrument_label(serial_no, drawer_name)
    return f"Çek/senet durumu değiştirildi: {kimlik} → {etiket}"


def financial_instrument_deleted(serial_no: str, drawer_name: str) -> str:
    """Metin `session.delete`ten ONCE kurulur — sonra kurulsaydi numara ve
    keside guvenilir okunamaz, silinenin NE OLDUGU kaybolurdu."""
    return f"Çek/senet kaydı silindi: {financial_instrument_label(serial_no, drawer_name)}"
