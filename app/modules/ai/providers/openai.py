"""OpenAI adaptörü — AI-1'in **TEK** yazılmış sağlayıcısı (§9-A9).

Diğer iki ad (`anthropic`, `gemini`) `factory`de **tanınır** ama adaptörleri bu
dilimde yazılmaz; tanınan-ama-yazılmamış ile hiç-olmayan **ayrı** hatalardır.

## 🔴 `store=false` AÇIKÇA gönderilir (§9-A2)

Varsayılana güvenilmez: sağlayıcının varsayılanı bir gün değişebilir ve ERP
verisi (hakediş tutarı, personel adı, şantiye) sağlayıcıda **birikmeye** başlar,
hiçbir test kırmızı olmaz. Bu yüzden alan istek gövdesine yazılır ve bekçisi
gövdeyi **fiilen** okur (B13) — "kodda `store` geçiyor" iddiası ölçüm değildir.

## 🔴 `response_format` GÖNDERİLMEZ

Yapısal çıktı yalnız araç şeması düzeyindedir (`strict`). Yanıtın kendisini
JSON'a zorlamak, modelin bilmediği alanı **uydurmasını** teşvik eder; oysa bu
hattın tüm meselesi "bilmiyorsan bilmiyorum de"dir.

## Taşıyıcı dikiş yeri

`akitici` kurucudan geçer. 🔴 Testler **gerçek OpenAI çağrısı yapmaz**: sahte
akıtıcı istek gövdesini yakalar ve önceden yazılmış parçaları döker. Ağ çağrısı
yapan bir test, anahtar olmadığı için ya atlanır (sahte-yeşil) ya da CI'ı
sağlayıcının çalışma süresine bağlar.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, Final

import httpx

from app.modules.ai.providers.base import (
    AiOlay,
    AracArgumanParcasi,
    AracCagrisiBasladi,
    AracCagrisiHazir,
    Hata,
    Kullanim,
    Mesaj,
    MetinParcasi,
    Reddetme,
    TurBitti,
    TurSebebi,
    girdi_semasi,
)
from app.modules.ai.registry import ToolSpec

VARSAYILAN_TABAN_URL: Final[str] = "https://api.openai.com/v1"

#: Ham `finish_reason` → `TurSebebi`. 🔴 Eşlenmeyen değer `kesildi`ye düşer,
#: `bitti`ye DEĞİL: bilinmeyen bir sebebi "işini bitirdi" saymak, eksik bir
#: cevabı tam gibi sunmaktır.
SEBEP_ESLEMESI: Final[dict[str, TurSebebi]] = {
    "stop": TurSebebi.bitti,
    "tool_calls": TurSebebi.arac,
    "function_call": TurSebebi.arac,
    "length": TurSebebi.kesildi,
    "content_filter": TurSebebi.filtrelendi,
}

#: Sağlayıcıya giden parça akıtıcısı: istek gövdesini alır, çözülmüş JSON
#: parçalarını döker. Testler bunu değiştirir.
Akitici = Callable[[dict[str, Any]], AsyncIterator[dict[str, Any]]]


class OpenAIProvider:
    """`LLMProvider` uygulaması (Chat Completions, akışlı)."""

    ad = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        taban_url: str = VARSAYILAN_TABAN_URL,
        akitici: Akitici | None = None,
        zaman_asimi: float = 60.0,
    ) -> None:
        if not api_key:
            # Fabrikanın işi ama ikinci kilit: anahtarsız bir örnek kurulursa
            # hata "sağlayıcı yok" gibi görünmesin.
            raise ValueError("OpenAI adaptörü anahtarsız kurulamaz.")
        self._api_key = api_key
        self._model = model
        self._taban_url = taban_url.rstrip("/")
        self._zaman_asimi = zaman_asimi
        self._akitici: Akitici = akitici or self._http_akitici

    # ------------------------------------------------------------------ #
    # Şema
    # ------------------------------------------------------------------ #

    def arac_semasi(self, spec: ToolSpec) -> dict[str, Any]:
        """`strict` fonksiyon aracı şeması.

        🔴 `description` alanına `ToolSpec.aciklama` **birebir** gider: "NE ZAMAN
        / NE SORMAZ" metni modelin gördüğü tek yönlendirmedir ve kataloğun
        dışında ikinci bir kopyası olmamalıdır.
        """
        return {
            "type": "function",
            "function": {
                "name": spec.ad,
                "description": spec.aciklama,
                "parameters": girdi_semasi(spec),
                "strict": True,
            },
        }

    # ------------------------------------------------------------------ #
    # Gövde
    # ------------------------------------------------------------------ #

    def istek_govdesi(
        self,
        *,
        sistem: str,
        gecmis: Sequence[Mesaj],
        araclar: Sequence[ToolSpec],
    ) -> dict[str, Any]:
        """Sağlayıcıya gidecek **tam** gövde. Bekçiler bunu doğrudan okur."""
        govde: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": sistem}, *_mesajlar(gecmis)],
            # 🔴 §9-A2. Varsayılana GÜVENİLMEZ.
            "store": False,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if araclar:
            govde["tools"] = [self.arac_semasi(s) for s in araclar]
            govde["tool_choice"] = "auto"
        # `response_format` · `temperature` · `top_p` · `top_k` YOK — bilerek.
        return govde

    # ------------------------------------------------------------------ #
    # Tur
    # ------------------------------------------------------------------ #

    async def tur(
        self,
        *,
        sistem: str,
        gecmis: Sequence[Mesaj],
        araclar: Sequence[ToolSpec],
    ) -> AsyncIterator[AiOlay]:
        """Tek turu akıtır; ham parçaları ortak olaylara çevirir."""
        govde = self.istek_govdesi(sistem=sistem, gecmis=gecmis, araclar=araclar)
        birikenler: dict[int, dict[str, str]] = {}
        sebep: TurSebebi | None = None
        kullanim = Kullanim()
        reddedildi: list[str] = []

        try:
            async for parca in self._akitici(govde):
                for olay in _secim_olaylari(parca, birikenler, reddedildi):
                    yield olay
                yeni_sebep = _sebep(parca)
                if yeni_sebep is not None:
                    sebep = yeni_sebep
                yeni_kullanim = _kullanim(parca)
                if yeni_kullanim is not None:
                    kullanim = yeni_kullanim
        except httpx.HTTPError as exc:
            # 🔴 Hata METNİ taşınmaz, TİPİ taşınır: sağlayıcı gövdesi istek
            # başlıklarını (yani Bearer'ı) yankılayabilir (B24).
            yield Hata(kod="saglayici_hatasi", mesaj=type(exc).__name__)
            yield TurBitti(sebep=TurSebebi.kesildi, kullanim=kullanim)
            return

        if reddedildi:
            yield Reddetme(metin="".join(reddedildi))
            yield TurBitti(sebep=TurSebebi.reddetme, kullanim=kullanim)
            return

        for indeks in sorted(birikenler):
            biriken = birikenler[indeks]
            yield AracCagrisiHazir(
                cagri_id=biriken["id"],
                arac_adi=biriken["ad"],
                argumanlar=_arguman_coz(biriken["arguman"]),
            )

        # 🔴 Sebep hiç gelmediyse `bitti` VARSAYILMAZ: akış koptu demektir.
        yield TurBitti(sebep=sebep or TurSebebi.kesildi, kullanim=kullanim)

    # ------------------------------------------------------------------ #
    # Varsayılan HTTP akıtıcısı
    # ------------------------------------------------------------------ #

    async def _http_akitici(self, govde: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Gerçek OpenAI SSE akışı. Testlerde **kullanılmaz**."""
        async with httpx.AsyncClient(timeout=self._zaman_asimi) as istemci:
            async with istemci.stream(
                "POST",
                f"{self._taban_url}/chat/completions",
                json=govde,
                headers={"Authorization": f"Bearer {self._api_key}"},
            ) as yanit:
                yanit.raise_for_status()
                async for satir in yanit.aiter_lines():
                    if not satir.startswith("data:"):
                        continue
                    veri = satir[5:].strip()
                    if veri == "[DONE]":
                        return
                    try:
                        yield json.loads(veri)
                    except json.JSONDecodeError:
                        continue


