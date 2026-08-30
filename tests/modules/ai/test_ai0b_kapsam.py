"""B9 — **META-TEST**: katalogdaki HER araç için kapsam iddiası.

| Bekçi | Mutasyon (KIRMIZI olmalı) | Pozitif kontrol (YEŞİL kalmalı) |
|---|---|---|
| B9 | Bir aracın `ucler` yolunu doğrudan servise bağla | Kapsamı OLAN aktör veriyi **GÖRÜR** |

## 🔴 SKIP YOK — ama "her araca aynı iddia" da YANLIŞ

İlk hâlim her araca aynı cümleyi kuruyordu ("kapsamsız aktör `ScopedEmpty`
alır") ve **üç araçta yanlış olduğu ölçüldü**:

* `onay_kutum` kapsamlı bir küme değil, **aktörün kendi kuyruğunu** döndürür;
  boş olması kapsam dışılık DEĞİLDİR ve `ScopedEmpty` yazmak "yetkin dar" ima
  ederdi.
* `gosterge_ozeti` bir LİSTE değil bir KART döndürür; kapsam farkı zarf
  **hâlinde** değil, kartın **içindeki sayıda** görünür.
* `yetkilerim` / `navigate_to` hiç kapsamlı veri okumaz.

Bu yüzden her araç için **adlandırılmış, bilinçli** bir beklenti yazılır ve
`BEKLENTILER` sözlüğünün katalogla **küme eşitliği** ayrıca bekçilenir: yeni bir
araç eklenip beklentisi yazılmazsa test SKIP olmaz, **KIRMIZI** olur.

🔴 Bu dosya "bekçi kendi ölçtüğü yolu kurmaz" kuralına uyar: rotalar
`build_read_plane`in kurduğu rotalardır, testin eklediği rota YOKTUR.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.modules.ai import audit as ai_audit
from app.modules.ai.registry import ToolRegistry
from app.modules.ai.result import NotFound, Ok, ScopedEmpty, ToolError
from app.modules.ai.tools.catalog import CATALOG, READ_TOOLS
from app.modules.users.models import UserProjectAccess

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _denetim_sussun(monkeypatch):
    """Denetim yazımı B6/B6b'nin işidir; burada ölçülen şey KAPSAM.

    (Gerçek yazım ayrı session açar ve testin savepoint'i dışına düşerek işçi
    veritabanına sızardı.)
    """

    async def _sahte(**kwargs):
        return None

    monkeypatch.setattr(ai_audit, "record_tool_call", _sahte)


@pytest.fixture
async def kapsam_kurulumu(seeded_db, user_factory, project_factory):
    """İki aktör + iki proje + iki şantiye.

    * `iceriden` — A projesine erişimi VAR.
    * `disaridan` — hiçbir projeye erişimi YOK ama **AYNI ROL, AYNI İZİN
      SEVİYELERİ**. 🔴 Fark YETKİDE değil KAPSAMDA: testin ölçtüğü şey
      `require_permission` değil `visible_*` zinciridir.

    Rol `site_chief` seçildi çünkü dört aracın DÖRDÜNÜN de kapısını taşıyor
    (ölçüldü: `dashboard=_LIM` · `projects=_LIM` · `timesheet=_F` · `ai=_V`).
    `project_manager` seçilemezdi: matriste `timesheet=_N`dir ve
    `puantaj_haftasi` kataloğa hiç girmezdi.
    """
    from app.modules.sites.models import Site, SiteStatus

    a_projesi = await project_factory(code="AI-A", name="A Projesi")
    b_projesi = await project_factory(code="AI-B", name="B Projesi")

    a_santiye = Site(
        project_id=a_projesi.id,
        code="AI-A-S1",
        name="A Şantiyesi",
        status=SiteStatus.active,
        start_date=date(2026, 1, 1),
    )
    b_santiye = Site(
        project_id=b_projesi.id,
        code="AI-B-S1",
        name="B Şantiyesi",
        status=SiteStatus.active,
        start_date=date(2026, 1, 1),
    )
    seeded_db.add_all([a_santiye, b_santiye])

    iceriden = await user_factory("iceriden@fiil.example.com", "Sifre1234!", "site_chief")
    disaridan = await user_factory("disaridan@fiil.example.com", "Sifre1234!", "site_chief")
    seeded_db.add(UserProjectAccess(user_id=iceriden.id, project_id=a_projesi.id))
    await seeded_db.flush()

    # 🔴 KİMLİK HARİTASINDAN ÇIKAR — `populate_existing` kanonunun bu testteki
    # yüzü. Okuma düzlemi bu testte AYNI session'ı kullanır ve
    # `get_current_user` `session.get(User, ..., options=[joinedload(User.role)])`
    # çağırır; nesne haritada ROL YÜKLENMEDEN dururken `options` SESSİZCE YOK
    # SAYILIR ve `User.role` (`lazy="raise"`) patlar. Üretimde her istek kendi
    # session'ını alır, dolayısıyla bu satır testin kurgusunun bedelidir —
    # bir ürün kusuru DEĞİL. (`expire_all()` denendi ve `MissingGreenlet`
    # ürettiği ÖLÇÜLDÜ: expire edilmiş öznitelik senkron erişimde IO ister.)
    seeded_db.expunge(iceriden)
    seeded_db.expunge(disaridan)

    return {
        "iceriden": iceriden,
        "disaridan": disaridan,
        "a_projesi_id": a_projesi.id,
        "b_projesi_id": b_projesi.id,
        "a_santiye_id": a_santiye.id,
        "b_santiye_id": b_santiye.id,
    }


def _argumanlar(arac_adi: str, kurulum) -> dict:
    if arac_adi == "puantaj_haftasi":
        return {"site_id": str(kurulum["a_santiye_id"]), "iso_year": 2026, "iso_week": 30}
    if arac_adi == "navigate_to":
        return {"ekran": "projeler"}
    return {}


async def _cagir(arac_adi, user, kurulum, transport_factory, actor_factory, seeded_db, **ek):
    kayit = ToolRegistry(READ_TOOLS)
    return await kayit.invoke(
        arac_adi=arac_adi,
        argumanlar={**_argumanlar(arac_adi, kurulum), **ek},
        actor=await actor_factory(user),
        transport=transport_factory(user),
    )


# --------------------------------------------------------------------------- #
# Araç başına BİLİNÇLİ beklenti
# --------------------------------------------------------------------------- #


def _bekle_scoped_empty(dis, ic) -> None:
    assert isinstance(dis, ScopedEmpty), f"kapsamsız aktör {type(dis).__name__} aldı"
    assert isinstance(ic, Ok) and ic.row_count >= 1
    # 🔴 `Empty` DEĞİL: ikisi ayrılmazsa AI "hiç proje yok" der ve YALAN söyler.
    assert "kapsamınızda değil" in dis.mesaj()
    assert "hiç kayıt yok" not in dis.mesaj()


def _bekle_notfound(dis, ic) -> None:
    assert isinstance(dis, NotFound), f"kapsamsız aktör {type(dis).__name__} aldı"
    assert isinstance(ic, Ok)


def _bekle_kart_farki(dis, ic) -> None:
    """Kart döndüren araç: zarf hâli AYNI, ama kartın SAYISI farklı."""
    assert isinstance(dis, Ok) and isinstance(ic, Ok)
    assert ic.data["gorunur_proje_sayisi"] > dis.data["gorunur_proje_sayisi"] == 0


def _bekle_kendi_kuyrugu(dis, ic) -> None:
    """`onay_kutum`: aktörün KENDİ kuyruğu. Kimseye imza düşmediği için ikisi de
    boştur ve bu **kapsam dışılık DEĞİLDİR** — `ScopedEmpty` yazmak yanlış olurdu."""
    assert isinstance(dis, Ok) and isinstance(ic, Ok)
    assert dis.row_count == ic.row_count == 0
    assert dis.data["my_approval_roles"] == ic.data["my_approval_roles"] == []


def _bekle_kapsamsiz(dis, ic) -> None:
    """Kapsamlı veri OKUMAYAN araç: iki aktör aynı ŞEKLİ alır."""
    assert isinstance(dis, Ok) and isinstance(ic, Ok)
    assert set(dis.data) == set(ic.data)


#: 🔴 Her araç için ADLANDIRILMIŞ beklenti. Kümesi katalogla eşitlenir.
BEKLENTILER = {
    "projeleri_listele": _bekle_scoped_empty,
    "puantaj_haftasi": _bekle_notfound,
    "gosterge_ozeti": _bekle_kart_farki,
    "onay_kutum": _bekle_kendi_kuyrugu,
    "yetkilerim": _bekle_kapsamsiz,
    "navigate_to": _bekle_kapsamsiz,
}


def test_B9_BEKLENTILER_katalogla_KUME_ESITTIR() -> None:
    """Yeni bir araç eklenip beklentisi yazılmazsa SKIP değil KIRMIZI."""
    assert set(BEKLENTILER) == {s.ad for s in CATALOG}


# --------------------------------------------------------------------------- #
# B9 — HER araç için parametrize
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec", CATALOG, ids=lambda s: s.ad)
async def test_B9_kapsam_farki_HER_ARAC_ICIN_olculur(
    spec, kapsam_kurulumu, transport_factory, actor_factory, seeded_db
):
    dis = await _cagir(
        spec.ad,
        kapsam_kurulumu["disaridan"],
        kapsam_kurulumu,
        transport_factory,
        actor_factory,
        seeded_db,
    )
    ic = await _cagir(
        spec.ad,
        kapsam_kurulumu["iceriden"],
        kapsam_kurulumu,
        transport_factory,
        actor_factory,
        seeded_db,
    )
    assert not isinstance(dis, ToolError), f"{spec.ad} (dışarıdan): {dis}"
    # 🔴 POZİTİF KONTROL: bu satır olmadan test "kapsam çalışıyor"u değil
    # "hiçbir şey dönmüyor"u kanıtlardı.
    assert not isinstance(ic, ToolError), f"{spec.ad} (içeriden): {ic}"
    BEKLENTILER[spec.ad](dis, ic)


@pytest.mark.parametrize("spec", CATALOG, ids=lambda s: s.ad)
async def test_B9_kapsam_disi_zarfta_A_PROJESININ_izi_YOKTUR(
    spec, kapsam_kurulumu, transport_factory, actor_factory, seeded_db
):
    """Her araca uygulanabilen TEK tekdüze iddia: kapsam dışı aktörün zarfında
    içerideki varlıkların adı ya da kimliği **hiç geçmez**."""
    dis = await _cagir(
        spec.ad,
        kapsam_kurulumu["disaridan"],
        kapsam_kurulumu,
        transport_factory,
        actor_factory,
        seeded_db,
    )
    metin = str(dis.govde())
    for iz in (
        "A Projesi",
        "AI-A",
        "A Şantiyesi",
        str(kapsam_kurulumu["a_projesi_id"]),
        str(kapsam_kurulumu["a_santiye_id"]),
    ):
        assert iz not in metin, f"`{spec.ad}` kapsam dışı zarfta {iz!r} sızdırdı"


async def test_B9_POZITIF_KONTROL_iceridekinin_zarfinda_A_PROJESI_GORUNUR(
    kapsam_kurulumu, transport_factory, actor_factory, seeded_db
):
    """Yukarıdaki 'iz yok' iddiası, iz **görülebilir olduğu için** anlamlıdır."""
    ic = await _cagir(
        "projeleri_listele",
        kapsam_kurulumu["iceriden"],
        kapsam_kurulumu,
        transport_factory,
        actor_factory,
        seeded_db,
    )
    assert "A Projesi" in str(ic.govde())
    assert "B Projesi" not in str(ic.govde())


# --------------------------------------------------------------------------- #
# AI-0 kabul ölçütü 5 + S14
# --------------------------------------------------------------------------- #


async def test_B9_KABUL_OLCUTU_5_baska_projenin_santiyesi_NotFound_A_ile_GORUNUR(
    kapsam_kurulumu, transport_factory, actor_factory, seeded_db
):
    gorunmeyen = await _cagir(
        "puantaj_haftasi",
        kapsam_kurulumu["iceriden"],
        kapsam_kurulumu,
        transport_factory,
        actor_factory,
        seeded_db,
        site_id=str(kapsam_kurulumu["b_santiye_id"]),
    )
    assert isinstance(gorunmeyen, NotFound), gorunmeyen

    gorunen = await _cagir(
        "puantaj_haftasi",
        kapsam_kurulumu["iceriden"],
        kapsam_kurulumu,
        transport_factory,
        actor_factory,
        seeded_db,
    )
    assert isinstance(gorunen, Ok), gorunen
    assert gorunen.data["site_name"] == "A Şantiyesi"


async def test_S14_gorunmeyen_var_olan_ile_var_olmayan_BAYT_BAYT_AYNI(
    kapsam_kurulumu, transport_factory, actor_factory, seeded_db
):
    async def _sonda(site_id) -> dict:
        sonuc = await _cagir(
            "puantaj_haftasi",
            kapsam_kurulumu["iceriden"],
            kapsam_kurulumu,
            transport_factory,
            actor_factory,
            seeded_db,
            site_id=str(site_id),
        )
        return sonuc.govde()

    assert await _sonda(kapsam_kurulumu["b_santiye_id"]) == await _sonda(uuid.uuid4())


# --------------------------------------------------------------------------- #
# B9 MUTASYONU — aracın ucu yerine SERVİSE bağlanması
# --------------------------------------------------------------------------- #


def test_B9_MUTASYON_servise_baglanan_arac_KAPSAMI_KAYBEDER() -> None:
    """🔴 #1 mimarisini öldüren ölçümün birebir yeniden üretimi.

    `timesheet/week.py::build(...)` **aktör ALMAZ**; kapsam kapısı router'ın
    çağırdığı `service.visible_site(session, user, site_id)`tir. Bir araç ucu
    değil servisi sarsaydı, `timesheet:view` olan HERKES erişimi olmayan
    projelerin puantajını okurdu. Bu test o olguyu kilitler: ölçüm bir gün
    değişirse (servis aktör almaya başlarsa) burası kırmızı olur ve T2 kararı
    yeniden düşünülür.
    """
    import inspect

    from app.modules.timesheet import router as timesheet_router
    from app.modules.timesheet import service as timesheet_service
    from app.modules.timesheet import week as timesheet_week

    imza = inspect.signature(timesheet_week.build)
    assert not ({"actor", "user"} & set(imza.parameters)), (
        f"`timesheet.week.build` artık aktör alıyor: {list(imza.parameters)}. "
        "#1'i çürüten ölçüm yeniden yapılmalı."
    )
    assert hasattr(timesheet_service, "visible_site")
    assert "visible_site" in inspect.getsource(timesheet_router)
