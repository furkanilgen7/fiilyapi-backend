"""Ünite "hangi tarafta" yüklemi — kat karşılığı paylaşımının TEK kopyası.

## Neden ayrı bir modül

`owner_side` üzerinden yapılan üç yönlü ayrım (BİZ · ARSA · henüz atanmamış)
bu dosya açılmadan ÖNCE **üç ayrı yerde** elle yazılıydı:

1. `land_share.get_summary` — `land-share/summary` ucunun `our_side` /
   `owner_side` / `unassigned` bölümleri,
2. `costs.our_share_value` — KK 121 "BİZİM PAY" değer toplamı,
3. E4 proje kartının taraf sayaçları (`our_unit_count` / `owner_unit_count`).

Üçü de AYNI projeyi AYNI soruyla sorgular. Tek bir kopyada yapılacak bir kayma
— örneğin atanmamış üniteyi "bizim" saymak, ya da `is` yerine `==` ile enum'u
dizgeyle karşılaştırmak — kart ile özet ucunun AYNI PROJE hakkında FARKLI sayı
söylemesi demekti; üstelik her uç kendi kopyasına göre doğru kaldığı için hiçbir
davranış testi çelişkiyi yakalayamazdı. Yüklem bu yüzden burada TEK kopyadır ve
yapısal bir bekçi (`test_taraf_yuklemi_TEK_dosyada_yasar_kopyalanmaz`) kopyanın
geri gelmesini engeller.

## Neden SAF ve YAPRAK

`units/summary.py` ve `land_share_balance.py` ile aynı gerekçe: bu modül oturum,
yetki, şema ve para bilmez — modül düzeyindeki tek bağı `units.models`tir ve o da
yalnız `app.core.db`ye bağlı bir yapraktır. Böylece `cost_cards` (modül düzeyi
bağları YAPRAKLA sınırlı) ve `costs` bu modülü gecikmeli import'a başvurmadan
çağırabilir, çember kapanmaz.

## Üç küme AYRIKTIR ve toplamları TÜM ünitedir

`owner_side IS NULL` bir üçüncü taraf DEĞİL, "noter paylaşımı henüz yapılmadı"
hâlidir: ne bizim paya ne arsa payına sayılır. Bu yüzden `len(ours) + len(owner)`
toplam ünite sayısına EŞİT DEĞİLDİR ve olması da beklenmez — atanmamış ünitenin
görünürlüğü `land-share/summary` ucunun `unassigned` bölümünde durur.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.units.models import Unit, UnitOwnerSide


def is_ours(unit: Unit) -> bool:
    """KKP 90 "Sahip" sütununda `BIZ` (yüklenici payı)."""
    return unit.owner_side is UnitOwnerSide.contractor


def is_owner(unit: Unit) -> bool:
    """KKP 90 "Sahip" sütununda `ARSA` (arsa sahibi payı)."""
    return unit.owner_side is UnitOwnerSide.landowner


def is_unassigned(unit: Unit) -> bool:
    """Taraf henüz ATANMAMIŞ. Saklanan bir üçüncü durum değil, `NULL`ın kendisidir."""
    return unit.owner_side is None


@dataclass(frozen=True)
class UnitSides:
    """Bir projenin ünitelerinin üç AYRIK kümesi (bkz. modül notu).

    Donuk ve yeni listeler taşır: çağıran kümeyi değiştirse bile kaynak
    koleksiyona dokunmaz (kart hesabının "ORM nesnesini DEĞİŞTİRMEZ" kuralı).
    """

    ours: list[Unit]
    owner: list[Unit]
    unassigned: list[Unit]


def partition(units: Sequence[Unit]) -> UnitSides:
    """Üniteleri TEK geçişte üç kümeye ayırır.

    Üç ayrı list comprehension yerine tek döngü: ayrımın hepsi burada olduğu için
    kümeler arasındaki "ayrık ve tüketici" ilişkisi de tek yerde okunur.
    """
    ours: list[Unit] = []
    owner: list[Unit] = []
    unassigned: list[Unit] = []
    for unit in units:
        if is_ours(unit):
            ours.append(unit)
        elif is_owner(unit):
            owner.append(unit)
        else:
            unassigned.append(unit)
    return UnitSides(ours=ours, owner=owner, unassigned=unassigned)


def ours(units: Sequence[Unit]) -> list[Unit]:
    """Yalnız BİZİM PAY üniteleri — üç kümenin hepsine ihtiyacı olmayan çağıran için."""
    return [unit for unit in units if is_ours(unit)]
