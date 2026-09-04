"""AI-0b yapısal bekçileri — B10 · B14 · B15 · B16 · B17 · B20 · B25 · B26 (+S1, S15).

Hepsi **koddan ölçer**, elle yazılmış listeye güvenmez. Tek istisna
`UNGATED_ALLOWLIST`tir ve o da bilinçlidir: kapısız uçlar **ad ad** yazılır,
çünkü "kapısı yok" ile "kapısını çıkaramadım" farklı iki şeydir ve ikincisi
**SKIP değil KIRMIZI**dır.
"""

from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.core.access import AccessLevel
from app.main import app
from app.modules.ai.registry import ToolKapsami, ToolKumesi, ToolRegistry, ToolSpec
from app.modules.ai.result import Restricted, ToolError
from app.modules.ai.tools import schemas
from app.modules.ai.tools.catalog import CATALOG, READ_TOOLS, YONETISIM_DENYLIST
from app.modules.ai.transport import YolReddedildi, kacisla
from tests.modules.ai.conftest import sahte_aktor, tam_izin

AI_KOK = Path(__file__).parents[3] / "app" / "modules" / "ai"

#: 🔴 Kapısız GET'ler — **AD AD** (ölçüldü: 10 üye). Bir araç bu listede
#: olmayan kapısız bir ucu sararsa B10 kırmızı olur.
UNGATED_ALLOWLIST: frozenset[str] = frozenset(
    {
        "/approvals",
        "/approvals/settings",
        "/auth/me",
        "/company",
        "/company/logo",
        "/health",
        "/leave-requests/self",
        "/leave-types",
        "/settings/notifications",
        "/settings/preferences",
    }
)

#: 🔴 S30 — **YAZAN GET**'ler. `get_or_create_singleton` → `session.add` →
#: `flush()`; salt-okunur bağlantıda **500** üretir. Katalogdan PEŞİNEN
#: dışlanırlar.
#:
#: ⚠️ Emir yalnız `GET /company`i sayıyordu; ölçüm **İKİSİNİ** buldu:
#: `GET /company/logo` da aynı `service.get_company` zincirini çağırır
#: (`company/router.py:117`). Yani liste iki üyelidir.
YAZAN_GETLER: frozenset[str] = frozenset({"/company", "/company/logo"})


# --------------------------------------------------------------------------- #
# Rota tablosu + kapı çıkarıcı (mevcut, kanıtlanmış desen)
# --------------------------------------------------------------------------- #


def _api_rotalari(rotalar) -> list[APIRoute]:
    """🔴 fastapi 0.141'de `app.routes` doğrudan `APIRoute` VERMEZ (43 öge, 1'i
    `APIRoute`). Ara katman `_IncludedRouter`dır ve özyineleme şarttır."""
    cikti: list[APIRoute] = []
    for rota in rotalar:
        if isinstance(rota, APIRoute):
            cikti.append(rota)
        elif type(rota).__name__ == "_IncludedRouter":
            cikti.extend(_api_rotalari(rota.original_router.routes))
        elif hasattr(rota, "routes"):
            cikti.extend(_api_rotalari(rota.routes))
    return cikti


def _kapilar(rota: APIRoute) -> set[tuple[str, AccessLevel]]:
    """Rotanın kapıları — CLOSURE serbest değişkenlerinden.

    🔴 Ayrım FONKSİYON ADINDAN yapılmaz: `require_permission` da
    `require_permission_or_chain_step` de içeride `_check` adında bir kapanış
    döndürür. Ölçülen şey kapanışın TAŞIDIĞI değerlerdir. Yalnız birini tanıyan
    bir betik "kapısız operasyon 23" der; gerçek **17**'dir.
    """
    bulunan: set[tuple[str, AccessLevel]] = set()
    for bagimlilik in rota.dependant.dependencies:
        cagri = bagimlilik.call
        kod = getattr(cagri, "__code__", None)
        kapanis = getattr(cagri, "__closure__", None)
        if kod is None or not kapanis:
            continue
        serbest = {
            ad: hucre.cell_contents for ad, hucre in zip(kod.co_freevars, kapanis, strict=True)
        }
        if "module_key" in serbest and "min_level" in serbest:
            bulunan.add((serbest["module_key"], serbest["min_level"]))
    return bulunan


