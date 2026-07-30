"""B9 — Excel ice aktarma: SAF cozumleme katmani (spec §6.4, §7.8).

Bu modul veritabanina DOKUNMAZ ve servis katmanindan HICBIR SEY ITHAL ETMEZ.
Boylece bagimlilik yonu tek yonludur (`service` → `importer`) ve baslik/hucre
mantigi bir HTTP istegi ya da DB olmadan test edilebilir. Alan kurallarindan
DB'ye ihtiyac duyanlar (`net > brut`, `owner_side` proje tipi, blokta mevcut
`unit_no`) BILEREK burada degil, servistedir — tekil `POST` ile ayni kod yolunu
kullanmalari icin.

DOSYA HICBIR YERE YAZILMAZ: girdi `bytes`'tir, `io.BytesIO` uzerinden okunur.
Bir dosya yolu ya da gecici dosya bu modulde YOKTUR ve eklenmemelidir (spec §7.8).
"""

import io
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, DecimalException

from openpyxl import load_workbook

from app.modules.units.models import UnitKind, UnitOwnerSide

# Spec §7.8 sinir tablosu — sihirli sayi birakilmaz.
# 1000 satirlik bir `.xlsx` ~50 KB'tir; 2 MB fazlasiyla yeterlidir ve bellek
# saldirisini keser. KY'de 52, KKP'de 42 unite var; 1000 en buyuk gercekci
# projenin de ustundedir.
MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 1000
# 60 hatali satirin tamamini govdeye dizmek yaniti okunamaz kilar; ilk 50 hata
# kullaniciya dosyayi duzeltmeye yeter, kalani ozetlenir (spec §7.8).
MAX_REPORTED_ERRORS = 50

# Spec §7.11 tablosundan BIREBIR. Ice aktarmaya ozgu metinler burada durur ki
# servis onlari ithal edebilsin; ters yon (importer → service) dongu olurdu.
IMPORT_BAD_TYPE = "Yalnızca .xlsx dosyası yüklenebilir"
IMPORT_TOO_LARGE = "Dosya çok büyük (en fazla 2 MB)"
IMPORT_TOO_MANY_ROWS = f"Dosyada en fazla {MAX_IMPORT_ROWS} satır olabilir"
IMPORT_MISSING_HEADERS = "Excel başlıkları eksik: {fields}"
IMPORT_ROW_ERRORS = "Dosya işlenemedi, {count} satırda hata var"

_XLSX_SUFFIX = ".xlsx"
_MONEY = Decimal("0.01")

# Turkce `İ/ı` TUZAGI: `"İ".lower()` iki karakter uretir (`i` + U+0307 birlesik
# nokta), dolayisiyla ham `.lower()` ile "LİSTE FİYATI" hicbir zaman "liste
# fiyatı"na esitlenmez ve baslik eslestirmesi SESSIZCE basarisiz olur. Tum `i`
# turevleri TEK harfe katlanir; boylede ASCII yazan ("LISTE FIYATI") kullanici da
# ayni anahtara duser.
_LETTER_FOLD = str.maketrans({"İ": "i", "I": "i", "ı": "i", "i": "i"})


def normalize_header(raw: object) -> str:
    """Baslik/sozluk anahtari normalizasyonu: `İ/ı` katlama + kucultme + bosluk sadelestirme."""
    text = "" if raw is None else str(raw)
    return re.sub(r"\s+", " ", text.translate(_LETTER_FOLD).lower()).strip()


@dataclass(frozen=True)
class ImportColumn:
    label: str  # Kullaniciya gosterilen Turkce baslik (mockup etiketiyle birebir)
    field: str
    required: bool


# Spec §7.8 sutun tablosu — A `Blok` … I `Pay`. Sira DEGISTIRILEMEZ: eksik
# baslik mesaji bu sirayla uretilir.
COLUMNS: tuple[ImportColumn, ...] = (
    ImportColumn("Blok", "block_name", True),
    ImportColumn("Ünite No", "unit_no", True),
    ImportColumn("Tür", "unit_kind", True),
    ImportColumn("Tip", "layout", False),
    ImportColumn("Brüt m²", "gross_area_m2", False),
    ImportColumn("Net m²", "net_area_m2", False),
    ImportColumn("Liste Fiyatı", "list_price", False),
    ImportColumn("Rayiç Değer", "appraisal_value", False),
    ImportColumn("Pay", "owner_side", False),
)

_DECIMAL_FIELDS = ("gross_area_m2", "net_area_m2", "list_price", "appraisal_value")

_KIND_BY_LABEL = {
    normalize_header("Daire"): UnitKind.apartment,
    normalize_header("Dükkan"): UnitKind.shop,
}
_OWNER_SIDE_BY_LABEL = {
    normalize_header("BİZ"): UnitOwnerSide.contractor,
    normalize_header("ARSA"): UnitOwnerSide.landowner,
}