# --------------------------------------------------------------------------- #
# Ham parça → olay
# --------------------------------------------------------------------------- #


def _secim_olaylari(
    parca: dict[str, Any],
    birikenler: dict[int, dict[str, str]],
    reddedildi: list[str],
) -> list[AiOlay]:
    olaylar: list[AiOlay] = []
    for secim in parca.get("choices") or []:
        delta = secim.get("delta") or {}
        icerik = delta.get("content")
        if icerik:
            olaylar.append(MetinParcasi(metin=icerik))
        red = delta.get("refusal")
        if red:
            reddedildi.append(red)
        for cagri in delta.get("tool_calls") or []:
            indeks = int(cagri.get("index", 0))
            fonksiyon = cagri.get("function") or {}
            biriken = birikenler.setdefault(indeks, {"id": "", "ad": "", "arguman": ""})
            if cagri.get("id"):
                biriken["id"] = cagri["id"]
            if fonksiyon.get("name"):
                biriken["ad"] = fonksiyon["name"]
                olaylar.append(AracCagrisiBasladi(cagri_id=biriken["id"], arac_adi=biriken["ad"]))
            arguman = fonksiyon.get("arguments")
            if arguman:
                biriken["arguman"] += arguman
                olaylar.append(AracArgumanParcasi(cagri_id=biriken["id"], parca=arguman))
    return olaylar


