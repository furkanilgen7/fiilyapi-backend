"""TB9 T1 — `accounting_periods` **DELETE YOLU** bekçisi (üç ayrı kusur sınıfı).

## Neden bu dosya var

`periods_service.lock_period` iki ifadeden oluşur (UPSERT-SONRA-KİLİTLE):

    1. INSERT … ON CONFLICT (year, month) DO NOTHING
    2. SELECT … WHERE year=? AND month=? FOR UPDATE

İkisinin arasında satır ORTADAN KALKARSA 2. ifadenin `scalar_one()`ı hiçbir şey
bulamaz ve ayrımsız bir **500** (`NoResultFound`) doğar.

🔴 **Bu deliğin TEK gerçek tetikleyicisi satırın DELETE edilmesidir** — ve
`accounting_periods` için bugün bir DELETE yolu YOKTUR. Yani bugünkü
güvenliğimiz bir KOD ÖZELLİĞİ değil bir **YOKLUK**tur. Yokluklar sessizce
dolar: bir gün "dönem kaydını temizleyelim" diyen bir uç, bir bakım betiği ya da
`ON DELETE CASCADE` taşıyan bir yabancı anahtar eklenir ve `lock_period`
kırılganlaşır — hiçbir test kırmızıya dönmeden. Bu dosya tam o YOKLUĞU
bekçiler. `lock_period`in KODUNA DOKUNULMADI: düzeltilecek bir kusur yok,
korunacak bir ön koşul var.

## Ölçülen davranış (T0 turu · **yerel PG 18.4** · ham `asyncpg` + `pg_stat_activity` tanığı)

`ON CONFLICT DO NOTHING`in yaygın olarak sanılan *"çatışan satırı ne kilitler ne
döndürür, kaybeden BOŞ ELLER döner"* hâli **bu delikte doğmaz**:

* Çatışan tuple **in-progress** ise ifade `Lock/transactionid` üzerinde **BEKLER**
  (bekleme `pg_stat_activity.wait_event` ile görüldü).
* Kazanan **abort ederse** ifade kendiliğinden INSERT yoluna döner: kaybeden
  satırı KENDİSİ yazar (`INSERT 0 1`).
* Kazanan **commit ederse** `INSERT 0 0` olur ve ardından gelen
  `SELECT … FOR UPDATE` satırı **BULUR**.

Yani *"kaybeden boş eller döner → `NoResultFound`"* hâli **HİÇ DOĞMAZ**. 8
eşzamanlı işçiyle, rollback/commit karışık 600 gerçek `lock_period` çağrısında
**sıfır** hata ölçüldü.

🔴 **Canlının Postgres sürümü AYRICA DOĞRULANMADI** — yukarıdaki ölçüm yerel
PG 18.4 üzerindedir.

## Neden ÜÇ AYRI TEST (birleştirilmedi)

Üç kusur sınıfı birbirini MASKELER (`IK3-RATE-FIX` kanonu: *"atladı mı? /
bağırdı mı? AYRI testlerle çakılır"*). Tek testte toplansaydı, HTTP ucu
eklendiğinde kırmızıya dönen tek satır hangi katmanın kırıldığını söylemez ve
ilk `assert`ten sonra kalan iki ölçüm HİÇ KOŞMAZDI:

1. **UÇ** — `accounting_periods` yüzeyinde `DELETE` metodlu rota yok (FastAPI'nin
   KENDİ rota tablosundan ölçülür; elle yazılmış bir yol listesi bayatlardı).
2. **SERVİS** — `app/` altında `AccountingPeriod` satırını silen çağrı yok
   (AST ile; kapsamı `_delete_ihlalleri` docstring'inde DÜRÜSTÇE yazılıdır).
3. **ŞEMA** — `accounting_periods`e bakan yabancı anahtar yok; ileride biri
   eklenirse `ON DELETE CASCADE`/`SET NULL`/`SET DEFAULT` OLAMAZ. Ölçüm
   `pg_constraint`ten yapılır, kaynak kodundan DEĞİL.
"""

import ast
import re
from pathlib import Path

from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app

#: Taranan ağaç. `alembic/` KAPSAM DIŞIDIR: migration'lar şemayı kurar, çalışma
#: zamanında `lock_period` ile yarışmaz. Şema tarafını 3. test ölçer.
APP_DIZINI = Path(__file__).parents[3] / "app"

