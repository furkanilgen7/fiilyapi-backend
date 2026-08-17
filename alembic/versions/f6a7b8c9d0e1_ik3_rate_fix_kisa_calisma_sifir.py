"""ik3 rate fix kisa calisma orani sifir (KK-5)

IK3-RATE-FIX — 2026 oran tohumundaki `short_work_pct` degerini **1 → 0** ceker.

🔴 **BU BIR TOHUM DEGIL, VERI DUZELTMESIDIR.** 2026 oran tohumu
`c5d6e7f8a9b0` (İK-3 cekirdegi) icinde ZATEN basiliyor ve canlida uygulanmis
durumda (`RATE_SEED_2026`, 4 satir). Ikinci bir tohum migration'i
`ON CONFLICT DO NOTHING` altinda HICBIR SEY yapmazdi: satirlar zaten var,
cakisma atlanir ve yanlis deger yerinde kalirdi. Bu yuzden burada `INSERT`
degil hedefli bir `UPDATE` kosar.

🔑 **KK-5 (kullanici karari, 2026-08-16): "SGK %1 kisa calisma odenegi YOK,
hesaplanmaz."** `c5d6e7f8a9b0:102` bu orani mockup etiketine (SGK 81 "Kisa
Calisma Odenegi (%1)") bakarak `1` basmisti; mevzuatta ayri bir "%1 kisa
calisma primi" YOKTUR. Karar yalniz "satiri basmamakla" uygulanamaz —
`short_work_total`, `sgk.py`de `_RATE_FIELDS[4:]` uzerinden
`employer_burden_total`in ICINDE tasiniyor ve `summary.py`nin maliyet tabanini
brutun %1'i kadar sisiriyor. Dogru cozum oranin `0` OLMASIDIR;
`models.py:276` `short_work_pct >= 0` CHECK'i `0`i acikca yasal kilar.

--------------------------------------------------------------------------
🔴 `= 1` KOSULU ZORUNLUDUR — KULLANICININ KENDI DEGERI EZILMEZ
--------------------------------------------------------------------------
`UPDATE ... SET short_work_pct = 0 WHERE year = 2026` kosulsuz yazilsaydi,
kullanicinin `PUT /payroll/rates/2026/{source}` ile ELLE girdigi bir deger de
sessizce silinirdi. Duzeltilmesi gereken yalniz TOHUMUN bastigi `1`dir; baska
her deger kullanicinin iradesidir ve dokunulmaz. (MU-SEED'in
`ON CONFLICT DO NOTHING` kararinin buradaki karsiligi budur.)

--------------------------------------------------------------------------
🔴 KILITLI DONEM KAPISI — DURDURMAZ, **ATLAR ve BAGIRIR** (yonetim karari)
--------------------------------------------------------------------------
`service.upsert_rate` o yilda `approved`/`paid` bir donem varsa oran yazisini
**409** ile reddeder (`guards.RATES_LOCKED_BY_PERIOD`). Gerekcesi K1'dir: oran
satira KOPYALANMAZ (tek gercek kaynak `payroll_rates`) ve `summary.py`/`sgk.py`
isveren tarafini donemin yilina ait CANLI setten turetir — oran degisince
ONAYLANMIS donemin raporlanmis toplamlari ve SGK bildiriminin TAMAMI geriye
donuk degisirdi. Ayni olgu burada da korunur.

🔴 **AMA TEPKI `RuntimeError` DEGILDIR.** Ilk tasarim DURDURUYORDU; yonetim
bunu degistirdi ve gerekcesi baglayicidir:

1. Migration'in durmasi = `alembic upgrade head` patlar = **uygulama HIC
   ACILMAZ** (`Dockerfile:22` `alembic upgrade head && uvicorn …` — patlayan
   migration `&&`yi kisa devre yapar). Bu, gecen turda PG 16/18 enum tuzagiyla
   kil payi onlenen **URETIM KESINTISI** sinifinin aynisidir. Bir KORKULUK,
   korudugu seyden daha buyuk bir hasar uretemez.
2. Veri riski deneme verisinde sifira yakindir: bordro ekrani bugune kadar
   yoktu (F-BOR yeni merge edildi), donem onaylamak icin dogrudan API cagirmak
   gerekirdi.
3. Canli DB OLCULEMIYOR (yetki disi). Olculemeyen bir olguya "uygulamayi
   acmama" riski baglanamaz.
4. **KK-8** (2026-08-17): "gecmis donemler donmus kalsin, duzeltme yolu
   acilmasin." Kilitli bir yili ATLAMAK bu kararla TUTARLIDIR; durmak degil.

🔴 **SESSIZ ATLAMA YASAK** ("ayni yesil iki anlam tasir"): atlama ERROR
duzeyinde, tek satirda, gozle bulunabilir bir kayit birakir. `alembic.ini` kok
logger'i WARNING/stderr'dir ve `alembic` logger'i INFO'dur → ERROR her iki
yoldan da Railway deploy gunlugune duser.

🔴 **ATLAMA KALICIDIR — ACIK BORC.** Alembic bir revizyonu BIR KEZ kosar;
atlanan duzeltme o veritabaninda **bir daha calismaz**. Yil sonradan kilitten
ciksa bile kendiliginden uygulanmaz ve `upsert_rate` de o yila 409 verir. Bu
yuzden gunluk satiri operatore ne yapmasi gerektigini de yazar.

🔴 **KAPININ SIRASI ONEMLIDIR.** Once "degisecek satir var mi" olculur.
Degisecek satir YOKSA migration hicbir sey yapmaz ve kapi HIC CALISMAZ — cunku
korunacak bir degisiklik de yoktur. Boylece gurultu yalnizca gercekten anlamli
oldugu senaryoda cikar: tohum degeri (`1`) HALA yerinde VE o yilda kilitli
donem VAR.

--------------------------------------------------------------------------
🔴 DOWNGRADE NO-OP'TUR — VERI KAPISININ BURADAKI BICIMI
--------------------------------------------------------------------------
Downgrade `short_work_pct`i `1`e GERI YAZMAZ. Geri yazmak, kullanicinin
acikca reddettigi (KK-5) yanlis bir orani geri getirmek ve ondan sonraki her
bordro hesabini yeniden sismis uretmek olurdu — yani "geri alma" adi altinda
veri BOZMA. Ustelik geri yazma, bu migration'dan SONRA kullanicinin elle
girdigi bir degeri de ezerdi (`= 0` kosulu bile ayirt edemezdi: 0 hem bizim
yazdigimiz hem kullanicinin yazabilecegi bir degerdir).

Bu migration SEMA DEGISTIRMEZ; geri alinacak yapisal bir sey yoktur ve
downgrade semayi BOZMADAN birakir. `upgrade → downgrade → upgrade` turu bu
sayede guvenlidir ve ikinci `upgrade` PATLAMAZ (idempotent: `= 1` kosulu
ikinci kosuda hicbir satir bulmaz).

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-17

"""