_KIND_CHOICES = "Daire, Dükkan"
_OWNER_SIDE_CHOICES = "BİZ, ARSA"


@dataclass(frozen=True)
class ImportRow:
    """Cozumlenmis TEK satir. Excel satir numarasi (`row`) korunur: hata raporu
    kullaniciyi dosyadaki satira gonderebilmelidir (baslik = 1, veri 2'den baslar)."""

    row: int
    block_name: str
    unit_no: str
    unit_kind: UnitKind
    layout: str | None
    gross_area_m2: Decimal | None
    net_area_m2: Decimal | None
    list_price: Decimal | None
    appraisal_value: Decimal | None
    owner_side: UnitOwnerSide | None


@dataclass(frozen=True)
class RowError:
    """`UnitImportRowError` semasinin saf karsiligi — importer Pydantic'e bagimli degildir."""

    row: int
    column: str | None
    message: str


class ImportFileError(Exception):
    """Dosyanin TAMAMINI reddeden hata (tip, boyut, satir sayisi, eksik baslik).

    Satir bazli hatalardan ayridir: bunlar `errors` listesi uretmez, dosya hic
    islenmez.
    """


def parse_kind(raw: object) -> UnitKind:
    kind = _KIND_BY_LABEL.get(normalize_header(raw))
    if kind is None:
        raise ValueError(f"Tür tanınmıyor ({_KIND_CHOICES})")
    return kind


def parse_owner_side(raw: object) -> UnitOwnerSide | None:
    """Bos hucre `None` doner: pay noterden SONRA girilir (KKP 78, spec §5.3)."""
    key = normalize_header(raw)
    if not key:
        return None
    side = _OWNER_SIDE_BY_LABEL.get(key)
    if side is None:
        raise ValueError(f"Pay tanınmıyor ({_OWNER_SIDE_CHOICES})")
    return side


def _text(raw: object) -> str:
    """Excel sayisal hucresi metin alanina duserse (`Ünite No` = 12) `12.0` OLMAZ."""
    if raw is None:
        return ""
    if isinstance(raw, float) and raw.is_integer():
        return str(int(raw))
    return str(raw).strip()


