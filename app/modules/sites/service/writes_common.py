"""Yazma uclarinin PAYLASILAN yardimcilari — santiye ve bolum ikisi de okur.

Iki kopya zamanla ayrisir: `_resolve_user_name` FK -> ad anlik goruntusunu,
`_merged_for_validation` ise PATCH'in BIRLESIK dogrulama kaydini TEK yerde
kurar (santiye `update_site` + bolum `update_section`)."""

import uuid
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import SiteValidationError
from app.modules.sites import guards, repository


async def _resolve_user_name(session: AsyncSession, user_id: uuid.UUID) -> str:
    """Verilen kullanicinin `full_name` anlik goruntusunu doner (spec §9).

    Yok ya da pasifse 422 — 404 DEGIL: istenen kaynak santiyedir, kullanici
    burada bir ALAN DEGERIDIR. 404 donmek "bu UUID'li kullanici yok" bilgisini
    santiye ucundan sizdirmak olurdu.

    IZINLI (`on_leave`) personel ATANABILIR: gerekcesi
    `repository.get_assignable_user` docstring'inde (karar 2026-07-30).
    """
    user = await repository.get_assignable_user(session, user_id)
    if user is None:
        raise SiteValidationError(guards.USER_NOT_FOUND)
    return user.full_name


def _merged_for_validation(
    row: object, changes: dict, fields: tuple[str, ...], **extra: object
) -> SimpleNamespace:
    """Mevcut satir + patch = dogrulamanin gordugu kayit (§5.3).

    Yalniz patch'i dogrulamak yanlis olurdu: `end_date` gonderilip `start_date`
    satirda duruyorsa ters tarih araligi FARK EDILMEDEN gecerdi. Yalniz satiri
    dogrulamak da yanlis olurdu: yayina gecirirken eksik alani AYNI istekte
    gonderen kullanici haksiz yere reddedilirdi.

    SANTIYE VE BOLUM PAYLASIR (P6 T5): iki PATCH da ayni birlestirme kuralina
    ihtiyac duyar ve ikinci bir kopya zamanla ilkinden ayrisirdi. Fark yalnizca
    okunan ALAN LISTESIDIR; `extra` ise dogrulayicinin bekledigi ama satirdan
    turemeyen alanlara ayrilmistir (`validate_site` icin `sections=[]`:
    bolumler PATCH govdesinde YOKTUR (§7.3) ve mevcut bolumleri yeniden
    dogrulamak bu istegin isi degildir).
    """
    merged = {field: changes.get(field, getattr(row, field)) for field in fields}
    return SimpleNamespace(**merged, **extra)