def _sebep(parca: dict[str, Any]) -> TurSebebi | None:
    for secim in parca.get("choices") or []:
        ham = secim.get("finish_reason")
        if ham:
            # Bilinmeyen → `kesildi` (fail-closed).
            return SEBEP_ESLEMESI.get(ham, TurSebebi.kesildi)
    return None


def _kullanim(parca: dict[str, Any]) -> Kullanim | None:
    ham = parca.get("usage")
    if not ham:
        return None
    return Kullanim(girdi=ham.get("prompt_tokens"), cikti=ham.get("completion_tokens"))


def _arguman_coz(metin: str) -> dict[str, Any]:
    """Biriken argüman JSON'unu çözer.

    🔴 Çözülemeyen JSON `{}` olur, istisna DEĞİL: huni zaten şema doğrulaması
    yapar ve `gecersiz_argüman` döndürür. Burada patlamak, tüm turu bir model
    çıktısı yüzünden 500'e çevirirdi.
    """
    if not metin.strip():
        return {}
    try:
        cozulen = json.loads(metin)
    except json.JSONDecodeError:
        return {}
    return cozulen if isinstance(cozulen, dict) else {}


def _mesajlar(gecmis: Sequence[Mesaj]) -> list[dict[str, Any]]:
    """Ortak `Mesaj` → OpenAI mesaj listesi.

    🔴 `sistem` rolü BURADA ÜRETİLMEZ: sistem metni `istek_govdesi`nde tek yerde
    başa konur. `gecmis` içinden sistem mesajı geçirilebilseydi, araç sonucundan
    gelen bir metin "sistem" rolüne tırmanabilirdi.
    """
    cikti: list[dict[str, Any]] = []
    for mesaj in gecmis:
        if mesaj.rol == "kullanici":
            cikti.append({"role": "user", "content": mesaj.icerik})
        elif mesaj.rol == "asistan":
            kayit: dict[str, Any] = {"role": "assistant", "content": mesaj.icerik or None}
            if mesaj.arac_cagrilari:
                kayit["tool_calls"] = [
                    {
                        "id": c.cagri_id,
                        "type": "function",
                        "function": {
                            "name": c.arac_adi,
                            "arguments": json.dumps(dict(c.argumanlar), ensure_ascii=False),
                        },
                    }
                    for c in mesaj.arac_cagrilari
                ]
            cikti.append(kayit)
        elif mesaj.rol == "arac":
            cikti.append(
                {
                    "role": "tool",
                    "tool_call_id": mesaj.cagri_id or "",
                    "content": mesaj.icerik,
                }
            )
        else:  # pragma: no cover - `ROLLER` kapalı küme
            raise ValueError(f"Bilinmeyen rol: {mesaj.rol!r}")
    return cikti
