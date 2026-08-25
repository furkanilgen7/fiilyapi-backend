"""SEC-ARGON bekçileri: argon2 pin'i + parola özetinin maliyet parametreleri.

🔴 Neden: `PasswordHasher()` VARSAYILAN parametrelerle kurulduğunda ve kütüphane
`>=` ile bırakıldığında, kütüphane sürümü değiştiği gün üretilen parolalar sessizce
BAŞKA maliyet parametreleriyle hash'lenir. Argon2 özeti kendi parametrelerini metninde
taşıdığı için eskiler doğrulanmaya devam eder → hiçbir test kırılmaz, hiçbir uyarı
çıkmaz, veritabanında iki farklı güvenlik seviyesinde parola birikir.
`ruff==0.15.22` ve `pydantic==2.13.4` pinlerinin gerekçesiyle aynı sınıftan: üretilen
artefakt (burada: özetin maliyeti) aracın sürümüne bağlıdır, koda değil.
"""

import base64
import importlib.metadata
import re
from pathlib import Path

import pytest

from app.core.security import hash_password, verify_password

REPO_KOK = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_KOK / "pyproject.toml"
REQUIREMENTS = REPO_KOK / "requirements.txt"

# 🔴 İKİ paket birden pinlenir. `argon2-cffi` maliyet VARSAYILANLARINI tanımlar;
# `argon2-cffi-bindings` özeti fiilen ÜRETEN katmandır (`starlette` ↔ `fastapi` emsali).
# İkincisi GEÇİŞLİ bir bağımlılıktır — pinlenmezse `argon2-cffi` pinliyken bile kayar
# (ölçüldü: canlı imaj 2026-08-25 deploy'unda sessizce 25.1.0 → 26.1.0'a taşındı).
PINLI_PAKETLER = ("argon2-cffi", "argon2-cffi-bindings")


def _pin_deseni(paket: str) -> re.Pattern[str]:
    """Yalnız TAM sürüm pini eşleşir; `argon2-cffi>=23.1` bu desene UYMAZ.

    İki paket adı iç içe geçiyor (`argon2-cffi` ⊂ `argon2-cffi-bindings`) ama ayrı bir
    sözcük sınırı GEREKMEZ: desendeki `==` zaten sınırın kendisidir — `argon2-cffi==`
    aranırken `argon2-cffi-bindings==` satırında `argon2-cffi`den sonra `-` gelir ve
    eşleşme düşer. ÖLÇÜLDÜ: `(?![\w-])` lookahead'i eklenip kaldırıldığında kapı
    **7 passed** kalıyor → eşdeğer mutant, kör bekçi değil. Bu yüzden konmadı;
    iki paketin ayrı ayrı bekçilendiğini kanıtlayan mutasyon "pini SİL" turudur.
    """
    return re.compile(rf'^\s*"?{re.escape(paket)}==([0-9][0-9A-Za-z.\-]*)"?,?\s*$', re.MULTILINE)


def _pin_oku(yol: Path, paket: str) -> str:
    eslesme = _pin_deseni(paket).findall(yol.read_text(encoding="utf-8"))
    assert len(eslesme) == 1, (
        f"{yol.name} içinde `{paket}==<tam sürüm>` biçiminde TEK bir satır bulunmalı "
        f"(bulunan: {eslesme}). Aralık (`>=`) bırakılırsa — ya da paket hiç yazılmayıp "
        "geçişli bağımlılık olarak bırakılırsa — her kurulum farklı bir sürüm çözer ve "
        "parola maliyet parametreleri sessizce kayar."
    )
    return eslesme[0]


@pytest.mark.parametrize("paket", PINLI_PAKETLER)
def test_argon2_pini_IKI_dosyada_da_TAM_surumle_yazilmistir(paket: str) -> None:
    """Pin bir NİYET beyanıdır; iki dosyanın ayrışması da sürüklenme kapısıdır.

    `pyproject.toml` yerel/CI kurulumunu, `requirements.txt` Railway Docker imajını
    besler. Biri güncellenip öbürü unutulursa canlı ile yerel farklı sürüm koşar.
    """
    assert _pin_oku(PYPROJECT, paket) == _pin_oku(REQUIREMENTS, paket), (
        f"pyproject.toml ile requirements.txt farklı {paket} sürümü pinliyor: "
        f"{_pin_oku(PYPROJECT, paket)} != {_pin_oku(REQUIREMENTS, paket)}"
    )


@pytest.mark.parametrize("paket", PINLI_PAKETLER)
def test_KURULU_argon2_surumu_pin_ile_AYNI(paket: str) -> None:
    """🔴 Pin kaydı ≠ pin kurulumu (TB-PIN'in 'kurulu yorumlayıcı imzası' bekçisinin emsali).

    Sanal ortamda pinden başka bir sürüm kurulu olabilir; o durumda dosyadaki pin
    hiçbir şey bekçilemez. Fiilen ölçülmüş kardeşi: sistem `ruff` 0.8.6 ↔ repo pini
    0.15.22 ayrışıp dokunulmamış ağaçta sahte kırmızı üretti.
    """
    kurulu = importlib.metadata.version(paket)
    pin = _pin_oku(PYPROJECT, paket)
    assert kurulu == pin, (
        f"Kurulu {paket} {kurulu}, pin {pin}. Ortamı tazele: "
        "`.venv/bin/pip install -e '.[dev]'`. Pin CANLIDA KOŞANA göre seçilmiştir "
        "(canlı build log'undan doğrudan okundu); yükseltme AYRI bir karardır."
    )