def _get_rotalari() -> dict[str, APIRoute]:
    return {r.path: r for r in _api_rotalari(app.routes) if "GET" in (r.methods or set())}


# --------------------------------------------------------------------------- #
# B10 — kapı BEYANI == ucun GERÇEK kapısı (KÜME)
# --------------------------------------------------------------------------- #


def test_B10_POZITIF_KONTROL_kapi_cikarici_IKI_FABRIKAYI_da_taniyor() -> None:
    """Çıkarıcı yalnız `require_permission`ı tanısaydı zincir uçları 'kapısız'
    görünürdü. Ölçülmüş olgu: `require_permission_or_chain_step` de kapanışında
    `module_key`/`min_level` taşır (bilinçli tasarım — gate.py docstring'i)."""
    rotalar = _get_rotalari()
    zincirli = rotalar.get("/projects/{project_id}/progress-payments/diary-suggestion")
    assert zincirli is not None
    # İKİ kapı taşıyan iki uçtan biri (ölçüldü: tam 2 operasyon).
    assert len(_kapilar(zincirli)) == 2, _kapilar(zincirli)
    assert {m for m, _ in _kapilar(zincirli)} == {"progress_payments", "site_diary"}


@pytest.mark.parametrize("spec", CATALOG, ids=lambda s: s.ad)
def test_B10_arac_kapi_beyani_ucun_GERCEK_kapisina_ESITTIR(spec: ToolSpec) -> None:
    rotalar = _get_rotalari()
    for uc in spec.ucler:
        rota = rotalar.get(uc)
        assert rota is not None, (
            f"`{spec.ad}` var olmayan bir ucu sarıyor: {uc}. "
            "Kapı çıkarılamadı — bu SKIP değil KIRMIZIDIR."
        )
        gercek = _kapilar(rota)
        assert gercek == set(spec.kapilar), (
            f"`{spec.ad}` kapı BEYANI ile ucun GERÇEK kapısı ayrışıyor.\n"
            f"  beyan: {sorted(spec.kapilar)}\n  gerçek: {sorted(gercek)}"
        )
        if not gercek:
            assert uc in UNGATED_ALLOWLIST, (
                f"`{uc}` kapısız görünüyor ama UNGATED_ALLOWLIST'te YOK. "
                "Ya kapı çıkarıcı onu göremiyor (kırmızı) ya da yeni bir "
                "kapısız uç doğdu ve bilinçli olarak listeye yazılmalı."
            )


def test_B10_MUTASYON_module_key_degistirilirse_KIRMIZI_olur() -> None:
    """`kapilar`daki `module_key` değiştirilirse test kırmızı olmalı — yani B10
    eşdeğer bir mutant taşımıyor."""
    import dataclasses

    from app.modules.ai.tools.catalog import PROJELERI_LISTELE

    mutant = dataclasses.replace(
        PROJELERI_LISTELE, kapilar=frozenset({("inventory", AccessLevel.view)})
    )
    rota = _get_rotalari()["/projects"]
    assert _kapilar(rota) != set(mutant.kapilar)