TABLO = "accounting_periods"
MODEL_ADI = "AccountingPeriod"

#: Dönem satırı DÖNDÜREN yardımcılar — dönüşleri `session.delete()`e verilirse
#: bu, `AccountingPeriod` adı hiç geçmeden bir silme yolu olurdu.
DONEM_DONDUREN = frozenset({"lock_period"})

#: Ham SQL metin sabiti. Yalnız LİTERAL biçimi görür (f-string/birleştirme DEĞİL).
_HAM_SQL = re.compile(rf"delete\s+from\s+(public\.)?\"?{TABLO}\"?", re.IGNORECASE)

#: `pg_constraint.confdeltype` → satırı SESSİZCE yok eden `ON DELETE` kuralları.
#: `a` (NO ACTION) ve `r` (RESTRICT) burada YOKTUR: ikisi de silmeyi ENGELLER.
#:
#: 🔴 Sorgu `confdeltype`ı `text`e ÇEVİRİR ve bu bir süs değildir (mutasyonla
#: ölçüldü): kolon PG'nin `"char"` tipindedir ve `asyncpg` onu **`bytes`**
#: olarak döndürür (`b"c"`). Çevrilmeden karşılaştırılınca `b"c" in
#: YIKICI_ON_DELETE` DAİMA yanlış olur — yani yıkıcı-kural iddiası ölü koddur
#: ve `ON DELETE CASCADE` taşıyan bir FK'yi HİÇ görmez. İlk uygulamada tam bu
#: oldu: cascade mutasyonu testi kırmızıya çevirdi ama YANLIŞ iddiadan
#: ("bugün sıfır FK"), doğru olandan değil.
YIKICI_ON_DELETE = {"c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}


# --------------------------------------------------------------------------- #
# 1 — UÇ
# --------------------------------------------------------------------------- #


def _kayitli_rotalar() -> list[APIRoute]:
    """Uygulamanın TÜM `APIRoute`ları.

    ⚠️ `app.routes` düz listesi YETMEZ (HZ-1 dersi): bu FastAPI sürümü
    `include_router`ı tembel bir `_IncludedRouter` sarmalayıcısı olarak tutar ve
    düz listede yalnız doğrudan dekoratörle tanımlanmış yollar görünür.
    Sarmalayıcı açılmasaydı bekçi HER ZAMAN yeşil kalırdı — yani hiçbir şey
    ölçmeden "DELETE ucu yok" derdi (SAHTE YEŞİL).
    """

    def gez(rotalar: list) -> list[APIRoute]:
        toplanan: list[APIRoute] = []
        for rota in rotalar:
            if isinstance(rota, APIRoute):
                toplanan.append(rota)
            elif type(rota).__name__ == "_IncludedRouter":
                toplanan += gez(rota.original_router.routes)
        return toplanan

    return gez(app.routes)


def test_1_UC_accounting_periods_yuzeyinde_DELETE_metodlu_rota_YOK() -> None:
    """🔴 Dönem kaydını HTTP üzerinden silen bir uç YOK.

    İki ölçüt birleştirilir, çünkü tek başına ikisi de kaçırırdı:
    (a) yol `/accounting-periods` ile başlıyorsa — kök başka bir router'a
    taşınsa bile yüzeyin adı budur; (b) uç fonksiyonu `periods_router`da
    yaşıyorsa — bir gün `prefix` değişse dahi dosya aynı kalır.

    Bekçi ÖNCE rota tablosunun gerçekten dolduğunu iddia eder: `_IncludedRouter`
    sarmalayıcısı bir sürüm yükseltmesinde adını değiştirirse liste boşalır ve
    asıl iddia hiçbir şey ölçmeden geçerdi.
    """
    rotalar = _kayitli_rotalar()
    donem_yollari = [r.path for r in rotalar if r.path.startswith("/accounting-periods")]
    assert donem_yollari, (
        "rota tablosu `/accounting-periods` yolu GÖRMÜYOR — `_kayitli_rotalar` "
        "sarmalayıcıyı açamamış olabilir; bu bekçi ölçmeden yeşil kalamaz"
    )

    silenler = [
        f"{sorted(r.methods)} {r.path}  ({r.endpoint.__module__}.{r.endpoint.__name__})"
        for r in rotalar
        if "DELETE" in r.methods
        and (
            r.path.startswith("/accounting-periods")
            or r.endpoint.__module__ == "app.modules.accounting.periods_router"
        )
    ]
    assert silenler == [], (
        "accounting_periods yüzeyinde DELETE metodlu rota AÇILMIŞ: "
        f"{silenler}. `lock_period` iki ifadesi arasında satırın silinmesine "
        "karşı KORUNMASIZDIR (bkz. bu dosyanın modül docstring'i)."
    )


# --------------------------------------------------------------------------- #
# 2 — SERVİS (AST)
# --------------------------------------------------------------------------- #


def _adlar(dugum: ast.AST) -> set[str]:
    """Alt ağaçtaki TÜM `Name.id` + `Attribute.attr` kimlikleri.

    `models.AccountingPeriod` ile çıplak `AccountingPeriod` aynı kümeye düşer;
    içe aktarma biçimi iddiayı değiştirmez.
    """
    return {
        d.id if isinstance(d, ast.Name) else d.attr
        for d in ast.walk(dugum)
        if isinstance(d, ast.Name | ast.Attribute)
    }


def _silme_adlari(agac: ast.AST) -> set[str]:
    """`delete`in bu modüldeki YEREL adları — takma ad (`as`) çözülür.

    🔴 Bu ÖLÇÜLDÜ: ilk uygulama çağrının adına (`delete`) doğrudan bakıyordu ve
    `from sqlalchemy import delete as sa_delete` + `sa_delete(AccountingPeriod)`
    mutasyonunu KAÇIRDI (bekçi yeşil kaldı). İçe aktarma tablosu okunmadan bir
    ad denetimi, adı değiştiren tek satırla atlatılabilir.

    `import sqlalchemy as sa` → `sa.delete(...)` biçimi ayrıca ele alınmaz:
    orada çağrı bir `Attribute`tır ve `attr` zaten `delete`tir.
    """
    adlar = {"delete"}
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.ImportFrom):
            adlar |= {a.asname or a.name for a in dugum.names if a.name == "delete"}
    return adlar


