"""🔴 Ertelenmiş UQ ihlali istemciye 200 dönüyordu, satırlar ise YAZILMIYORDU (kayıt 25).

## Kusur — ölçülmüş mekanizma

`site_plan_rows` tekilliği `DEFERRABLE INITIALLY DEFERRED`dır
(`models.py:91-100`): ihlal `flush()`ta DEĞİL **transaction'ın commit'inde**
patlar. O commit `app/core/db.py` `get_db`nin teardown'undadır ve FastAPI
0.141.1 teardown'u YANIT GÖNDERİLDİKTEN SONRA koşturur
(`routing.py:140-146` — `await response(scope, receive, send)` `request_stack`in
İÇİNDEDİR). Starlette 1.6.0 da `response_started` olduğu için işleyiciyi
ÇAĞIRAMAZ (`_exception_handler.py:55`). Sonuç:

    istemci 200 + kaydettiği satırları görür · veritabanında HİÇBİR ŞEY yoktur

## Yarışın gerçek penceresi (uydurma değil, koddan ölçüldü)

`write.save_rows` kilidi `repository.locked_site_rows` (`repository.py:167-179`)
YALNIZ MEVCUT satırları `FOR UPDATE` eder — **hayalet (phantom) INSERT'e karşı
korumasızdır**. Izgara boşken hiçbir satır kilitlenmez; iki şef aynı etiketi
aynı anda eklerse ikisi de "yok" görür, ikisi de yazar.

Aşağıdaki bekçi bu pencereyi ZAMANLAMA olarak kurar, MEKANİZMA olarak değil:
`locked_site_rows` sarılır, GERÇEK sorgu koşar, dönüşten hemen önce **AYRI ve
GERÇEK bir oturum** rakip satırı yazıp COMMIT eder. Test edilen kodun tek satırı
bile değiştirilmez; yalnız rakibin ne zaman commit ettiği belirlenir — böylece
yarış kilitlenmeden (deadlock) ve çakmadan (flake) tekrarlanabilir olur.

## Mevcut bekçiler neden KÖR

* Kök `client` fikstürü (`tests/conftest.py:267-271`) `get_db`yi TAMAMEN ezer;
  override commit ETMEZ, yani ertelenmiş kısıt hiçbir plan testinde HİÇ
  denetlenmez.
* `tests/modules/test_boq_models.py` ertelenmiş kısıtı yalnız ORM düzeyinde,
  elle `SET CONSTRAINTS ALL IMMEDIATE` koşarak ölçer — HTTP yığınından hiç
  geçmez.

⚠️ Bu dosya `.env`/`TEST_DATABASE_URL` veritabanına DOKUNMAZ: kendi tek
kullanımlık veritabanını açar, `get_db`nin oturum fabrikasını oraya yönlendirir
ve sonunda düşürür.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.db as core_db
from app.core.config import settings
from app.core.db import Base, get_db
from app.core.security import create_access_token
from app.main import app as ana_app
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from app.modules.roles.models import Role
from app.modules.roles.seed_data import seed_reference_data
from app.modules.site_planning import repository as plan_repository
from app.modules.site_planning.models import PlanResourceKind, SitePlanRow
from app.modules.sites.models import Section, Site
from app.modules.users.models import User

#: Çakışan etiket. `section_id` NULL OLAMAZ: Postgres'te NULL'lu UQ dalı
#: kısıtlamaz (`write._assert_row_shape` docstring'i), yarış penceresi kapanırdı.
ETIKET = "Kalıp Ekibi"

#: `site_diary=_A` (planlama kendi izin modülünü açmaz) **ve** `projects=_A` —
#: `visible_projects` admin süzgecini atlar, `UserProjectAccess` gerekmez.
ROL = "system_admin"


def _asyncpg_dsn(database: str) -> str:
    base = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    return base.rsplit("/", 1)[0] + f"/{database}"


def _sqlalchemy_dsn(database: str) -> str:
    return settings.test_database_url.rsplit("/", 1)[0] + f"/{database}"


async def _admin(sql: str) -> None:
    baglanti = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await baglanti.execute(sql)
    finally:
        await baglanti.close()


class _Ortam:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bearer: str,
        site: Site,
        section_id: uuid.UUID,
    ) -> None:
        self.Session = session_factory
        self.bearer = bearer
        self.site_id = site.id
        self.project_id = site.project_id
        self.section_id = section_id


@asynccontextmanager
async def _gercek_ortam(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[_Ortam]:
    """Tek kullanımlık veritabanı + GERÇEK `get_db` (override YOK)."""
    database = f"planuq_{uuid.uuid4().hex[:8]}"
    await _admin(f'CREATE DATABASE "{database}"')
    engine = create_async_engine(_sqlalchemy_dsn(database))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as kurulum:
            await seed_reference_data(kurulum)
            role = (await kurulum.execute(select(Role).where(Role.key == ROL))).scalar_one()
            user = User(
                email="planuq@fiil.test",
                password_hash="x",
                full_name="Plan UQ Bekçisi",
                role_id=role.id,
            )
            project = Project(
                code="UQ-P01",
                name="Ertelenmiş Kısıt Projesi",
                status=ProjectStatus.active,
                project_type=ProjectType.taahhut,
            )
            kurulum.add_all([user, project])
            await kurulum.flush()
            site = Site(project_id=project.id, code="UQ-A", name="A-Blok")
            kurulum.add(site)
            await kurulum.flush()
            section = Section(site_id=site.id, code="UQ-B1", name="Kat 6–10 Kaba", sort_order=1)
            kurulum.add(section)
            await kurulum.flush()
            # 🔴 COMMIT ŞART: rakip oturum AYRI bir bağlantıdır, commit
            # edilmemiş kurulumu göremezdi.
            await kurulum.commit()
            ortam = _Ortam(
                Session, create_access_token(user.id, user.token_version), site, section.id
            )

        monkeypatch.setattr(core_db, "SessionLocal", Session)
        assert get_db not in ana_app.dependency_overrides, (
            "`get_db` override edilmiş: bu dosya GERÇEK teardown commit'ini ölçmek zorunda."
        )
        yield ortam
    finally:
        await engine.dispose()
        await _admin(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')


def _rakibi_araya_sok(monkeypatch: pytest.MonkeyPatch, ortam: _Ortam) -> None:
    """`locked_site_rows` DÖNDÜKTEN SONRA rakip satırı yazıp COMMIT eder.

    Sarmalayıcı yalnız ZAMANLAMA kurar: gerçek `FOR UPDATE` sorgusu aynen koşar
    (ızgara boş olduğu için hiçbir satır kilitlenmez — kusurun kendisi budur) ve
    rakip GERÇEK bir oturumdan GERÇEKTEN commit eder. Bir kez tetiklenir.
    """
    gercek = plan_repository.locked_site_rows
    tetiklendi = False

    async def _sarmal(session: AsyncSession, site_id: uuid.UUID) -> list[SitePlanRow]:
        nonlocal tetiklendi
        sonuc = await gercek(session, site_id)
        if not tetiklendi:
            tetiklendi = True
            async with ortam.Session() as rakip:
                rakip.add(
                    SitePlanRow(
                        site_id=ortam.site_id,
                        project_id=ortam.project_id,
                        kind=PlanResourceKind.crew,
                        section_id=ortam.section_id,
                        label=ETIKET,
                    )
                )
                await rakip.commit()
        return sonuc

    monkeypatch.setattr(plan_repository, "locked_site_rows", _sarmal)


async def _satirlari_kaydet(ortam: _Ortam, etiket: str = ETIKET) -> httpx.Response:
    """`raise_app_exceptions=False`: kusurlu hâlde istemcinin GERÇEKTEN ne
    gördüğünü (200) ölçebilmek için — sunucu tarafındaki çöküş yanıttan SONRA
    doğar ve istemciyi hiç ilgilendirmez."""
    transport = httpx.ASGITransport(app=ana_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as istemci:
        return await istemci.put(
            f"/sites/{ortam.site_id}/plan/rows",
            headers={"Authorization": f"Bearer {ortam.bearer}"},
            json={
                "rows": [
                    {
                        "kind": PlanResourceKind.crew.value,
                        "section_id": str(ortam.section_id),
                        "label": etiket,
                        "sort_order": 0,
                    }
                ]
            },
        )


async def _satir_sayisi(ortam: _Ortam) -> int:
    async with ortam.Session() as taze:
        return int(await taze.scalar(select(func.count()).select_from(SitePlanRow)) or 0)


async def test_hayalet_cakisma_200_DEGIL_409_doner(monkeypatch) -> None:
    """🔴 ASIL BEKÇİ.

    Mutasyon: `write.save_rows`taki `SET CONSTRAINTS ALL IMMEDIATE` silinince
    ihlal teardown commit'ine kaçar, istemci **200** görür ve bu test KIRMIZI
    olur.
    """
    async with _gercek_ortam(monkeypatch) as ortam:
        _rakibi_araya_sok(monkeypatch, ortam)

        yanit = await _satirlari_kaydet(ortam)

        assert yanit.status_code == 409, (
            f"İstemci {yanit.status_code} aldı. Ertelenmiş UQ ihlali istek İÇİNDE "
            "doğmadıysa yanıt çoktan gönderilmiştir ve 409'a çevrilemez — "
            f"kullanıcı kaydettiğini sanır. Gövde: {yanit.text}"
        )
        # Kullanıcıya YAZILMIŞ diye gösterilen satır veritabanında YOKTUR:
        # geriye yalnız rakibin satırı kalır.
        assert await _satir_sayisi(ortam) == 1


async def test_CAKISMA_YOKSA_kaydetme_200_kalir(monkeypatch) -> None:
    """🔴 POZİTİF KONTROL: `SET CONSTRAINTS` haksız 409 ÜRETMEZ.

    Rakip BAŞKA bir etiket yazar; çakışma yoktur. "Her zaman 409" ya da
    ertelemenin tamamını kıran bir mutant bu testi KIRMIZI yapar.
    """
    async with _gercek_ortam(monkeypatch) as ortam:
        _rakibi_araya_sok(monkeypatch, ortam)

        yanit = await _satirlari_kaydet(ortam, etiket="Demir Ekibi")

        assert yanit.status_code == 200, yanit.text
        # 🔴 ÖLÇÜLDÜ: rakibin satırı SİLİNMEZ. DEĞİŞTİRME semantiği yalnız
        # `locked_site_rows`un OKUDUĞU kimlikleri siler (`write.py:136`) ve o
        # okuma rakipten ÖNCEYDİ — yani hayalet satır bu istekte hayatta kalır.
        # Bu, testin kurduğu bir şey değil, yarış penceresinin kendisidir.
        assert sorted(r["label"] for r in yanit.json()["rows"]) == ["Demir Ekibi", ETIKET]
        assert await _satir_sayisi(ortam) == 2
