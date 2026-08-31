"""Hesap planı iş kuralları (MU-1 T3a) — liste · oluştur · detay · PATCH · DELETE.

Spec: `docs/superpowers/specs/2026-08-15-mu1-muhasebe-cekirdegi-design.md` §7, §11.

## 🔴 Bu dosyanın YAZMADIĞI üç şey

1. **Bakiye.** Hiçbir toplam burada hesaplanmaz; tek kaynak `balance.py`dir (K3)
   ve bu modül yalnızca çıktısını YANITA taşır. İkinci bir formül açılsaydı liste
   ile detay aynı hesap için farklı sayı basar ve bakiye SAKLANMADIĞI için hiçbir
   kolon farkı ele vermezdi.
2. **Kod dilbilgisi.** Ebeveyn/çocuk/sınıf/düzey `codes.py`den okunur; burada
   `code[:2]` gibi bir dilimleme YOKTUR.
3. **Yetki.** Üç kapı (`view`/`full`/`admin`) router'dadır (`require_permission`);
   burada `if actor.role …` YOKTUR.

## 🔴 KAPSAM SÜZGECİ YOKTUR (IDOR unutulmuş DEĞİLDİR)

Hesap planı ŞİRKET GENELİDİR: tabloda proje/şantiye FK'sı yoktur, HP'nin beş
sütununda hiçbir alan şantiye göstermez (spec §3). `suppliers`/`stock_items`
emsali — erişimi `accounting` izin modülü denetler. Bu yüzden `visible_projects`
çağrısı YOKTUR ve "görünmeyen kayıt" hâli de yoktur: 404 yalnız var OLMAYAN
kimlik içindir.

## Hangi kural hangi koda düşer

| Durum | Kod | Sınıf |
|---|---|---|
| Var olmayan hesap | 404 | `NotFoundError` |
| Biçim ihlali (kod deseni, uzunluk, `limit` tavanı, türev alan) | 422 | Pydantic |
| Aynı hesap kodu | 409 | `DuplicateError` |
| Satırlı hesapta `code` değişimi · satırlı ebeveynin altına çocuk (K-Ş3) | 409 | `ConflictError` |
| Fiş satırı ya da alt hesabı olan hesabın silinmesi | 409 | `RelatedRecordsExistError` |

Son üç satır SERVİSTE, DB'ye düşmeden önce yakalanır: düşselerdi kullanıcı ya
ham bir 500 ya da `IntegrityError` handler'ının ayrımsız "Veri bütünlüğü hatası"
409'unu alırdı. ⚠️ Üstelik FK/UNIQUE ihlallerinin SQLSTATE davranışına dayanmak
PG sürümleri arasında (yerel 18 / CI 16) güvenli değildir. DB kısıtları SON
savunma olarak yerinde KALIR.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, DuplicateError, NotFoundError, RelatedRecordsExistError
from app.modules.accounting import balance as balance_module
from app.modules.accounting import codes, guards, repository
from app.modules.accounting.models import ChartAccount, ChartAccountType
from app.modules.accounting.schemas import (
    ChartAccountCreate,
    ChartAccountListResponse,
    ChartAccountResponse,
    ChartAccountUpdate,
)
from app.modules.audit import messages

__all__ = [
    "create_account",
    "delete_account",
    "get_account_response",
    "is_leaf_account",
    "list_accounts",
    "update_account",
]


async def is_leaf_account(session: AsyncSession, account: ChartAccount) -> bool:
    """🔴 §4c YAPRAK KURALININ TEK KAYNAĞI: hesabın çocuğu var mı?

    Fiş satırı YALNIZCA çocuğu olmayan hesaba kesilir. Kanıt: E8'in altı satırının
    HEPSİ en derin biçimdedir (`NNN.NN`) ve HP'nin grup satırları (HP:72,97,115)
    Tür/Bakiye sütunlarını hiç basmaz. Gerekçe: üst hesabın bakiyesi
    çocuklarınınkinin toplamıdır; hem üste hem alta kayıt atılırsa MU-2'nin mizanı
    ÇİFT SAYAR.

    İki kullanıcısı vardır ve ikisi de buradan okur:
    * **T3a** — DELETE'in "alt hesabı var" 409'u (aşağıda);
    * **T3b** — `validation.balance_blockers`ın üçüncü engeli (fiş satırı yalnız
      yaprak hesaba, **422**).

    Ayrı ayrı yazılsalardı biri torunları (`12` → `120.01`) kapsamayı unutur ve
    yaprak tanımı iki yerde ayrışırdı.
    """
    return not await repository.has_child_accounts(session, account.code)


async def _account_or_404(
    session: AsyncSession, account_id: uuid.UUID, *, for_update: bool = False
) -> ChartAccount:
    account = await repository.get_account(session, account_id, for_update=for_update)
    if account is None:
        raise NotFoundError(guards.ACCOUNT_MISSING)
    return account


async def _balance_of(session: AsyncSession, account_id: uuid.UUID) -> Decimal:
    """Tekil bakiye — TEK KAYNAK `balance.balances_for` (K3).

    Fonksiyon yalnız VAR OLAN hesapla çağrılır ve her hesap için satır döner
    (satırsız hesapta `COALESCE` devrededir), dolayısıyla anahtar her zaman vardır.
    """
    return (await balance_module.balances_for(session, [account_id]))[account_id]


async def _assert_code_free(
    session: AsyncSession, code: str, *, exclude_id: uuid.UUID | None = None
) -> None:
    """409 — aynı kod iki kez açılsaydı yevmiye satırları iki karta bölünür ve
    bakiye (K3) ikiye ayrılırdı. UQ yarış durumu emniyet ağı olarak KALIR."""
    if await repository.code_exists(session, code, exclude_id=exclude_id):
        raise DuplicateError(guards.ACCOUNT_DUPLICATE_CODE)


async def _assert_parent_has_no_lines(session: AsyncSession, code: str) -> None:
    """🔴 K-Ş3 (§11) — YAPRAK KURALININ TERS YÖNÜ.

    Fiş satırı OLAN bir hesabın altına çocuk açmak **409**dur: yoksa `120`e satır
    atıp sonra `120.01` açmak yaprak kuralını GEÇMİŞE DÖNÜK deler ve MU-2 mizanı
    üst hesabın bakiyesini çift sayardı.

    İki erken çıkış vardır ve ikisi de meşrudur:
    * grubun ebeveyni YOKTUR (sınıf bir kayıt değildir, `parent_code` → `None`);
    * ebeveynin KAYDI olmayabilir — `e5f6a7b8c9d0` (MU-SEED) NN grubunu ve NNN
      ana hesabını tohumlar ama `NNN.NN` alt hesap YAZMAZ (K2); üstelik
      kullanıcı ana hesabı silmiş ya da hiç migrate etmemiş olabilir (R14).
      Kayıt yoksa satırı da yoktur.

    Yalnız BİR düzey yukarı bakılır: iki düzey yukarıdaki bir hesabın satırı
    varsa zaten arada duran çocuk açılırken bu kapı ısırmıştır.
    """
    ebeveyn_kodu = codes.parent_code(code)
    if ebeveyn_kodu is None:
        return
    ebeveyn = await repository.get_account_by_code(session, ebeveyn_kodu)
    if ebeveyn is None:
        return
    if await repository.count_journal_lines_for_account(session, ebeveyn.id):
        raise ConflictError(guards.PARENT_HAS_JOURNAL_LINES)


# --- Uç 1: liste ---


async def list_accounts(
    session: AsyncSession,
    *,
    q: str | None,
    account_type: ChartAccountType | None,
    is_active: bool | None,
    limit: int | None,
    offset: int,
) -> ChartAccountListResponse:
    """HP:58-62 tablosunun veri kaynağı — her satır TÜRETİLMİŞ bakiye taşır.

    Sorgu sayısı hesap sayısından BAĞIMSIZDIR (satırlar + sayım): bakiye,
    satırlarla AYNI `Select` içinde türetilir (`test_liste_N_ARTI_1_YAPMAZ`).

    `total` süzgeçle AYNI yardımcıdan geçer; ayrışsaydı pasif hesaplar "sayfa
    dışında kalmış" gibi görünürdü.

    🔴 **`limit=None` → SAYFALAMA YOK** (`audit.repository` emsali): eşleşen tüm
    hesaplar döner. Liste ucu bunu ASLA göndermez (orada `limit` hâlâ `int` ve
    tavanı 200'dür, aşımı **422**); tek çağıranı `export.xlsx` ucudur ve Excel
    ile ekran AYNI süzgeç/sıralama/bakiye kaynağından beslensin diye ikinci bir
    sorgu yolu açılmaz.
    """
    satirlar = await repository.list_accounts_with_balance(
        session, q=q, account_type=account_type, is_active=is_active, limit=limit, offset=offset
    )
    total = await repository.count_accounts(
        session, q=q, account_type=account_type, is_active=is_active
    )
    return ChartAccountListResponse(
        items=[ChartAccountResponse.from_row(account, bakiye) for account, bakiye in satirlar],
        total=total,
        # 🔴 `limit=None` (Excel ucu) zarfa `total` olarak yazılır ve bu bir
        # KIRPMA DEĞİLDİR: hiçbir sınır uygulanmadığında uygulanabilecek en
        # küçük doğru sınır kümenin kendi büyüklüğüdür, yani `items` tam
        # olduğunda `limit == total` doğrudur. Alanın kendisi `int | None`a
        # genişletilmedi çünkü `ChartAccountListResponse` bu dilimin dosya
        # sınırı DIŞINDADIR (`schemas.py`) ve nullable bir `limit` liste ucunun
        # yayımlanmış sözleşmesini değiştirirdi. Dosya ucu zarfın sayfalama
        # alanlarını zaten OKUMAZ; yalnız `items` kullanılır.
        limit=total if limit is None else limit,
        offset=offset,
    )


# --- Uç 3: detay ---


async def get_account_response(
    session: AsyncSession, account_id: uuid.UUID
) -> ChartAccountResponse:
    """Tek hesap; bakiye liste ucuyla AYNI kaynaktan gelir (K3)."""
    account = await _account_or_404(session, account_id)
    return ChartAccountResponse.from_row(account, await _balance_of(session, account.id))


# --- Uç 2: oluştur ---


async def create_account(
    session: AsyncSession, data: ChartAccountCreate
) -> tuple[ChartAccount, str]:
    """Doğrulamaların HEPSİ yazımdan ÖNCEDİR (`create_account` HZ-1 deseni).

    Sıra bilinçlidir: önce tekillik (**409**, R16), sonra K-Ş3 (**409**). Kod
    biçimi zaten ŞEMADA (aynı desenle) reddedilmiştir; DB CHECK'i son savunmadır.

    `is_active` gövdeden gelir çünkü kullanımdan kaldırma yolu odur.
    """
    kod = data.code
    await _assert_code_free(session, kod)
    await _assert_parent_has_no_lines(session, kod)

    account = ChartAccount(
        code=kod,
        name=data.name.strip(),
        account_type=data.account_type,
        is_active=data.is_active,
        # 🔑 MT-1/KK-1 — kontra bayrağı gövdeden gelir; varsayılanı `False`tur.
        is_contra=data.is_contra,
    )
    session.add(account)
    await session.flush()
    await session.refresh(account)
    return account, messages.chart_account_created(account.code, account.name)


# --- Uç 4: PATCH ---


async def update_account(
    session: AsyncSession, account_id: uuid.UUID, data: ChartAccountUpdate
) -> tuple[ChartAccount, str]:
    """Kısmi güncelleme; kayıt DENETİMLERDEN ÖNCE kilitlenir (TOCTOU).

    `exclude_unset` ŞARTTIR: gönderilmeyen alan ile gönderilen alan AYNI şey
    değildir. Onsuz, yalnız adı düzelten bir istek kaydın türünü ve durumunu
    SESSİZCE ezerdi. Dört kolonun hiçbiri nullable olmadığı için açıkça `null`
    göndermek bir TEMİZLEME değildir ve "değişmedi" sayılır.

    🔴 `code` kapısı DEĞİŞİME bakar, gönderilmiş olmaya değil: aynı kodu geri
    göndermek serbesttir (form kodu taşır), farklı bir koda geçmek ise yalnız
    hiç fiş satırı olmayan hesapta mümkündür — aksi hâlde tüm geçmiş yevmiye
    sessizce kayardı (satırlar `account_id` ile bağlıdır ama defter KODU basar).
    Yeni kod ayrıca tekillik ve K-Ş3 kapılarından geçer.

    `updated_at` sunucu damgasıdır (`onupdate=func.now()`) ve UPDATE'ten sonra
    ORM'deki değer BAYATTIR; async bağlamda tembel yükleme `MissingGreenlet`
    = **500** demektir (P11 dersi). Açık `refresh` bu pencereyi kapatır.
    """
    account = await _account_or_404(session, account_id, for_update=True)
    verilen = data.model_dump(exclude_unset=True)

    yeni_kod = verilen.get("code")
    if yeni_kod is not None and yeni_kod != account.code:
        if await repository.count_journal_lines_for_account(session, account.id):
            raise ConflictError(guards.ACCOUNT_CODE_LOCKED)
        await _assert_code_free(session, yeni_kod, exclude_id=account.id)
        await _assert_parent_has_no_lines(session, yeni_kod)
        account.code = yeni_kod

    if verilen.get("name") is not None:
        account.name = verilen["name"].strip()
    if verilen.get("account_type") is not None:
        account.account_type = verilen["account_type"]
    if verilen.get("is_active") is not None:
        account.is_active = verilen["is_active"]
    # 🔑 MT-1/KK-1: kontra bayrağı da düzeltilebilir olmalıdır — bir hesap
    # yanlışlıkla kontra işaretlenirse bilanço kalemi 2× tutar kayar ve geri
    # dönüş yolu yalnız buradan geçer.
    if verilen.get("is_contra") is not None:
        account.is_contra = verilen["is_contra"]

    await session.flush()
    await session.refresh(account)
    return account, messages.chart_account_updated(account.code, account.name)


# --- Uç 5: DELETE ---


async def delete_account(session: AsyncSession, account_id: uuid.UUID) -> str:
    """YALNIZ `admin` (kapı router'da) + fiş satırı ve alt hesabı OLMAYAN hesap.

    🔴 İki sayım FK ihlaline / sessiz kopmaya DÜŞMEDEN önce koşar:
    * fiş satırı — `journal_lines.account_id` RESTRICT'tir; düşseydi kullanıcıya
      ya ham bir 500 ya da ayrımsız "Veri bütünlüğü hatası" giderdi. CASCADE'e
      KAYILMAZ: hesabın silinmesi yevmiye satırlarını yok eder ve türetilmiş
      bakiye (K3) **kaydığı fark edilmeden** kayardı.
    * alt hesap — hiyerarşi kodun içinde taşındığı için (K4) DB'de FK YOKTUR;
      ebeveyn silinseydi `120.01` sahipsiz kalır ve zincir sessizce kopardı.

    Sıra bilinçlidir: mali iz (fiş satırı) önce sorulur, çünkü kullanıcının
    öğrenmesi gereken ilk şey odur. Kaldırma yolu `PATCH is_active=false`tur.

    Denetim metni silmeden ÖNCE kurulur; sonra kurulsaydı kod ve ad güvenilir
    okunamaz ve silinenin NE OLDUĞU kaybolurdu.
    """
    account = await _account_or_404(session, account_id, for_update=True)
    if await repository.count_journal_lines_for_account(session, account.id):
        raise RelatedRecordsExistError(guards.ACCOUNT_HAS_JOURNAL_LINES)
    if not await is_leaf_account(session, account):
        raise RelatedRecordsExistError(guards.ACCOUNT_HAS_CHILDREN)
    detail = messages.chart_account_deleted(account.code, account.name)
    await session.delete(account)
    await session.flush()
    return detail
