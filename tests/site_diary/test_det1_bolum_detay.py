"""DET-1.B — Bölüm Detay › Günlük Kayıt: bölüm süzgeci (Kural A) + salt okunur detay bağlamı.

Kural A (kullanıcı kararı 2026-09-25): bölümün günlüğü = başlığı (`section_id`) bu bölüm
olan gün ∪ bu bölüme MİKTAR SATIRI yazılmış gün. Gün başına tek kayıt olduğundan
(`uq_site_diary_entries_site_date`) bir gün HEM başlıkta HEM satırda eşleşse de BİR kez döner.

Kurgu (şantiye SD-A; B1 = "A Blok", B2 = "B Blok"):

    gün  başlık  satır bölümleri   B1'de?
    d1   B1      —                 ✔ yalnız başlık
    d2   —       B1                ✔ yalnız satır
    d3   B1      B1, B1(2. kalem)  ✔ ikisi (tekrarsız)
    d4   B2      B2                ✘ hiçbiri
    d5   —       —                 ✘ hiçbiri
    d6   B2      B1, B2            ✔ yalnız satır (başlık başka bölüm)
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import day_hooks
from app.modules.contracts.models import Subcontractor
from app.modules.site_diary import guards
from app.modules.site_diary.models import (
    DiaryStatus,
    SiteDiaryEntry,
    SiteDiaryLine,
    SiteDiaryWorkerCount,
    WorkerSource,
)
from app.modules.sites.models import Section
from app.modules.users.models import User
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio

D1 = date(2026, 5, 4)
DAYS = [D1 + timedelta(days=i) for i in range(6)]  # d1..d6


def _line_kw(item, section: Section | None) -> dict:  # noqa: ANN001
    return {
        "boq_item_id": item.id,
        "section_id": section.id if section else None,
        "code": item.code,
        "description": item.description,
        "unit": item.unit,
        "unit_price": item.unit_price,
        "quantity": Decimal("1.000"),
    }


def _line(item, section: Section | None) -> SiteDiaryLine:  # noqa: ANN001
    return SiteDiaryLine(**_line_kw(item, section))


@pytest.fixture
async def kurgu(seeded_db: AsyncSession, santiye, bolum: Section, admin_kullanicisi: User):
    site, _, items = santiye
    b1 = bolum
    b2 = Section(site_id=site.id, code="B-2", name="B Blok")
    seeded_db.add(b2)
    await seeded_db.flush()
    plan = [
        (b1, []),
        (None, [(items[0], b1)]),
        (b1, [(items[0], b1), (items[1], b1)]),
        (b2, [(items[0], b2)]),
        (None, []),
        (b2, [(items[0], b1), (items[1], b2)]),
    ]
    entries = []
    for day, (header, lines) in zip(DAYS, plan, strict=True):
        entry = SiteDiaryEntry(
            site_id=site.id,
            project_id=site.project_id,
            entry_date=day,
            section_id=header.id if header else None,
            status=DiaryStatus.draft,
            created_by=admin_kullanicisi.id,
        )
        entry.lines.extend(_line(item, sec) for item, sec in lines)
        seeded_db.add(entry)
        entries.append(entry)
    await seeded_db.flush()
    return site, b1, b2, entries


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Sürücüye giden HER ifade (`test_work_category._sorgu_sayaci` deseni)."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


def _ids(body: dict) -> list[str]:
    return [item["id"] for item in body["items"]]


# ------------------------------------------------------------------ liste · Kural A


async def test_liste_bolum_suzgeci_baslik_birlesim_satir_tekrarsiz(
    client: AsyncClient, admin_headers, kurgu
) -> None:
    site, b1, _, e = kurgu
    yanit = await client.get(
        f"/sites/{site.id}/diary", params={"section_id": str(b1.id)}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    body = yanit.json()
    # d6 (yalnız satır, başlık B2) · d3 (ikisi, iki B1 satırı → TEK kez) · d2 (yalnız satır)
    # · d1 (yalnız başlık); d4/d5 (hiçbiri) YOK — en yeni gün önce
    assert _ids(body) == [str(e[5].id), str(e[2].id), str(e[1].id), str(e[0].id)]
    assert body["total"] == 4


async def test_liste_bolum_verilmezse_davranis_aynen(
    client: AsyncClient, admin_headers, kurgu
) -> None:
    site, _, _, e = kurgu
    yanit = await client.get(f"/sites/{site.id}/diary", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    assert _ids(yanit.json()) == [str(x.id) for x in reversed(e)]
    assert yanit.json()["total"] == 6


@pytest.mark.parametrize(
    ("offset", "beklenen"),
    [(0, [5, 2]), (2, [1, 0]), (3, [0]), (4, [])],
)
async def test_liste_bolum_sayfalama_total_suzulmus_kume(
    client: AsyncClient, admin_headers, kurgu, offset: int, beklenen: list[int]
) -> None:
    site, b1, _, e = kurgu
    yanit = await client.get(
        f"/sites/{site.id}/diary",
        params={"section_id": str(b1.id), "limit": 2, "offset": offset},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    body = yanit.json()
    assert _ids(body) == [str(e[i].id) for i in beklenen]
    assert (body["total"], body["limit"], body["offset"]) == (4, 2, offset)


async def test_liste_bolum_suzgeci_donem_suzgeciyle_birlesir(
    client: AsyncClient, admin_headers, kurgu, gunluk_fabrikasi, admin_kullanicisi
) -> None:
    site, b1, _, e = kurgu
    haziran = await gunluk_fabrikasi(site, admin_kullanicisi, entry_date=date(2026, 6, 1))
    haziran.section_id = b1.id
    yanit = await client.get(
        f"/sites/{site.id}/diary",
        params={"section_id": str(b1.id), "year": 2026, "month": 5},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert str(haziran.id) not in _ids(yanit.json())
    assert yanit.json()["total"] == 4


async def test_liste_baska_santiyenin_bolumu_422(
    client: AsyncClient, admin_headers, kurgu, seeded_db, santiye_fabrikasi
) -> None:
    site, _, _, _ = kurgu
    diger, _, _ = await santiye_fabrikasi("SD-X")
    yabanci = Section(site_id=diger.id, code="X-1", name="X")
    seeded_db.add(yabanci)
    await seeded_db.flush()
    for section_id in (yabanci.id, uuid.uuid4()):
        yanit = await client.get(
            f"/sites/{site.id}/diary", params={"section_id": str(section_id)}, headers=admin_headers
        )
        assert yanit.status_code == 422, yanit.text
        assert yanit.json()["detail"] == guards.SECTION_MISMATCH


# ------------------------------------------------------------------ detay · adlar


async def test_detay_adlari_tek_istekte(
    client: AsyncClient, admin_headers, kurgu, admin_kullanicisi, santiye
) -> None:
    site, b1, b2, e = kurgu
    _, project, _ = santiye
    yanit = await client.get(f"/diary/{e[5].id}", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    body = yanit.json()
    assert body["section_name"] == "B Blok"
    assert body["site_name"] == site.name
    assert body["project_name"] == project.name
    assert body["created_by_name"] == admin_kullanicisi.full_name
    by_section = {line["section_id"]: line["section_name"] for line in body["lines"]}
    assert by_section == {str(b1.id): "A Blok", str(b2.id): "B Blok"}


async def test_detay_bolumsuz_baslik_ve_satir_adi_null(
    client: AsyncClient, admin_headers, kurgu, seeded_db, santiye
) -> None:
    site, _, _, e = kurgu
    _, _, items = santiye
    seeded_db.add(SiteDiaryLine(entry_id=e[4].id, **_line_kw(items[0], None)))
    await seeded_db.flush()
    body = (await client.get(f"/diary/{e[4].id}", headers=admin_headers)).json()
    assert body["section_id"] is None and body["section_name"] is None
    assert [line["section_name"] for line in body["lines"]] == [None]


async def test_detay_taseron_satiri_firma_adi(
    client: AsyncClient, admin_headers, kurgu, seeded_db
) -> None:
    _, _, _, e = kurgu
    firma = Subcontractor(name="Kaya Duvar")
    seeded_db.add(firma)
    await seeded_db.flush()
    seeded_db.add_all(
        [
            SiteDiaryWorkerCount(
                entry_id=e[0].id,
                trade="Duvarcı",
                source=WorkerSource.subcontractor,
                count=4,
                subcontractor_id=firma.id,
                hours=Decimal("9"),
            ),
            SiteDiaryWorkerCount(
                entry_id=e[0].id, trade="Kalıpçı", source=WorkerSource.company, count=2
            ),
        ]
    )
    await seeded_db.flush()
    body = (await client.get(f"/diary/{e[0].id}", headers=admin_headers)).json()
    names = {row["trade"]: row["subcontractor_name"] for row in body["worker_counts"]}
    assert names == {"Duvarcı": "Kaya Duvar", "Kalıpçı": None}


# ------------------------------------------------------------------ detay · gönderen


async def test_gonderen_damgalanir_reopen_temizler_yeniden_gonderim_ezer(
    client: AsyncClient, admin_headers, sef_headers, kurgu, admin_kullanicisi, sef_kullanicisi
) -> None:
    _, _, _, e = kurgu
    entry_id = e[4].id  # satırsız + bölümsüz: gönderim ön-koşulları yalnız EV'den gelebilir
    taslak = (await client.get(f"/diary/{entry_id}", headers=admin_headers)).json()
    assert (taslak["submitted_by"], taslak["submitted_by_name"]) == (None, None)

    gonder = await client.post(f"/diary/{entry_id}/submit", headers=sef_headers)
    assert gonder.status_code == 200, gonder.text
    assert gonder.json()["submitted_by"] == str(sef_kullanicisi.id)
    assert gonder.json()["submitted_by_name"] == sef_kullanicisi.full_name

    geri = await client.post(f"/diary/{entry_id}/reopen", headers=admin_headers)
    assert geri.status_code == 200, geri.text
    assert (geri.json()["submitted_by"], geri.json()["submitted_by_name"]) == (None, None)

    tekrar = await client.post(f"/diary/{entry_id}/submit", headers=admin_headers)
    assert tekrar.status_code == 200, tekrar.text
    assert tekrar.json()["submitted_by"] == str(admin_kullanicisi.id)
    okunan = (await client.get(f"/diary/{entry_id}", headers=admin_headers)).json()
    assert okunan["submitted_by_name"] == admin_kullanicisi.full_name


# ------------------------------------------------------------------ detay · kilit (port)


async def test_detay_kilit_porttan_gelir_rapor_tarihiyle(
    client: AsyncClient, admin_headers, kurgu
) -> None:
    _, _, _, e = kurgu
    rapor = DAYS[3]

    async def kilitli(_session, _site_id, day):  # noqa: ANN001, ANN202
        return "kilitli" if day == DAYS[1] else None

    async def rapor_tarihi(_session, _site_id, _day):  # noqa: ANN001, ANN202
        return rapor

    snapshot = day_hooks.registered()
    day_hooks.unregister_all()
    try:
        day_hooks.register_day_lock(kilitli, report_date=rapor_tarihi)
        acik = (await client.get(f"/diary/{e[0].id}", headers=admin_headers)).json()
        kapali = (await client.get(f"/diary/{e[1].id}", headers=admin_headers)).json()
    finally:
        day_hooks.restore(snapshot)
    assert (acik["locked"], acik["lock_report_date"]) == (False, None)
    assert (kapali["locked"], kapali["lock_report_date"]) == (True, rapor.isoformat())


async def test_detay_port_bossa_kilitsiz(client: AsyncClient, admin_headers, kurgu) -> None:
    _, _, _, e = kurgu
    snapshot = day_hooks.registered()
    day_hooks.unregister_all()
    try:
        body = (await client.get(f"/diary/{e[1].id}", headers=admin_headers)).json()
    finally:
        day_hooks.restore(snapshot)
    assert (body["locked"], body["lock_report_date"]) == (False, None)


# ------------------------------------------------------------------ detay · önceki / sonraki


@pytest.mark.parametrize(
    ("index", "prev", "next_"),
    [(0, None, 1), (2, 1, 3), (5, 4, None)],
)
async def test_komsular_santiye_baglaminda_tarih_sirasi(
    client: AsyncClient, admin_headers, kurgu, index: int, prev, next_
) -> None:
    _, _, _, e = kurgu
    body = (await client.get(f"/diary/{e[index].id}", headers=admin_headers)).json()
    assert body["prev_id"] == (None if prev is None else str(e[prev].id))
    assert body["next_id"] == (None if next_ is None else str(e[next_].id))
    # DET-1.B ek: komşunun GÜNÜ aynı sorgudan (istemci sayfalı listeden bilemez)
    assert body["prev_entry_date"] == (None if prev is None else DAYS[prev].isoformat())
    assert body["next_entry_date"] == (None if next_ is None else DAYS[next_].isoformat())


@pytest.mark.parametrize(
    ("index", "prev", "next_"),
    # B1 kümesi: d1 · d2 · d3 · d6 — d4/d5 ATLANIR
    [(0, None, 1), (1, 0, 2), (2, 1, 5), (5, 2, None)],
)
async def test_komsular_bolum_baglaminda_kural_a(
    client: AsyncClient, admin_headers, kurgu, index: int, prev, next_
) -> None:
    _, b1, _, e = kurgu
    yanit = await client.get(
        f"/diary/{e[index].id}", params={"section_id": str(b1.id)}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    body = yanit.json()
    assert body["prev_id"] == (None if prev is None else str(e[prev].id))
    assert body["next_id"] == (None if next_ is None else str(e[next_].id))
    # DET-1.B ek: komşunun GÜNÜ aynı sorgudan (istemci sayfalı listeden bilemez)
    assert body["prev_entry_date"] == (None if prev is None else DAYS[prev].isoformat())
    assert body["next_entry_date"] == (None if next_ is None else DAYS[next_].isoformat())


async def test_komsular_baska_santiye_kaydina_atlamaz(
    client: AsyncClient,
    admin_headers,
    kurgu,
    santiye_fabrikasi,
    gunluk_fabrikasi,
    admin_kullanicisi,
) -> None:
    _, _, _, e = kurgu
    # Yabancı kayıtlar BİZİM ilk/son kaydımızın DIŞINDA: süzgeçsiz sorgu onları komşu sanırdı
    # (aynı güne koymak yetmez — tarih eşitliğinde sıra keyfi, mutasyon N4 hayatta kalıyordu).
    diger, _, _ = await santiye_fabrikasi("SD-Y")
    await gunluk_fabrikasi(diger, admin_kullanicisi, entry_date=DAYS[0] - timedelta(days=1))
    await gunluk_fabrikasi(diger, admin_kullanicisi, entry_date=DAYS[-1] + timedelta(days=1))
    ilk = (await client.get(f"/diary/{e[0].id}", headers=admin_headers)).json()
    son = (await client.get(f"/diary/{e[-1].id}", headers=admin_headers)).json()
    assert (ilk["prev_id"], son["next_id"]) == (None, None)


async def test_detay_baska_santiyenin_bolumu_422(
    client: AsyncClient, admin_headers, kurgu, seeded_db, santiye_fabrikasi
) -> None:
    _, _, _, e = kurgu
    diger, _, _ = await santiye_fabrikasi("SD-Z")
    yabanci = Section(site_id=diger.id, code="Z-1", name="Z")
    seeded_db.add(yabanci)
    await seeded_db.flush()
    yanit = await client.get(
        f"/diary/{e[0].id}", params={"section_id": str(yabanci.id)}, headers=admin_headers
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == guards.SECTION_MISMATCH


# ------------------------------------------------------------------ liste satırı · ek (#129)


async def test_liste_satiri_bolum_adi_ve_bolum_satir_sayisi(
    client: AsyncClient, admin_headers, kurgu
) -> None:
    site, b1, _, e = kurgu
    yanit = await client.get(
        f"/sites/{site.id}/diary", params={"section_id": str(b1.id)}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    satirlar = {item["id"]: item for item in yanit.json()["items"]}
    # (başlık bölümünün adı, B1'e düşen satır sayısı) — d6 başlığı B2 ama bir B1 satırı taşır
    beklenen = {
        e[5].id: ("B Blok", 1),
        e[2].id: ("A Blok", 2),
        e[1].id: (None, 1),
        e[0].id: ("A Blok", 0),
    }
    assert {
        uuid.UUID(k): (v["section_name"], v["section_line_count"]) for k, v in satirlar.items()
    } == beklenen


async def test_liste_satiri_bolumsuz_sorguda_satir_sayisi_null(
    client: AsyncClient, admin_headers, kurgu
) -> None:
    site, _, _, e = kurgu
    items = (await client.get(f"/sites/{site.id}/diary", headers=admin_headers)).json()["items"]
    assert {item["section_line_count"] for item in items} == {None}
    adlar = {uuid.UUID(item["id"]): item["section_name"] for item in items}
    assert (adlar[e[0].id], adlar[e[3].id], adlar[e[4].id]) == ("A Blok", "B Blok", None)


async def test_liste_bolum_adlari_sabit_sorgu_n_arti_bir_yok(
    client: AsyncClient, admin_headers, kurgu
) -> None:
    """Bölüm adı sayfa başına TEK `IN (…)` sorgusu; satır sayısı yüklenmiş satırlardan
    (ek sorgu YOK). 6 kayıtlı sayfa ile 1 kayıtlı sayfa AYNI sayıda `sections` sorgusu atar."""
    site, b1, _, _ = kurgu

    async def _bolum_sorgulari(limit: int) -> int:
        with _sorgu_sayaci() as ifadeler:
            yanit = await client.get(
                f"/sites/{site.id}/diary",
                params={"section_id": str(b1.id), "limit": limit},
                headers=admin_headers,
            )
        assert yanit.status_code == 200, yanit.text
        return sum(1 for s in ifadeler if "from sections" in s.lower())

    assert await _bolum_sorgulari(1) == await _bolum_sorgulari(4)