def test_B10_ZINCIR_dalindaki_mutant_HAYATTA_KALABILIR_bu_hal_AYRICA_ele_alinir() -> None:
    """🔴 DÜRÜST NOT — B10'un bilinen sınırı.

    `require_permission_or_chain_step` bir İKAME dalı taşır: modül kapısı 403
    verirse zincirin sıradaki adımının onay rolüne bakar ve taşıyorsa GEÇİRİR.
    Yani böyle bir uç **tek bir `(module_key, min_level)` çiftine
    İNDİRGENEMEZ**: kapı beyanı doğru olsa bile aktör onu kapıdan geçmeden
    okuyabilir.

    Bu test o hâli **kapatmaz**, KAYDA GEÇİRİR ve yapısal olarak kilitler:
    AI-0b'nin altı aracının hiçbiri ikame dalı taşıyan bir ucu sarmıyor. Bir
    gün sararsa bu test kırmızı olur ve şef `kapilar` yerine gerçek bir zincir
    iddiası yazmak zorunda kalır.
    """
    ikame_uclari = set()
    for rota in _api_rotalari(app.routes):
        for bagimlilik in rota.dependant.dependencies:
            cagri = bagimlilik.call
            kod = getattr(cagri, "__code__", None)
            kapanis = getattr(cagri, "__closure__", None)
            if kod is None or not kapanis:
                continue
            serbest = dict(zip(kod.co_freevars, kapanis, strict=True))
            if "document_type" in serbest and "document_id_param" in serbest:
                ikame_uclari.add(rota.path)
    assert ikame_uclari, "ikame kapısı taşıyan uç bulunamadı — çıkarıcı bozuk olabilir"
    sarilan = {uc for s in CATALOG for uc in s.ucler}
    assert sarilan & ikame_uclari == set(), (
        "Bir araç İKAME dalı taşıyan bir ucu sarıyor. `kapilar` beyanı o uçta "
        f"YETMEZ: {sorted(sarilan & ikame_uclari)}"
    )


# --------------------------------------------------------------------------- #
# B25 — `response_model is None` olan uç araç OLAMAZ
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec", CATALOG, ids=lambda s: s.ad)
def test_B25_sarilan_her_uc_response_model_TASIR(spec: ToolSpec) -> None:
    rotalar = _get_rotalari()
    for uc in spec.ucler:
        assert rotalar[uc].response_model is not None, (
            f"`{spec.ad}` `response_model` taşımayan bir ucu sarıyor: {uc}. "
            "JSON olmayan uçlar (export.xlsx, download, logo) araç OLAMAZ."
        )
    from pydantic import BaseModel

    assert issubclass(spec.yanit_modeli, BaseModel), "ORM ASLA dönmez"


def test_B25_MUTASYON_response_modelsiz_bir_uc_GERCEKTEN_VAR() -> None:
    """Pozitif kontrol: `response_model is None` olan uçlar gerçekten var,
    yani yukarıdaki iddia boş bir kümede dolaşmıyor."""
    modelsiz = [y for y, r in _get_rotalari().items() if r.response_model is None]
    assert modelsiz, "hiç `response_model`sız GET yok — B25 hiçbir şey ölçmüyor olurdu"
    assert not (set(modelsiz) & {uc for s in CATALOG for uc in s.ucler})


# --------------------------------------------------------------------------- #
# S30 — yazan GET katalogdan PEŞİNEN dışlanır
# --------------------------------------------------------------------------- #


def test_S30_yazan_GET_katalogda_YOKTUR() -> None:
    """`GET /company` `get_or_create_singleton` → `session.add` yapar; salt-okunur
    bağlantıda **500** üretir. Kapı D onu yakalar ama sonuç `ToolError`dur —
    bu yüzden peşinen dışlanır."""
    sarilan = {uc for s in CATALOG for uc in s.ucler}
    assert sarilan & YAZAN_GETLER == set()


def test_S30_POZITIF_KONTROL_yazan_GET_gercekten_YAZIYOR() -> None:
    """İddianın boş olmadığının kanıtı — **çağrı zinciri boyunca** ölçülür.

    🔴 Bu testin ilk hâli `company/router.py`de `get_or_create` arıyordu ve
    KIRMIZI oldu: yazma router'da değil, iki katman aşağıda. "Router'da yok →
    yazmıyor" çıkarımı tam olarak bu deponun sevmediği sessiz yanlıştır.
    Gerçek zincir: `router.get_company_endpoint` → `service.get_company` →
    `repository.get_or_create_singleton` → `session.add` + `flush()`.
    """
    from app.modules.company import repository as company_repository
    from app.modules.company import service as company_service

    servis = Path(company_service.__file__).read_text(encoding="utf-8")
    depo = Path(company_repository.__file__).read_text(encoding="utf-8")
    assert "get_or_create_singleton" in servis
    govde = depo[depo.index("async def get_or_create_singleton") :]
    govde = govde[: govde.index("async def set_logo")]
    assert "session.add(" in govde and "flush()" in govde, (
        "`GET /company`in yazan-GET olduğu iddiası artık doğrulanamıyor; "
        "YAZAN_GETLER listesi yeniden ölçülmeli."
    )


