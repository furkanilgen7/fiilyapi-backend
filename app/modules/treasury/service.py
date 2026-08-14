"""Banka hesabı iş kuralları (HZ-1 T3) — liste · oluştur · detay · PATCH · DELETE.

Spec: `docs/superpowers/specs/2026-08-14-hz1-hazine-cekirdegi-design.md` §2.1, §4.

## 🔴 Bu dosyanın YAZMADIĞI iki şey

1. **Bakiye.** Hiçbir toplam burada hesaplanmaz; tek kaynak `balance.py`dir
   (K2) ve bu modül yalnızca çıktısını YANITA taşır. İkinci bir formül açılsaydı
   liste ile detay aynı hesap için farklı sayı basar ve bakiye SAKLANMADIĞI
   için hiçbir kolon farkı ele vermezdi.
2. **Yetki.** Üç kapı (`view`/`full`/`admin`) router'dadır (`require_permission`);
   burada `if actor.role …` YOKTUR.

## 🔴 K3 — KAPSAM SÜZGECİ YOKTUR (IDOR unutulmuş DEĞİLDİR)

Hesap ŞİRKET GENELİDİR: tabloda proje/şantiye FK'sı yoktur, E9'da hiçbir alan
şantiye göstermez. `suppliers`/`customers` emsali — erişimi `treasury` izin
modülü denetler. Bu yüzden `visible_projects` çağrısı YOKTUR ve "görünmeyen
kayıt" hâli de yoktur: 404 yalnız var OLMAYAN kimlik içindir.

## Hangi kural hangi koda düşer

| Durum | Kod | Sınıf |
|---|---|---|
| Var olmayan hesap | 404 | `NotFoundError` |
| Biçim ihlali (uzunluk, ölçek, `limit` tavanı, bilinmeyen alan) | 422 | Pydantic |
| Kasa'da ad zorunluluğu (birleşik değerler üzerinde) | 422 | `TreasuryValidationError` |
| Aynı IBAN | 409 | `DuplicateError` |
| Ödemesi olan hesabın silinmesi | 409 | `RelatedRecordsExistError` |

Son iki satır SERVİSTE, DB'ye düşmeden önce yakalanır: DB'ye düşselerdi
kullanıcı ya ham bir 500 ya da `IntegrityError` handler'ının ayrımsız
"Veri bütünlüğü hatası" 409'unu alırdı. ⚠️ Üstelik FK/UNIQUE ihlallerinin
SQLSTATE davranışına dayanmak PG sürümleri arasında (yerel 18 / CI 16) güvenli
değildir. DB kısıtları SON savunma olarak yerinde KALIR.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    DuplicateError,
    NotFoundError,
    RelatedRecordsExistError,
    TreasuryValidationError,
)
from app.modules.audit import messages
from app.modules.treasury import balance as balance_module
from app.modules.treasury import repository
from app.modules.treasury.models import BankAccount, BankAccountType
from app.modules.treasury.schemas import (
    BankAccountCreate,
    BankAccountListResponse,
    BankAccountResponse,
    BankAccountUpdate,
    normalize_iban,
)

__all__ = [
    "PERMISSION_MODULE",
    "create_account",
    "delete_account",
    "get_account_response",
    "list_accounts",
    "update_account",
]

PERMISSION_MODULE = "treasury"
"""İzin anahtarı — seed'de ZATEN vardı ("Hazine", grup MALI, `sort_order: 14`,
`roles/seed_data.py:103`). 🔴 **Yeni izin modülü AÇILMAZ, matris satırına
DOKUNULMAZ, izin migration'ı YOKTUR.**