def _donem_bagli_adlar(agac: ast.AST) -> set[str]:
    """Modül içinde `AccountingPeriod`a bağlandığı GÖRÜLEBİLEN yerel adlar.

    Dört bağlanma biçimi okunur: model adını içeren bir atama sağ tarafı ·
    `DONEM_DONDUREN` bir çağrının dönüşü · `AccountingPeriod` anotasyonlu
    parametre/değişken · böyle bir addan dönen `for` hedefi. Son biçim zincirli
    olabildiği için küme SABİT NOKTAYA kadar genişletilir.

    Küme BİLEREK geniştir (ör. `stmt = select(AccountingPeriod)` de girer):
    bir bekçide yanlış alarm, kaçırılan bir silme yolundan ucuzdur.
    """
    bagli: set[str] = set()

    def hedef_adlari(dugum: ast.AST) -> set[str]:
        return {d.id for d in ast.walk(dugum) if isinstance(d, ast.Name)}

    while True:
        onceki = set(bagli)
        for d in ast.walk(agac):
            if isinstance(d, ast.arg) and d.annotation is not None:
                if MODEL_ADI in _adlar(d.annotation):
                    bagli.add(d.arg)
            elif isinstance(d, ast.AnnAssign):
                kaynak = _adlar(d.annotation) | (_adlar(d.value) if d.value else set())
                if MODEL_ADI in kaynak or kaynak & DONEM_DONDUREN or kaynak & bagli:
                    bagli |= hedef_adlari(d.target)
            elif isinstance(d, ast.Assign):
                kaynak = _adlar(d.value)
                if MODEL_ADI in kaynak or kaynak & DONEM_DONDUREN or kaynak & bagli:
                    for hedef in d.targets:
                        bagli |= hedef_adlari(hedef)
            elif isinstance(d, ast.For | ast.AsyncFor):
                kaynak = _adlar(d.iter)
                if MODEL_ADI in kaynak or kaynak & DONEM_DONDUREN or kaynak & bagli:
                    bagli |= hedef_adlari(d.target)
        if bagli == onceki:
            return bagli