def test_S30_yazan_GETler_kapisiz_listede_de_DURUYOR() -> None:
    """İkisi de `UNGATED_ALLOWLIST` üyesidir: yani bir araç onları sarsaydı
    B10'un kapısızlık dalından SESSİZCE geçerdi. S30 bu yüzden AYRI bir
    bekçidir."""
    assert YAZAN_GETLER <= UNGATED_ALLOWLIST


# --------------------------------------------------------------------------- #
# B14 — IMPORT SINIRI (`ai/tools/**`)
# --------------------------------------------------------------------------- #


def _tools_kaynaklari() -> list[Path]:
    return sorted((AI_KOK / "tools").rglob("*.py"))


def test_B14_POZITIF_KONTROL_taranan_dosya_kumesi_BOS_DEGIL() -> None:
    assert len(_tools_kaynaklari()) >= 4


@pytest.mark.parametrize("yol", _tools_kaynaklari(), ids=lambda p: p.name)
def test_B14_tools_altinda_service_repository_models_IMPORT_EDILEMEZ(yol: Path) -> None:
    agac = ast.parse(yol.read_text(encoding="utf-8"))
    yasak: list[str] = []
    for dugum in ast.walk(agac):
        adlar: list[str] = []
        if isinstance(dugum, ast.Import):
            adlar = [a.name for a in dugum.names]
        elif isinstance(dugum, ast.ImportFrom) and dugum.module:
            adlar = [dugum.module] + [f"{dugum.module}.{a.name}" for a in dugum.names]
        for ad in adlar:
            if re.match(r"^app\.modules\.[a-z_]+\.(service|repository|models)\b", ad):
                yasak.append(ad)
    assert yasak == [], (
        f"{yol.name} servisi/repository'yi/ORM'i import ediyor: {yasak}. "
        "Araçlar SERVİSİ DEĞİL UCU sarar (T2) — `timesheet/week.py::build` "
        "aktör ALMAZ ve kapsam kapısı router'dadır."
    )


@pytest.mark.parametrize("yol", _tools_kaynaklari(), ids=lambda p: p.name)
def test_B14_tools_altinda_select_ve_session_TOKENI_SIFIRDIR(yol: Path) -> None:
    kaynak = yol.read_text(encoding="utf-8")
    # 🔴 Yorum ve docstring'ler AYIKLANIR: bu dosyaların docstring'leri gerekçe
    # olarak `select(`/`session.` yazıyor ve bir bekçinin kendi gerekçesine
    # takılması sahte-kırmızıdır (`route.test.ts`in yorum ayıklamayan bekçisi
    # tam olarak bu tuzağa düşüyor).
    agac = ast.parse(kaynak)
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.Expr) and isinstance(dugum.value, ast.Constant):
            if isinstance(dugum.value.value, str):
                dugum.value.value = ""
    temiz = ast.unparse(agac)
    temiz = "\n".join(s.split("#", 1)[0] for s in temiz.splitlines())
    assert "select(" not in temiz, f"{yol.name} `select(` içeriyor"
    assert "session." not in temiz, f"{yol.name} `session.` içeriyor"


