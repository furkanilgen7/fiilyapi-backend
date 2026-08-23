"""Denetim metinleri — hazine: banka/kasa hesabi, odeme (HZ-1 T3/T4) + cek/senet (FIN-1)."""

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
