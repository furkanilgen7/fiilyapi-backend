r"""fathak canli tutarsiz hakedis faturasi OLCUMU (veri DEGISTIRMEZ)

FAT-HAK — kullanici karari 2026-09-03: bir hakedise baglanan ASIL faturanin
ara toplami (`invoices.subtotal`), hakedisin BRUT tutarina esit olmalidir;
tolerans +/-0,01 TL.

--------------------------------------------------------------------------
NICIN BIR MIGRATION — VE NICIN YALNIZ OLCUM
--------------------------------------------------------------------------
Yeni kapi CANLIDA ZATEN VAR OLAN faturalari da baglar: kural dogmadan once
kesilmis, brutunden sapan bir fatura artik hakedisi `paid` yapamaz (409) ve
`send`/`approve` edilemez (422). "Kac kayit etkilenir" sorusunun cevabi
gelistirme makinesinden OLCULEMEZ (canli DB'ye erisim YOK, WORKFLOW §7); bu
depoda o sorunun tek mesru cevabi olcumu MIGRATION'IN ICINE yazip deploy
gunlugunden okumaktir.

VERI DEGISTIRILMEZ. Duzeltme bir URUN KARARIDIR (faturayi mi duzeltmeli,
hakedisi mi) ve sessizce yapilamaz: hangi tarafin dogru oldugunu yalniz
kullanici bilir. Bu yuzden `raise` de YOKTUR — `Dockerfile` acilista
`alembic upgrade head && uvicorn` kosar ve bir `raise` kisa devre yapip
UYGULAMAYI HIC ACMAZDI (WORKFLOW §7 kanonu: "WARNING dus, BASARIYLA bit").

--------------------------------------------------------------------------
SQL'DEKI TOPLAMA URUNUN IKINCI KOPYASIDIR — VE BILINCLIDIR
--------------------------------------------------------------------------
Urunun tek toplama kopyasi `progress_payments.calculations.gross_total`tur ve
satir tutari CIFT yuvarlanir:

    line_total = round(round(contract_unit_price * coefficient, 2) * quantity, 2)

Asagidaki SQL bunu birebir tekrarlar. Normalde bu YASAKTIR ("iki farkli
dogruluk tanimi"), ama burada iki gerekce onu mesru kilar: (a) migration
uygulandiktan sonra DONMUS bir anlik goruntudur, yasayan bir kural degildir;
(b) alternatifi ORM'i migration icine sokmaktir ve o, uygulama kodu degistikce
uygulanmis bir migration'in davranisini degistirir.

PG `numeric` icin `ROUND(v, 2)` yarim-yukari yuvarlar — `ROUND_HALF_UP` ile
ayni. `float` KULLANILMAZ.

--------------------------------------------------------------------------
SUZGEC: YALNIZ BAGLAYICI FATURALAR
--------------------------------------------------------------------------
Iade faturasi (`document_type = 'refund'`) mesru bicimde ayni kaynaga
baglanabilir ve tutari asil belgeninkinden farkli OLABILIR (kismi iade).
Suzgec bu yuzden `invoicing.models.BINDING_SOURCE_WHERE` ile AYNI metindir;
donmus kopyadir ve bir bekci testi ikisinin esitligini iddia eder.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4d7e1c9f2a3"
down_revision: str | Sequence[str] | None = "a7c2e9d4b6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `invoicing.models.BINDING_SOURCE_WHERE`in DONMUS kopyasi.
WHERE_SQL = "document_type <> 'refund'"

#: Kullanici kararinin toleransi (TL).
TOLERANS = "0.01"

#: Deploy gunlugunde GOZLE aranan greplenebilir imza.
OLCUM_LOG_PREFIX = "FAT-HAK OLCUM"

#: `(aile adi, fatura kaynak kolonu, hakedis tablosu, satir tablosu, satir FK'si)`
#: Kume `treasury.realized.SOURCE_DIRECTION` ile AYNI iki kolondur; kira
#: hakedisi ve siparis kuralin DISINDADIR (kiyaslanabilir bir "brut"leri yok).
AILELER: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "isveren",
        "progress_payment_id",
        "progress_payments",
        "progress_payment_lines",
        "payment_id",
    ),
    (
        "taseron",
        "subcontractor_progress_payment_id",
        "subcontractor_progress_payments",
        "subcontractor_progress_payment_lines",
        "payment_id",
    ),
)


def _olcum_sql(kaynak_kolonu: str, hakedis_tablosu: str, satir_tablosu: str, satir_fk: str):
    """Bir ailenin `(toplam baglayici fatura, ihlalli fatura, en buyuk sapma)` sorgusu."""
    return sa.text(
        "WITH brut AS ("
        "  SELECT h.id AS hakedis_id,"
        "         COALESCE(SUM(ROUND(ROUND(l.contract_unit_price * l.coefficient, 2)"
        f"                * l.quantity, 2)), 0) AS gross"
        f"    FROM {hakedis_tablosu} h"
        f"    LEFT JOIN {satir_tablosu} l ON l.{satir_fk} = h.id"
        "   GROUP BY h.id"
        ")"
        " SELECT count(*) AS baglayici,"
        f"        count(*) FILTER (WHERE abs(i.subtotal - b.gross) > {TOLERANS}) AS ihlalli,"
        f"        COALESCE(MAX(abs(i.subtotal - b.gross)), 0) AS en_buyuk_sapma"
        "   FROM invoices i"
        f"   JOIN brut b ON b.hakedis_id = i.{kaynak_kolonu}"
        f"  WHERE i.{kaynak_kolonu} IS NOT NULL AND {WHERE_SQL}"
    )


def upgrade() -> None:
    """SALT OKUMA. Sonuc deploy gunlugune yazilir; sema ve veri DEGISMEZ."""
    logger = logging.getLogger("alembic.runtime.migration")
    baglanti = op.get_bind()

    toplam_ihlal = 0
    for aile, kaynak_kolonu, hakedis_tablosu, satir_tablosu, satir_fk in AILELER:
        satir = baglanti.execute(
            _olcum_sql(kaynak_kolonu, hakedis_tablosu, satir_tablosu, satir_fk)
        ).one()
        toplam_ihlal += satir.ihlalli
        logger.warning(
            "%s %s: baglayici_fatura=%s ihlalli=%s en_buyuk_sapma=%s",
            OLCUM_LOG_PREFIX,
            aile,
            satir.baglayici,
            satir.ihlalli,
            satir.en_buyuk_sapma,
        )

    if toplam_ihlal:
        logger.warning(
            "%s SONUC: %s adet CANLI fatura yeni tutar kapisini GECEMEZ — "
            "bu hakedisler `mark-paid` (409) ve `send`/`approve` (422) alacaktir. "
            "Duzeltme URUN KARARIDIR, bu migration veri DEGISTIRMEZ.",
            OLCUM_LOG_PREFIX,
            toplam_ihlal,
        )
    else:
        logger.warning(
            "%s SONUC: ihlalli fatura YOK, kapi hicbir kaydi kilitlemiyor.", OLCUM_LOG_PREFIX
        )


def downgrade() -> None:
    """NO-OP — yukari yon veri yazmadi, geri alinacak bir sey yok."""
