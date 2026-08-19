"""Santiye/bolum KOD URETIMI (spec §3.2 · P6 §5).

🔴 `_next_site_code` `projects.service` tarafindan da YENIDEN KULLANILIR
(kopya kod uretimi yok) — bu yuzden kendi dosyasinda durur."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import today
from app.modules.sites import repository

# Santiye kodu oneki (spec §3.2, mockup satir 67 yer tutucusu `SNT-2026-003`).
_SITE_CODE_PREFIX = "SNT"

# Bolum kodu oneki + hane sayisi (P6 §5, `Form - Bolum Ekle` satir 68 yer
# tutucusu `BLM-06`). Iki hane MUCBIR SINIR DEGILDIR: 99'u asan bir santiyede
# `:02d` kendiliginden uc haneye tasar, kod uretimi durmaz.
_SECTION_CODE_PREFIX = "BLM"
_SECTION_CODE_DIGITS = 2


async def _next_site_code(session: AsyncSession) -> str:
    """SNT-{YYYY}-{NNN} uretir (spec §3.2): o yilin en buyuk sirasi + 1, 3 hane, 1'den.

    `projects.service._next_project_code` deseninin birebiri:

    * **Sayimla DEGIL maksimum+1** — silinen kod yeniden kullanilmaz.
    * **Kapsam SIRKET GENELI**: sorgu `project_id` suzgeci TASIMAZ. Iki farkli
      projede ayni `SNT-2026-003` kullaniciyi yaniltir; kod evrakta kurumsal
      kimlik gibi okunur.
    * Sayisal soneki ayristirilamayan kodlar (canlidaki ad-turevi `A-BLOK`,
      `MERKEZ`) sessizce ATLANIR — hata uretmez, sayaci kaydirmaz. Bu kodlara
      hicbir `UPDATE` yazilmaz, yerlerinde kalirlar.

    Yaris durumunda `uq_sites_project_code` ihlali mevcut IntegrityError -> 409
    isleyicisine dusar; otomatik yeniden deneme YAPILMAZ (spec §8.3).
    """
    prefix = f"{_SITE_CODE_PREFIX}-{today().year}-"
    codes = await repository.list_codes_with_prefix(session, prefix)
    max_seq = 0
    for code in codes:
        suffix = code[len(prefix) :]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return f"{prefix}{max_seq + 1:03d}"


async def _next_section_code(session: AsyncSession, site_id: uuid.UUID) -> str:
    """`BLM-NN` uretir (P6 §5): SANTIYE ICINDEKI en buyuk sira + 1, 2 hane, 1'den.

    `_next_site_code` deseninin birebiri — ayni uc ozellik gecerlidir:

    * **Sayimla DEGIL maksimum+1** — silinen kod yeniden kullanilmaz ve elle
      verilmis `BLM-06` sayaci ilerletir (sonraki otomatik kod `BLM-07`'dir).
    * Sayisal soneki ayristirilamayan kodlar (canlidaki ad-turevi `GENEL`)
      sessizce ATLANIR — hata uretmez, sayaci kaydirmaz, `UPDATE` almazlar.
    * Yaris durumunda kismi indeks `uq_sections_site_code` ihlali mevcut
      IntegrityError -> 409 isleyicisine duser; otomatik yeniden deneme YAPILMAZ.

    TEK FARK kapsamdir: santiye sayaci sirket geneli, bolum sayaci SANTIYE
    ICIDIR — gerekcesi `repository.list_section_codes_with_prefix` docstring'inde.
    """
    prefix = f"{_SECTION_CODE_PREFIX}-"
    codes = await repository.list_section_codes_with_prefix(session, site_id, prefix)
    max_seq = 0
    for code in codes:
        suffix = code[len(prefix) :]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return f"{prefix}{max_seq + 1:0{_SECTION_CODE_DIGITS}d}"