Matris satırı `"treasury": [_A, _F, _N, _N, _N, _F, _V, _N]`, yani kapılar:
* okuma (`view`)  → PM · muhasebe · patron · sysadmin
* yazma (`full`)  → muhasebe · patron · sysadmin (**PM yazamaz**)
* silme (`admin`) → YALNIZ sysadmin — `full` silmeyi KAPSAMAZ (repo kanonu)
"""

# 404 — var olmayan hesap. K3 gereği "görünmeyen hesap" hâli YOKTUR; hesap
# şirket geneli olduğu için izni olan herkes hepsini görür.
ACCOUNT_MISSING = "Banka hesabı bulunamadı"

# 422 — `ck_bank_accounts_cash_has_name` servis katmanında ÖNCE yakalanır. Kasa
# satırında IBAN yoktur (E9:83) ve ad da boş kalırsa kart TAMAMEN isimsiz
# görünürdü.
CASH_NEEDS_DISPLAY_NAME = "Kasa hesabı için görünen ad zorunludur"

# 409 — `uq_bank_accounts_iban` (kısmi, `WHERE iban IS NOT NULL`). Servis
# IntegrityError'a düşmeden ÖNCE açık bir SELECT ile bunu fırlatır ki kullanıcı
# alanına özel Türkçe mesaj alsın; UQ yarış durumu emniyet ağı olarak KALIR.
IBAN_DUPLICATE = "Bu IBAN başka bir hesapta kayıtlı"

# 409 — ödemesi olan hesap silinemez (FK RESTRICT'in servis karşılığı).
# Kullanımdan kaldırma yolu `is_active=false`tur (repo kanonu).
ACCOUNT_HAS_PAYMENTS = "Bu hesaba bağlı ödeme kayıtları var; hesap silinemez"


def _assert_cash_has_name(account_type: BankAccountType, display_name: str | None) -> None:
    """🔴 Kural BİRLEŞİK değerler üzerinde koşar (`CustomerValidationError` deseni).

    PATCH kısmi gövde gönderir: kullanıcı yalnız `account_type: cash` yollasa
    bile kayıttaki `display_name` NULL olabilir ve kasa adsız kalırdı. Bu yüzden
    denetim ÇAĞIRANIN birleştirdiği değerler üzerindedir, şemada değil.
    """
    if account_type is BankAccountType.cash and not (display_name or "").strip():
        raise TreasuryValidationError(CASH_NEEDS_DISPLAY_NAME)


async def _assert_iban_free(
    session: AsyncSession, iban: str | None, *, exclude_id: uuid.UUID | None = None
) -> None:
    """NULL IBAN hiç sorgulanmaz: kısmi indeks onları çoklanabilir bırakır ve
    burada aransaydı İKİNCİ kasa hesabı hiç açılamazdı (E9:83)."""
    if iban is None:
        return
    if await repository.iban_exists(session, iban, exclude_id=exclude_id):
        raise DuplicateError(IBAN_DUPLICATE)


def _clean(deger: str | None) -> str | None:
    """Kenar boşlukları atılır; boşa dönen metin NULL'dır.

    Boş metin saklansaydı kısmi indeks `display_name` için önemsiz olurdu ama
    `ck_bank_accounts_cash_has_name` CHECK'i "NOT NULL" gördüğü için GEÇERDİ:
    isimsiz bir kasa DB'ye girerdi.
    """
    if deger is None:
        return None
    temiz = deger.strip()
    return temiz or None


async def _account_or_404(
    session: AsyncSession, account_id: uuid.UUID, *, for_update: bool = False
) -> BankAccount:
    account = await repository.get_account(session, account_id, for_update=for_update)
    if account is None:
        raise NotFoundError(ACCOUNT_MISSING)
    return account


async def _balance_of(session: AsyncSession, account_id: uuid.UUID) -> Decimal:
    """Tekil bakiye — TEK KAYNAK `balance.balances_for` (K2).

    Sözlükte bulunmayan kimlik `ZERO`ya düşmez, `opening_balance`a da: fonksiyon
    yalnız VAR OLAN hesapla çağrılır ve her hesap için satır döner (ödemesiz
    hesapta `coalesce` devrededir).
    """
    return (await balance_module.balances_for(session, [account_id]))[account_id]


# --- Uç 1: liste ---


async def list_accounts(
    session: AsyncSession, *, is_active: bool | None, limit: int, offset: int
) -> BankAccountListResponse:
    """E9:70-84 kart şeridinin veri kaynağı — her satır TÜRETİLMİŞ bakiye taşır.

    Sorgu sayısı hesap sayısından BAĞIMSIZDIR (satırlar + sayım): bakiye,
    satırlarla AYNI `Select` içinde türetilir.

    `total` süzgeçle AYNI yardımcıdan geçer; ayrışsaydı pasif hesaplar "sayfa
    dışında kalmış" gibi görünürdü.
    """
    satirlar = await repository.list_accounts_with_balance(
        session, is_active=is_active, limit=limit, offset=offset
    )
    total = await repository.count_accounts(session, is_active=is_active)
    return BankAccountListResponse(
        items=[BankAccountResponse.from_row(account, bakiye) for account, bakiye in satirlar],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- Uç 3: detay ---


async def get_account_response(session: AsyncSession, account_id: uuid.UUID) -> BankAccountResponse:
    """Tekil kart; bakiye liste ucuyla AYNI kaynaktan gelir (K2)."""
    account = await _account_or_404(session, account_id)
    return BankAccountResponse.from_row(account, await _balance_of(session, account.id))


# --- Uç 2: oluştur ---


async def create_account(session: AsyncSession, data: BankAccountCreate) -> tuple[BankAccount, str]:
    """Doğrulamaların HEPSİ yazımdan ÖNCEDİR (`create_invoice` deseni).

    Sıra bilinçlidir: önce gövde kuralı (Kasa'da ad, **422**), sonra tekillik
    (**409**). Ters olsaydı adsız bir kasa için kullanıcı önce IBAN hatası
    alabilirdi.

    `opening_balance` SAKLANAN TEK para alanıdır; bakiye ondan TÜRETİLİR.
    """
    iban = normalize_iban(data.iban)
    display_name = _clean(data.display_name)
    _assert_cash_has_name(data.account_type, display_name)
    await _assert_iban_free(session, iban)

    account = BankAccount(
        bank_name=data.bank_name.strip(),
        account_type=data.account_type,
        iban=iban,
        display_name=display_name,
        opening_balance=data.opening_balance,
        is_active=data.is_active,
    )
    session.add(account)
    await session.flush()
    await session.refresh(account)
    return account, messages.bank_account_created(account.bank_name, account.display_name)


# --- Uç 4: PATCH ---


async def update_account(
    session: AsyncSession, account_id: uuid.UUID, data: BankAccountUpdate
) -> tuple[BankAccount, str]:
    """Kısmi güncelleme — kurallar BİRLEŞİK değerler üzerinde koşar.

    Kayıt DENETİMLERDEN ÖNCE kilitlenir (TOCTOU): kilit ile karar arasına başka
    bir işlem giremesin.

    `exclude_unset` ŞARTTIR: gönderilmeyen alan ile açıkça `null` gönderilen
    alan AYNI şey değildir. Onsuz, yalnız `bank_name` düzelten bir istek kaydın
    IBAN'ını ve görünen adını SESSİZCE silerdi.

    `updated_at` sunucu damgasıdır (`onupdate=func.now()`) ve UPDATE'ten sonra
    ORM'deki değer BAYATTIR; async bağlamda tembel yükleme `MissingGreenlet`
    = **500** demektir (P11 dersi). Açık `refresh` bu pencereyi kapatır.
    """
    account = await _account_or_404(session, account_id, for_update=True)
    verilen = data.model_dump(exclude_unset=True)

    account_type = verilen.get("account_type", account.account_type)
    display_name = (
        _clean(verilen["display_name"]) if "display_name" in verilen else account.display_name
    )
    iban = normalize_iban(verilen["iban"]) if "iban" in verilen else account.iban

    _assert_cash_has_name(account_type, display_name)
    await _assert_iban_free(session, iban, exclude_id=account.id)

    account.account_type = account_type
    account.display_name = display_name
    account.iban = iban
    if "bank_name" in verilen:
        account.bank_name = verilen["bank_name"].strip()
    if "opening_balance" in verilen and verilen["opening_balance"] is not None:
        account.opening_balance = verilen["opening_balance"]
    if "is_active" in verilen and verilen["is_active"] is not None:
        account.is_active = verilen["is_active"]

    await session.flush()
    await session.refresh(account)
    return account, messages.bank_account_updated(account.bank_name, account.display_name)


# --- Uç 5: DELETE ---


async def delete_account(session: AsyncSession, account_id: uuid.UUID) -> str:
    """YALNIZ `admin` (kapı router'da) + ödemesi OLMAYAN hesap.

    🔴 Ödeme sayımı FK ihlaline DÜŞMEDEN önce koşar: düşseydi kullanıcıya ya ham
    bir 500 ya da ayrımsız "Veri bütünlüğü hatası" giderdi. CASCADE'e de
    KAYILMAZ — bir hesabın silinmesi tahsilat geçmişini yok eder ve türetilmiş
    bakiye (K2) sessizce kayardı.

    Denetim metni silmeden ÖNCE kurulur; sonra kurulsaydı ad güvenilir okunamaz
    ve silinenin NE OLDUĞU kaybolurdu.
    """
    account = await _account_or_404(session, account_id, for_update=True)
    if await repository.count_payments_for_account(session, account.id):
        raise RelatedRecordsExistError(ACCOUNT_HAS_PAYMENTS)
    detail = messages.bank_account_deleted(account.bank_name, account.display_name)
    await session.delete(account)
    await session.flush()
    return detail
