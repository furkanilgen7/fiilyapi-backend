"""🔴 SÖZLEŞME SÜRÜKLENME KAPISI (TB-PIN, 2026-08-25).

Bu dosya, `openapi.json`ın **içeriğini** kilitler.

**Neden var:** Sözleşme bir kod çıktısı değil, **yorumlayıcı davranışının** çıktısıdır.
`pydantic`/`fastapi`/`starlette` sürüm aralığı bırakıldığında tek satır kod değişmeden
554 şemanın yüzlercesi değişebiliyordu (ölçüldü: pydantic 2.11.10 → 2.12+ geçişinde
`Decimal` alanları `pattern` kazanıyor, 5 → 643 alan) ve **hiçbir kapı görmüyordu.**
Frontend tiplerini (`schema.d.ts`) bu sözleşmeden ürettiği için sürüklenme orada
**sessizce bayat tip** olarak birikiyordu.

**Mevcut sayaç bekçisi bu sınıfa YAPISAL OLARAK KÖRDÜR:**
`tests/modules/treasury/test_finpay_payment_instrument.py` içindeki
`test_YOL_ve_OPERASYON_sayisi_SABIT_kalir` **yol** ve **operasyon** SAYAR. İkisi de
sürümle değişmez (231/339 dört ayrı ölçümde de aynıydı) — sayıyı kilitleyen kapı
**içeriği** kilitlemez. Bu dosya o boşluğu kapatır; ikisi birbirinin yerine geçmez.

**🔴 BU TEST BİR DEVİR BORCU ÜRETİCİSİDİR — İSTENEN DAVRANIŞ BUDUR.**
Sözleşmeyi **kasıtlı** değiştiren bir dilim (yeni uç, yeni alan, tip değişikliği) bu
testi kırmızı görür. Şefin yapması gereken:

    1) Taban dosyasını yenile:
       UPDATE_OPENAPI_BASELINE=1 .venv/bin/pytest tests/contract/test_openapi_contract_baseline.py
    2) `git diff -- tests/contract/openapi_baseline.json` ile değişikliğin
       **beklenen** olduğunu gözle doğrula (diff okunabilir: sıralı + girintili JSON).
    3) **Raporuna FRONTEND DEVRİ GEREKTİĞİNİ yaz** — `frontend/openapi/openapi.json`
       ve `pnpm gen:api` ile `schema.d.ts` yenilenmelidir. Bkz. README "OpenAPI şeması".

Tabanı **gerekçesiz** yenilemek kapıyı hükümsüz kılar; yenileme her zaman diff'iyle
birlikte gerekçelendirilir.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

BASELINE_PATH = Path(__file__).with_name("openapi_baseline.json")

# Taban dosyası bu üç ayarla yazılır ve YALNIZ bunlarla okunur/karşılaştırılır.
# `sort_keys` şart: sözlük sırası yorumlayıcı ayrıntısıdır, sözleşmenin parçası değildir —
# sıralamadan kaynaklanan sahte kırmızıyı burada peşinen eliyoruz.
_DUMP_KWARGS: dict[str, Any] = {"sort_keys": True, "indent": 2, "ensure_ascii": False}

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "trace"})

# Farkın basımı asla ekranı boğmasın; ilk N kalem sorunu teşhis etmeye yeter.
_MAX_REPORTED = 25


def _canonical_text(schema: dict[str, Any]) -> str:
    """Sözleşmenin kanonik metni: anahtar sıralı, girintili, UTF-8 okunur."""
    return json.dumps(schema, **_DUMP_KWARGS) + "\n"


def _fingerprint(node: Any) -> str:
    return hashlib.sha256(
        json.dumps(node, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()[:12]


def _tum_degerler(node: Any, anahtar: str) -> list[Any]:
    """Ağacın HER derinliğinde `anahtar` altındaki değerleri toplar.

    Yüzeysel bir tarama yetmez: `pattern` iç içe `anyOf`/`items`/`additionalProperties`
    altında da yaşar; yalnız `properties`e bakan bir bekçi onları kaçırır.
    """
    bulunan: list[Any] = []
    if isinstance(node, dict):
        for ad, deger in node.items():
            if ad == anahtar and not isinstance(deger, (dict, list)):
                bulunan.append(deger)
            else:
                bulunan.extend(_tum_degerler(deger, anahtar))
    elif isinstance(node, list):
        for oge in node:
            bulunan.extend(_tum_degerler(oge, anahtar))
    return bulunan


def _generate() -> dict[str, Any]:
    from app.main import app

    # `app.openapi()` sonucu önbelleğe alır; testin sırası ne olursa olsun aynı nesneyi
    # üretmesi için JSON turundan geçiriyoruz (tuple/Decimal gibi sızıntıları da eler).
    return json.loads(json.dumps(app.openapi(), ensure_ascii=False))


def _operations(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{metot.upper()} {yol}": govde
        for yol, uc in schema.get("paths", {}).items()
        for metot, govde in uc.items()
        if metot in _HTTP_METHODS
    }


def _schemas(schema: dict[str, Any]) -> dict[str, Any]:
    return schema.get("components", {}).get("schemas", {})


def _alan_farki(beklenen: Any, uretilen: Any) -> list[str]:
    """İki şema/operasyon gövdesi arasında ALAN düzeyinde okunur fark üretir."""
    if not isinstance(beklenen, dict) or not isinstance(uretilen, dict):
        return ["(gövde sözlük değil — tümüyle değişmiş)"]
    b_alan = beklenen.get("properties", beklenen)
    u_alan = uretilen.get("properties", uretilen)
    if not isinstance(b_alan, dict) or not isinstance(u_alan, dict):
        return ["(alan listesi okunamadı — tümüyle değişmiş)"]
    satirlar: list[str] = []
    for ad in sorted(set(b_alan) - set(u_alan)):
        satirlar.append(f"      - alan SİLİNDİ: {ad}")
    for ad in sorted(set(u_alan) - set(b_alan)):
        satirlar.append(f"      + alan EKLENDİ: {ad}")
    for ad in sorted(set(b_alan) & set(u_alan)):
        if _fingerprint(b_alan[ad]) != _fingerprint(u_alan[ad]):
            eski = json.dumps(b_alan[ad], sort_keys=True, ensure_ascii=False)
            yeni = json.dumps(u_alan[ad], sort_keys=True, ensure_ascii=False)
            satirlar.append(
                f"      ~ alan DEĞİŞTİ: {ad}\n"
                f"          taban   : {eski}\n"
                f"          üretilen: {yeni}"
            )
    return satirlar or ["      ~ gövde değişti (alan dışı: açıklama/örnek/gerekli-alan listesi)"]


def _bolum_raporu(baslik: str, beklenen: dict[str, Any], uretilen: dict[str, Any]) -> list[str]:
    silinen = sorted(set(beklenen) - set(uretilen))
    eklenen = sorted(set(uretilen) - set(beklenen))
    degisen = [
        ad
        for ad in sorted(set(beklenen) & set(uretilen))
        if _fingerprint(beklenen[ad]) != _fingerprint(uretilen[ad])
    ]
    if not (silinen or eklenen or degisen):
        return []
    satirlar = [f"  {baslik}:"]
    for ad in silinen[:_MAX_REPORTED]:
        satirlar.append(f"    - SİLİNDİ: {ad}")
    for ad in eklenen[:_MAX_REPORTED]:
        satirlar.append(f"    + EKLENDİ: {ad}")
    for ad in degisen[:_MAX_REPORTED]:
        satirlar.append(f"    ~ DEĞİŞTİ: {ad}")
        satirlar.extend(_alan_farki(beklenen[ad], uretilen[ad]))
    toplam = len(silinen) + len(eklenen) + len(degisen)
    if toplam > _MAX_REPORTED:
        satirlar.append(f"    … toplam {toplam} kalem, ilk {_MAX_REPORTED} tanesi basıldı")
    return satirlar


def test_openapi_sozlesmesi_TABANDAN_SAPMAZ() -> None:
    """Uygulamadan üretilen sözleşme, commit'li tabanla **birebir** aynı olmalıdır."""
    uretilen = _generate()

    if os.environ.get("UPDATE_OPENAPI_BASELINE") == "1":
        BASELINE_PATH.write_text(_canonical_text(uretilen), encoding="utf-8")
        raise AssertionError(
            f"UPDATE_OPENAPI_BASELINE=1 ile çağrıldı: {BASELINE_PATH.name} YENİDEN YAZILDI.\n"
            "🔴 Şimdi `git diff` ile değişikliği gözle doğrula ve raporuna FRONTEND DEVRİ "
            "gerektiğini yaz. Bu bayrak olmadan tekrar koş: kapı yeşile dönmeli."
        )

    assert BASELINE_PATH.exists(), (
        f"{BASELINE_PATH} yok. Üretmek için: "
        "UPDATE_OPENAPI_BASELINE=1 .venv/bin/pytest "
        "tests/contract/test_openapi_contract_baseline.py"
    )
    taban = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    if _canonical_text(taban) == _canonical_text(uretilen):
        return

    rapor = [
        "🔴 OPENAPI SÖZLEŞMESİ TABANDAN SAPTI.",
        "",
        "Olası iki sebep VARDIR ve ayırt edilmelidir:",
        "  (a) KASITLI değişiklik (yeni uç/alan) → tabanı yenile + FRONTEND DEVRİ raporla.",
        "  (b) KÜTÜPHANE SÜRÜKLENMESİ (pin kaydı/kurulum ayrıştı) → ÖNCE sürümü ölç:",
        "      .venv/bin/pip list | grep -iE '^(fastapi|starlette|pydantic|pydantic-settings) '",
        "      Beklenen pinler pyproject.toml [project.dependencies] içinde.",
        "",
        f"  taban   : {len(taban.get('paths', {}))} yol · "
        f"{len(_operations(taban))} operasyon · {len(_schemas(taban))} şema",
        f"  üretilen: {len(uretilen.get('paths', {}))} yol · "
        f"{len(_operations(uretilen))} operasyon · {len(_schemas(uretilen))} şema",
        "",
    ]
    onek_uzunlugu = len(rapor)
    rapor += _bolum_raporu("OPERASYONLAR", _operations(taban), _operations(uretilen))
    rapor += _bolum_raporu("ŞEMALAR", _schemas(taban), _schemas(uretilen))

    # `paths`/`components` dışında bir yer oynadıysa (info, openapi sürümü, securitySchemes…)
    # yukarıdaki iki bölüm BOŞ döner — sessiz geçmesin.
    if len(rapor) == onek_uzunlugu:
        rapor.append(
            "  (fark `paths`/`components.schemas` DIŞINDA: `openapi` sürümü, `info`, "
            "`securitySchemes` vb. — tam farkı görmek için tabanı yenileyip `git diff` al.)"
        )

    rapor += [
        "",
        "Tabanı yenilemek için:",
        "  UPDATE_OPENAPI_BASELINE=1 .venv/bin/pytest "
        "tests/contract/test_openapi_contract_baseline.py",
    ]
    raise AssertionError("\n".join(rapor))


