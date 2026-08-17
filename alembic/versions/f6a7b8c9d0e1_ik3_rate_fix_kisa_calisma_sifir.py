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
🔴 KILITLI DONEM KAPISI — SERVIS KORKULUGU ARKADAN DOLANILMAZ
--------------------------------------------------------------------------
`service.upsert_rate` o yilda `approved`/`paid` bir donem varsa oran yazisini
**409** ile reddeder (`guards.RATES_LOCKED_BY_PERIOD`). Gerekcesi K1'dir: oran
satira KOPYALANMAZ (tek gercek kaynak `payroll_rates`) ve `summary.py`/`sgk.py`
isveren tarafini donemin yilina ait CANLI setten turetir — oran degisince
ONAYLANMIS donemin raporlanmis toplamlari ve SGK bildiriminin TAMAMI geriye
donuk degisir. Bir migration'in bu korkulugu arkadan dolanmasi PARA SINIFI bir
kusurdur, o yuzden ayni kapi burada da vardir ve `RuntimeError` ile DURUR.
Sessizce atlamak YASAKTIR ("ayni yesil iki anlam tasir"): operator neyin
engellendigini gormek zorundadir.

🔴 **KAPININ SIRASI ONEMLIDIR.** Once "degisecek satir var mi" olculur.
Degisecek satir YOKSA migration hicbir sey yapmaz ve kapi HIC CALISMAZ — cunku
korunacak bir degisiklik de yoktur. Boylece kapi yalnizca gercekten tehlikeli
olan tek senaryoda ates eder: tohum degeri (`1`) HALA yerinde VE o yilda
kilitli donem VAR. Ters sirada yazilsaydi, hicbir sey degistirmeyecek olan bir
migration bile canlida acilisi kilitlerdi (`Dockerfile:22`
`alembic upgrade head && uvicorn …` — patlayan migration `&&`yi kisa devre
yapar ve **uygulama HIC BASLAMAZ**).

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

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

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
        raise RuntimeError(
            f"IK3-RATE-FIX durduruldu: {TARGET_YEAR} yilinda onaylanmis/odenmis "
            f"{len(kilitli)} bordro donemi var -> {donemler}. "
            f"`short_work_pct` {SEEDED_SHORT_WORK_PCT} -> {CORRECTED_SHORT_WORK_PCT} "
            f"(KK-5) duzeltmesi {len(hedef_satirlar)} oran satirini "
            f"({', '.join(hedef_satirlar)}) etkileyecekti; oran satira "
            "KOPYALANMADIGI icin bu donemlerin raporlanmis isveren yuku ve SGK "
            "bildiriminin TAMAMI geriye donuk degisirdi. `service.upsert_rate` "
            "ayni durumda 409 verir; migration onu arkadan dolanmaz. Once bu "
            "donemlerin geriye donuk degismesi acikca kararlastirilmalidir. "
            "Sema BOZULMADAN birakildi."
        )

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
