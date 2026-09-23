"""🔴 YAPISAL BEKÇİ (kayıt 2 + 3, `kalan_is` madde "YAPISAL BEKÇİ"): yeni bir
`deferrable=True` kısıt sessizce eklenemez.

## Neden bu bekçi var

`app/core/db.py:83`teki `await session.commit()` `get_db`nin TEARDOWN'undadır.
`get_db` bir async generator olduğu için FastAPI onu hesaplanmış
`scope="request"` ile ele alır (ölçüldü:
`.venv/.../fastapi/dependencies/models.py:229-234` `_get_computed_scope`),
yani teardown `routing.py:145`teki `await response(scope, receive, send)`ten
SONRA çalışır (ayrıca `tests/core/test_teardown_commit_http_olcum.py`de gerçek
bir uvicorn sunucusuyla ÖLÇÜLDÜ: istemci `200 {"ok": true}` görüyor, sunucu
`ERROR: Exception in ASGI application` logluyor — kayıtlı hiçbir exception
handler ÇAĞRILMIYOR).

`DEFERRABLE INITIALLY DEFERRED` bir UNIQUE kısıt tam olarak bu pencereyi açar:
ihlal `flush()`ta DEĞİL, transaction COMMIT'inde patlar — yani tam bu
teardown'da. Bugün iki böyle kısıt var ve İKİSİ DE ayrı bir mekanizmayla
korunuyor:

* `site_plan_rows` (`uq_site_plan_rows_site_kind_section_label`) —
  `write.save_rows` her yazmada `repository.enforce_row_uniqueness_now` ile
  `SET CONSTRAINTS ... IMMEDIATE` çalıştırır (`site_planning/write.py:143`),
  yani ihlal artık `flush()`ta patlar ve normal `IntegrityError` yoluna
  (409) girer — teardown'a hiç ulaşmaz.
* `boq_item_section_allocations` (`uq_boq_item_section_allocations_item_section`)
  — `repository.lock_item` poz satırını `FOR UPDATE` kilitler ve UQ anahtarı
  poz-başınadır; çapraz-istek yarışı bu kilitle SERİLEŞTİRİLİR, ihlal fiilen
  hiç doğmaz.

Bu bekçi YENİ bir `deferrable=True` kısıtın bu ALLOWLIST'e bilerek
eklenmesini zorunlu kılar — eklenmezse test KIRMIZI olur ve yazarı yukarıdaki
iki desenden birini (ya da `Depends(get_db, scope="function")` geçişini)
seçmeye iter.

⚠️ Bu bekçi teardown deliğini KAPATMAZ (o `app/core/db.py`nin 362 çağrı
yerini etkileyen daha büyük bir onarım ister, bkz. ölçüm raporu). Yalnız
deliğin SESSİZCE BÜYÜMESİNİ engeller.
"""

from __future__ import annotations

from sqlalchemy import UniqueConstraint

import app.main  # noqa: F401  — tüm modelleri import ederek Base.metadata'yı doldurur
from app.core.db import Base

#: (tablo_adı, kısıt_adı) -> korunma mekanizmasının kısa açıklaması.
#: Yeni bir satır eklerken açıklama alanı BOŞ bırakılmaz; bu dosyanın
#: docstring'i güncellenmelidir.
BILINEN_DEFERRABLE_KISITLAR: dict[tuple[str, str], str] = {
    (
        "site_plan_rows",
        "uq_site_plan_rows_site_kind_section_label",
    ): "write.save_rows -> repository.enforce_row_uniqueness_now (SET CONSTRAINTS IMMEDIATE)",
    (
        "boq_item_section_allocations",
        "uq_boq_item_section_allocations_item_section",
    ): "repository.lock_item (FOR UPDATE poz satır kilidi, UQ anahtarı poz-başına)",
}


def _metadata_deferrable_kisitlari() -> set[tuple[str, str]]:
    bulunanlar: set[tuple[str, str]] = set()
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if not isinstance(constraint, UniqueConstraint):
                continue
            if not constraint.deferrable:
                continue
            assert constraint.name is not None, (
                f"Adsız deferrable UQ kısıt bulundu ({table.name}); bekçi yalnız "
                "adlandırılmış kısıtları izleyebilir."
            )
            bulunanlar.add((table.name, constraint.name))
    return bulunanlar


def test_YENI_deferrable_kisit_allowlistsiz_eklenemez() -> None:
    """🔴 ASIL BEKÇİ. Mutasyon: allowlist'ten bir satır silinirse ya da
    modelde yeni bir `deferrable=True` UQ eklenip allowlist'e işlenmezse bu
    test KIRMIZI olur."""
    bulunanlar = _metadata_deferrable_kisitlari()
    bilinen = set(BILINEN_DEFERRABLE_KISITLAR)

    yeni_ve_korunmasiz = bulunanlar - bilinen
    assert not yeni_ve_korunmasiz, (
        "YENİ bir deferrable=True UNIQUE kısıt bulundu ama ALLOWLIST'te yok: "
        f"{yeni_ve_korunmasiz}. Bu kısıt `app/core/db.py:83`teki teardown "
        "commit'inde patlayabilir ve istemci 200 görüp veri hiç yazılmamış "
        "olabilir (bkz. tests/core/test_teardown_commit_http_olcum.py). "
        "Ya `site_plan_rows` desenini (SET CONSTRAINTS IMMEDIATE) ya da "
        "`boq_item_section_allocations` desenini (FOR UPDATE serileştirme) "
        "uygula, sonra bu dosyadaki BILINEN_DEFERRABLE_KISITLAR'a ekle."
    )

    artik_yok = bilinen - bulunanlar
    assert not artik_yok, (
        f"Allowlist'te olup metadata'da artık bulunmayan kısıt(lar): {artik_yok}. "
        "Kısıt kaldırıldıysa (ör. migration ile) bu satırı da BILINEN_DEFERRABLE_KISITLAR'dan sil."
    )
