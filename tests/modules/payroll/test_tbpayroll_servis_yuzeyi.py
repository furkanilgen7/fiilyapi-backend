"""TB-PAYROLL anlik goruntusu — `payroll.service` MODUL YUZEYI donmus haldedir.

## Neden bu dosya var

`service.py` 1349 satirdi (tavan 800) ve bir PAKETE bolundu. Bolme davranis
KORUYAN olmak zorundaydi; ama "tum kume yesil" bunu KANITLAMAZ: TB-AUDIT turunda
tek Turkce karakterlik bir mutasyon butun test kumesine GORUNMEZ kaldi, yalniz
bolme-oncesi anlik goruntu yakaladi. Servis icin ayni tuzagin karsiligi sudur:

* bir ad cepheden **dusebilir** (cagiran ancak CANLIDA `AttributeError` yer),
* bir imza **sessizce degisebilir** (varsayilan deger, `*` sinirinin yeri,
  parametre sirasi),
* saf bir yardimcinin **cikti METNI** kayabilir (bordro kapilarinin 409/422
  cumleleri Turkce'dir ve hicbir test tam metni okumaz).

🔴 Bu modul KULLANICININ GOZU UZERINDEDIR: 2026-08-23'te "bordro kismi
calismiyor" denildi, teshis kusurun BU DOSYADA OLMADIGINI gosterdi (eksik olan
bir frontend yuzeyi). Bolmenin tek kabul olcutu hicbir davranisin degismemesidir.

Bu dosya uc yuzeyi de dondurur. Referans metin `tbpayroll_servis_yuzeyi.txt`tir
ve **bolmeden ONCE** (`47d53f7` tabani, tek dosyalik `service.py`) uretilmistir.

## Sozlesme: ESKI AD KUMESI ALT KUMEDIR

Bolme sonrasi cephe pakete alt modul adlari EKLER (`core`, `periods`, ...);
bu bir kayip degildir. Bu yuzden kural sudur: **anlik goruntudeki her satir
sonrasinda AYNEN bulunmalidir**; yeni ad eklenmesi serbesttir. Kayip ya da
degisen tek satir bile KIRMIZIDIR.

`app.modules.payroll.service[.altmodul]` modul yollari `<service>` olarak
NORMALLESTIRILIR: bir adin hangi alt dosyada durdugu cephenin sozlesmesi
DEGILDIR, tasinmasi serbesttir. Yabanci modul yollari (`app.core.errors`,
`app.modules.payroll.compute`, ...) normallestirilmez — onlarin degismesi
gercek bir sozlesme kaymasidir.

## 🔴 TABANDAN CIKARILAN IKINCI SATIR + DEGISEN ALAN (PUAN-SAAT-3, 2026-08-28)

    async def _man_day_counts(...) -> dict[uuid.UUID, int]
    'days': 22   ->   'days': Decimal('22')

Bordro SAATE uyarlandi. `_man_day_counts` "saati olan hucre"yi SAYIYORDU ve
4 saatlik gunu TAM GUN gosteriyordu (yevmiyelide fazla odeme); yerini
`_work_hours` (normal/FM/toplam turevi) ve `_overtime_multiplier` aldi — ikisi
de cepheye EKLENDI, ad kaybi bilinclidir. `PayrollLine.days` de `Integer`dan
`Numeric(6,1)`e genisledi: adam-gun artik bir SAYIM degil bir TUREVDIR
(`toplam saat / 9`). **Deger degismedi** (`22` = `Decimal('22')`), yalnizca
TIPI genisledi. Taban BU IKI DEGISIKLIK icin duzenlendi, yeniden URETILMEDI.

## 🔴 TABANDAN CIKARILAN TEK SATIR (PUAN-SAAT, 2026-08-28)

    set MAN_DAY_CODES = {TimesheetCode.overtime, TimesheetCode.worked}

Puantaj gun kodundan adam-saate gecti: `worked`/`overtime` kodlari KALKTI ve
"sahada gecmis gun" olcutu bir KOD KUMESI olmaktan cikip bir SQL kosuluna
dondu (`timesheet.matrix.worked_day_clause`). Ad cepheden bilerek dusuruldu ve
yerine yenisi eklendi; SAYDIGI SATIRLAR degismedi (goc her `worked`/`overtime`
hucresine saat yazar). Taban BU TEK SATIR icin duzenlendi, yeniden URETILMEDI.

## Yeniden uretim

    python -c "import importlib.util as u; \
      s=u.spec_from_file_location('y','tests/modules/payroll/test_tbpayroll_servis_yuzeyi.py'); \
      m=u.module_from_spec(s); s.loader.exec_module(m); print(m.build_surface())" \
      > tests/modules/payroll/tbpayroll_servis_yuzeyi.txt

DB gerektirmez — bilincidir: anlik goruntu ne fikstur ne semaya bagimlidir.
"""