def test_B14_MUTASYON_import_eklenirse_YAKALANIR(tmp_path: Path) -> None:
    """Bekçinin eşdeğer olmadığının kanıtı: aynı denetleyici, ihlalli bir
    dosyada gerçekten konuşuyor."""
    sahte = tmp_path / "mutant.py"
    sahte.write_text(
        "from app.modules.timesheet.service import visible_site\nx = visible_site\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError):
        test_B14_tools_altinda_service_repository_models_IMPORT_EDILEMEZ(sahte)


# --------------------------------------------------------------------------- #
# B15 — TEK HUNİ: dispatcher dışında handler import eden modül YOK
# --------------------------------------------------------------------------- #


def test_B15_handlerlari_YALNIZ_catalog_import_eder() -> None:
    """Kapı E. Bir modül handler'ı doğrudan import ederse huninin dışına çıkar
    (izin + denetim + yol kaçışı + tavan hiç koşmaz)."""
    izinli = {AI_KOK / "tools" / "catalog.py"}
    ihlal: list[str] = []
    for yol in (AI_KOK.parents[2]).rglob("*.py"):
        if ".venv" in yol.parts or yol in izinli:
            continue
        if "tests" in yol.parts:
            continue
        kaynak = yol.read_text(encoding="utf-8")
        if "ai.tools.reads" in kaynak and "import" in kaynak:
            ihlal.append(str(yol))
    assert ihlal == [], f"handler'ı huninin dışından import eden modül(ler): {ihlal}"


def test_B15_POZITIF_KONTROL_catalog_handlerlari_GERCEKTEN_import_eder() -> None:
    kaynak = (AI_KOK / "tools" / "catalog.py").read_text(encoding="utf-8")
    assert "from app.modules.ai.tools.reads import handlers" in kaynak


# --------------------------------------------------------------------------- #
# S15 — AI'ın kendi kimliği YOKTUR
# --------------------------------------------------------------------------- #


def test_S15_ai_altinda_SessionLocal_YALNIZ_audit_ve_conversations_pyde() -> None:
    """🔴 AI-CHAT-2'de küme İKİ üyeye çıktı — sessizce değil, **ADIYLA**.

    `conversations.py` asistan cevabını saklar ve bu yazı §5-33 gereği akış
    gövdesinde koşar; `AiSessionLocal` salt-okunur olduğu için geriye tek doğru
    seçenek kendi yazılabilir session'ıdır. Üçüncü bir dosya eklenirse bu test
    yine kırmızı olur.

    🔴 **DÜZELTİLDİ (AI-SOHBET-FIX).** Bu docstring eskiden gerekçeyi *"`get_db`
    SÖKÜLDÜKTEN sonra koşar: istek session'ı kapalı"* diye yazıyordu. Sıra
    ÖLÇÜLDÜ ve tersi çıktı: `yield` bağımlılıkları akış gövdesi BİTTİKTEN sonra
    sökülür, yani istek session'ı o sırada hâlâ AÇIK ama COMMIT EDİLMEMİŞTİR.
    Ayrı session'ın satırı görememesinin sebebi budur ve canlıda her tur bu
    yüzden FK ihlaline düştü (bkz. `test_aisohbetfix_kalicilik.py`).
    """
    kullananlar = {
        yol.name
        for yol in AI_KOK.rglob("*.py")
        if re.search(r"^\s*(async with )?SessionLocal\(", yol.read_text(encoding="utf-8"), re.M)
    }
    assert kullananlar == {"audit.py", "conversations.py"}, (
        f"`SessionLocal(` beklenmedik dosyalarda: {sorted(kullananlar)}. "
        "İki istisna vardır: `audit.py` (denetim ayrı session ister) ve "
        "`conversations.py` (asistan cevabı akış gövdesinde saklanır, §5-33)."
    )


def test_S15_ai_altinda_bootstrap_admin_ve_AccessLevel_admin_LITERALI_YOK() -> None:
    ihlal: list[str] = []
    for yol in AI_KOK.rglob("*.py"):
        kaynak = yol.read_text(encoding="utf-8")
        agac = ast.parse(kaynak)
        for dugum in ast.walk(agac):
            if isinstance(dugum, ast.Expr) and isinstance(dugum.value, ast.Constant):
                if isinstance(dugum.value.value, str):
                    dugum.value.value = ""
        temiz = "\n".join(s.split("#", 1)[0] for s in ast.unparse(agac).splitlines())
        for desen in ("settings.admin_", "bootstrap", "AccessLevel.admin"):
            if desen in temiz:
                ihlal.append(f"{yol.name}: {desen}")
    assert ihlal == [], ihlal


def test_S15_invoke_actor_ZORUNLU_varsayilani_YOK() -> None:
    import inspect

    imza = inspect.signature(ToolRegistry.invoke)
    actor = imza.parameters["actor"]
    assert actor.default is inspect.Parameter.empty, "`actor` varsayılan taşıyor — S15 ihlali"
    assert actor.kind is inspect.Parameter.KEYWORD_ONLY


# --------------------------------------------------------------------------- #
# S1 — `Scope` DEKORATİFTİR, `ActorContext` onu TAŞIMAZ
# --------------------------------------------------------------------------- #


def test_S1_ActorContext_scope_ALANI_TASIMAZ() -> None:
    """Ölçüldü: `Scope`un 14 isabetinin hepsi `roles/` altında, hiçbir süzgeç
    `permission.scope` okumuyor — `_FIN` ile `_V` **bit bit aynı** veriyi
    veriyor. Kapsam etiketini yetki gerekçesi diye taşımak, İzin Matrisi
    ekranının bugünkü yalanını AI'a taşırdı."""
    import dataclasses

    from app.modules.ai.registry import ActorContext

    alanlar = {f.name for f in dataclasses.fields(ActorContext)}
    assert "scope" not in alanlar, (
        "`ActorContext`e `scope` eklenmiş. `Scope` DEKORATİFTİR (A7 kararı "
        "gelene kadar): kod onu hiçbir yerde uygulamıyor."
    )


def test_S1_ai_modulu_Scope_enumunu_HIC_kullanmaz() -> None:
    kullananlar = [
        yol.name
        for yol in AI_KOK.rglob("*.py")
        if re.search(r"\bScope\.", yol.read_text(encoding="utf-8"))
    ]
    assert kullananlar == [], kullananlar


# --------------------------------------------------------------------------- #
# B16 — yol parametresi
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kotu", ["..", ".", "", "a/b", "..%2F", "a\\b"])
def test_B16_nokta_segment_ve_slash_REDDEDILIR(kotu: str) -> None:
    if kotu == "..%2F":
        # `%2F` zaten kaçışlanmış bir `/`dir; `quote` onu yeniden kaçışlar ve
        # segment sınırı geçilmez — yine de nokta önekiyle reddedilmesi
        # BEKLENMEZ, o yüzden ayrı ele alınır.
        assert kacisla(kotu) == "..%252F"
        return
    with pytest.raises(YolReddedildi):
        kacisla(kotu)


def test_B16_POZITIF_KONTROL_gecerli_UUID_normal_gecer() -> None:
    kimlik = uuid.uuid4()
    assert kacisla(kimlik) == str(kimlik)


def test_B16_MUTASYON_quote_TEK_BASINA_YETMEZ() -> None:
    """🔴 Ölçülmüş olgu: `quote('..', safe='')` **`..`yı DEĞİŞTİRMEZ**.

    Yani "tipli parametre + quote" kombinasyonunu savunma sanan bir tasarım
    S27'ye karşı korumasızdır; yükü taşıyan tek önlem açık reddir.
    """
    from urllib.parse import quote

    assert quote("..", safe="") == ".."


async def test_B16_arac_hunisi_kotu_yolu_REDDEDER(transport_factory, monkeypatch) -> None:
    from app.modules.ai import audit as ai_audit
    from app.modules.ai.tools.catalog import PUANTAJ_HAFTASI

    async def _sahte(**kwargs):
        return None

    monkeypatch.setattr(ai_audit, "record_tool_call", _sahte)
    kayit = ToolRegistry((PUANTAJ_HAFTASI,))
    sonuc = await kayit.invoke(
        arac_adi="puantaj_haftasi",
        # `site_id` TİPLİ (`uuid.UUID`) olduğu için `..` şema katmanında düşer.
        argumanlar={"site_id": "..", "iso_year": 2026, "iso_week": 30},
        actor=sahte_aktor({"timesheet": AccessLevel.view}),
        transport=transport_factory(bearer="x"),
    )
    assert isinstance(sonuc, ToolError) and sonuc.kod == "gecersiz_argüman"


# --------------------------------------------------------------------------- #
# B17 — `ReadOnlyTransport`
# --------------------------------------------------------------------------- #


def test_B17_GET_disi_metot_YOKTUR(transport_factory) -> None:
    tasima = transport_factory(bearer="x")
    for metot in ("post", "put", "patch", "delete", "request", "send", "stream"):
        assert not hasattr(tasima, metot), f"`{metot}` var — yazma yüzeyi doğdu"


def test_B17_POZITIF_KONTROL_get_VARDIR(transport_factory) -> None:
    assert callable(transport_factory(bearer="x").get)


async def test_B17_spec_disi_yol_REDDEDILIR(transport_factory) -> None:
    tasima = transport_factory(bearer="x")
    with pytest.raises(YolReddedildi):
        await tasima.get("/company", izinli_desenler=("/projects",))


async def test_B17_POZITIF_KONTROL_gecerli_GET_gecer(transport_factory) -> None:
    tasima = transport_factory(bearer="x")
    yanit = await tasima.get("/health", izinli_desenler=("/health",))
    assert yanit.status_code == 200


async def test_B17_MUTASYON_ham_httpx_istemcisi_HER_YOLU_gecirirdi(okuma_duzlemi) -> None:
    """#3'ün ölümcül açığı: bağlam tam bir httpx istemcisi taşısaydı."""
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=okuma_duzlemi), base_url="http://okuma"
    ) as ham:
        # Hiçbir `ucler` kontrolü yok — istediği yola gidebiliyor.
        assert (await ham.get("/company")).status_code in {200, 401, 403, 500}


