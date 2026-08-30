"""B6 · B6b — AI araç denetimi (`ai_tool_calls`).

| Bekçi | Mutasyon (KIRMIZI olmalı) | Pozitif kontrol (YEŞİL kalmalı) |
|---|---|---|
| B6 | Yazımı istek session'ına taşı | Başarılı çağrıda **iki** satır (`started`+`finished`) |
| B6b | Audit session'ını boz → handler **çağrılmamış** olmalı | Normal turda handler çağrılır |

🔴 Bu dosyanın can alıcı noktası şudur: `record_tool_call` **AYRI** bir session
açar ve **COMMIT** eder. Ölçüldü ki `audit/service.py::record_audit` "COMMIT
ETMEZ, `flush()` bile çağırmaz" ve `core/db.py::get_db` istisnada `rollback()`
eder — yani istek session'ına yazılan bir korkuluk, araç patladığında **kendi
kaydını siler**. B6'nın mutasyonu tam olarak o kaymayı taklit eder.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.access import AccessLevel
from app.modules.ai import audit as ai_audit
from app.modules.ai.audit import record_tool_call
from app.modules.ai.models import AiToolCall, AiToolCallOrigin, AiToolCallPhase, AiToolDecision
from app.modules.ai.registry import ToolRegistry
from app.modules.ai.result import ToolError
from app.modules.ai.tools.catalog import NAVIGATE_TO
from tests.modules.ai.conftest import sahte_aktor, tam_izin

pytestmark = pytest.mark.asyncio


async def _satirlar(session, call_ids: set[uuid.UUID] | None = None) -> list[AiToolCall]:
    stmt = select(AiToolCall).order_by(AiToolCall.occurred_at)
    satirlar = list((await session.execute(stmt)).scalars())
    if call_ids is not None:
        satirlar = [s for s in satirlar if s.call_id in call_ids]
    return satirlar


# --------------------------------------------------------------------------- #
# record_tool_call — AYRI SESSION + COMMIT
# --------------------------------------------------------------------------- #


async def test_B6_denetim_satiri_ISTEK_SESSIONUNDAN_BAGIMSIZ_KALIR(db_session, monkeypatch):
    """🔴 B6'nın kalbi: yazım ayrı session'da olduğu için istek session'ının
    rollback'i satırı **silmez**.

    Test oturumu dış bir transaction üzerinde SAVEPOINT ile koşar; gerçek bir
    ikinci bağlantı açmak sonucu görünmez kılardı. Bu yüzden `SessionLocal`
    burada AYNI test bağlantısına yöneltilir ama **AYRI bir session nesnesi**
    olarak; ölçülen şey "yazımın istek session'ından bağımsız olması"dır.
    """
    yazilanlar: list[str] = []

    class _AyriSession:
        def __init__(self) -> None:
            self.eklenen: list[AiToolCall] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def add(self, nesne):
            self.eklenen.append(nesne)

        async def commit(self):
            yazilanlar.append("commit")
            for nesne in self.eklenen:
                db_session.add(nesne)
            await db_session.flush()

    monkeypatch.setattr(ai_audit, "SessionLocal", _AyriSession)

    call_id = uuid.uuid4()
    await record_tool_call(
        call_id=call_id,
        phase=AiToolCallPhase.started,
        user_id=None,
        tool_name="projeleri_listele",
        module_keys=["projects"],
        arguments={},
        decision=AiToolDecision.allowed,
        resolved_path="/projects",
    )

    # 🔴 Mutasyonun yakaladığı satır: COMMIT çağrıldı mı?
    assert yazilanlar == ["commit"], (
        "`record_tool_call` COMMIT etmedi. `record_audit` deseni kopyalanmış "
        "olabilir — o fonksiyon 'COMMIT ETMEZ, flush() bile çağırmaz' der ve "
        "bu tabloda o desen korkuluğun kendi kaydını sildirirdi."
    )
    satirlar = await _satirlar(db_session, {call_id})
    assert len(satirlar) == 1
    assert satirlar[0].resolved_path == "/projects"
    assert satirlar[0].origin is AiToolCallOrigin.ai


async def test_B6_MUTASYON_istek_sessionuna_yazilirsa_ROLLBACK_satiri_SILER(db_session):
    """`record_tool_call` istek session'ına yazsaydı ne olurdu.

    Mutasyonu elle kuruyoruz: satırı istek session'ına ekle, sonra o session'ı
    geri al (araç patladığında `get_db`nin yaptığı şey). Satır **KAYBOLUR** —
    yani B6 eşdeğer bir mutant taşımıyor.
    """
    call_id = uuid.uuid4()
    savepoint = await db_session.begin_nested()
    db_session.add(
        AiToolCall(
            call_id=call_id,
            phase=AiToolCallPhase.started,
            user_id=None,
            tool_name="mutant",
            module_keys=[],
            arguments={},
            decision=AiToolDecision.allowed,
            origin=AiToolCallOrigin.ai,
        )
    )
    await db_session.flush()
    assert len(await _satirlar(db_session, {call_id})) == 1  # yazıldı…
    await savepoint.rollback()
    assert await _satirlar(db_session, {call_id}) == []  # …ve rollback SİLDİ


# --------------------------------------------------------------------------- #
# B6 — başarılı çağrıda TAM İKİ satır
# --------------------------------------------------------------------------- #


async def test_B6_basarili_cagride_TAM_IKI_satir_ve_TEK_call_id(monkeypatch, transport_factory):
    kayitlar: list[dict] = []

    async def _sahte(**kwargs):
        kayitlar.append(kwargs)

    monkeypatch.setattr(ai_audit, "record_tool_call", _sahte)

    kayit = ToolRegistry((NAVIGATE_TO,))
    sonuc = await kayit.invoke(
        arac_adi="navigate_to",
        argumanlar={"ekran": "projeler"},
        actor=sahte_aktor(tam_izin()),
        transport=transport_factory(bearer="kullanilmayacak"),
    )
    assert not isinstance(sonuc, ToolError), sonuc

    assert len(kayitlar) == 2, f"iki satır bekleniyordu, {len(kayitlar)} yazıldı"
    assert [k["phase"] for k in kayitlar] == [
        AiToolCallPhase.started,
        AiToolCallPhase.finished,
    ]
    assert len({k["call_id"] for k in kayitlar}) == 1, "iki satır AYNI call_id taşımalı"
    assert all(k["decision"] is AiToolDecision.allowed for k in kayitlar)


async def test_B6_arac_PATLASA_DA_started_satiri_YAZILMIS_olur(monkeypatch, transport_factory):
    """Araç kasten patlatılır: `started` satırı DURUR."""
    kayitlar: list[dict] = []

    async def _sahte(**kwargs):
        kayitlar.append(kwargs)

    monkeypatch.setattr(ai_audit, "record_tool_call", _sahte)

    import httpx

    async def _patlayan(ctx, girdi):
        raise httpx.ConnectError("kasten")

    import dataclasses

    patlayan_spec = dataclasses.replace(NAVIGATE_TO, calistir=_patlayan)
    kayit = ToolRegistry((patlayan_spec,))
    sonuc = await kayit.invoke(
        arac_adi="navigate_to",
        argumanlar={"ekran": "projeler"},
        actor=sahte_aktor(tam_izin()),
        transport=transport_factory(bearer="kullanilmayacak"),
    )
    assert isinstance(sonuc, ToolError) and sonuc.kod == "ust_kaynak_hatasi"
    assert [k["phase"] for k in kayitlar] == [
        AiToolCallPhase.started,
        AiToolCallPhase.finished,
    ]
    assert kayitlar[1]["error"] == "ConnectError"


# --------------------------------------------------------------------------- #
# B6b — FAIL-CLOSED
# --------------------------------------------------------------------------- #


async def test_B6b_denetim_yazilamazsa_HANDLER_CAGRILMAZ(monkeypatch, transport_factory):
    """🔴 Fail-closed. Denetim bozulur, handler'ın çağrılmadığı ÖLÇÜLÜR."""
    cagrildi: list[str] = []

    async def _izleyen_handler(ctx, girdi):
        cagrildi.append("handler")
        raise AssertionError("buraya HİÇ gelinmemeliydi")

    async def _bozuk(**kwargs):
        raise RuntimeError("denetim tablosu erişilemez")

    monkeypatch.setattr(ai_audit, "record_tool_call", _bozuk)

    import dataclasses

    spec = dataclasses.replace(NAVIGATE_TO, calistir=_izleyen_handler)
    kayit = ToolRegistry((spec,))
    sonuc = await kayit.invoke(
        arac_adi="navigate_to",
        argumanlar={"ekran": "projeler"},
        actor=sahte_aktor(tam_izin()),
        transport=transport_factory(bearer="kullanilmayacak"),
    )
    assert isinstance(sonuc, ToolError) and sonuc.kod == "denetim_yazilamadi"
    assert cagrildi == [], "denetim yazılamadığı hâlde handler KOŞTU (fail-OPEN)"


