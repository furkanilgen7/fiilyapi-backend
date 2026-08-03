"""Hakediş "günlükten doldur" ÖNERİSİ (T5; spec §4, §7 S2/S5).

## 🛑 Bu modül HİÇBİR ŞEY YAZMAZ

Spec §4'ün ilk cümlesi: **otomasyon YOK**. Ay sonu kendiliğinden hakediş
ÜRETİLMEZ; bu iki uç yalnızca "günlüğe göre bu dönem şu miktarlar oldu" der.
Öneriyi kalıcılaştırmak kullanıcının AYRI `PUT …/lines` çağrısıdır — geri
alınamaz bir yazmayı bir GET'in yan etkisi yapmak, kullanıcının onaylamadığı bir
evrakı üretmek olurdu.

Bu yüzden burada `session.add`/`flush`/`commit` YOKTUR ve denetim kaydı da
AÇILMAZ (repo deseninde okuma uçları denetlenmez; bir denetim satırı yazmak bu
ucu fiilen bir YAZMA yoluna çevirirdi). Kural `tests/site_diary/test_suggestion.py`
içinde DB izi karşılaştırmasıyla sabitlenmiştir.

## Sözleşme: yanıt `PUT …/lines` gövdesine BİREBİR uyar

`lines[]` tipi hakediş modüllerinin KENDİ giriş şemasıdır (`ProgressPaymentLineInput`
/ `SubcontractorProgressPaymentLineInput`) — öneri için ikinci bir şekil
tanımlanmaz. Kullanıcı gövdeyi kopyalayıp doğrudan gönderebilir.

`quantity_source=diary` damgası bu ucun İŞİ DEĞİLDİR: satır ancak `PUT …/lines`
ile kalıcılaştığında damgalanabilir. (Bugün taşeron `PUT …/lines` gövdesi
`quantity_source` KABUL ETMEZ — bilinçli bir karar: istekten alınması `diary`
rozetini sahte doldurmanın yolu olurdu. Damganın gerçekten inmesi ayrı bir
dilimin işidir; bu dilim yazma yolunu DEĞİŞTİRMEZ.)

## Toplama kuralı TEK kopyadır

Yalnız `submitted` günlükler ve dönem süzgeci
`repository.submitted_period_conditions`tan gelir — T4 özetiyle AYNI gövde.
İkinci bir toplama kuralı açılsaydı "Hakediş Özeti" ekranı ile "günlükten doldur"
düğmesi aynı ay için FARKLI sayılar söylerdi.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_payments import guards as employer_guards
from app.modules.progress_payments.schemas import ProgressPaymentLineInput
from app.modules.site_diary import guards, repository
from app.modules.site_diary.schemas import EmployerDiarySuggestion, SubcontractorDiarySuggestion
from app.modules.site_diary.service import visible_project
from app.modules.subcontractor_progress_payments.schemas import (
    SubcontractorProgressPaymentLineInput,
)
from app.modules.subcontractor_progress_payments.service import visible_contract
from app.modules.users.models import User


def _reason(line_count: int, skipped_unbridged_count: int) -> str | None:
    """Boş listenin GEREKÇESİ — sessiz boş liste yok.

    Sıra bilinçlidir: köprü eksikliği "miktar yok"tan DAHA BİLGİLENDİRİCİDİR.
    Kullanıcı günlüğe miktar girdiğini bilir; ona "miktar yok" demek onu var
    olmayan bir veri kaybını aramaya gönderirdi — asıl eksik BOQ köprüsüdür.
    """
    if line_count > 0:
        return None
    if skipped_unbridged_count > 0:
        return guards.SUGGESTION_NO_BRIDGE
    return guards.SUGGESTION_NO_QUANTITY


async def employer_suggestion(
    session: AsyncSession,
    actor: User,
    project_id: uuid.UUID,
    *,
    year: int | None,
    month: int | None,
) -> EmployerDiarySuggestion:
    """`GET /projects/{project_id}/progress-payments/diary-suggestion`.

    Kapsam kararı PROJE üzerindendir ve 404 metni hakediş modülünün TEK
    "bulunamadı" cümlesidir (`PAYMENT_MISSING`): uç o modülün yolunun altında
    yaşar, komşu `…/progress-payments/summary` ucundan FARKLI bir cümle dönmesi
    elinde UUID olan kullanıcıya projenin varlığını sızdırırdı.

    Sorgu sayısı SABİTTİR (kapsam + satırlar + köprüsüz sayacı); poz ya da
    şantiye başına sorgu KOŞULMAZ.
    """
    project = await visible_project(session, actor, project_id, employer_guards.PAYMENT_MISSING)
    rows = await repository.employer_suggestion_rows(session, project.id, year=year, month=month)
    skipped = await repository.employer_unbridged_item_count(
        session, project.id, year=year, month=month
    )
    lines = [
        ProgressPaymentLineInput(contract_item_id=contract_item_id, site_id=site_id, quantity=total)
        for contract_item_id, site_id, total in rows
    ]
    return EmployerDiarySuggestion(
        project_id=project.id,
        year=year,
        month=month,
        lines=lines,
        skipped_unbridged_count=skipped,
        reason=_reason(len(lines), skipped),
    )


async def subcontractor_suggestion(
    session: AsyncSession,
    actor: User,
    contract_id: uuid.UUID,
    *,
    year: int | None,
    month: int | None,
) -> SubcontractorDiarySuggestion:
    """`GET /subcontractor-contracts/{contract_id}/progress-payments/diary-suggestion`.

    Spec §7 S5 (ONAYLI): `site_id` NULL olan proje-geneli sözleşme kapsam
    DIŞIDIR. Boş liste SESSİZCE dönmez — `reason` alanı nedeni söyler, çünkü
    "şantiyesiz sözleşme" ile "bu ay miktar yok" kullanıcı için tamamen farklı
    iki durumdur ve ilkinin çözümü sözleşmeye şantiye bağlamaktır.

    Şantiyesiz sözleşmede köprü sayacı da KOŞMAZ: hangi şantiyenin günlüğüne
    bakılacağı belirsizken "köprüsüz poz" saymak uydurma bir sayı üretirdi.
    """
    contract, _ = await visible_contract(session, actor, contract_id)
    if contract.site_id is None:
        return SubcontractorDiarySuggestion(
            contract_id=contract.id,
            site_id=None,
            year=year,
            month=month,
            lines=[],
            skipped_unbridged_count=0,
            reason=guards.SUGGESTION_CONTRACT_WITHOUT_SITE,
        )

    rows = await repository.subcontractor_suggestion_rows(
        session, contract.id, contract.site_id, year=year, month=month
    )
    skipped = await repository.subcontractor_unbridged_item_count(
        session, contract.id, contract.site_id, year=year, month=month
    )
    lines = [
        SubcontractorProgressPaymentLineInput(contract_item_id=item_id, quantity=total)
        for item_id, total in rows
    ]
    return SubcontractorDiarySuggestion(
        contract_id=contract.id,
        site_id=contract.site_id,
        year=year,
        month=month,
        lines=lines,
        skipped_unbridged_count=skipped,
        reason=_reason(len(lines), skipped),
    )