import datetime as dt
import inspect
import pathlib
import re
import uuid
from decimal import Decimal

from app.modules.payroll import compute, service
from app.modules.payroll.models import (
    PayrollLine,
    PayrollLineStatus,
    PayrollPeriod,
    PayrollPeriodStatus,
)
from app.modules.personnel.models import Personnel
from app.modules.site_diary.models import WorkerSource

ANLIK_GORUNTU = pathlib.Path(__file__).with_name("tbpayroll_servis_yuzeyi.txt")

_SERVICE_ROOT = "app.modules.payroll.service"

# Anlik goruntu deterministik olmak zorunda: UUID uretilmez, SABIT degerler kullanilir.
_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_ID2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
_ID3 = uuid.UUID("33333333-3333-3333-3333-333333333333")
_ZAMAN = dt.datetime(2026, 3, 4, 5, 6, 7, tzinfo=dt.UTC)
_GUN = dt.date(2026, 3, 4)

#: Varsayilan `repr` BELLEK ADRESI basar (`... object at 0x10a8a4440>`) ve adres
#: her kosuda degisir. Sabitlenmezse anlik goruntu KENDI KENDINE kirmizi verir
#: ve gercek bir yuzey kaymasi bu gurultunun icinde kaybolur.
_ADRES = re.compile(r" at 0x[0-9a-fA-F]+>")


def _scrub(metin: str) -> str:
    return _ADRES.sub(" at 0xADRES>", metin)


def _normalize_module(ad: str) -> str:
    """Servis paketinin IC yolunu `<service>` yapar; yabanci yollara dokunmaz."""
    if ad == _SERVICE_ROOT or ad.startswith(_SERVICE_ROOT + "."):
        return "<service>"
    return ad


def _describe(ad: str, nesne: object) -> list[str]:
    if inspect.isfunction(nesne):
        onek = "async def" if inspect.iscoroutinefunction(nesne) else "def"
        return [f"{onek} {ad}{inspect.signature(nesne)}"]
    if inspect.isclass(nesne):
        yol = _normalize_module(nesne.__module__)
        satirlar = [f"class {ad} <- {yol}.{nesne.__qualname__}"]
        if yol == "<service>":
            satirlar.append(f"    __init__{inspect.signature(nesne.__init__)}")
        return satirlar
    if inspect.ismodule(nesne):
        return [f"module {ad} -> {_normalize_module(nesne.__name__)}"]
    if isinstance(nesne, frozenset | set):
        # `repr(frozenset)` sirasi calisma zamanina gore DEGISIR — siralanir.
        uyeler = sorted(repr(uye) for uye in nesne)
        return [f"set {ad} = {{{', '.join(uyeler)}}}"]
    return [_scrub(f"other {ad}: {type(nesne).__module__}.{type(nesne).__qualname__} = {nesne!r}")]


def _yuzey_satirlari() -> list[str]:
    satirlar: list[str] = []
    for ad in sorted(vars(service)):
        if ad.startswith("__"):
            continue
        satirlar.extend(_describe(ad, getattr(service, ad)))
    return satirlar


def _period(durum: PayrollPeriodStatus) -> PayrollPeriod:
    return PayrollPeriod(
        id=_ID,
        year=2026,
        month=7,
        status=durum,
        payment_due_date=_GUN,
        approved_by_id=None,
        approved_at=None,
        paid_at=None,
        sgk_submitted_at=None,
    )


