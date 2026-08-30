"""`ReadOnlyTransport` — araçların DIŞ DÜNYAYA açılan **tek** kapısı (B17, B-D5).

#3 mimarisinin ölümcül açığı buydu: `ToolSpec`te metot alanı yoktu ve araç
bağlamı **tam bir httpx istemcisi** taşıyordu. Yani bir araç `client.post(...)`
yazabilir ve dört kapının hiçbiri konuşmazdı.

Bu sınıf iki şeyi **yapısal olarak** imkânsızlaştırır:

1. **GET dışı metot yoktur.** `post`/`put`/`patch`/`delete` diye bir üye
   BULUNMAZ; `AttributeError`, çalışma zamanı reddi değil.
2. **Yol serbest değildir.** Her çağrı bir `ToolSpec`in `ucler` desenine
   uymak zorundadır; uymayan yol fail-closed reddedilir.

## 🔴 Yol parametresi (S27) — üç önlemin İKİSİ bu vektöre karşı ETKİSİZ

Ölçüldü: `httpx.ASGITransport` üzerinden `GET /x/../secret` **200** döner ve
`/secret`in gövdesini verir.

* `quote(arg, safe="")` **`..`yı DEĞİŞTİRMEZ.** Python nokta karakterini hiçbir
  `safe` değerinde kaçışlamaz; `quote` yalnız `/`yi öldürür.
* Tipli yol parametresi (`uuid.UUID`) tek başına yetmez: tip **dönüşümü**
  argümanı reddeder ama `str` tipli bir parametre eklendiği an delik geri gelir.

**Yük taşıyan tek önlem NOKTA-SEGMENT REDDİDİR.** Somut kanıt: `arg='..'` ile
`f"/projects/{arg}/progress-payments"` isteği `GET /progress-payments`e taşınır
ve 401 döner — gerçek, kimlik isteyen bir listeleme ucu.

Aynı sertleştirme frontend BFF'te ZATEN vardır (`api/backend/[...path]/route.ts`
`path.some(segment => segment === ".." || segment === "." || segment === "")`);
deseni oradan alınmıştır. 🔴 Ama BFF **frontend** deposundadır ve AI hattı
oradan geçmez: bu, ikinci bir kopya değil, **hattın kendi ilk savunmasıdır**.
"""

from __future__ import annotations

import re
from typing import Any, Final
from urllib.parse import quote

import httpx

#: Bir yol parametresinde ASLA bulunamayacak segmentler.
YASAK_SEGMENTLER: Final[frozenset[str]] = frozenset({"", ".", ".."})


class YolReddedildi(ValueError):
    """Yol parametresi ya da çözülmüş yol fail-closed reddedildi."""


def kacisla(deger: object) -> str:
    """Yol parametresini metne çevirir ve **nokta-segment** açısından reddeder.

    `quote(safe="")` yine de uygulanır (`/` ve sorgu ayıracı öldürülür), ama
    esas iş buradaki açık reddir — `quote` `..`yı değiştirmez.
    """
    metin = str(deger)
    if metin in YASAK_SEGMENTLER or "/" in metin or "\\" in metin:
        raise YolReddedildi(f"Yol parametresi reddedildi: {metin!r}")
    return quote(metin, safe="")


def _desen_to_regex(desen: str) -> re.Pattern[str]:
    """`/sites/{site_id}/timesheet/week` → tam eşleşen regex.

    Parametre yuvası **tek segmenti** karşılar (`[^/]+`): `/` içeren bir değer
    zaten `kacisla` tarafından reddedilir, bu ikinci kilittir.
    """
    parcalar = re.split(r"(\{[a-z_]+\})", desen)
    kalip = "".join(
        "[^/]+" if p.startswith("{") and p.endswith("}") else re.escape(p) for p in parcalar
    )
    return re.compile(f"^{kalip}$")


class ReadOnlyTransport:
    """Okuma düzlemine **yalnız GET** yapan taşıyıcı.

    Kimlik: kullanıcının **kendi** access token'ı (T1 — AI'ın kendi kimliği
    YOKTUR). `get_current_user` okuma düzleminde override EDİLMEZ, dolayısıyla
    token geçersizse uç 401 döner ve bu "yetkin yok"tan **AYRI** bir hâldir.
    """

    def __init__(self, istemci: httpx.AsyncClient, *, bearer: str) -> None:
        self._istemci = istemci
        self._bearer = bearer
        #: 🔴 Denetime **fiilen çağrılan** yol yazılabilsin diye tutulur. Huninin
        #: `started` satırı çağrıdan ÖNCE yazılmak zorunda olduğu için oradaki
        #: yol *öngörülmüş* yoldur; `finished` satırı burayı kullanır ve ikisi
        #: ayrışırsa iz bunu gösterir.
        self.cagrilan_yollar: list[str] = []
        self.son_yanit_kodu: int | None = None

    async def get(self, yol: str, *, izinli_desenler: tuple[str, ...], params: dict | None = None):
        """`izinli_desenler`den en az birine uyan bir yolu GET eder.

        `izinli_desenler` **çağıranın seçtiği bir kolaylık değil**, `ToolSpec`in
        `ucler` alanıdır ve `ToolRegistry.invoke` onu buraya zorla geçirir.
        """
        if not any(_desen_to_regex(d).match(yol) for d in izinli_desenler):
            raise YolReddedildi(f"Yol araç kapsamı dışında: {yol!r}")
        if any(s in YASAK_SEGMENTLER for s in yol.split("/")[1:]):
            raise YolReddedildi(f"Yolda nokta/boş segment: {yol!r}")
        yanit = await self._istemci.get(
            yol,
            params=params,
            headers={"Authorization": f"Bearer {self._bearer}"},
        )
        self.cagrilan_yollar.append(yol)
        self.son_yanit_kodu = yanit.status_code
        return yanit

    def __getattr__(self, ad: str) -> Any:
        """GET dışı her metot adı için **açıklayıcı** hata.

        `AttributeError` zaten yeterdi; bu dal yalnızca hatayı okunur kılar ve
        `hasattr(transport, "post")` sorgusunu da `False` tutar.
        """
        if ad in {"post", "put", "patch", "delete", "request", "stream", "send"}:
            raise AttributeError(
                f"ReadOnlyTransport.{ad} YOKTUR. AI hattında yazma reddedilmez, "
                "VAR OLMAZ (Kapı D). Okuma düzleminde GET dışı rota da bulunmaz."
            )
        raise AttributeError(ad)
