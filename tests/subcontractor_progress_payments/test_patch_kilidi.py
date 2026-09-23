"""PATCH yolunun durum kapısı KİLİT ALTINDA okunur (kayıt 390/391).

`service.update` durum kapısını (`status != draft` → 409) kilitsiz okunan satır
üzerinde veriyordu: kardeş ÜÇ yazma yolu (`save_lines`, `refresh_prices`,
`delete_payment`) `visible_payment_locked` kullanırken PATCH `visible_payment`
kullanıyordu. Eşzamanlı bir `approve` ile PATCH birbirini görmeden geçebilir;
üstelik PATCH dönem değiştirdiğinde `lines.restamp_for_period` ONAYLANMIŞ
satırların `quantity_source` damgasını yeniden yazar.

🔴 Neden DAVRANIŞ testi değil de SQL-METİN testi:
`tests/progress_payments/test_concurrency.py` bu soruyu bu depoda zaten ÖLÇTÜ
(denetim M11 + T4b): `FOR UPDATE` tamamen kaldırılsa bile davranış testleri
YEŞİL kalıyor, çünkü yolun sonundaki `UPDATE` zaten satır kilidi alır ve ikinci
transaction onu beklemek zorundadır. Kilidin KENDİSİNİ yakalayan tek bekçi
ifadenin metnidir. Sıra da burada sabitlenir — önce sözleşme, sonra hakediş —
çünkü ters sırada kilitleyen bir yol karşılıklı kilitlenme doğurur.
"""

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.subcontractor_progress_payments import service
from app.modules.subcontractor_progress_payments.schemas import (
    SubcontractorProgressPaymentUpdate,
)
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio


async def test_patch_once_sozlesmeyi_sonra_hakedisi_for_update_ile_okur(
    seeded_db: AsyncSession,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
    sozlesme_sahibi,
    admin_kullanicisi,
) -> None:
    contract, _, _ = taseron_sozlesmesi
    payment = await hakedis_fabrikasi(contract, sozlesme_sahibi)

    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        await service.update(
            seeded_db,
            admin_kullanicisi,
            payment.id,
            SubcontractorProgressPaymentUpdate(description="kilit denemesi"),
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)

    kilitli = [ifade for ifade in ifadeler if "FOR UPDATE" in ifade]
    sozlesme = [i for i, ifade in enumerate(kilitli) if "FROM subcontractor_contracts" in ifade]
    hakedis = [
        i for i, ifade in enumerate(kilitli) if "FROM subcontractor_progress_payments" in ifade
    ]
    assert sozlesme, f"PATCH sözleşme satırını FOR UPDATE ile okumadı: {kilitli}"
    assert hakedis, f"PATCH hakediş satırını FOR UPDATE ile okumadı: {kilitli}"
    assert sozlesme[0] < hakedis[0], f"kilit sırası ters: {kilitli}"