def _line(durum: PayrollLineStatus, *, netli: bool = True) -> PayrollLine:
    return PayrollLine(
        id=_ID2,
        payroll_period_id=_ID,
        personnel_id=_ID3,
        personnel_source=WorkerSource.company,
        days=22,
        gross_amount=Decimal("50000.00") if netli else None,
        deduction_amount=Decimal("12879.50") if netli else None,
        net_amount=Decimal("37120.50") if netli else None,
        bank_amount=Decimal("37120.50") if netli else None,
        cash_amount=Decimal("0.00") if netli else None,
        tax_base_amount=Decimal("42500.00") if netli else None,
        cumulative_tax_base=Decimal("297500.00") if netli else None,
        income_tax_amount=Decimal("8500.00") if netli else None,
        is_overridden=False,
        overridden_by_id=None,
        overridden_at=None,
        previous_gross_amount=None,
        status=durum,
        excluded_reason=None,
    )


def _person(*, devir_yili: int | None) -> Personnel:
    kisi = Personnel(id=_ID3, full_name="Ayse Yilmaz")
    kisi.opening_tax_base = Decimal("125000.00")
    kisi.opening_tax_base_year = devir_yili
    return kisi


def _computed(durum: PayrollLineStatus) -> compute.ComputedLine:
    return compute.ComputedLine(
        days=19,
        gross_amount=Decimal("41000.00"),
        deduction_amount=Decimal("10561.19"),
        net_amount=Decimal("30438.81"),
        bank_amount=Decimal("30438.81"),
        cash_amount=Decimal("0.00"),
        tax_base_amount=Decimal("34850.00"),
        cumulative_tax_base=Decimal("243950.00"),
        income_tax_amount=Decimal("5227.50"),
        status=durum,
        excluded_reason="Taseron iscisi" if durum is PayrollLineStatus.excluded else None,
    )


def _hata_metni(cagri: object) -> str:
    """Fonksiyonu kosar; yukselen istisnayi `TIP: metin` olarak dondurur."""
    try:
        cagri()
    except Exception as hata:
        return f"{type(hata).__name__}: {hata}"
    return "OK"


_LINE_ALANLARI = (
    "personnel_source",
    "days",
    "gross_amount",
    "deduction_amount",
    "net_amount",
    "bank_amount",
    "cash_amount",
    "tax_base_amount",
    "cumulative_tax_base",
    "income_tax_amount",
    "status",
    "excluded_reason",
    "is_overridden",
    "previous_gross_amount",
)


def _satir_dokumu(line: PayrollLine) -> str:
    return repr({alan: getattr(line, alan) for alan in _LINE_ALANLARI})


