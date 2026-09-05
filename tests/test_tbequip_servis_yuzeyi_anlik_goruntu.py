"""TB-EQUIP — `equipment/service` bölünmesinin ANLIK GÖRÜNTÜ bekçisi.

## Neden bu dosya var

`app/modules/equipment/service.py` 962 satırlık TEK dosyaydı (tavan 800) ve alt
modüllere bölündü. **Bölmenin gerçek riski testlerin GÖRMEDİĞİ bir risktir**
(TB-AUDIT dersi): bir imza varsayılanı, bir anahtar-kelime-yalnız (`*`) sınırı,
bir sabitin ölçeği ya da bir eşik karşılaştırması bölme sırasında sessizce
kayabilir ve uçtan uca testlerin çoğu bunu görmez — çünkü onlar HTTP cevabına
bakar, servis YÜZEYİNE değil.

👉 Bu yüzden bölmenin güvencesi yalnız mevcut testler DEĞİL, bu dosyadır:
bölmeden **önce** dondurulmuş bir referansla, bölmeden **sonra** okunan yüzeyin
BİREBİR aynı olduğunu kanıtlar.

## Referans dürüst müdür?

`_ANLIK_GORUNTU` dosyası **bölmeden ÖNCEKİ ağaçta** üretildi ve o hâliyle
commit'lendi (`chore/tbequip-bolme` ilk commit'i). Bölmeden sonra YENİDEN
ÜRETİLMEDİ — yalnız karşılaştırıldı. Referansı yeniden üretmek bu bekçiyi
hiçliğe çevirir; yüzeyi bilerek değiştiren bir dilim referansı
`python -m tests.test_tbequip_servis_yuzeyi_anlik_goruntu` ile tazeler ve
**farkı incelemede görünür kılar** — sessizce değil.

## Kapsam

1. **Yüzey:** modülün TÜM modül düzeyi sembolleri (özel `_` adları DÂHİL) —
   sabitler `repr` ile, fonksiyonlar TAM imzasıyla (anotasyon + varsayılan +
   `*` sınırı + `async` damgası + dönüş tipi), sınıflar alanlarıyla.
   Bir sembol cepheden okunamıyorsa `getattr` burada patlar: cephenin
   EKSİKSİZ olduğunun kanıtı budur (`__all__` yeterli DEĞİLDİR).
2. **Saf yardımcıların ÇIKTILARI:** DB'ye dokunmayan her yardımcı, sınır
   değerleriyle fiilen KOŞTURULUR ve sonucu (ya da hata metni) donar. Yalnız
   imza dondurulsaydı `<` -> `<=` gibi bir mutasyon GÖRÜNMEZ olurdu.
## 🔴 URL-4 (2026-09-05) — IKI satir ELLE guncellendi

`get_equipment_or_404` ve `visible_equipment`in ucuncu parametresi
`equipment_id: uuid.UUID`ten `equipment_ref: uuid.UUID | str`e GENISLETILDI:
okuma ucu artik ad slug'i ile de cozuluyor. Tip DARALMADI, GENISLEDI — UUID
geciren her mevcut cagiran aynen calisir. Bekci degisimi DOGRU YAKALADI ve
dosya yeniden uretilmedi, iki satir elle degistirildi.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from collections import defaultdict
from datetime import date, time
from decimal import Decimal
from pathlib import Path

from app.core.errors import EquipmentValidationError
from app.modules.equipment import service
from app.modules.equipment.models import EquipmentOwnership, WorkLogType

_ANLIK_GORUNTU = Path(__file__).with_name("tbequip_servis_yuzeyi_anlik_goruntu.txt")


def _paket_dosyalari() -> list[Path]:
    """`service` modülünü oluşturan .py dosyaları (tek dosya da paket de olur)."""
    kaynak = Path(inspect.getfile(service))
    if kaynak.name == "__init__.py":
        return sorted(p for p in kaynak.parent.glob("*.py") if p.name != "__init__.py")
    return [kaynak]


def _tanimlar() -> dict[str, list[str]]:
    """AST ile: sembol adı -> onu TANIMLAYAN yerler (`dosya:satır`).

    🔴 `grep` DEĞİL AST: docstring'lerde ve yorumlarda sembol adları geçiyor
    (ör. `_month_bounds` ile `_lock_equipment` başka fonksiyonların
    docstring'lerinde) ve metinsel arama onları TANIM sanardı.

    İçe aktarmalar TANIM SAYILMAZ: bölmeden sonra alt modüller birbirinden ad
    alacak, ama tanım hâlâ TEK yerdedir.
    """
    bulunan: dict[str, list[str]] = defaultdict(list)
    for yol in _paket_dosyalari():
        agac = ast.parse(yol.read_text(encoding="utf-8"))
        for dugum in agac.body:
            adlar: list[str] = []
            if isinstance(dugum, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                adlar = [dugum.name]
            elif isinstance(dugum, ast.Assign):
                adlar = [t.id for t in dugum.targets if isinstance(t, ast.Name)]
            elif isinstance(dugum, ast.AnnAssign) and isinstance(dugum.target, ast.Name):
                adlar = [dugum.target.id]
            for ad in adlar:
                bulunan[ad].append(f"{yol.name}:{dugum.lineno}")
    return dict(bulunan)


def _imza(nesne: object) -> str:
    """Fonksiyonun TAM imzası — anotasyon, varsayılan ve `*` sınırı DÂHİL.

    `eval_str=False` bilinçli: kaynaktaki anotasyon METNİ dondurulur, çözülmüş
    nesne değil. `uuid.UUID` -> `UUID` gibi bir içe aktarma biçimi değişikliği
    davranışı değiştirmez ama METNİ değiştirir; burada onu da görmek İSTİYORUZ,
    çünkü bölmede en sık kayan şey içe aktarma bloğudur.
    """
    imza = inspect.signature(nesne)  # type: ignore[arg-type]
    damga = "async def" if inspect.iscoroutinefunction(nesne) else "def"
    return _normalize(f"{damga} {nesne.__name__}{imza}")


#: 🔴 CEPHEYE İNDİRGENEN paket yolları — `service` VE `models`.
#:
#: `inspect.signature` bir sınıf anotasyonunu `modul.QualName` olarak basar.
#: Bir sınıf cephesi aynı kalarak bir alt modüle taşındığında bu METİN değişir
#: (`...models.Equipment` -> `...models.core.Equipment`) ama DAVRANIŞ değişmez:
#: sınıf AYNI nesnedir, cepheden aynen okunur ve `openapi.json` çıktısı
#: (ölçüldü: iki ayrı yorumlayıcıda da) BAYT BAYT aynı kalır.
#:
#: Normalizasyon YALNIZ bu iki paketin GERÇEK parça adlarını kapsar; adlar
#: diskten okunur, elle yazılmaz. Bir anotasyon BAŞKA bir modüle kayarsa
#: (`schemas`, `repository`, başka bir modülün `models`i) normalize EDİLMEZ ve
#: bekçi kırmızı verir — kanıtı `test_normalizasyon_baska_modulu_YUTMAZ`.
_CEPHELER = ("app.modules.equipment.service", "app.modules.equipment.models")


def _paket_parcalari(paket_yolu: str) -> list[str]:
    """Bir cephenin disk üzerindeki parça adları (`__init__.py` hariç)."""
    modul = importlib.import_module(paket_yolu)
    kaynak = Path(inspect.getfile(modul))
    if kaynak.name != "__init__.py":
        return []
    return sorted(p.stem for p in kaynak.parent.glob("*.py") if p.name != "__init__.py")


def _normalize(metin: str) -> str:
    for cephe in _CEPHELER:
        for parca in sorted(_paket_parcalari(cephe), key=len, reverse=True):
            metin = metin.replace(f"{cephe}.{parca}.", f"{cephe}.")
    return metin


def _repr(deger: object) -> str:
    """🔴 DETERMİNİSTİK `repr`.

    Ham `repr(frozenset(...))` süreçten sürece DEĞİŞİR (`PYTHONHASHSEED` dizge
    karmalarını rastgeleleştirir). Ölçüldü: `_HOURS_INPUTS` iki ardışık koşuda
    iki farklı sırayla basıldı. Böyle bir bekçi kodun değişmediği turlarda da
    kırmızı verir ve ilk sahte kırmızıda susturulur — yani hiç yazılmamış
    olurdu. Küme ÜYELERİ sıralanır; üye EKLENİRSE/ÇIKARSA satır yine değişir.
    """
    if isinstance(deger, frozenset | set):
        tur = "frozenset" if isinstance(deger, frozenset) else "set"
        return f"{tur}({sorted(map(repr, deger))})"
    return repr(deger)


def _sinif_dokumu(ad: str, nesne: type) -> list[str]:
    satirlar = [f"class {ad}({', '.join(t.__name__ for t in nesne.__bases__)})"]
    for alan, tur in getattr(nesne, "__annotations__", {}).items():
        satirlar.append(f"  {ad}.{alan}: {tur if isinstance(tur, str) else tur!r}")
    alanlar = getattr(nesne, "_fields", None)
    if alanlar is not None:
        satirlar.append(f"  {ad}._fields = {alanlar!r}")
    return satirlar


def _yuzey() -> list[str]:
    """Modülün TÜM sembollerinin kanonik, sıralı dökümü."""
    satirlar: list[str] = []
    for ad in sorted(_tanimlar()):
        nesne = getattr(service, ad)
        if isinstance(nesne, type):
            satirlar.extend(_sinif_dokumu(ad, nesne))
        elif callable(nesne):
            satirlar.append(_imza(nesne))
        else:
            satirlar.append(f"{ad} = {_repr(nesne)}")
    return satirlar


def _cagri(fn: object, *args: object, **kwargs: object) -> str:
    """Bir çağrının SONUCUNU ya da hatasını tek satıra indir."""
    gosterim = ", ".join([repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()])
    try:
        sonuc = repr(fn(*args, **kwargs))  # type: ignore[operator]
    except Exception as hata:  # noqa: BLE001 - hata METNİ de yüzeyin parçası
        sonuc = f"!{type(hata).__name__}: {hata}"
    return f"{fn.__name__}({gosterim}) = {sonuc}"  # type: ignore[attr-defined]


#: `_week_buckets`e verilen ham günlük satırlar. Ayın 1'i CUMA'dır (2026-05-01):
#: ilk kova KIRPILI (1-3 Mayıs), son kova da kırpılıdır — kırpma kaybolursa
#: `start_date`/`end_date` DEĞİŞİR ve bekçi görür.
_GUNLUK_SATIRLAR = [
    (date(2026, 5, 1), WorkLogType.worked, Decimal("8.00")),
    (date(2026, 5, 2), WorkLogType.breakdown, Decimal("3.50")),
    # Beraberlik: `worked` KAZANIR (baskın tip kuralı) — `>` -> `>=` mutasyonu
    # tam burada kırmızı verir.
    (date(2026, 5, 4), WorkLogType.worked, Decimal("5.00")),
    (date(2026, 5, 5), WorkLogType.breakdown, Decimal("5.00")),
    # Arıza baskın hafta.
    (date(2026, 5, 12), WorkLogType.breakdown, Decimal("9.00")),
    (date(2026, 5, 13), WorkLogType.worked, Decimal("1.00")),
    (date(2026, 5, 31), WorkLogType.worked, Decimal("2.25")),
]


def _saf_yardimci_ciktilari() -> list[str]:
    """DB'ye dokunmayan her yardımcıyı SINIR değerleriyle fiilen koştur.

    Buradaki her satır bir mutasyon sınıfını bekçiler; hangi satırın neyi
    tuttuğu yorumlarda yazılıdır.
    """
    satirlar: list[str] = []

    # --- Dönem aritmetiği: ay sonu, artık yıl, yıl dönümü ---
    for gun in (
        date(2026, 1, 15),
        date(2026, 2, 1),
        date(2024, 2, 29),  # artık yıl
        date(2026, 11, 30),
        date(2026, 12, 31),  # yıl dönümü dalı
    ):
        satirlar.append(_cagri(service._month_bounds, gun))
    for yil, ay in ((2026, 1), (2026, 2), (2024, 2), (2026, 4), (2026, 12)):
        satirlar.append(_cagri(service.month_bounds, yil, ay))
    # Haftanın YEDİ günü: `weekday()` yerine `isoweekday()` kayması görünsün.
    for ofset in range(7):
        satirlar.append(_cagri(service._monday, date(2026, 5, 4 + ofset)))

    # --- `_week_buckets`: kırpma + baskın tip + toplam ---
    satirlar.append(
        "_week_buckets(2026-05) = "
        + repr(
            [
                (k.index, k.start_date, k.end_date, k.hours, k.dominant_record_type)
                for k in service._week_buckets(
                    date(2026, 5, 1), date(2026, 5, 31), _GUNLUK_SATIRLAR
                )
            ]
        )
    )
    # Kayıtsız ay: her kova `hours=0` ve `dominant_record_type=None` olmalı —
    # "kayıt yoksa `worked` yaz" mutasyonu burada kırmızı verir.
    satirlar.append(
        "_week_buckets(2026-05, BOS) = "
        + repr(
            [
                (k.index, k.start_date, k.end_date, k.hours, k.dominant_record_type)
                for k in service._week_buckets(date(2026, 5, 1), date(2026, 5, 31), [])
            ]
        )
    )

    # --- K11 `_resolve_hours`: DÖRT kapı + sınır (`end == start`) + ölçek ---
    for start, end, hours in (
        (time(8, 0), time(17, 30), None),  # normal
        (time(8, 0), time(8, 0), None),  # 🔴 SINIR: eşitlik REDDEDİLMEZ
        (time(17, 0), time(8, 0), None),  # gece vardiyası -> 422
        (time(8, 0), None, None),  # yarım aralık -> 422
        (None, time(8, 0), None),  # yarım aralık (ters) -> 422
        (time(8, 0), time(17, 0), Decimal("9")),  # sunucu hesabı ezilemez -> 422
        (None, None, Decimal("8")),  # doğrudan saat -> ölçeğe çekilir
        (None, None, Decimal("7.126")),  # 🔴 yuvarlama ölçeği
        (None, None, None),  # ne aralık ne saat -> 422
        (time(0, 0), time(23, 59), None),  # gün sınırı
    ):
        satirlar.append(_cagri(service._resolve_hours, start_time=start, end_time=end, hours=hours))

    # --- K2 `_assert_purchase_amount`: DÖRT bileşim (yetki/durum kapısı) ---
    for sahiplik in EquipmentOwnership:
        for bedel in (None, Decimal("0"), Decimal("125000.50")):
            satirlar.append(_cagri(service._assert_purchase_amount, sahiplik, bedel))

    # --- K19 `_quantize_unit_price`: ROUND_HALF_UP sınırı ---
    for ham in (
        Decimal("41.12345"),  # 5 -> YUKARI (HALF_EVEN olsaydı 41.1234 olurdu)
        Decimal("41.12355"),
        Decimal("41.1"),
        Decimal("0"),
        Decimal("-41.12345"),
    ):
        satirlar.append(_cagri(service._quantize_unit_price, ham))

    # --- K12 tavan METNİ: `mevcut`/`girilen` argüman SIRASI takası görünsün ---
    satirlar.append(
        "DAILY_HOURS_EXCEEDED.format = "
        + repr(service.DAILY_HOURS_EXCEEDED.format(mevcut=Decimal("20.5"), girilen=Decimal("4.5")))
    )
    return satirlar


def _uret() -> str:
    satirlar = _yuzey() + ["", "# --- saf yardımcı çıktıları ---"] + _saf_yardimci_ciktilari()
    return "\n".join(satirlar) + "\n"


def test_servis_yuzeyi_bolme_oncesi_referansla_birebir_ayni() -> None:
    """🔴 Bu dilimin TEK gerçek güvencesi.

    Referans bölmeden ÖNCE donduruldu; bölme bir imzayı, bir varsayılanı ya da
    bir eşiği sessizce değiştirseydi burada KIRMIZI olurdu.
    """
    beklenen = _ANLIK_GORUNTU.read_text(encoding="utf-8")
    assert beklenen.strip(), "referans anlık görüntü BOŞ — bekçi hiçbir şey ölçmüyor olurdu"

    uretilen = _uret()

    beklenen_satirlar = beklenen.splitlines()
    uretilen_satirlar = uretilen.splitlines()
    eksik = set(beklenen_satirlar) - set(uretilen_satirlar)
    fazla = set(uretilen_satirlar) - set(beklenen_satirlar)
    assert not eksik and not fazla, (
        f"servis yüzeyi DEĞİŞTİ.\n  kaybolan {len(eksik)}: {sorted(eksik)[:5]}\n"
        f"  yeni {len(fazla)}: {sorted(fazla)[:5]}"
    )
    assert uretilen == beklenen


def test_anlik_goruntu_bos_degil_ve_tum_sembolleri_kapsiyor() -> None:
    """Bekçinin girdisinin BOŞ OLMADIĞI ayrıca kanıtlanır.

    Referans yanlışlıkla boşalsa ya da sembollerin yarısı düşse üstteki test
    yine yeşil kalabilirdi ("hiçbir şeyi hiçbir şeyle karşılaştırmak").
    """
    # 🔴 MK-4 (+2 sembol, +1 fonksiyon, +2 satır): `RENTAL_PERIOD_ORDER` sabiti
    # ve `_assert_rental_period` kapısı. Kural SERVİSE konuldu (şemaya ya da
    # yalnız DB `CHECK`ine değil) çünkü PATCH'te gövde ile DB satırının
    # BİRLEŞİMİNE bakar — `_assert_purchase_amount` (K2) emsalinin birebiri.
    # Sayılar bilinçli olarak ELLE güncellenir: yüzeyi genişleten dilim onu
    # GÖRÜNÜR kılmak zorundadır.
    tanimlar = _tanimlar()
    assert len(tanimlar) == 51, f"sembol sayısı 51 olmalı, {len(tanimlar)} bulundu"
    nesneler = {a: getattr(service, a) for a in tanimlar}
    fonksiyonlar = [a for a, n in nesneler.items() if callable(n) and not isinstance(n, type)]
    assert len(fonksiyonlar) == 31, f"fonksiyon sayısı 31 olmalı, {len(fonksiyonlar)} bulundu"

    satirlar = _ANLIK_GORUNTU.read_text(encoding="utf-8").splitlines()
    assert len(satirlar) == 101, f"anlık görüntü 101 satır olmalı, {len(satirlar)} bulundu"
    for ad in tanimlar:
        assert any(
            s.startswith(f"{ad} = ")
            or s.startswith(f"def {ad}(")
            or s.startswith(f"async def {ad}(")
            or s.startswith(f"class {ad}(")
            for s in satirlar
        ), f"`{ad}` anlık görüntüde HİÇ geçmiyor — bekçi onu kapsamıyor"


def test_saf_yardimci_ciktilari_gercekten_kosuyor() -> None:
    """🔴 Çıktı bloğunun POZİTİF KONTROLÜ.

    Blok sessizce boşalsa (ör. bir `for` döngüsü boş kümede dönse) üstteki
    bekçi yine yeşil kalırdı. Burada hem SATIR SAYISI hem de hata dalının
    fiilen koştuğu ayrıca kanıtlanır: kapılardan biri kaldırılsaydı `!`
    satırlarının sayısı düşerdi.
    """
    ciktilar = _saf_yardimci_ciktilari()
    assert len(ciktilar) == 41, f"saf yardımcı çıktısı 41 satır olmalı, {len(ciktilar)} bulundu"
    hatalar = [s for s in ciktilar if "!EquipmentValidationError" in s]
    assert len(hatalar) == 6, f"beklenen 6 doğrulama hatası, {len(hatalar)} bulundu"
    assert issubclass(EquipmentValidationError, Exception)


def test_normalizasyon_baska_modulu_YUTMAZ() -> None:
    """🔴 `_normalize`ın POZİTİF KONTROLÜ.

    Normalizasyon iki cephenin KENDİ parçalarını yutar. Kör bir `replace`
    olsaydı gerçek bir kayma da (bir tipin `schemas`a ya da başka bir modüle
    taşınması) sessizce yutulur ve bekçi hiçbir şey bekçilemezdi.
    """
    assert _normalize("app.modules.equipment.service.core.EquipmentSummary") == (
        "app.modules.equipment.service.EquipmentSummary"
    )
    assert _normalize("app.modules.equipment.models.core.Equipment") == (
        "app.modules.equipment.models.Equipment"
    )
    # BAŞKA modüller DOKUNULMADAN geçer:
    for yabanci in (
        "app.modules.equipment.schemas.EquipmentCreate",
        "app.modules.equipment.repository.Foo",
        "app.modules.personnel.models.core.Personnel",
        "app.modules.equipment.rental_service.Bar",
    ):
        assert _normalize(yabanci) == yabanci, f"normalizasyon YUTTU: {yabanci}"


def test_paylasilan_yardimcilarin_tek_kopyasi_var() -> None:
    """🔴 Hiçbir sembol İKİ KEZ tanımlı olmamalı.

    Bölme sırasında bir yardımcıyı iki alt modüle KOPYALAMAK en sinsi
    bozulmadır: bugün iki kopya aynı sonucu verir, yarın biri düzeltilir öteki
    kalır (`month_bounds` / `_month_bounds` ikilisi tam bu sınıftandır) ve
    *"tek kopyayı çağır"* diyen bir sonraki dilim İKİ ADAY bulur.
    """
    coklu = {ad: yerler for ad, yerler in _tanimlar().items() if len(yerler) > 1}
    assert not coklu, f"AYNI sembol birden çok yerde tanımlı: {coklu}"


def test_parca_dosyalari_satir_tavaninin_altinda() -> None:
    """Bölmenin AMACI ölçülür: hiçbir parça 800 satır tavanını aşmamalı.

    Bekçi olmadan bir sonraki dilim en büyük parçayı yeniden tavana taşıyabilir
    ve kimse fark etmezdi.
    """
    kaynak = Path(inspect.getfile(service))
    dosyalar = [kaynak] if kaynak.name != "__init__.py" else sorted(kaynak.parent.glob("*.py"))
    asanlar = {
        p.name: len(p.read_text(encoding="utf-8").splitlines())
        for p in dosyalar
        if len(p.read_text(encoding="utf-8").splitlines()) > 800
    }
    assert not asanlar, f"800 satır tavanını aşan parça(lar): {asanlar}"


if __name__ == "__main__":  # pragma: no cover - referansı elle tazelemek için
    _ANLIK_GORUNTU.write_text(_uret(), encoding="utf-8")
    print(f"referans yazildi: {_ANLIK_GORUNTU}")
