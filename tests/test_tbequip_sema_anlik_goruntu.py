"""TB-EQUIP — `equipment/models` ŞEMA anlık görüntüsü (bölme bekçisi).

## Neden bu dosya var

`app/modules/equipment/models.py` 874 satır (tavan 800) ve bölünmesi
tartışıldı. Bir **SQLAlchemy eşleyici dosyasını** bölmek servis bölmekle aynı
iş DEĞİLDİR:

* Sınıf artık içe aktarılmıyorsa tablosu `Base.metadata`ya **kaydolmaz**;
  `import` yeşil kalır, `alembic autogenerate` o tabloyu "SİLİNECEK" diye
  raporlar ve hata **ilk sorguda / ilk migration'da** patlar. Cephe bu yüzden
  her sınıfı **gerçekten içe aktarmalıdır** (`__all__` yetmez).
* `ForeignKey("equipment.id")` gibi **dize hedefler** de `Base.metadata`dan
  çözülür: hedef tablo kaydolmamışsa `NoReferencedTableError` yine ilk
  kullanımda çıkar.

👉 "İçe aktarma çalıştı" yanılsamasını kıran TEK ölçüm şudur: `Base.metadata`
üzerinden **tablo + sütun + kısıt + indeks** dökümünü almak ve donmuş referansla
karşılaştırmak. Bu dosya onu yapar.

## Kapsam ve tazeleme

Yalnız **ekipman modülünün tabloları** (7 tablo). Bir dilim bu tablolara bilerek
kolon eklerse referans `python -m tests.test_tbequip_sema_anlik_goruntu` ile
tazelenir ve **fark incelemede görünür** — sessizce değil. Şemayı değiştiren
dilim zaten bir migration yazıyordur; bu dosyayı da tazelemek o migration'ın
kapsamının parçasıdır.
## 🔴 URL-4 (2026-09-05) — anlik goruntu YALNIZ EKLEME ile guncellendi

`equipment.slug` ve `equipment_rental_invoices.slug` kolonlari + iki kismi
benzersiz indeks eklendi (okunabilir URL, `f3a7c9e1d5b2`). Fark ALINDI ve
YALNIZ DORT SATIRIN EKLENDIGI, HICBIR SATIRIN KAYBOLMADIGI dogrulandiktan
SONRA referans yeniden uretildi — korukorune "yesillenene kadar uret" YAPILMADI.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from sqlalchemy import CheckConstraint, Column, ForeignKeyConstraint, Table, UniqueConstraint
from sqlalchemy.sql.elements import ClauseElement

from app.core.db import Base
from app.modules.equipment import models

_ANLIK_GORUNTU = Path(__file__).with_name("tbequip_sema_anlik_goruntu.txt")


def _paket_dosyalari() -> list[Path]:
    """`models` modülünü oluşturan .py dosyaları (tek dosya da paket de olur)."""
    kaynak = Path(inspect.getfile(models))
    if kaynak.name == "__init__.py":
        return sorted(p for p in kaynak.parent.glob("*.py") if p.name != "__init__.py")
    return [kaynak]


def _tanimli_siniflar() -> dict[str, str]:
    """AST ile: modülde TANIMLI her sınıf adı -> `dosya:satır`.

    Bölmeden sonra cephe bunların HEPSİNİ okunabilir kılmalıdır; biri eksikse
    `getattr` aşağıda patlar. Bu, eşleyici kaydının fiilen yapıldığının
    kanıtıdır — `__all__` listesi bunu KANITLAMAZ.
    """
    bulunan: dict[str, str] = {}
    for yol in _paket_dosyalari():
        for dugum in ast.parse(yol.read_text(encoding="utf-8")).body:
            if isinstance(dugum, ast.ClassDef):
                bulunan[dugum.name] = f"{yol.name}:{dugum.lineno}"
    return bulunan


def _ekipman_tablolari() -> list[Table]:
    """Bu modülün TANIMLADIĞI tablolar — `Base.metadata`dan okunur.

    Tablo adına göre değil SINIFA göre seçilir: adla süzülseydi bir sınıf
    kaydolmayı bıraktığında tablosu listeden sessizce düşer ve bekçi hiçbir şey
    demezdi (eksilen satır "beklenen" sanılırdı). Sınıftan gidince kayıp sınıf
    `getattr`da patlar.
    """
    tablolar: list[Table] = []
    for ad in sorted(_tanimli_siniflar()):
        nesne = getattr(models, ad)
        tablo = getattr(nesne, "__table__", None)
        if isinstance(tablo, Table):
            tablolar.append(tablo)
    return sorted(tablolar, key=lambda t: t.name)


def _deger(ham: object) -> str:
    """🔴 ADRESSİZ gösterim — sahte KIRMIZInın kaynağı burasıydı.

    Ölçüldü: ham `repr` iki ardışık koşuda iki farklı dizge üretti
    (`<function uuid4 at 0x10bdadee0>`, `<TextClause object at 0x10bd8c590>`).
    Bellek adresi taşıyan bir referans HER koşuda kırmızı verir; böyle bir
    bekçi ilk turda susturulur, yani hiç yazılmamış olurdu. Çağrılabilir
    varsayılan ADIYLA, sunucu varsayılanı ÜRETTİĞİ SQL METNİYLE donar —
    ikisi de davranışın gerçek taşıyıcısıdır.
    """
    if ham is None:
        return "None"
    ic = getattr(ham, "arg", ham)
    if callable(ic):
        return getattr(ic, "__name__", repr(ic))
    if isinstance(ic, ClauseElement):
        return f"sql:{ic}"
    return repr(ic)


def _sutun_satiri(tablo: Table, sutun: Column[object]) -> str:
    return (
        f"{tablo.name}.{sutun.name}: tur={sutun.type!r} null={sutun.nullable} "
        f"pk={sutun.primary_key} varsayilan={_deger(sutun.default)} "
        f"sunucu={_deger(sutun.server_default)}"
    )


def _kisit_satiri(kisit: object) -> str:
    kolonlar = sorted(c.name for c in getattr(kisit, "columns", []))
    ek = ""
    if isinstance(kisit, ForeignKeyConstraint):
        ek = " -> " + ",".join(
            f"{fk.target_fullname}(ondelete={fk.ondelete},onupdate={fk.onupdate})"
            for fk in kisit.elements
        )
    elif isinstance(kisit, CheckConstraint):
        ek = f" sql={kisit.sqltext}"
    elif isinstance(kisit, UniqueConstraint):
        ek = " UQ"
    return f"  KISIT {type(kisit).__name__} {kisit.name} {kolonlar}{ek}"  # type: ignore[attr-defined]


def _uret() -> str:
    """🔴 Kısıtlar SATIR METNİNE göre sıralanır, ada göre DEĞİL.

    Ölçüldü: `Table.constraints` bir KÜMEdir ve adsız (`name=None`) yabancı
    anahtar kısıtları `(tur, ad)` anahtarında BERABERE kalıyor; sıra koşudan
    koşuya değişti ve bekçi kod değişmediği hâlde kırmızı verdi. Sahte
    KIRMIZI da sahte yeşil kadar zararlıdır: ilk turda susturulur.
    """
    satirlar: list[str] = []
    for tablo in _ekipman_tablolari():
        satirlar.append(f"TABLO {tablo.name}")
        satirlar.extend("  " + _sutun_satiri(tablo, s) for s in tablo.columns)
        satirlar.extend(sorted(_kisit_satiri(k) for k in tablo.constraints))
        satirlar.extend(
            sorted(
                f"  INDEKS {i.name} {[c.name for c in i.columns]} unique={i.unique}"
                for i in tablo.indexes
            )
        )
    return "\n".join(satirlar) + "\n"


def test_ekipman_semasi_referansla_birebir_ayni() -> None:
    """🔴 `models` bölünürse bu testin TEK işi vardır: şema OYNAMADI mı?"""
    beklenen = _ANLIK_GORUNTU.read_text(encoding="utf-8")
    assert beklenen.strip(), "referans anlık görüntü BOŞ — bekçi hiçbir şey ölçmüyor olurdu"

    uretilen = _uret()
    beklenen_satirlar = beklenen.splitlines()
    uretilen_satirlar = uretilen.splitlines()
    eksik = set(beklenen_satirlar) - set(uretilen_satirlar)
    fazla = set(uretilen_satirlar) - set(beklenen_satirlar)
    assert not eksik and not fazla, (
        f"ekipman ŞEMASI DEĞİŞTİ.\n  kaybolan {len(eksik)}: {sorted(eksik)[:5]}\n"
        f"  yeni {len(fazla)}: {sorted(fazla)[:5]}"
    )
    assert uretilen == beklenen


def test_cephe_her_sinifi_gercekten_ice_aktariyor() -> None:
    """🔴 `__all__` DEĞİL, fiilen içe aktarım.

    Bir sınıf cepheden okunamıyorsa `getattr` patlar; okunabiliyorsa modül
    yüklenmiş ve tablosu `Base.metadata`ya kaydolmuştur.
    """
    tanimli = _tanimli_siniflar()
    assert len(tanimli) == 18, f"sınıf sayısı 18 olmalı, {len(tanimli)} bulundu"
    for ad in tanimli:
        assert hasattr(models, ad), f"`{ad}` cepheden okunamıyor — eşleyici KAYIT OLMAMIŞ olabilir"

    tablolar = {t.name for t in _ekipman_tablolari()}
    assert tablolar == {
        "equipment",
        "equipment_work_logs",
        "equipment_fuel_logs",
        "equipment_rental_invoices",
        "equipment_rental_invoice_lines",
        "equipment_document_types",
        "equipment_documents",
    }, f"ekipman tabloları eksik/fazla: {sorted(tablolar)}"
    assert tablolar <= set(Base.metadata.tables), "tablolar `Base.metadata`ya KAYDOLMAMIŞ"


def test_yabanci_anahtar_hedefleri_cozulebiliyor() -> None:
    """🔴 `ForeignKey("equipment.id")` dize hedefi ÇÖZÜLÜYOR mu?

    Hedef tablo `Base.metadata`ya kaydolmamışsa `.column` erişimi
    `NoReferencedTableError` atar — ve bu hata normalde İLK SORGUDA çıkardı,
    içe aktarmada değil. Burada onu içe aktarma anında zorluyoruz.
    """
    sayac = 0
    for tablo in _ekipman_tablolari():
        for sutun in tablo.columns:
            for fk in sutun.foreign_keys:
                assert fk.column is not None, f"{tablo.name}.{sutun.name} -> {fk.target_fullname}"
                sayac += 1
    assert sayac == 18, f"yabancı anahtar sayısı 18 olmalı, {sayac} bulundu"


if __name__ == "__main__":  # pragma: no cover - referansı elle tazelemek için
    _ANLIK_GORUNTU.write_text(_uret(), encoding="utf-8")
    print(f"referans yazildi: {_ANLIK_GORUNTU}")