def _davranis_satirlari() -> list[str]:
    satirlar: list[str] = []

    satirlar.append(f"PERMISSION_MODULE = {service.PERMISSION_MODULE!r}")
    satirlar.append(f"SECTION_ORDER = {tuple(k.value for k in service.SECTION_ORDER)!r}")

    # `month_bounds`: subat/artik yil/31 gunluk ay + yil sinirlari.
    for yil, ay in ((2026, 1), (2026, 2), (2024, 2), (2026, 4), (2026, 12), (2027, 7)):
        satirlar.append(f"month_bounds({yil}, {ay}) = {service.month_bounds(yil, ay)!r}")

    # `_opening_tax_base` — K7 devir matrahi, YIL niteleyicisi fail-closed.
    for devir_yili in (None, 2025, 2026, 2027):
        for yil in (2026, 2027):
            satirlar.append(
                f"_opening_tax_base(devir_yili={devir_yili!r}, yil={yil}) = "
                f"{service._opening_tax_base(_person(devir_yili=devir_yili), yil)!r}"
            )

    # `_apply` — hesabin TUM alanlari satira birlikte yazilir.
    for durum in PayrollLineStatus:
        line = _line(PayrollLineStatus.pending)
        service._apply(line, WorkerSource.freelance, _computed(durum))
        satirlar.append(f"_apply(hesap.status={durum.value}) = {_satir_dokumu(line)}")

    # `_promote_period_after_compute` — T6: bos donem onaya DUSMEZ.
    for durum in PayrollPeriodStatus:
        for etiket, satirlar_kumesi in (
            ("bos", []),
            ("pending_var", [_line(PayrollLineStatus.pending)]),
            ("pending_yok", [_line(PayrollLineStatus.excluded)]),
        ):
            period = _period(durum)
            service._promote_period_after_compute(period, satirlar_kumesi)
            satirlar.append(
                f"_promote_period_after_compute({durum.value}, {etiket}) -> {period.status.value}"
            )

    # `_line_response` — BY satir govdesi.
    for durum in PayrollLineStatus:
        yanit = service._line_response(_line(durum), "Ayse Yilmaz")
        satirlar.append(f"_line_response({durum.value}) = {yanit.model_dump()!r}")
    satirlar.append(
        "_line_response(netsiz) = "
        + repr(
            service._line_response(
                _line(PayrollLineStatus.uncomputed, netli=False), "X"
            ).model_dump()
        )
    )

    # `_assert_line_editable` — UC kapi, SIRASIYLA (donem -> excluded -> satir).
    for donem_durumu in PayrollPeriodStatus:
        for satir_durumu in PayrollLineStatus:
            satirlar.append(
                f"_assert_line_editable({donem_durumu.value}, {satir_durumu.value}) -> "
                + _hata_metni(
                    lambda d=donem_durumu, s=satir_durumu: service._assert_line_editable(
                        _period(d), _line(s)
                    )
                )
            )

    # `_assert_line_decidable` — IKI ortak kapi (donem + K2 excluded).
    for donem_durumu in PayrollPeriodStatus:
        for satir_durumu in PayrollLineStatus:
            satirlar.append(
                f"_assert_line_decidable({donem_durumu.value}, {satir_durumu.value}) -> "
                + _hata_metni(
                    lambda d=donem_durumu, s=satir_durumu: service._assert_line_decidable(
                        _period(d), _line(s)
                    )
                )
            )

    # `_apply_split` — S3 kurus invarianti + S4 netsiz satir.
    bolusumler = (
        (Decimal("37120.50"), Decimal("0.00")),
        (Decimal("20000.00"), Decimal("17120.50")),
        (Decimal("20000.00"), Decimal("17120.49")),
        (Decimal("0.00"), Decimal("0.00")),
        (Decimal("37120.51"), Decimal("0.00")),
    )
    for banka, elden in bolusumler:
        line = _line(PayrollLineStatus.pending)
        satirlar.append(
            f"_apply_split(net=37120.50, banka={banka}, elden={elden}) -> "
            + _hata_metni(lambda ln=line, b=banka, e=elden: service._apply_split(ln, b, e))
            + f" | banka={line.bank_amount!r} elden={line.cash_amount!r}"
        )
    netsiz = _line(PayrollLineStatus.uncomputed, netli=False)
    satirlar.append(
        "_apply_split(netsiz) -> "
        + _hata_metni(lambda: service._apply_split(netsiz, Decimal("1.00"), Decimal("0.00")))
    )

    return satirlar


def build_surface() -> str:
    """Iki bolumluk anlik goruntu metni: MODUL YUZEYI + SAF YARDIMCI CIKTILARI."""
    parcalar = [
        "# TB-PAYROLL anlik goruntusu — `app.modules.payroll.service`",
        "# Uretim: tests/modules/payroll/test_tbpayroll_servis_yuzeyi.py :: build_surface()",
        "",
        "## A. MODUL YUZEYI (ad + imza + varsayilanlar)",
        "",
        *_yuzey_satirlari(),
        "",
        "## B. SAF YARDIMCI CIKTILARI (deger + hata metni)",
        "",
        *_davranis_satirlari(),
        "",
    ]
    return "\n".join(parcalar)


def test_servis_yuzeyi_anlik_goruntuyle_ayni() -> None:
    """Bolme oncesi yuzeyin HER SATIRI hala var ve AYNEN ayni.

    Alt kume kurali bilinclidir (modul docstring'i): cephe yeni ad EKLEYEBILIR,
    ama eskisini dusuremez ya da degistiremez.
    """
    beklenen = ANLIK_GORUNTU.read_text(encoding="utf-8").splitlines()
    guncel = set(build_surface().splitlines())

    kayip = [satir for satir in beklenen if satir not in guncel]
    assert not kayip, "Bolme sonrasi YUZEY KAYBI/DEGISIMI:\n" + "\n".join(kayip)
