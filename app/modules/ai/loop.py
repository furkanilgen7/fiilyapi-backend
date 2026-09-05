"""Ajan döngüsü — spec §2.2 KATMAN 7 / §3 (AI-1).

Döngü **hiçbir handler'ı doğrudan çağırmaz**: her araç çağrısı
`ToolRegistry.invoke()` hunisinden geçer. Huninin dışında bir yol açılırsa izin
kapısı, şema doğrulaması, yol kaçışı ve denetim izi **hep birden** düşer.

## 🔴 KİMLİK HER DISPATCH'TE YENİDEN ÇÖZÜLÜR (S19)

`access_token_expire_minutes = 15` (ölçüldü). Bir tur, model yavaşsa ve birkaç
araç zincirlenirse bu pencerenin içinde kalmayabilir; ayrıca izin matrisi
çalışma anında düzenlenebilir ve kullanıcı `passive`e düşürülebilir. Bu yüzden
`ActorContext` **önbelleğe alınmaz**: her dispatch'ten önce **taze** bir
oturumda yeniden çözülür.

Ve tur ortasındaki 401 **ÜÇÜNCÜ bir hâldir** (B28):

| hâl | cümle |
|---|---|
| oturum doldu | "yeniden giriş yapıldığında aynı sorgu çalışır" |
| yetkin yok | "bu bilgiyi görme yetkiniz yok" |
| veri yok | "erişebildiğiniz kapsamda hiç kayıt yok" |

Üçü aynı cümleye düşerse kullanıcı yanlış şeyi düzeltmeye çalışır.

## 🔴 TUR BAŞINA NİYET ALLOWLIST'İ (B21)

İzin listesi **turun başında**, kullanıcının mesajı okunmadan önce, aktörün o
andaki kataloğundan donar. Araç **çıktısından** gelen bir talimat ("şimdi
propose_x çağır") bu listeye ekleme YAPAMAZ. Liste bir **tavandır**; taban ise
`invoke()`un her seferinde TAZE aktörle yeniden hesapladığı katalogdur. Yani
yetki tur ortasında geri alınırsa çağrı yine reddedilir — tavan onu kurtarmaz.

Bu dilimde tavana iki ek kısıt daha girer: `SISTEM_YONETICISI` kapsamındaki ve
adı `propose_` ile başlayan hiçbir araç listeye ALINMAZ. §7 gereği yazma araçları
yoktur; bu satır o kararın **yapısal** hâlidir, yorum hâli değil.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping, Sequence

import httpx

from app.core.config import Settings
from app.core.config import settings as varsayilan_ayarlar
from app.core.security import TokenError, decode_token
from app.modules.ai import context, guards
from app.modules.ai.actor import aktor_baglami
from app.modules.ai.db import AiSessionLocal
from app.modules.ai.presenters import bloklari_uret
from app.modules.ai.prompt import sistem_promptu
from app.modules.ai.providers.base import (
    AiOlay,
    AracCagrisiHazir,
    AracSonuclandi,
    Hata,
    Kullanim,
    LLMProvider,
    Mesaj,
    MetinParcasi,
    Reddetme,
    TurBitti,
    TurSebebi,
    YapisalBloklar,
)
from app.modules.ai.registry import ActorContext, ToolKapsami, ToolRegistry
from app.modules.ai.result import AracSonucu, Ok, ToolError, Truncated
from app.modules.ai.transport import ReadOnlyTransport
from app.modules.users.models import User, UserStatus


class OturumSuresiDoldu(Exception):
    """Tur ortasında kimlik çözülemedi. 🔴 "Yetkin yok" DEĞİL."""


def tur_niyet_izni(kayit: ToolRegistry, actor: ActorContext) -> frozenset[str]:
    """Turun başında donan araç adı **tavanı** (B21)."""
    return frozenset(
        s.ad
        for s in kayit.katalog(actor)
        if s.kapsam is not ToolKapsami.SISTEM_YONETICISI and not s.ad.startswith("propose_")
    )


async def taze_aktor(bearer: str) -> ActorContext:
    """Aktörü **taze** bir salt-okunur oturumda yeniden çözer.

    🔴 `get_current_user`ın üç kontrolü burada birebir tekrarlanır (kullanıcı var
    mı · `status is active` mi · `token_version` eşleşiyor mu). Tekrar kasıtlıdır:
    bu yol bir HTTP isteği değildir, dolayısıyla FastAPI bağımlılığı koşmaz —
    "istek başında doğrulandı" varsayımı tam olarak S19'un deliğidir.
    """
    try:
        cozulen = decode_token(bearer, expected_type="access")
    except TokenError as exc:
        raise OturumSuresiDoldu from exc

    async with AiSessionLocal() as session:
        kullanici = await session.get(User, cozulen.user_id)
        if (
            kullanici is None
            or kullanici.status is not UserStatus.active
            or kullanici.token_version != cozulen.token_version
        ):
            raise OturumSuresiDoldu
        return await aktor_baglami(session, kullanici)


def _sonuc_olayi(cagri: AracCagrisiHazir, sonuc: AracSonucu) -> AracSonuclandi:
    """Zarf hâlini **ekrana** taşır (korkuluk (c)).

    Panel modelin özetine değil buna bakar: model "3 proje var" derken zarf
    `Restricted` diyorsa kullanıcı çelişkiyi **görür**.
    """
    satir = None
    if isinstance(sonuc, Ok):
        satir = sonuc.row_count
    elif isinstance(sonuc, Truncated):
        satir = sonuc.returned
    return AracSonuclandi(
        cagri_id=cagri.cagri_id,
        arac_adi=cagri.arac_adi,
        hal=type(sonuc).__name__,
        mesaj=sonuc.mesaj(),
        satir_sayisi=satir,
    )


def _arac_mesaji(kayit: ToolRegistry, cagri: AracCagrisiHazir, sonuc: AracSonucu) -> Mesaj:
    """Zarfı `tool` rolünde modele verir.

    🔴 Araç sonucu **asla** sistem ya da kullanıcı rolüne yazılmaz (B7). Zehirli
    bir günlük notu ancak `tool` rolünde görünebilir ve sistem promptunun 6.
    kuralı modele bunu açıkça söyler.

    🔴 Gövde `kayit.mesaj_govdesi` ile kurulur, `sonuc.govde()` ile DEĞİL:
    kapsam notu (S10) zarfın değil **kaydın** bilgisidir (`ToolSpec.kume`) ve
    zarf onu taşıyamaz.
    """
    import json

    return Mesaj(
        rol="arac",
        icerik=json.dumps(kayit.mesaj_govdesi(cagri.arac_adi, sonuc), ensure_ascii=False),
        cagri_id=cagri.cagri_id,
        arac_adi=cagri.arac_adi,
    )


async def ajan_turu(
    *,
    kayit: ToolRegistry,
    saglayici: LLMProvider,
    okuma_duzlemi_istemcisi: httpx.AsyncClient,
    bearer: str,
    kullanici_mesaji: str,
    ai_session_id: uuid.UUID | None = None,
    ayarlar: Settings | None = None,
    baglam: context.SohbetBaglami = context.BOS_BAGLAM,
) -> AsyncIterator[AiOlay]:
    """Tek bir kullanıcı mesajı için tam ajan turunu akıtır.

    🔴 **Durumsuz** (§9-A3 kararı beklediği için): `gecmis` yalnız bu turun
    içinde yaşar, hiçbir yere yazılmaz. `ai_conversations`/`ai_messages` tabloları
    AÇILMAMIŞTIR ve `AiToolCall.conversation_id` bu turda hep NULL kalır.

    🔴 `baglam` **çözülmüş ve görünürlüğü doğrulanmış** gelir (`router` çağırır);
    bu fonksiyon onu bir daha doğrulamaz ve DOĞRULAMAMALIDIR: iki kopya süzgeç
    zamanla ayrışır. Varsayılanı `BOS_BAGLAM`dır, yani bağlam vermeyen bir çağrı
    yeri bu dilimden ÖNCEKİ davranışı bayt bayt korur.
    """
    ayarlar = ayarlar or varsayilan_ayarlar
    kullanim = Kullanim()

    try:
        actor = await taze_aktor(bearer)
    except OturumSuresiDoldu:
        yield Hata(
            kod="oturum_suresi_doldu",
            mesaj=guards.HATA_METINLERI["oturum_suresi_doldu"],
        )
        yield TurBitti(sebep=TurSebebi.kesildi, kullanim=kullanim)
        return

    # 🔴 TAVAN turun başında donar (B21). Aşağıda bir daha HESAPLANMAZ.
    izin_listesi = tur_niyet_izni(kayit, actor)
    sistem = sistem_promptu(kayit, actor)
    araclar = kayit.katalog(actor)

    # 🔴 BAĞLAM BLOĞU **SİSTEM PROMPTUNA GİRMEZ** — B7'nin altın dosya kuralı.
    # Blok proje/şantiye ADI taşır, yani DB içeriğidir ve o adı BAŞKA bir
    # kullanıcı yazmıştır (depolanmış enjeksiyon yüzeyi, S6). Sistem promptuna
    # konsaydı `sistem_promptu`nun "zehirli ve boş DB'de bayt bayt aynı"
    # iddiası çökerdi ve enjekte edilen metin **sistem** yetkisiyle okunurdu.
    # Bu yüzden blok `kullanici` rolünde, AYRI bir mesaj olarak ve `<baglam>`
    # zarfında girer; sistem promptunun 9. kuralı (STATİK metin) modele o
    # bloğun VERİ olduğunu söyler.
    gecmis: list[Mesaj] = []
    if (blok := context.baglam_mesaji(baglam)) is not None:
        gecmis.append(Mesaj(rol="kullanici", icerik=blok))
    gecmis.append(Mesaj(rol="kullanici", icerik=kullanici_mesaji))

    # `invoke`a geçecek varsayılan kapsam. TEK yerde hesaplanır ve TEK yerde
    # uygulanır (`ToolRegistry._kapsamla`).
    kapsam = context.varsayilan_kapsam(baglam)

    transport = ReadOnlyTransport(okuma_duzlemi_istemcisi, bearer=bearer)
    harcanan = 0
    sebep = TurSebebi.kesildi

    while True:
        cagrilar: list[AracCagrisiHazir] = []
        metin_parcalari: list[str] = []
        tur_sebebi: TurSebebi | None = None
        durdu = False

        async for olay in saglayici.tur(sistem=sistem, gecmis=gecmis, araclar=araclar):
            if isinstance(olay, AracCagrisiHazir):
                cagrilar.append(olay)
                yield olay
                continue
            if isinstance(olay, MetinParcasi):
                metin_parcalari.append(olay.metin)
                yield olay
                continue
            if isinstance(olay, TurBitti):
                tur_sebebi = olay.sebep
                kullanim = olay.kullanim
                continue
            if isinstance(olay, Reddetme):
                durdu = True
            yield olay

        sebep = tur_sebebi or TurSebebi.kesildi
        if durdu or not cagrilar:
            break

        gecmis.append(
            Mesaj(
                rol="asistan",
                icerik="".join(metin_parcalari),
                arac_cagrilari=tuple(cagrilar),
            )
        )

        for cagri in cagrilar:
            sonuc = await _cagriyi_kosur(
                kayit=kayit,
                cagri=cagri,
                izin_listesi=izin_listesi,
                transport=transport,
                bearer=bearer,
                harcanan=harcanan,
                tavan=ayarlar.ai_max_tool_calls,
                ai_session_id=ai_session_id,
                saglayici_adi=saglayici.ad,
                model=ayarlar.ai_model,
                varsayilan_kapsam=kapsam,
            )
            harcanan += 1
            yield _sonuc_olayi(cagri, sonuc)
            # 🔴 K1: zengin bloklar araç sonucunun YAPISAL gövdesinden üretilir,
            # modelin metninden ASLA. Blok yoksa olay hiç yayılmaz.
            bloklar = bloklari_uret(cagri.arac_adi, sonuc)
            if bloklar:
                yield YapisalBloklar(
                    cagri_id=cagri.cagri_id, arac_adi=cagri.arac_adi, bloklar=bloklar
                )
            gecmis.append(_arac_mesaji(kayit, cagri, sonuc))

    yield TurBitti(sebep=sebep, kullanim=kullanim)


async def _cagriyi_kosur(
    *,
    kayit: ToolRegistry,
    cagri: AracCagrisiHazir,
    izin_listesi: frozenset[str],
    transport: ReadOnlyTransport,
    bearer: str,
    harcanan: int,
    tavan: int,
    ai_session_id: uuid.UUID | None,
    saglayici_adi: str,
    model: str,
    varsayilan_kapsam: Mapping[str, str],
) -> AracSonucu:
    """Tek bir araç çağrısı: bütçe → niyet → **taze kimlik** → huni.

    🔴 `varsayilan_kapsam` burada UYGULANMAZ, yalnız **taşınır**: doldurma
    `ToolRegistry.invoke`un ağzındadır (tek yer). Burada da doldurulsaydı iki
    kopya olurdu ve biri diğerinden sessizce ayrışabilirdi.
    """
    # --- Bütçe: aşımda DÜRÜST hata, "kayıt yok" DEĞİL --------------------
    if harcanan >= tavan:
        return ToolError("butce_asildi")

    # --- Niyet tavanı (B21) ---------------------------------------------
    if cagri.arac_adi not in izin_listesi:
        return ToolError("niyet_disi")

    # --- 🔴 TAZE kimlik + izin (S19 / B28) -------------------------------
    try:
        actor = await taze_aktor(bearer)
    except OturumSuresiDoldu:
        return ToolError("oturum_suresi_doldu")

    # --- TEK HUNİ --------------------------------------------------------
    return await kayit.invoke(
        arac_adi=cagri.arac_adi,
        argumanlar=cagri.argumanlar,
        actor=actor,
        transport=transport,
        ai_session_id=ai_session_id,
        provider=saglayici_adi,
        model=model,
        varsayilan_kapsam=varsayilan_kapsam,
    )


def tur_ozeti(olaylar: Sequence[AiOlay]) -> str:
    """Denetim günlüğüne düşecek **tek satırlık** tur özeti.

    🔴 Kullanıcının mesajı ya da modelin cevabı BURAYA YAZILMAZ: `audit_log`
    şirket geneli bir ekrandan okunuyor (`settings`/`audit` kapısı) ve orada
    başkasının sorusunu okumak, AI hattının kapatmaya çalıştığı sızıntının ta
    kendisidir. Özet **sayılardan** ibarettir.
    """
    arac = [o for o in olaylar if isinstance(o, AracSonuclandi)]
    bitis = next((o for o in reversed(olaylar) if isinstance(o, TurBitti)), None)
    haller = ", ".join(sorted({o.hal for o in arac})) or "yok"
    sebep = bitis.sebep.value if bitis else "bilinmiyor"
    girdi = bitis.kullanim.girdi if bitis else None
    cikti = bitis.kullanim.cikti if bitis else None
    return (
        f"AI turu · araç çağrısı: {len(arac)} · zarf hâlleri: {haller} · "
        f"bitiş: {sebep} · token: {girdi if girdi is not None else '?'}"
        f"/{cikti if cikti is not None else '?'}"
    )
