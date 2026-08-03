"""Şantiye günlüğü durum makinesi (T4; spec §2, §3).

## Tablo İKİ hücreden ibarettir

| Durum       | `submit`              | `reopen`               |
|-------------|-----------------------|------------------------|
| `draft`     | → `submitted` (damga) | —                      |
| `submitted` | —                     | → `draft` (damga silinir) |

Hakediş evrağının dört durumlu onay makinesi (`progress_payments.transitions`)
BURAYA BAĞLANMAZ: `build_transition_table` `PaymentAction`'ın beş eylemini
(`approve`/`reject`/`mark_paid`/`unapprove`) getirirdi ve günlük kaydın onay
süreci YOKTUR (model docstring'i, spec §2). Paylaşılan tek şey DESENDİR, tablo
değil — ortak bir tablo iki farklı iş kuralını tek yerde tutmak olurdu.

Boş hücre SESSİZ geçiş DEĞİLDİR (409): ikinci `submit`, ilk gönderimin damgasını
sessizce üzerine yazardı; taslağın `reopen`u ise hiç yapılmamış bir gönderimi
geri almış gibi davranırdı.

## `reopen` neden `admin`?

Yanlış gönderimin düzeltilmesi kaydı GİRENİN değil sistem yöneticisinin işidir:
gönderilmiş bir günlük hakedişe giden sayının kaynağıdır (`summary` YALNIZ
`submitted` sayar) — kendi kaydını geri açabilen bir rol, hakediş rakamını
denetimsiz değiştirebilirdi. Matriste `site_diary=_A` yalnız `system_admin`
sütunundadır (patron `_F`); matris DEĞİŞMEZ (spec §1), kapı seviyesi bu yüzden
`admin`dir — router'da.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.site_diary import guards, service
from app.modules.site_diary.models import DiaryStatus
from app.modules.site_diary.service import EntryContext
from app.modules.users.models import User

__all__ = ["TRANSITIONS", "DiaryAction", "perform"]


class DiaryAction(str, enum.Enum):
    """Uç yollarıyla BİREBİR (`POST /diary/{id}/submit|reopen`)."""

    submit = "submit"
    reopen = "reopen"


#: Spec §2 durum akışı. Sözlükte OLMAYAN her (durum, eylem) ikilisi 409'dur.
TRANSITIONS: dict[tuple[DiaryStatus, DiaryAction], DiaryStatus] = {
    (DiaryStatus.draft, DiaryAction.submit): DiaryStatus.submitted,
    (DiaryStatus.submitted, DiaryAction.reopen): DiaryStatus.draft,
}


def _stamp(context: EntryContext, action: DiaryAction) -> None:
    """`submitted_at` damgası — durum kolonuyla BİRLİKTE yaşar.

    `reopen` damgayı TEMİZLER: taslak bir kayıtta "gönderildi" saati kalsaydı
    ekran gönderilmemiş bir kaydı gönderilmiş gibi etiketler, denetim de yanlış
    zamanı gösterirdi. Yeniden `submit` damgayı YENİDEN yazar (eski değeri
    korumaya çalışmak, gerçekte olan ikinci gönderimi gizlerdi).
    """
    if action is DiaryAction.submit:
        context.entry.submitted_at = datetime.now(UTC)
    elif action is DiaryAction.reopen:
        context.entry.submitted_at = None


async def perform(
    session: AsyncSession, actor: User, entry_id: uuid.UUID, action: DiaryAction
) -> EntryContext:
    """Tek geçiş yolu. Sıra: kapsam(404) → kilit → tablo(409) → damga.

    Kapsam süzgeci geçiş tablosundan ÖNCE koşar (spec §3): görünmeyen bir kaydın
    DURUMU hakkında 409 ile bilgi sızdırılmaz. Kilit ZORUNLUDUR — kilitsiz
    okunsaydı eşzamanlı bir `PUT …/lines` kendi durum kapısını TOCTOU ile
    atlatır, gönderilmiş kayda satır yazabilirdi (`service.save_lines` bu
    kilidin karşı tarafıdır).

    Zorunluluk doğrulaması (dolu olması gereken alanlar) BU DİLİMDE YOKTUR:
    hangi alanın zorunlu olduğu mockup'ta işaretli değildir ve icat edilmez.
    """
    context = await service.visible_entry_locked(session, actor, entry_id)

    new_status = TRANSITIONS.get((context.entry.status, action))
    if new_status is None:
        raise ConflictError(guards.INVALID_STATUS_TRANSITION)

    context.entry.status = new_status
    _stamp(context, action)
    await session.flush()
    # `updated_at` server `onupdate` ile yenilendigi icin expire olur; acik
    # refresh olmadan yanit insasi `MissingGreenlet` verir.
    await session.refresh(context.entry)
    return context
