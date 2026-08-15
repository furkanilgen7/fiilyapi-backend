# TB5 — Yerel Takvim Borç Paketi (backend) · tasarım spec'i

Tarih: 2026-08-15 · Yönetim oturumu · Repo: `backend/` · base `main` @ `dd16da6`

---

## 1. Kusur — ÜRETİMDE, PARA YÜZEYİNDE, KANITLI

`date.today()` **sunucunun yerel saatini** okur; Railway'de bu **UTC**'dir. Türkiye UTC+3
olduğu için **her gün 21:00–24:00 arasında `date.today()` DÜNÜ döndürür.**

**Kanıt (yönetim `main` @ `4942885`'te bizzat koştu, 2026-08-15 00:2x TSİ / 21:2x UTC):**
```
tests/sales/test_installments.py::test_plan_uretimi_mockup_ornegini_birebir_uretir
assert satirlar[0]["due_date"] == date.today().isoformat()
AssertionError: assert '2026-08-14' == '2026-08-15'
```
Yani **saat 21:00'den sonra açılan bir satışta peşinat vadesi "dün" yazılır** ve kayıt
doğduğu anda **gecikmiş** görünür. Aynı sınıf; hakediş dönemi, puantaj günü, belge geçerliliği,
izin bakiyesi, sipariş tarihi ve **yıl bazlı numara üreticileri** için de geçerlidir.

🔴 **Kusur GÖRÜNMEZDİR:** pencere yalnız akşam 21:00–24:00'te açıktır. Gündüz koşulan her test
yeşildir. Bu yüzden "testler yeşil" bu kusuru **hiç** kapatmaz.

## 2. Doğru araç ZATEN VAR — kullanılmamış

`app/core/timezone.py` bu işi tam olarak yapar ve docstring'i kusuru **kelimesi kelimesine** anlatır:

```python
def today() -> date:
    """... `date.today()` sunucunun yerel saatini (Railway'de UTC) kullanir; TR gecesi ..."""
    return datetime.now(DISPLAY_TIMEZONE).date()

def day_start_utc(day: date) -> datetime: ...
def day_end_utc(day: date)   -> datetime: ...
def to_display(value: datetime) -> datetime: ...
```

`DISPLAY_TIMEZONE` `settings.display_timezone`tan gelir (`Europe/Istanbul`), `zoneinfo` ile —
sabit `+03:00` ofset **varsayılmaz**, DST doğru çevrilir.

**Emsal (doğru yapılmış iki yer):** `invoicing/summary.py` (FAT-1) ve `treasury/cash_flow.py`
(HZ-1) — ikisi de ay penceresini `DISPLAY_TIMEZONE`de kurar. Yani desen kanıtlı, yayılmamış.

## 3. Kapsam

**34 çağrı yeri** (`grep -rn "date\.today()\|datetime\.utcnow()" app/` — yorum satırları hariç).
Modüller: `sales` · `procurement` · `invoicing` · `equipment` · `personnel`.

### K1 — HER çağrı yeri ÜÇ sınıftan birine ayrılır, körlemesine değiştirilmez

| Sınıf | Ne yapılır | Örnek |
|---|---|---|
| **A. İş takvimi** — kullanıcıya görünen bir gün/ay üretir ya da bir tarihle karşılaştırılır | `timezone.today()`ye çevrilir | vade, "gecikmiş mi", ay penceresi, belge geçerliliği |
| **B. Numara üreticisi** — `…-YYYY-NNNN` yıl bileşeni | `timezone.today().year` | `procurement/numbering.py:77` · `invoicing/numbering.py:75` |
| **C. Teknik/denetim damgası** — kullanıcı takvimi değil, olay anı | **DOKUNULMAZ**, gerekçesi yazılır | `created_at` server default, audit `occurred_at` |

🔴 **Her çağrı yeri için verdict ve gerekçe raporlanır.** "Hepsini değiştirdim" YETMEZ —
C sınıfını değiştirmek `timestamptz` semantiğini bozar.

### K2 — Enjeksiyon deseni KORUNUR
Repoda zaten yerleşik ve DOĞRU olan bir desen var: saf çekirdek `today`yi **parametre olarak**
alır, `date.today()`yi yalnız uç/servis sınırı çağırır (`sales/service.py:245` · `plan.py:114` ·
`personnel/leave.py:83` · `equipment/document_service.py:136` bunu açıkça belgeliyor).
**Bu desen BOZULMAZ** — yalnız sınırdaki çağrı `timezone.today()` olur. Saf çekirdeğe
`timezone` import ettirmek testleri saate bağımlı kılardı.

## 4. 🔴 BEKÇİ — dilimin ASIL teslimatı

Düzeltmenin kendisi mekaniktir; **nüksü engelleyen bekçi kalıcı değerdir.**

`tests/test_local_calendar_guard.py`:
- `app/` altındaki **her** `.py` AST ile taranır; `date.today()` ve `datetime.utcnow()`
  çağrıları bulunur.
- İzin verilen tek yer: `app/core/timezone.py`.
- C sınıfı istisnalar **açık bir listede**, her biri **tek satır gerekçeyle**.
- 🔴 **MUTASYON KANITI ZORUNLU:** bir dosyaya `date.today()` geri konunca bekçi **KIRMIZI**
  olmalı; kanıt raporda. (2026-08-14 dersi: frontend'in BFF bekçisinin tek iddiası
  `length > 0`'dı — hiçbir şeyi yakalamıyordu. **"Test var" ≠ "test bekçilik ediyor".**)
- Bekçi **AST tabanlıdır**, düz metin grep DEĞİL — `# date.today()` yorumu ya da bir dizedeki
  metin bekçiyi tetiklememeli, gerçek çağrı ise kaçmamalı.

## 5. 🔴 REGRESYON TESTİ — pencere ZORLA açılır

Kusur günün yalnız 3 saatinde görünür; **testi o saate bırakmak kabul edilemez.**
Her düzeltilen A/B sınıfı davranış için, sistem saati **TR gecesine sabitlenerek** test yazılır:
`DISPLAY_TIMEZONE`de 22:30 olan bir ana denk gelen UTC anı enjekte edilir (ör. `freezegun` yoksa
`timezone.today`in okuduğu `datetime.now` monkeypatch'lenir) ve **doğru günün** üretildiği
doğrulanır. **Sabit `sleep`/gerçek saate bağımlılık YASAK.**

En az şu üçü açıkça testlenir:
1. `sales` peşinat vadesi (kanıtlanmış kusur — **RED→GREEN**)
2. bir numara üreticisi (yıl sınırı: 31 Aralık 22:00 TSİ → **doğru yıl**, bir önceki değil)
3. bir "gecikmiş mi" karşılaştırması

## 6. Kapsam dışı
- **Frontend**: denetlendi, bu sınıf **YOK** — `isoDate` yerel bileşenlerle yazılmış ve
  `toISOString()` kullanmama gerekçesi yorumda yazılı. Frontend dilimi AÇILMAZ.
- `created_at`/`updated_at` server default'ları (C sınıfı).
- Kullanıcıya `DISPLAY_TIMEZONE` seçtirmek — tek şirketli ERP, `settings`te tek değer.

## 7. Kararlar
| # | Karar | Gerekçe |
|---|---|---|
| K1 | Üç sınıflı ayrım, her çağrı yerine verdict | C'yi değiştirmek `timestamptz`i bozar |
| K2 | Enjeksiyon deseni korunur, yalnız sınır çağrısı değişir | saf çekirdek saate bağımlı olmamalı |
| K3 | Bekçi **AST tabanlı** + mutasyon kanıtlı | grep yorum/dizeye takılır; kanıtsız bekçi sahtedir |
| K4 | Regresyon **saat enjekte ederek** yazılır | kusur günün 3 saatinde görünür, şansa bırakılamaz |
| K5 | Şema/migration **YOK** | yalnız okuma anındaki takvim düzeltiliyor; kayıtlı tarihler değişmez |