def test_B17_navigate_to_HICBIR_uca_gidemez() -> None:
    from app.modules.ai.tools.catalog import NAVIGATE_TO

    assert NAVIGATE_TO.ucler == ()


# --------------------------------------------------------------------------- #
# B20 — katı sözlük araması
# --------------------------------------------------------------------------- #


async def test_B20_bilinmeyen_arac_adi_HIC_SORGU_KOSTURMAZ(transport_factory, monkeypatch) -> None:
    from app.modules.ai import audit as ai_audit

    async def _sahte(**kwargs):
        return None

    monkeypatch.setattr(ai_audit, "record_tool_call", _sahte)
    tasima = transport_factory(bearer="x")
    kayit = ToolRegistry(READ_TOOLS)
    # `projeleri_listele`ye ÇOK benzeyen bir ad: bulanık eşleşme olsaydı geçerdi.
    sonuc = await kayit.invoke(
        arac_adi="projeleri_listle",
        argumanlar={},
        actor=sahte_aktor(tam_izin()),
        transport=tasima,
    )
    assert isinstance(sonuc, ToolError) and sonuc.kod == "bilinmeyen_arac"
    assert tasima.cagrilan_yollar == [], "bilinmeyen ad DB'ye/uca gitti"


def test_B20_MUTASYON_difflib_yedegi_eklenirse_ad_ESLESIRDI() -> None:
    """Bulanık eşleşmenin gerçekten tehlikeli olduğunun kanıtı."""
    import difflib

    adlar = [s.ad for s in READ_TOOLS]
    assert difflib.get_close_matches("projeleri_listle", adlar, n=1, cutoff=0.8) == [
        "projeleri_listele"
    ], "bu mutant gerçek bir aracı çağırırdı"


