"""Denetim metinleri — bordro (IK-3 T3/T4/T5): donem, satir, onay/odeme, SGK."""

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


# TB6 T1 — tarife de KULLANICININ KENDI GIRDISIDIR (turemez), o hâlde oran
# satirinin ISTISNASI burada da gecerlidir: DEGERLER YAZILIR. "TUTAR metne
# girmez" kurali TUREV paralar icindir; dilim esigi bir tutar degil, mevzuatin
# kendisidir ve tabloda yalnizca SON hali durur.
def payroll_tax_brackets_updated(
    year: int, income_kind: str, brackets: list[tuple[int, object, object]], is_active: bool
) -> str:
    dilimler = " · ".join(
        f"{ordinal}: {'üstü' if ust is None else ust} → %{oran}" for ordinal, ust, oran in brackets
    )
    durum = "aktif" if is_active else "pasif"
    return f"Gelir vergisi tarifesi güncellendi: {year}/{income_kind} ({durum}) · {dilimler}"