def test_taban_dosyasi_KANONIK_bicimde_yazilmistir() -> None:
    """Taban dosyasının kendisi kanonik olmalı.

    🔴 Bu ayrı bir bekçidir, üsttekinin tekrarı DEĞİL: taban elle düzenlenip
    sıralaması/girintisi bozulursa üstteki test `json.loads` sonrası yine yeşil kalır
    (karşılaştırma nesne düzeyinde), ama dosyanın `git diff`i okunmaz hâle gelir ve
    "diff'i gözle doğrula" adımı fiilen çalışmaz.
    """
    assert BASELINE_PATH.exists()
    ham = BASELINE_PATH.read_text(encoding="utf-8")
    assert ham == _canonical_text(json.loads(ham)), (
        f"{BASELINE_PATH.name} kanonik biçimde değil (sort_keys + indent=2 + sonda \\n). "
        "Elle düzenlenmiş olabilir. Yenile: UPDATE_OPENAPI_BASELINE=1 .venv/bin/pytest "
        "tests/contract/test_openapi_contract_baseline.py"
    )


def test_sozlesme_IMZASI_canli_ile_ayni_yorumlayici_ailesinden() -> None:
    """🔴 Pin'in **fiilen kurulu** olduğunu ölçen bekçi (pin kaydı ≠ pin kurulumu).

    `pyproject.toml`daki pin bir NİYET beyanıdır; sanal ortamda başka bir sürüm kurulu
    olabilir (fiilen: sistem `ruff` 0.8.6 ile repo pini 0.15.22 ayrışıp sahte kırmızı
    üretti). Sözleşmenin **imzası** kurulu yorumlayıcıyı ele verir ve canlıdan
    ölçülmüştür (2026-08-25, kimliksiz `GET /openapi.json`).

    🔴 İddialar bilinçli olarak **SAYI DEĞİL, VARLIK/YOKLUK** üzerinedir. Sayı iddiası
    (`643 pattern`) her yeni `Decimal` alanında kırmızı olur ve tabanın yanında **ikinci
    bir devir borcu** üretirdi; oysa bu testin işi kod kapsamını değil **yorumlayıcı
    ailesini** bekçilemektir. Ölçülen ayrışma:
      · pydantic **2.12+** → `Decimal` alanı `pattern` KAZANIR (repoda 643 alan)
      · pydantic **2.11.10** → aynı kodda `pattern` sayısı **5**'e düşer, bu desen HİÇ YOK
      · dosya yüklemede 2.12+ `contentMediaType` basar, eski aile `format: binary` basardı
    2.12.4 / 2.13.0 / 2.13.4 üçü de aynı imzayı üretir; ayrışma noktası 2.11 ↔ 2.12'dir.
    """
    sozlesme = _generate()

    # pydantic 2.12+ `Decimal` deseni. ELLE yazılmıştır (koddan/sabitten türetilmez):
    # türetilseydi mutasyon iki tarafı birden oynatır ve iddia kendini doğrulardı.
    decimal_deseni = r"^(?!^[-+.]*$)[+-]?0*\d*\.?\d*$"
    desenler = _tum_degerler(sozlesme, "pattern")
    assert decimal_deseni in desenler, (
        "pydantic 2.12+ `Decimal` deseni sözleşmede YOK → kurulu pydantic 2.12'den ESKİ "
        f"(bulunan farklı desen sayısı: {len(set(desenler))}). Canlı 2.12+ imzası taşıyor; "
        "`.venv/bin/pip list | grep -i pydantic` ile ölç."
    )

    # Dosya yükleme gövdeleri 2.12+ ailesinde `contentMediaType` basar, `format: binary` DEĞİL.
    assert _tum_degerler(sozlesme, "contentMediaType"), (
        "Hiç `contentMediaType` yok → dosya yükleme uçlarının şeması eski aile biçiminde."
    )
    assert "binary" not in _tum_degerler(sozlesme, "format"), (
        "`format: binary` geri geldi → yorumlayıcı ailesi değişti (canlı 0 tane basıyor)."
    )
