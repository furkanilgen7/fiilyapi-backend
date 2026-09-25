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

from app.core import day_hooks
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

    Zorunluluk doğrulaması (dolu olması gereken alanlar) ÇEKİRDEKTE YOKTUR:
    hangi alanın zorunlu olduğu mockup'ta işaretli değildir ve icat edilmez.

    PLN-B2.1 — iki PORT (`app.core.day_hooks`, kayıt yoksa no-op):
    * KİLİT (B2-6): İKİ eylem de kilitli güne 409 alır — `reopen` da bir yazmadır;
      kilidi açmak modülün (gerekçeli, gün düzeyi) işidir, çekirdeğin değil.
    * GÖNDER (B2-3/4/8): `submit` DB'ye YAZMADAN ÖNCE modülün ön-koşullarını sorar
      (422 + `reasons`). Sıra: kapsam(404) → kilit(409) → tablo(409) → port(422)
      → damga. Tablo porttan ÖNCE koşar: gönderilmiş kaydın ikinci `submit`i
      ön-koşul listesi değil "geçiş yapılamaz" almalıdır.
    """
    context = await service.visible_entry_locked(session, actor, entry_id)
    await service.assert_entry_days_unlocked(session, context.entry)

    new_status = TRANSITIONS.get((context.entry.status, action))
    if new_status is None:
        raise ConflictError(guards.INVALID_STATUS_TRANSITION)
    if action is DiaryAction.submit:
        await day_hooks.assert_submit_allowed(
            session,
            day_hooks.SubmitContext(
                entry_id=context.entry.id,
                site_id=context.entry.site_id,
                entry_date=context.entry.entry_date,
                actor_id=actor.id,
            ),
        )

    context.entry.status = new_status
    _stamp(context, action)
    await session.flush()
    # `updated_at` server `onupdate` ile yenilendigi icin expire olur; acik
    # refresh olmadan yanit insasi `MissingGreenlet` verir.
    await session.refresh(context.entry)
    return context
