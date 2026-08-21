"""Zincirin TANIMI — KODDA, veritabaninda DEGIL (sozlesme Y0/T2).

Adim listesi bir URUN KURALIDIR: hangi evragi kimin sirayla imzaladigi,
kullanicinin ekrandan degistirecegi bir sey degildir. DB'ye konsaydi kimsenin
cizmedigi bir duzenleme yuzeyi acilir ve "zincir bozuk" hatalari calisma
zamaninda dogardi. AYARDAN okunan TEK sey ESIKTIR (K3).

Mockup kaniti (`projedesign/Onay Kutusu.dc.html`):
  * `:120-144`  taseron hakedisi — Santiye Sefi -> Proje Muduru -> Muhasebe
  * `:150-178`  satinalma talebi — Satinalma -> Proje Muduru -> Muhasebe
  * `:210-240`  isveren hakedisi — Muhasebe
  * `:60-66`    "Patron · Final onay > ₺500K" / "₺500K alti -> PM + Muhasebe yeterli"
"""

from decimal import Decimal

from app.modules.approvals.models import ApprovalDocumentType, ApprovalRole

__all__ = [
    "CHAIN_DEFINITIONS",
    "DEFAULT_APPROVAL_THRESHOLD_TRY",
    "DOCUMENT_PERMISSION_MODULE",
    "PATRON_ROLE",
    "step_roles",
]

#: Esik ALTI zincirler. Esik asilirsa SONA `patron` adimi EKLENIR.
CHAIN_DEFINITIONS: dict[ApprovalDocumentType, tuple[ApprovalRole, ...]] = {
    ApprovalDocumentType.subcontractor_progress_payment: (
        ApprovalRole.site_chief,
        ApprovalRole.project_manager,
        ApprovalRole.accounting,
    ),
    ApprovalDocumentType.purchase_request: (
        ApprovalRole.procurement,
        ApprovalRole.project_manager,
        ApprovalRole.accounting,
    ),
    ApprovalDocumentType.progress_payment: (ApprovalRole.accounting,),
}

PATRON_ROLE = ApprovalRole.patron

#: 🔴 Esigin TEK sayisal kaynagi: `company.approval_threshold_try` kolonunun
#: `server_default`i de budur. `procurement/transitions.py`deki eski
#: `APPROVAL_THRESHOLD_TRY` sabiti KALDIRILDI (R6) — iki esik bir arada
#: yasasaydi kacinilmaz olarak ayrisir ve ayni tutar satinalmada esigin altinda,
#: onay zincirinde ustunde sayilirdi.
DEFAULT_APPROVAL_THRESHOLD_TRY = Decimal("500000.00")

#: "Kendi evraki" istisnasinin (bekci 5) bakacagi IZIN MODULU. `admin` seviyesi
#: EVRAGIN modulunde aranir: onay kutusunun kendi modulunde (`approvals`) admin
#: olmak, hakedisin uzerinde soz sahibi olmak demek DEGILDIR.
DOCUMENT_PERMISSION_MODULE: dict[ApprovalDocumentType, str] = {
    ApprovalDocumentType.subcontractor_progress_payment: "progress_payments",
    ApprovalDocumentType.purchase_request: "procurement",
    ApprovalDocumentType.progress_payment: "progress_payments",
}


def step_roles(
    document_type: ApprovalDocumentType, amount: Decimal | None, threshold: Decimal
) -> tuple[ApprovalRole, ...]:
    """Zincirin adim rolleri — esik degerlendirmesi BURADA, tek yerde.

    🔴 SINIR (R4): `amount >= threshold` ise Patron adimi EKLENIR. Yani TAM
    esik degeri (bugun ₺500.000) USTE dusher. Mockup sinirin hangi tarafa
    dustugunu SOYLEMEZ; mevcut kod (eski `procurement/transitions.py`
    `if total < THRESHOLD ... return`) bu yonu zaten uyguluyordu ve iki yuzey
    arasinda sessiz bir fark birakmamak icin ayni yon secildi.

    🔴 NULL-ESIK / FAIL-CLOSED (SA kanonu): `amount is None` "belirlenemedi"
    demektir ve BUYUK sayilir. Kucuk sayilsaydi ₺2M'lik bir evrak tek bir alan
    bos birakilarak Patron adimini atlardi — SA'da bu yol FIILEN bulunmustu.
    """
    roles = CHAIN_DEFINITIONS[document_type]
    if amount is None or amount >= threshold:
        return (*roles, PATRON_ROLE)
    return roles
