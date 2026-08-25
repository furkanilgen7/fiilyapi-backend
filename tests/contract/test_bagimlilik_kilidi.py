"""🔴 BAĞIMLILIK KİLİDİ KAPISI (TB-LOCK, 2026-08-25).

Bu dosya, **tam bağımlılık ağacının** (doğrudan + geçişli) commit'li kilit dosyalarıyla
fiilen kurulanın **ayrışmasını** kırmızı yapar.

**Neden var — hipotetik değil, ÖLÇÜLDÜ:**
`argon2-cffi` TB-PIN tarafından pinlenmişti ama parola özetini fiilen üreten
`argon2-cffi-bindings` **geçişli** olduğu için `>=` aralığında kaldı. Bindings `26.1.0`
2026-08-20'de çıktı ve **TB-PIN'in kendi deploy'u** `requirements.txt`i değiştirip Docker
katman önbelleğini düşürünce canlı imaj sessizce `25.1.0 → 26.1.0`'a taşındı.
👉 *Pinleyen dilimin kendisi, pinlemediği bir kütüphaneyi yükseltti.*
Elle pin **yetmez**: pinlenmeyen her geçişli katman aralıkta kalır ve
**üretilen sözleşme / parola maliyeti kod değişmeden kayar.**

**Asimetri:** frontend'de `pnpm-lock.yaml` VAR ve üretilen artefaktın üreticisini
(`openapi-typescript`) kilitliyor. Backend'de hiçbir kilit dosyası yoktu.

**Çözüm — iki kilit dosyası, tek tüketici (pip):**
  · `requirements.lock`      → ÜRETİM ağacı (41 paket). `Dockerfile` bunu kurar.
  · `requirements-dev.lock`  → üretim + dev/test ağacı (52 paket). CI bunu kurar.
Her ikisi de düz `requirements.txt` biçimindedir; `pip install -r` doğrudan tüketir,
**deploy akışına yeni araç girmez** (`uv`/`poetry` binary'si imaja EKLENMEZ).

**Kilit yenileme (kaynak dosya değiştiğinde ZORUNLU):**
    uv pip compile requirements.txt --python-version 3.12 \
        --python-platform x86_64-unknown-linux-gnu -o requirements.lock
    uv pip compile pyproject.toml --extra dev --python-version 3.12 \
        --python-platform x86_64-unknown-linux-gnu -o requirements-dev.lock
(Komutlar dosyaların kendi başlığında da yazılıdır.) Hedef platform **linux/x86_64**
seçilmiştir: hem Railway imajı (`python:3.12-slim`) hem CI (`ubuntu-latest`) odur.

⚠️ ÖLÇÜLDÜ: `uv pip compile -o X`, **var olan X'i TERCİH GİRDİSİ olarak okur** — bu
kasıtlıdır (gereksiz yükseltmeyi önler), ama elle bozulmuş bir kilit yenilemeden SAĞ ÇIKAR.
Kasıtlı yükseltme yaparken `--upgrade-package <ad>` kullan; sıfırdan çözüm istiyorsan kilit
dosyasını önce **sil**. Her iki durumda da `git diff` gözle doğrulanır.

🔴 **BU DOSYA BİR DEVİR BORCU ÜRETİCİSİDİR — İSTENEN DAVRANIŞ BUDUR.** Bağımlılık
ekleyen/yükselten dilim kilidi yenilemeden yeşil geçemez.
"""

from __future__ import annotations

import importlib.metadata as md
import re
import tomllib
from pathlib import Path

REPO_KOKU = Path(__file__).resolve().parents[2]

URETIM_KILIDI = REPO_KOKU / "requirements.lock"
DEV_KILIDI = REPO_KOKU / "requirements-dev.lock"
URETIM_KAYNAGI = REPO_KOKU / "requirements.txt"
PYPROJECT = REPO_KOKU / "pyproject.toml"
DOCKERFILE = REPO_KOKU / "Dockerfile"
CI_DOSYASI = REPO_KOKU / ".github" / "workflows" / "ci.yml"

# `pydantic[email]==2.13.4` gibi extra'lı ve `uvicorn[standard]==0.52.4` gibi kalemlerde
# ad ile sürümü ayırırken extra parantezini atmak gerekir.
_SATIR = re.compile(
    r"^(?P<ad>[A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*==\s*(?P<surum>[^\s;#]+)\s*(?:;.*)?$"
)


def _normalize(ad: str) -> str:
    """PEP 503 paket adı normalizasyonu (`argon2_cffi` ↔ `argon2-cffi`)."""
    return re.sub(r"[-_.]+", "-", ad).lower()


def _kilidi_oku(yol: Path) -> dict[str, str]:
    """Kilit/kaynak dosyasındaki `ad==surum` kalemlerini sözlüğe çevirir."""
    assert yol.exists(), (
        f"{yol.name} YOK. Üretmek için bu dosyanın modül docstring'indeki "
        "`uv pip compile` komutlarını koş."
    )
    bulunan: dict[str, str] = {}
    for ham in yol.read_text(encoding="utf-8").splitlines():
        satir = ham.strip()
        if not satir or satir.startswith(("#", "-")):
            continue
        eslesme = _SATIR.match(satir)
        if eslesme:
            bulunan[_normalize(eslesme.group("ad"))] = eslesme.group("surum")
    return bulunan