async def test_B6b_POZITIF_KONTROL_normal_turda_handler_CAGRILIR(monkeypatch, transport_factory):
    """İkinci yarı olmadan yukarıdaki test 'hiçbir şey olmuyor'u kanıtlardı."""
    cagrildi: list[str] = []

    async def _izleyen_handler(ctx, girdi):
        cagrildi.append("handler")
        from app.modules.ai.result import Ok

        return Ok(data={}, row_count=0)

    async def _sahte(**kwargs):
        return None

    monkeypatch.setattr(ai_audit, "record_tool_call", _sahte)

    import dataclasses

    spec = dataclasses.replace(NAVIGATE_TO, calistir=_izleyen_handler)
    kayit = ToolRegistry((spec,))
    await kayit.invoke(
        arac_adi="navigate_to",
        argumanlar={"ekran": "projeler"},
        actor=sahte_aktor(tam_izin()),
        transport=transport_factory(bearer="kullanilmayacak"),
    )
    assert cagrildi == ["handler"]


# --------------------------------------------------------------------------- #
# S27 — denetime ÇÖZÜLMÜŞ yol yazılır, ŞABLON DEĞİL
# --------------------------------------------------------------------------- #


async def test_S27_denetime_COZULMUS_yol_yazilir_sablon_DEGIL(monkeypatch, transport_factory):
    kayitlar: list[dict] = []

    async def _sahte(**kwargs):
        kayitlar.append(kwargs)

    monkeypatch.setattr(ai_audit, "record_tool_call", _sahte)

    from app.modules.ai.tools.catalog import PUANTAJ_HAFTASI

    site_id = uuid.uuid4()
    kayit = ToolRegistry((PUANTAJ_HAFTASI,))
    await kayit.invoke(
        arac_adi="puantaj_haftasi",
        argumanlar={"site_id": str(site_id), "iso_year": 2026, "iso_week": 30},
        actor=sahte_aktor({"timesheet": AccessLevel.view}),
        transport=transport_factory(bearer="gecersiz"),
    )
    yollar = {k["resolved_path"] for k in kayitlar}
    assert f"/sites/{site_id}/timesheet/week" in yollar
    assert "/sites/{site_id}/timesheet/week" not in yollar, (
        "Denetime ŞABLON yazıldı. `ai_tool_calls` o hâlde yalan söyler ve bu "
        "dilimin tüm meselesi atfedilebilirlikti (S27)."
    )


async def test_denetim_tablosuna_gercek_INSERT_CALISIR(db_session):
    """Şema sondası: model ile migration ayrışmışsa burada patlar."""
    db_session.add(
        AiToolCall(
            call_id=uuid.uuid4(),
            phase=AiToolCallPhase.finished,
            user_id=None,
            tool_name="sonda",
            module_keys=["projects", "timesheet"],
            arguments={"a": 1},
            decision=AiToolDecision.denied_permission,
            origin=AiToolCallOrigin.ai,
            resolved_path="/projects",
            http_status=403,
            latency_ms=12,
        )
    )
    await db_session.flush()
    assert await db_session.scalar(select(func.count()).select_from(AiToolCall)) >= 1