def parse_decimal(raw: object, label: str) -> Decimal | None:
    """Turkce sayi yazimi desteklenir: `1.234,56` → `1234.56`.

    Excel sayisal hucreleri zaten `int`/`float` gelir; metin hucreleri kullanicinin
    elle yazdigi hâldedir ve binlik/ondalik ayraci Turkce klavyede ters yerlestirilir.
    `float` ARA DEGERI KULLANILMAZ — para ve alan sutunlari `Decimal`'dir.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, bool):
        raise ValueError(f"{label} sayıya çevrilemedi")
    text = str(raw).strip().replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        value = Decimal(text)
    except (DecimalException, ValueError) as exc:
        raise ValueError(f"{label} sayıya çevrilemedi") from exc
    if value < 0:
        raise ValueError(f"{label} negatif olamaz")
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def ensure_xlsx(filename: str | None) -> None:
    """`.xls` / `.csv` REDDEDILIR (spec §7.8): `openpyxl` yalniz `.xlsx` okur ve
    yanlis tipe anlamsiz bir cozumleme hatasi vermek yerine acik mesaj verilir."""
    if not (filename or "").lower().endswith(_XLSX_SUFFIX):
        raise ImportFileError(IMPORT_BAD_TYPE)


def ensure_size(size: int | None) -> None:
    """Boyut IKI KEZ kontrol edilir (plan B9): akis basinda istemcinin bildirdigi
    uzunlukla, sonra GERCEKTEN okunan `bytes` uzunluguyla. Istemci basligina
    guvenilmez; `None` gelmesi kontrolu atlatmaz, yalnizca ikinci kontrole birakir."""
    if size is not None and size > MAX_IMPORT_BYTES:
        raise ImportFileError(IMPORT_TOO_LARGE)


def _header_index(sheet) -> dict[str, int]:
    """Ilk satir basliktir. Beklenmeyen ek sutunlar YOK SAYILIR (spec §7.8)."""
    header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), None) or ()
    positions = {normalize_header(cell): index for index, cell in enumerate(header_row)}
    index = {
        column.field: positions[normalize_header(column.label)]
        for column in COLUMNS
        if normalize_header(column.label) in positions
    }
    missing = [column.label for column in COLUMNS if column.required and column.field not in index]
    if missing:
        raise ImportFileError(IMPORT_MISSING_HEADERS.format(fields=", ".join(missing)))
    return index


def _cell(row: tuple, index: dict[str, int], field: str) -> object:
    position = index.get(field)
    if position is None or position >= len(row):
        return None
    return row[position]


def _parse_row(
    number: int, row: tuple, index: dict[str, int]
) -> tuple[ImportRow | None, list[RowError]]:
    """Bir satirin TUM hatalari toplanir — ilk hatada durulmaz.

    Kullanici 48 satirlik bir dosyayi hata basina bir kez yuklemek zorunda
    kalmamalidir (spec §7.8 gerekcesi).
    """
    errors: list[RowError] = []
    values: dict[str, object] = {}

    for column in (COLUMNS[0], COLUMNS[1], COLUMNS[3]):  # Blok, Ünite No, Tip
        text = _text(_cell(row, index, column.field))
        if column.required and not text:
            errors.append(RowError(number, column.label, f"{column.label} boş olamaz"))
        values[column.field] = text or None

    try:
        values["unit_kind"] = parse_kind(_cell(row, index, "unit_kind"))
    except ValueError as exc:
        errors.append(RowError(number, "Tür", str(exc)))

    for field in _DECIMAL_FIELDS:
        label = next(column.label for column in COLUMNS if column.field == field)
        try:
            values[field] = parse_decimal(_cell(row, index, field), label)
        except ValueError as exc:
            errors.append(RowError(number, label, str(exc)))

    try:
        values["owner_side"] = parse_owner_side(_cell(row, index, "owner_side"))
    except ValueError as exc:
        errors.append(RowError(number, "Pay", str(exc)))

    if errors:
        return None, errors
    return (
        ImportRow(
            row=number,
            block_name=str(values["block_name"]),
            unit_no=str(values["unit_no"]),
            unit_kind=values["unit_kind"],  # type: ignore[arg-type]
            layout=values["layout"],  # type: ignore[arg-type]
            gross_area_m2=values["gross_area_m2"],  # type: ignore[arg-type]
            net_area_m2=values["net_area_m2"],  # type: ignore[arg-type]
            list_price=values["list_price"],  # type: ignore[arg-type]
            appraisal_value=values["appraisal_value"],  # type: ignore[arg-type]
            owner_side=values["owner_side"],  # type: ignore[arg-type]
        ),
        [],
    )


def _duplicate_errors(rows: list[ImportRow]) -> list[RowError]:
    """Dosya ICINDE ayni `(Blok, Ünite No)` ikilisi — DB'ye hic gitmeden yakalanir.

    Hata IKINCI satira yazilir: kullanicinin silmesi gereken satir odur.
    """
    seen: set[tuple[str, str]] = set()
    errors: list[RowError] = []
    for parsed in rows:
        # Blok adi NORMALLESTIRILEREK eslesir (servis de blogu boyle bulur), ama
        # `unit_no` HARFI HARFINE karsilastirilir: `uq_units_block_no` tam
        # esitliktir, "A1" ile "a1" DB'de iki ayri unitedir.
        key = (normalize_header(parsed.block_name), parsed.unit_no)
        if key in seen:
            errors.append(
                RowError(parsed.row, "Ünite No", "Bu ünite numarası dosyada birden çok kez var")
            )
        seen.add(key)
    return errors


def parse_units_file(content: bytes) -> tuple[list[ImportRow], list[RowError]]:
    """`bytes` → cozumlenmis satirlar + satir bazli hatalar.

    Dosyanin tamamini reddeden durumlar `ImportFileError` firlatir; satir bazli
    hatalar DONDURULUR, cunku cagiran onlari DB kaynakli hatalarla BIRLESTIRIP
    tek raporda sunar (hep-ya-hic + satir bazli rapor, spec §7.8).
    """
    if len(content) > MAX_IMPORT_BYTES:
        raise ImportFileError(IMPORT_TOO_LARGE)
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl cesitli istisna tipleri firlatir
        raise ImportFileError(IMPORT_BAD_TYPE) from exc
    try:
        sheet = workbook.active
        index = _header_index(sheet)
        rows: list[ImportRow] = []
        errors: list[RowError] = []
        processed = 0
        # Satir numarasi Excel'in kendi numarasidir: baslik 1, veri 2'den baslar.
        for number, raw in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if all(cell is None or str(cell).strip() == "" for cell in raw):
                continue  # Tamamen bos satir (Excel'in kuyruk satirlari) sessizce atlanir
            processed += 1
            # Sinir OKUMA SIRASINDA uygulanir: 1001. satirda durulur, once tum
            # dosyayi bellege alip sonra saymak sinirin amacini bozardi.
            if processed > MAX_IMPORT_ROWS:
                raise ImportFileError(IMPORT_TOO_MANY_ROWS)
            parsed, row_errors = _parse_row(number, raw, index)
            if parsed is not None:
                rows.append(parsed)
            errors.extend(row_errors)
    finally:
        # `read_only` modunda acik kalan dosya tanitici birakilmaz.
        workbook.close()
    return rows, [*errors, *_duplicate_errors(rows)]