async def test_B20_POZITIF_KONTROL_gercek_ad_normal_dispatch(
    transport_factory, monkeypatch
) -> None:
    from app.modules.ai import audit as ai_audit

    async def _sahte(**kwargs):
        return None

    monkeypatch.setattr(ai_audit, "record_tool_call", _sahte)
    kayit = ToolRegistry(READ_TOOLS)
    sonuc = await kayit.invoke(
        arac_adi="navigate_to",
        argumanlar={"ekran": "projeler"},
        actor=sahte_aktor(tam_izin()),
        transport=transport_factory(bearer="x"),
    )
    assert not isinstance(sonuc, ToolError), sonuc


# --------------------------------------------------------------------------- #
# B26 — yönetişim denylist'i
# --------------------------------------------------------------------------- #


def test_B26_yonetisim_modullerine_KAPI_TASIYAN_arac_KAYDEDILEMEZ() -> None:
    ihlal = [
        (s.ad, modul) for s in CATALOG for modul, _ in s.kapilar if modul in YONETISIM_DENYLIST
    ]
    assert ihlal == [], (
        f"Yönetişim denylist ihlali: {ihlal}. S17: 'yalnız sysadmin yazar' "
        "cümlesi, AI'ın izin matrisini yeniden yazabilmesi DEMEK DEĞİLDİR."
    )


