"""izin kapsami: UYGULANMAYAN kapsamlar `all`a cekilir

Kullanici karari 2026-09-19. `role_permissions.scope` DEKORATIFTI: alti degeri
vardi, hicbiri hicbir ucta OKUNMUYORDU ve Izin Matrisi ekrani "Kendi / Proje /
Stok / Sinirli / Mali" etiketlerini YAZIYLA vaat ediyordu.

Olcum sonrasi UC kapsam matristen DUSTU (gerekcelerin tam hali
`tests/modules/test_izin_kapsami_bekcisi.py` docstring'indedir):

  own     — uygulanmasi KUSUR olurdu. `GET /approvals` bilerek kapisizdir ve
            `_pending_filter`in "Bekci 5"i senin ACTIGIN zinciri senin onay
            kutundan ZATEN CIKARIR. `created_by == aktor` suzgeci o bekciyi
            TERS CEVIRIRDI.
  project — FAZLALIK. Proje kapsami `UserProjectAccess`ten surulur ve
            `progress_payments` ile `approvals` onu ZATEN uygular.
  stock   — onay kutusu zaten kisiseldir.

Geriye UYGULANACAK iki kapsam kalir: `limited` ve `finance`.

## 🔴 NEDEN MIGRATION SART

`roles/seed_data.py` IDEMPOTENTTIR (`existing_permission_pairs`): seed matrisini
duzeltmek CANLI satirlari DEGISTIRMEZ. Migration kosmazsa canlida `own`/
`project`/`stock` tasiyan satirlar KALIR ve servisteki fren "mevcut kapsami geri
gondermek serbesttir" dedigi icin o satirlar SONSUZA DEK yasardi.

## Enum TIPI DARALTILMAZ

`scope` PG enum'udur; uyelerini dusurmek tip yeniden yazmayi (RENAME + CREATE +
ALTER COLUMN + DROP) ve OpenAPI kirmasini gerektirir. Bu migration YALNIZ VERIYI
duzeltir; uc tarafindaki kapiyi `roles/service.py` fail-closed olarak kapatir
(uygulanmayan kapsam ARTIK HIC yazilamaz). Tipin daraltilmasi ayri bir dilimin
isidir ve tek basina bir fayda uretmez.

## Geri alma

`downgrade` NO-OP'tur ve bu bilinclidir: hangi satirin ESKIDEN hangi uygulanmayan
kapsami tasidigi BILGISI bu migration'dan once de bir ise yaramiyordu (kimse
okumuyordu). Onu geri yazmak, silinen bir yalani yeniden kurmak olurdu.
"""

from alembic import op

revision = "b2c3d4e5f8a1"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None

#: 1) HER MODULDE dusen kapsamlar. `app/core/access.py::DROPPED_SCOPES` ile AYNI
#:    kumedir; migration app kodunu import ETMEZ (donmus olmali), bu yuzden
#:    esitligi `tests/modules/test_seed_migration_matches_seed_data.py` bekciler.
DUSEN = ("own", "project", "stock")

#: 2) KAPSAM KISITI TAMAMEN KALKAN MODUL. `finance` genel olarak DUSMEZ (baska
#:    modullerde uygulanacak) ama `approvals`ta da anlamsizdir: onay kutusunda
#:    tutari gizlemek IMZAYI imkansiz kilar. Bu yuzden hedefli ikinci adim.
KAPSAMSIZ_MODUL = "approvals"


def upgrade() -> None:
    op.execute(
        "UPDATE role_permissions SET scope = 'all' "
        f"WHERE scope IN ({', '.join(repr(d) for d in DUSEN)})"
    )
    op.execute(
        "UPDATE role_permissions SET scope = 'all' WHERE module_id IN "
        f"(SELECT id FROM modules WHERE key = '{KAPSAMSIZ_MODUL}')"
    )


def downgrade() -> None:
    """NO-OP — gerekcesi modul docstring'inde."""