def _delete_ihlalleri(kaynak: str) -> list[str]:
    """`AccountingPeriod` satırını silen çağrılar — AST ile, düz metin grep DEĞİL.

    Grep tercih edilmedi çünkü bu depoda gerekçeler docstring'lerde yaşar ve
    `session.delete(period)` cümlesi bir AÇIKLAMA olarak da geçer (aynı gerekçe:
    `test_mt1_statement_map.py`, `test_local_calendar_guard.py`).

    ## 🔴 KAPSAM — YAKALADIKLARI

    * `delete(AccountingPeriod)` · `sa.delete(models.AccountingPeriod)` ·
      `from sqlalchemy import delete as sa_delete` ardından
      `sa_delete(AccountingPeriod)` — SQLAlchemy Core/ORM toplu silme. Çağrının
      yerel adı içe aktarma tablosundan ÇÖZÜLÜR (`_silme_adlari`).
    * `session.delete(<ad>)` — `<ad>` AYNI DOSYADA `AccountingPeriod`a bağlanmış
      görünüyorsa (bkz. `_donem_bagli_adlar`).
    * `AccountingPeriod.__table__.delete()` — model ALICI tarafındayken.
    * `"DELETE FROM accounting_periods …"` — ham SQL **metin sabiti**.

    ## 🔴 KAPSAM — YAKALAMADIKLARI (bunlar "yakalanıyor" DEĞİLDİR)

    * **Dosyalar arası ad taşıması:** `p = baska_modul.donem_getir()` ardından
      `session.delete(p)`. Dönüş türü anotasyonları İZLENMEZ; yalnız aynı
      dosyadaki bağlanmalar okunur.
    * **Dolaylı/dinamik çağrı:** `sil = session.delete; sil(p)` ·
      `getattr(session, "delete")(p)` · bir yardımcıya geçirilen `session`.
      İçe aktarma takma adları çözülür, ÇALIŞMA ZAMANI yeniden bağlamaları
      çözülmez.
    * **Parçalı ham SQL:** f-string, `+` ile birleştirme, tablo adının bir
      sabitten gelmesi.
    * **ORM ilişkisi üzerinden dolaylı silme** (`cascade="all, delete-orphan"`
      koleksiyonundan çıkarma). Bugün `AccountingPeriod`a bakan hiçbir
      `relationship` YOKTUR; bu yolu şema tarafından 3. test bekçiler.
    * **`app/` DIŞI:** migration'lar, betikler, elle koşulan SQL.
    """
    agac = ast.parse(kaynak)
    bagli = _donem_bagli_adlar(agac)
    silme_adlari = _silme_adlari(agac)
    bulunan: list[str] = []

    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.Constant) and isinstance(dugum.value, str):
            if _HAM_SQL.search(dugum.value):
                bulunan.append(f"satır {dugum.lineno}: ham SQL {dugum.value.strip()[:70]!r}")
            continue
        if not isinstance(dugum, ast.Call):
            continue

        fonksiyon = dugum.func
        if isinstance(fonksiyon, ast.Name):
            cagrilan, alici = fonksiyon.id, set()
        elif isinstance(fonksiyon, ast.Attribute):
            cagrilan, alici = fonksiyon.attr, _adlar(fonksiyon.value)
        else:
            continue
        if cagrilan not in silme_adlari:
            continue

        argumanlar: set[str] = set()
        for arguman in [*dugum.args, *(k.value for k in dugum.keywords)]:
            argumanlar |= _adlar(arguman)

        if MODEL_ADI in alici:
            sebep = f"alıcı {MODEL_ADI}"
        elif MODEL_ADI in argumanlar:
            sebep = f"argüman {MODEL_ADI}"
        elif argumanlar & bagli:
            sebep = f"argüman {MODEL_ADI}'a bağlı ad: {sorted(argumanlar & bagli)}"
        else:
            continue
        bulunan.append(f"satır {dugum.lineno}: {ast.unparse(dugum)}  ({sebep})")

    return bulunan