def _pyproject_dogrudan_adlar() -> set[str]:
    """`pyproject.toml`daki DOĞRUDAN bağımlılıkların adları (runtime + dev extra).

    🔴 Bu küme kilit dosyasından TÜRETİLMEZ — ayrı bir kaynaktan okunur. Türetilseydi
    mutasyon iki tarafı birden oynatır ve iddia kendini doğrulardı (SEC-ARGON dersi).
    """
    veri = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    proje = veri["project"]
    kalemler = list(proje["dependencies"])
    for extra in proje.get("optional-dependencies", {}).values():
        kalemler.extend(extra)
    adlar = set()
    for kalem in kalemler:
        ad = re.split(r"[\[<>=!~;\s]", kalem, maxsplit=1)[0]
        if ad:
            adlar.add(_normalize(ad))
    return adlar


def _kurulu_surum(ad: str) -> str | None:
    try:
        return md.version(ad)
    except md.PackageNotFoundError:
        return None


def test_DEV_kilidi_ile_FIILEN_KURULU_agac_AYRISMAZ() -> None:
    """🔴 Kilit bir NİYET beyanıdır; sanal ortamda başka sürüm kurulu olabilir.

    Bu bekçi kilidi **kurulu ağaçla** karşılaştırır — iki bağımsız kaynak.
    (Emsal: `test_openapi_contract_baseline.py` içindeki "kurulu yorumlayıcı imzası".)
    """
    kilit = _kilidi_oku(DEV_KILIDI)
    assert kilit, f"{DEV_KILIDI.name} hiç kalem içermiyor — kilit BOŞ, kapı hükümsüz."

    ayrisan: list[str] = []
    for ad, beklenen in sorted(kilit.items()):
        kurulu = _kurulu_surum(ad)
        if kurulu is None:
            ayrisan.append(f"  · {ad}: kilit {beklenen} · KURULU DEĞİL")
        elif _normalize(kurulu) != _normalize(beklenen):
            ayrisan.append(f"  · {ad}: kilit {beklenen} · kurulu {kurulu}")

    assert not ayrisan, (
        "🔴 KİLİT DOSYASI İLE KURULU AĞAÇ AYRIŞTI "
        f"({len(ayrisan)}/{len(kilit)} paket):\n" + "\n".join(ayrisan) + "\n\n"
        "İki olası sebep VARDIR ve ayırt edilmelidir:\n"
        "  (a) Ortam bayat → kilidi kur:\n"
        "        .venv/bin/pip install -r requirements-dev.lock && "
        ".venv/bin/pip install -e . --no-deps\n"
        "  (b) Bağımlılık KASITLI değişti → kilidi YENİLE (modül docstring'indeki\n"
        "      `uv pip compile` komutları) ve `git diff` ile farkı gözle doğrula."
    )


def test_URETIM_kilidi_DEV_kilidinin_SURUM_ALT_KUMESIDIR() -> None:
    """🔴 Docker `requirements.lock`u kurar, testler `requirements-dev.lock`la koşar.

    İkisi ayrışırsa **kapıların doğruladığı sürümler canlıya gitmez** — kilit varken bile
    canlı test edilmemiş bir ağaçla koşar. Bu bekçi o boşluğu kapatır.
    """
    uretim = _kilidi_oku(URETIM_KILIDI)
    dev = _kilidi_oku(DEV_KILIDI)
    assert uretim, f"{URETIM_KILIDI.name} hiç kalem içermiyor — kilit BOŞ, kapı hükümsüz."

    sapan = [
        f"  · {ad}: uretim {surum} · dev {dev.get(ad, 'YOK')}"
        for ad, surum in sorted(uretim.items())
        if dev.get(ad) != surum
    ]
    assert not sapan, (
        "🔴 ÜRETİM KİLİDİ İLE DEV KİLİDİ AYRIŞTI — canlıya testlerin doğrulamadığı "
        f"sürümler gider ({len(sapan)} paket):\n" + "\n".join(sapan) + "\n"
        "İkisi de AYNI turda yenilenmelidir (modül docstring'i)."
    )


