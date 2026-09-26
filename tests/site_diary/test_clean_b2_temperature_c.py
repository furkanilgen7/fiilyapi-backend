"""CLEAN-B2 — `site_diary_entries.temperature_c` modelden ve yazıcısından KALKTI.

Genişlet/daralt'ın daralt adımı. Bekçiler:
* Model kolonu da, CHECK'i de TAŞIMAZ (`Base.metadata` — test DB'si `create_all` ile
  bundan kurulur, yani bu aynı zamanda test şemasıdır).
* `app/` içinde `temperature_c` adı YALNIZ eski istemci reddinde (`schemas.py`,
  `TEMPERATURE_C_REMOVED`, API sözleşmesi) geçer: servis yazıcısı
  (`_sync_legacy_temperature`) ya da başka bir yazıcı geri gelirse kırmızı.

Mutasyon: `models.py`ye `temperature_c` mapped kolonunu ya da `service.py`ye
`_sync_legacy_temperature`i geri koy → bu dosya kırmızı.
"""

from pathlib import Path

from app.modules.site_diary.models import SiteDiaryEntry

APP_DIR = Path(__file__).parents[2] / "app"
LEGACY = "temperature_c"
LEGACY_CHECK = "ck_site_diary_entries_temperature_range"
#: Adın geçmesine izin verilen TEK dosya: eski istemciye açık 422 (API sözleşmesi KALIR).
ALLOWED = {APP_DIR / "modules" / "site_diary" / "schemas.py"}


def test_model_temperature_c_kolonu_ve_checki_tasimaz() -> None:
    table = SiteDiaryEntry.__table__
    assert LEGACY not in table.c
    assert LEGACY not in SiteDiaryEntry.__mapper__.attrs
    assert LEGACY_CHECK not in {c.name for c in table.constraints}


def test_app_icinde_temperature_c_yalniz_eski_istemci_reddinde_gecer() -> None:
    hits = sorted(
        f"{path.relative_to(APP_DIR.parent)}:{no}"
        for path in APP_DIR.rglob("*.py")
        if path not in ALLOWED
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if LEGACY in line
    )
    assert hits == []