def test_2_SERVIS_app_altinda_AccountingPeriod_satirini_SILEN_cagri_YOK() -> None:
    """🔴 `app/` altında dönem satırını silen hiçbir çağrı YOK.

    Bekçi ÖNCE taramanın gerçekten dosya gördüğünü iddia eder: yol bir gün
    kayarsa (`parents[3]`) boş bir liste üzerinde koşan tarama hiçbir şey
    ölçmeden yeşil kalırdı — bu turda görülen SAHTE YEŞİL biçimi.
    """
    dosyalar = sorted(APP_DIZINI.rglob("*.py"))
    assert len(dosyalar) > 100, (
        f"{APP_DIZINI} altında yalnız {len(dosyalar)} dosya bulundu — tarama kökü "
        "kaymış olabilir; bu bekçi ölçmeden yeşil kalamaz"
    )

    ihlaller = {
        str(dosya.relative_to(APP_DIZINI)): bulunan
        for dosya in dosyalar
        if (bulunan := _delete_ihlalleri(dosya.read_text(encoding="utf-8")))
    }
    assert ihlaller == {}, (
        f"{MODEL_ADI} satırını silen çağrı(lar) açılmış: {ihlaller}. "
        "`lock_period`in iki ifadesi arasında satır kaybolabilir hâle gelir "
        "(bkz. bu dosyanın modül docstring'i)."
    )


# --------------------------------------------------------------------------- #
# 3 — ŞEMA (yabancı anahtar / `ON DELETE` kuralı)
# --------------------------------------------------------------------------- #


async def test_3_FK_accounting_periods_e_BAKAN_yabanci_anahtar_YOK_ve_CASCADE_OLAMAZ(
    db_session: AsyncSession,
) -> None:
    """🔴 Şemadan ölçülür — kaynak kodundan DEĞİL.

    Grep, `ForeignKey("accounting_periods.id")` yazımını görür; `ondelete`in
    migration'da sonradan değiştirilmiş olmasını GÖRMEZ. Kural nihai olarak
    `pg_constraint.confdeltype`ta yaşar, o yüzden orada okunur.

    İki iddia, iki AYRI kusur sınıfı:

    * **Bugün sıfır FK** — dolayısıyla cascade ile dolaylı silme yolu YOK.
    * **İleride biri eklenirse `ON DELETE` kuralı YIKICI olamaz.** Cascade/SET
      NULL bir dönem satırını, hiçbir muhasebe kodu "sil" demeden, KOMŞU bir
      tablodaki silmenin yan etkisi olarak yok eder — `lock_period` için bu tam
      olarak DELETE yoludur.

    Sıra bilinçlidir: yıkıcı kural varsa ÖNCE o bağırır. Zararsız (RESTRICT/NO
    ACTION) bir FK de ikinci iddiayı kırar ve bu DOĞRUDUR: yeni bir FK, bu
    bekçinin dayandığı YOKLUĞU değiştirir ve elle YENİDEN OKUNMALIDIR.
    """
    satirlar = (
        await db_session.execute(
            text(
                """
                SELECT c.conname,
                       CAST(CAST(c.conrelid AS regclass) AS text) AS kaynak_tablo,
                       CAST(c.confdeltype AS text) AS confdeltype
                FROM pg_constraint AS c
                WHERE c.contype = 'f'
                  AND c.confrelid = CAST(:tablo AS regclass)
                ORDER BY c.conname
                """
            ),
            {"tablo": TABLO},
        )
    ).all()

    yikicilar = [
        f"{ad} ({kaynak} → {TABLO}) ON DELETE {YIKICI_ON_DELETE[kural]}"
        for ad, kaynak, kural in satirlar
        if kural in YIKICI_ON_DELETE
    ]
    assert yikicilar == [], (
        f"{TABLO} YIKICI bir ON DELETE kuralıyla hedeflenmiş: {yikicilar}. "
        "Dönem satırı komşu bir silmenin yan etkisi olarak yok olabilir; "
        "`lock_period` iki ifadesi arasında KORUNMASIZ kalır."
    )
    assert satirlar == [], (
        f"{TABLO}e bakan YENİ yabancı anahtar(lar) eklenmiş: "
        f"{[(ad, kaynak, kural) for ad, kaynak, kural in satirlar]}. "
        "Bu bekçi 'dönem satırına bakan hiçbir FK yok' YOKLUĞUNA dayanıyordu; "
        "silme yolunun hâlâ kapalı olduğu ELLE yeniden okunmalıdır."
    )