import logging
from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

#: `alembic.ini` kok logger'i WARNING/stderr, `alembic` logger'i INFO'dur →
#: ERROR her iki yoldan da Railway deploy gunlugune duser. `alembic.runtime`
#: altinda durur ki migration ciktisiyla ayni akista okunsun.
logger = logging.getLogger("alembic.runtime.migration")

#: Atlama satirinin GREPLENEBILIR imzasi — deploy gunlugunde gozle aranir.
SKIP_LOG_PREFIX = "IK3-RATE-FIX ATLANDI"

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Duzeltilen yil. `c5d6e7f8a9b0:123` `RATE_SEED_YEAR` ile AYNI olmak
#: zorundadir: duzeltilen sey tam olarak o migration'in bastigi tohumdur.
TARGET_YEAR = 2026

#: Tohumun bastigi YANLIS deger (`c5d6e7f8a9b0:102`). `UPDATE`in `WHERE`i
#: budur — baska her deger kullanicinin iradesidir.
SEEDED_SHORT_WORK_PCT = Decimal("1")

#: KK-5'in bagladigi DOGRU deger.
CORRECTED_SHORT_WORK_PCT = Decimal("0")

#: Oran yazisini engelleyen donem durumlari — `service.LOCKED_PERIOD_STATUSES`
#: ile ayni kume. Migration uygulama kodunu IMPORT ETMEZ (uygulanmis bir
#: migration DONMUS olmalidir, uygulama kodu zamanla degisir — `a477fdf00fdf`
#: kanonu), bu yuzden deger KOPYALANMISTIR.
LOCKED_PERIOD_STATUSES = ("approved", "paid")


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Degisecek satir var mi? Yoksa migration NO-OP'tur ve kapi hic
    #    calismaz (docstring: "KAPININ SIRASI ONEMLIDIR").
    hedef_satirlar = (
        bind.execute(
            sa.text(
                "SELECT personnel_source::text FROM payroll_rates "
                "WHERE year = :year AND short_work_pct = :seeded "
                "ORDER BY personnel_source"
            ),
            {"year": TARGET_YEAR, "seeded": SEEDED_SHORT_WORK_PCT},
        )
        .scalars()
        .all()
    )
    if not hedef_satirlar:
        return

    # 2. KILITLI DONEM KAPISI — servis korkulugunun (409) migration karsiligi.
    kilitli = bind.execute(
        sa.text(
            "SELECT month, status::text FROM payroll_periods "
            "WHERE year = :year AND status = ANY(:statuses) ORDER BY month"
        ),
        {"year": TARGET_YEAR, "statuses": list(LOCKED_PERIOD_STATUSES)},
    ).all()
    if kilitli:
        donemler = ", ".join(f"{TARGET_YEAR}-{month:02d} ({status})" for month, status in kilitli)
        # 🔴 SESSIZ ATLAMA YASAK — tek satir, ERROR duzeyinde, gozle bulunabilir.
        #    Bu cagri ile asagidaki `return` AYRI kusur siniflaridir ve AYRI
        #    testlerle cakilidir: sinyali susturmak da atlamayi kaldirmak da
        #    kendi testini kirmizi yapar.
        logger.error(
            "%s: %s yilinda onaylanmis/odenmis %d bordro donemi var (%s) -> "
            "`short_work_pct` %s -> %s (KK-5) duzeltmesi bu yil icin ATLANDI. "
            "Etkilenecek %d oran satiri (%s) DOKUNULMADAN birakildi, degeri %s "
            "olarak KALDI. Gerekce: oran satira kopyalanmaz, degistirilseydi bu "
            "donemlerin raporlanmis isveren yuku ve SGK bildiriminin TAMAMI "
            "geriye donuk degisirdi (KK-8: gecmis donemler donmus kalir). "
            "🔴 BU DUZELTME BU VERITABANINDA BIR DAHA CALISMAYACAK (alembic "
            "revizyonu bir kez kosar): yil kilitten ciksa bile kendiliginden "
            "uygulanmaz. Duzeltme isteniyorsa acikca kararlastirilip elle "
            "yapilmalidir.",
            SKIP_LOG_PREFIX,
            TARGET_YEAR,
            len(kilitli),
            donemler,
            SEEDED_SHORT_WORK_PCT,
            CORRECTED_SHORT_WORK_PCT,
            len(hedef_satirlar),
            ", ".join(hedef_satirlar),
            SEEDED_SHORT_WORK_PCT,
        )
        # 🔴 ATLA — DURMA. Migration basariyla devam eder ve uygulama ACILIR.
        return

    # 3. Hedefli duzeltme. `= :seeded` kosulu ZORUNLU: kullanicinin elle
    #    girdigi baska bir deger EZILMEZ.
    op.execute(
        sa.text(
            "UPDATE payroll_rates SET short_work_pct = :corrected, updated_at = now() "
            "WHERE year = :year AND short_work_pct = :seeded"
        ).bindparams(
            corrected=CORRECTED_SHORT_WORK_PCT,
            year=TARGET_YEAR,
            seeded=SEEDED_SHORT_WORK_PCT,
        )
    )


def downgrade() -> None:
    """Downgrade schema.

    🔴 KASITLI NO-OP — gerekcesi modul docstring'inde ("DOWNGRADE NO-OP'TUR").
    Kisaca: `short_work_pct`i `1`e geri yazmak, kullanicinin KK-5 ile acikca
    reddettigi yanlis orani geri getirmek ve bu migration'dan sonra elle
    girilmis bir degeri ezmek olurdu. Sema degismedigi icin geri alinacak
    yapisal bir sey de yoktur.
    """