def test_DOGRUDAN_bagimliliklarin_TAMAMI_kilitlerde_KARSILANIR() -> None:
    """🔴 BAYAT KİLİT bekçisi: kaynak dosya değişip kilit yenilenmediğinde kırmızı.

    İki iddia:
      (a) `pyproject.toml`daki her doğrudan bağımlılık dev kilidinde YER ALIR
          (yeni paket eklenip kilit yenilenmezse kırmızı),
      (b) `requirements.txt`teki her `==` PİNİ üretim kilidindeki sürümle AYNIDIR
          (pin yükseltilip kilit yenilenmezse kırmızı).
    Ayrıca (a) bu dosyanın **boş ayrıştırmaya karşı** bekçisidir: ayrıştırıcı hiçbir şey
    döndürmezse iddia çöker.
    """
    dev = _kilidi_oku(DEV_KILIDI)
    dogrudan = _pyproject_dogrudan_adlar()
    assert dogrudan, "pyproject.toml'dan hiç doğrudan bağımlılık okunamadı."

    eksik = sorted(dogrudan - set(dev))
    assert not eksik, (
        f"🔴 pyproject.toml'daki {len(eksik)} doğrudan bağımlılık dev kilidinde YOK: "
        f"{eksik}\nKilit BAYAT — yenile (modül docstring'i)."
    )

    uretim = _kilidi_oku(URETIM_KILIDI)
    kaynak_pinleri = _kilidi_oku(URETIM_KAYNAGI)
    assert kaynak_pinleri, "requirements.txt'ten hiç `==` pini okunamadı."

    sapan = [
        f"  · {ad}: requirements.txt {surum} · requirements.lock {uretim.get(ad, 'YOK')}"
        for ad, surum in sorted(kaynak_pinleri.items())
        if uretim.get(ad) != surum
    ]
    assert not sapan, (
        "🔴 KAYNAK PİNİ İLE ÜRETİM KİLİDİ AYRIŞTI — kilit BAYAT "
        f"({len(sapan)} paket):\n" + "\n".join(sapan) + "\n"
        "Kilidi yenile (modül docstring'i)."
    )

    # (c) `requirements.txt` artık HİÇBİR YERDE doğrudan kurulmuyor (Dockerfile kilitten
    # kuruyor) — yalnızca üretim kilidinin KAYNAĞI. Bu yüzden `pyproject.toml`dan sessizce
    # ayrışabilir ve kimse görmez. İki dosyanın `==` pinleri aynı olmalıdır.
    pyproject_pinleri = {
        _normalize(es.group("ad")): es.group("surum")
        for kalem in tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
        if (es := _SATIR.match(kalem.strip()))
    }
    ikili_sapan = [
        f"  · {ad}: pyproject {surum} · requirements.txt {kaynak_pinleri.get(ad, 'YOK')}"
        for ad, surum in sorted(pyproject_pinleri.items())
        if kaynak_pinleri.get(ad) != surum
    ]
    assert not ikili_sapan, (
        "🔴 pyproject.toml İLE requirements.txt PİNLERİ AYRIŞTI "
        f"({len(ikili_sapan)} paket):\n" + "\n".join(ikili_sapan) + "\n"
        "requirements.txt'in kaynağı pyproject.toml [project.dependencies]'dir."
    )


def _yorumsuz(metin: str) -> str:
    """`#` ile başlayan satırları atar.

    🔴 Şart: aşağıdaki bekçi "eski kurulum satırı ARTIK YOK" diye iddia ediyor; oysa
    Dockerfile/CI yorumları o satırı **gerekçe olarak alıntılıyor**. Ham metinde arama
    yapan bir bekçi kendi gerekçe yorumunu kusur sanıp SAHTE KIRMIZI verir.
    """
    return "\n".join(satir for satir in metin.splitlines() if not satir.lstrip().startswith("#"))


def test_KILIT_dosyalari_KURULUMDA_FIILEN_KULLANILIR() -> None:
    """🔴 Kilit dosyası, onu KURAN adım olmadan yalnızca bir dekorasyondur.

    Docker `requirements.txt`e, CI `pip install -e ".[dev]"`e geri dönerse pip aralıkları
    yeniden çözer ve kilit hiçbir şeyi bekçilemez — üstelik üstteki bekçiler de
    kırmızı olmadan (CI ortamı kilitten kurulmadığı için) değil, tam tersine
    **kırmızıya boğulur** ve kilit kaldırılarak "düzeltilir". Bu bekçi kurulum
    adımını doğrudan kilitler.
    """
    dockerfile = _yorumsuz(DOCKERFILE.read_text(encoding="utf-8"))
    assert "pip install -r requirements.lock" in dockerfile, (
        "🔴 Dockerfile üretim kilidinden kurmuyor. Beklenen: "
        "`pip install -r requirements.lock`. Kilitten kurulmayan imaj, kilit "
        "dosyası commit'li olsa bile aralıkları yeniden çözer."
    )
    assert "requirements.txt" not in dockerfile, (
        "🔴 Dockerfile hâlâ `requirements.txt`e atıf yapıyor — kilitsiz kurulum yolu açık."
    )

    ci = _yorumsuz(CI_DOSYASI.read_text(encoding="utf-8"))
    assert "pip install -r requirements-dev.lock" in ci, (
        "🔴 CI dev kilidinden kurmuyor. Beklenen: `pip install -r requirements-dev.lock`."
    )
    assert 'pip install -e ".[dev]"' not in ci, (
        '🔴 CI hâlâ `pip install -e ".[dev]"` ile ÇÖZÜM yapıyor — kilit atlanır. '
        "Kurulum `-r requirements-dev.lock` + `pip install -e . --no-deps` olmalı."
    )