def test_uretilen_HASH_DIZESI_beklenen_maliyet_parametrelerini_tasir() -> None:
    """🔑 İddia, `PasswordHasher` nesnesinin ALANLARINDAN değil ÜRETİLEN ÖZETTEN okunur.

    Nesnenin alanlarını okumak `_hasher`ı kendisiyle karşılaştırmak olurdu ve
    parametreler kütüphane varsayılanına düşse bile yeşil kalırdı. Argon2 özeti
    parametrelerini metninde taşır: `$argon2id$v=19$m=...,t=...,p=...$<salt>$<hash>`.

    Beklenen değerler ELLE yazılmıştır (`app.core.security` sabitlerinden TÜRETİLMEZ):
    türetilseydi bir mutasyon iki tarafı birden oynatır ve iddia kendini doğrulardı.
    Değerler, canlıda bugün fiilen koşan argon2-cffi 25.1.0'ın varsayılanlarıyla
    ÖZDEŞTİR (ölçüldü) — bu dilim mevcut parolaların maliyetini değiştirmez.
    """
    ozet = hash_password("sec-argon-bekci-girdisi")

    assert ozet.startswith("$argon2id$v=19$m=65536,t=3,p=4$"), (
        f"Özetin maliyet parametreleri beklenenden farklı: {ozet.split('$')[:4]}. "
        "Beklenen: argon2id, v=19, m=65536, t=3, p=4."
    )

    _, _alg, _ver, _params, salt_b64, hash_b64 = ozet.split("$")
    assert len(base64.b64decode(salt_b64 + "=" * (-len(salt_b64) % 4))) == 16, (
        "salt_len 16 bayt değil."
    )
    assert len(base64.b64decode(hash_b64 + "=" * (-len(hash_b64) % 4))) == 32, (
        "hash_len 32 bayt değil."
    )


def test_acik_parametrelerle_uretilen_ozet_DOGRULANABILIR() -> None:
    """Parametreleri açığa çıkarmak doğrulamayı bozmamalı (yazma-okuma turu)."""
    parola = "sec-argon-bekci-girdisi-2"
    assert verify_password(parola, hash_password(parola)) is True


def test_parametreler_KUTUPHANE_VARSAYILANINDAN_MIRAS_ALINMIYOR(monkeypatch) -> None:
    """🔴 Bu dilimin ASIL kusurunu bekçileyen test: `PasswordHasher()` ↔ açık parametreler.

    Diğer bekçi ("üretilen özet m=65536,t=3,p=4 taşır") bugün İKİ yazımda da yeşildir,
    çünkü açık değerler kurulu sürümün varsayılanlarıyla ÖZDEŞ seçildi. Yani tek başına
    `PasswordHasher()`a geri dönüşü GÖREMEZ — kusur zaten "bugün hiçbir fark yok,
    yarın sessizce fark var" sınıfındandır.

    Bu test o yarını BUGÜNE getirir: kütüphanenin varsayılanları başka olsaydı ne
    olurdu? `argon2.PasswordHasher` başka varsayılanlar taşıyan bir alt sınıfla
    değiştirilip modül yeniden yüklenir. Parametreler AÇIKÇA veriliyorsa özet
    değişmez; varsayılana bırakılmışsa özet sahte varsayılanları taşır → KIRMIZI.
    """
    import importlib.util

    import argon2

    import app.core.security as security

    gercek_sinif = argon2.PasswordHasher

    class _BaskaVarsayilanlarlaHasher(gercek_sinif):  # type: ignore[misc, valid-type]
        """Kütüphanenin bir gün farklı varsayılanlarla gelmesini taklit eder."""

        def __init__(  # noqa: D107
            self,
            time_cost: int = 9,
            memory_cost: int = 1024,
            parallelism: int = 1,
            hash_len: int = 24,
            salt_len: int = 9,
            **kwargs: object,
        ) -> None:
            super().__init__(
                time_cost=time_cost,
                memory_cost=memory_cost,
                parallelism=parallelism,
                hash_len=hash_len,
                salt_len=salt_len,
                **kwargs,  # type: ignore[arg-type]
            )

    # 🔴 `importlib.reload(security)` KULLANILMAZ: modülü yerinde yeniden yüklemek
    # `TokenError` sınıf NESNESİNİ de yeniden yaratır ve onu daha önce import etmiş
    # modüllerdeki `except TokenError` dalları sessizce ıskalar (ölçüldü: tam kümede
    # 4 token testi kırmızıya döndü). Bunun yerine aynı kaynaktan AYRI ADLI, izole bir
    # modül kopyası yüklenir — hiçbir global durum değişmez.
    monkeypatch.setattr(argon2, "PasswordHasher", _BaskaVarsayilanlarlaHasher)
    spec = importlib.util.spec_from_file_location("_secargon_probe_security", security.__file__)
    assert spec is not None and spec.loader is not None
    kopya = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kopya)
    ozet = kopya.hash_password("sec-argon-varsayilan-sizma-testi")

    assert ozet.startswith("$argon2id$v=19$m=65536,t=3,p=4$"), (
        "🔴 Parola maliyet parametreleri KÜTÜPHANE VARSAYILANINDAN geliyor: kütüphane "
        f"varsayılanları değişince özet de değişti ({ozet.split('$')[3]}). "
        "`PasswordHasher(...)` açık time_cost/memory_cost/parallelism ile kurulmalı — "
        "aksi hâlde sürüm yükseltildiği gün o günden sonraki parolalar sessizce başka "
        "maliyetle hash'lenir ve hiçbir kapı bunu görmez."
    )
