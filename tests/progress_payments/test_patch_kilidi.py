"""PATCH yolunun durum kapısı KİLİT ALTINDA okunur (kayıt 280).

`service.update` durum kapısını (`status != draft` → 409) kilitsiz
`_visible_payment` üzerinden veriyordu. Aynı dosyada `save_lines` (:342) ve
`delete_payment` (:714) bu açığı KRIT-HAKEDIS K5 gerekçesiyle
`visible_payment_locked`a taşımış, PATCH taşınmamıştı. Eşzamanlı bir `approve`
ile PATCH birbirini görmeden geçebilir; dönem değişimi ayrıca
`lines.restamp_for_period`i tetikler (:302) ve ONAYLANMIŞ satırların
`quantity_source` damgasını yeniden yazar.

🔴 Neden DAVRANIŞ testi değil de SQL-METİN testi: `test_concurrency.py` bu
soruyu bu depoda zaten ÖLÇTÜ (denetim M11 + T4b) — `FOR UPDATE` tamamen
kaldırılsa bile davranış testleri YEŞİL kalıyor, çünkü yolun sonundaki `UPDATE`
zaten satır kilidi alır. Kilidin KENDİSİNİ yalnız ifadenin metni yakalar.
"""

import uuid

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_payments import service
from app.modules.progress_payments.models import ProgressPayment
from app.modules.progress_payments.schemas import ProgressPaymentUpdate
from app.modules.users.models import User
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio


async def test_patch_once_sozlesmeyi_sonra_hakedisi_for_update_ile_okur(
    seeded_db: AsyncSession,
    taslak_hakedisli_proje: uuid.UUID,
    hakedis_olusturan: User,
) -> None:
    payment = (
        await seeded_db.execute(
            select(ProgressPayment).where(ProgressPayment.project_id == taslak_hakedisli_proje)
        )
    ).scalar_one()

    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        await service.update(
            seeded_db,
            hakedis_olusturan,
            payment.id,
            ProgressPaymentUpdate(description="kilit denemesi"),
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)

    kilitli = [ifade for ifade in ifadeler if "FOR UPDATE" in ifade]
    sozlesme = [i for i, ifade in enumerate(kilitli) if "FROM project_contracts" in ifade]
    hakedis = [i for i, ifade in enumerate(kilitli) if "FROM progress_payments" in ifade]
    assert sozlesme, f"PATCH sözleşme satırını FOR UPDATE ile okumadı: {kilitli}"
    assert hakedis, f"PATCH hakediş satırını FOR UPDATE ile okumadı: {kilitli}"
    assert sozlesme[0] < hakedis[0], f"kilit sırası ters: {kilitli}"