def test_B26_MUTASYON_propose_approval_threshold_eklenirse_KIRMIZI() -> None:
    mutant = ToolSpec(
        ad="propose_approval_threshold",
        aciklama="mutant",
        kapsam=ToolKapsami.SISTEM_YONETICISI,
        kume=ToolKumesi.SIRKET_GENELI,
        kapilar=frozenset({("approvals", AccessLevel.admin)}),
        ucler=("/approvals/settings",),
        yol_parametreleri={},
        girdi=schemas.BosGirdi,
        yanit_modeli=schemas.AiYonlendirme,
        calistir=None,  # type: ignore[arg-type]
    )
    ihlal = [m for m, _ in mutant.kapilar if m in YONETISIM_DENYLIST]
    assert ihlal == ["approvals"]


def test_B26_POZITIF_KONTROL_onay_kutum_denyliste_TAKILMAZ() -> None:
    """🔴 İncelik: `onay_kutum` `GET /approvals`ı sarar ama o uç KAPISIZDIR
    (`kapilar == ∅`). Denylist kapı modülleri üzerinden çalışır, sarılan yol
    üzerinden değil — çünkü yasaklanan şey **yönetişim yüzeyine yetkiyle
    dokunmak**tır."""
    from app.modules.ai.tools.catalog import ONAY_KUTUM

    assert ONAY_KUTUM.kapilar == frozenset()
    assert [m for m, _ in ONAY_KUTUM.kapilar if m in YONETISIM_DENYLIST] == []


# --------------------------------------------------------------------------- #
# Katalog yapısal kilitleri
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec", CATALOG, ids=lambda s: s.ad)
def test_katalog_her_arac_TEK_UCLUDUR(spec: ToolSpec) -> None:
    """`registry._cozulmus_yol` birincil ucu çözer; çok uçlu bir araç
    eklendiğinde o satır yeniden düşünülmek zorunda kalsın."""
    assert len(spec.ucler) <= 1, f"`{spec.ad}` çok uçlu — `_cozulmus_yol` gözden geçirilmeli"


@pytest.mark.parametrize("spec", CATALOG, ids=lambda s: s.ad)
def test_katalog_yol_parametreleri_TIPLIDIR(spec: ToolSpec) -> None:
    for ad, tip in spec.yol_parametreleri.items():
        assert tip in {uuid.UUID, int}, f"`{spec.ad}.{ad}` tipsiz/serbest: {tip}"
        assert "{" + ad + "}" in spec.ucler[0]


def test_katalog_adlari_TEKILDIR() -> None:
    adlar = [s.ad for s in CATALOG]
    assert len(adlar) == len(set(adlar))


def test_PROPOSE_TOOLS_BOS_ama_dallanma_VAR() -> None:
    from app.modules.ai.tools.catalog import PROPOSE_TOOLS
    from app.modules.roles.models import SYSTEM_ADMIN_KEY

    assert PROPOSE_TOOLS == ()
    kaynak = (AI_KOK / "registry.py").read_text(encoding="utf-8")
    assert SYSTEM_ADMIN_KEY in kaynak or "SYSTEM_ADMIN_KEY" in kaynak


def test_Restricted_data_ALANI_TASIMAZ() -> None:
    """Kilit prompt'ta değil ŞEKİLDE: modelin 'boş liste' diye sunabileceği bir
    gövde bulunmaz."""
    import dataclasses

    assert "data" not in {f.name for f in dataclasses.fields(Restricted)}
    zarf = Restricted("payroll").govde()
    assert "veri" not in zarf
