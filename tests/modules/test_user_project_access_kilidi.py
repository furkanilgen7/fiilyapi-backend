"""Proje erişimi TAM-DEĞİŞTİRME yolu kullanıcı satırını KİLİTLER (kayıt 442).

`repository.replace_project_access` `DELETE` + `INSERT`i KİLİTSİZ koşuyordu ve
tabloda `(user_id, project_id)` üzerinde UNIQUE kısıt YOKTUR — migration
`e274019416f6:24-36` yalnız PK ile NON-UNIQUE bir indeks açar. İki eşzamanlı
`PUT` birbirinin `DELETE`iyle `INSERT`i arasına girebilir: sonuç ya İKİ kümenin
karışımı ya da AYNI projenin ÇİFT satırı olur. Erişim kararı
(`projects.visible_projects`) bu satırlardan okunduğu için sonuç sessiz bir
yetki sapmasıdır.

Onarım kısıt değil KİLİTtir: tüm yazıcılar kullanıcı satırında serileşir, bu
yüzden migration GEREKMEZ ve canlı satırlara dokunulmaz.

🔴 Bekçi SQL-METİN testidir. Bu depoda ölçüldü (`test_concurrency.py`, denetim
M11 + T4b): davranış testi `FOR UPDATE` kalksa bile yeşil kalabilir, çünkü
yolun sonundaki yazma zaten kilit alır. Kilidin KENDİSİNİ yalnız ifade metni
yakalar.
"""

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users import service
from app.modules.users.schemas import ProjectAccessInput
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio


async def test_erisim_degistirme_kullanici_satirini_for_update_ile_okur(
    seeded_db: AsyncSession, user_factory, project_factory
) -> None:
    user = await user_factory(email="kilit@t.co", password="parola1234", role_key="site_chief")
    project = await project_factory("KLT-A")

    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        await service.set_project_access(
            seeded_db,
            user.id,
            ProjectAccessInput(all_projects=False, project_ids=[project.id]),
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)

    kilitli = [ifade for ifade in ifadeler if "FOR UPDATE" in ifade]
    assert [i for i in kilitli if "FROM users" in i], (
        f"tam-değiştirme kullanıcı satırını FOR UPDATE ile okumadı: {kilitli}"
    )
