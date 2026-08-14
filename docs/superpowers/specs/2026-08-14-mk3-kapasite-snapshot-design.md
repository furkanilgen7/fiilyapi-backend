# MK-3 — Kira hakedişinde kalan canlı okuma (kapasite snapshot'ı)

Tarih: 2026-08-14 · Repo: `backend/` · Dal: `feat/mk3-kapasite-snapshot`
Yönetim oturumu yazdı. Öncül: `2026-08-14-mk2-kira-hakedisi-design.md` (K2/K4).

---

## 1. Sorun (MK-2'nin final review'ünde bulundu, kapatılmadan devredildi)

MK-2'nin K2 kuralı şudur: **onaylanmış bir faturanın tutarı, sonradan yapılan bir düzeltmeyle
oynayamaz.** Bunun için satıra kopyalanan girdiler: `worked_hours`, `breakdown_hours`, `site_id`
ve — final review'de yakalandığı üzere — `rate_amount`.

**Kalan tek delik:** `rate_period = monthly` olan faturada saatlik bedelin **paydası**
`equipment.monthly_capacity_hours`tan **CANLI okunuyor**. Ekipman kartındaki bu değer
değiştirilirse **onaylanmış (hatta ödenmiş) bir aylık-sabit kira faturasının tutarı geriye dönük
oynar.**

Şiddeti dar ama sınıfı aynı: **bir para yüzeyi.** F-TB1'in BORÇ 1'i de dar bir yoldu ve kendi
dilimini hak etmişti; bu da öyle.

**Kalıcı ders (MK-2'den, bu dilimin gerekçesi):** *bir türev para değeri N çarpandan oluşuyorsa,
snapshot iddiası N'in HEPSİNİ kapsamalıdır — birini kaçırmak deliği kapatmış gibi gösterir.*
MK-2'de saat donduruldu, bedel unutuldu; bedel donduruldu, payda unutuldu.

---

## 2. Kapsam

`equipment_rental_invoice_lines`'a **`capacity_hours`** snapshot kolonu + çözüm yolunun oradan
okuması + **canlı okuma sınıf araması** (§4).

**Kapsam dışı:** yeni uç, yeni ekran, Bakım Takvimi (mockup yok), fatura iş kuralı değişikliği.

---

## 3. Bağlanan kararlar

**K1 — Snapshot'lanan şey GİRDİdir, türev DEĞİL.** Yeni kolon `capacity_hours`
(Integer, **nullable**) — satır kurulurken `equipment.monthly_capacity_hours`tan kopyalanır.
🔴 **Çözülmüş saatlik bedel (`hourly_rate`) KOLONLAŞTIRILMAZ**: MK-2 K4 "para tek formülden türer,
kolonlaşmaz" kuralı ayakta kalır. Formül aynı yerde (`cost.py`) durur, yalnız **girdilerini
satırdan** alır.

**K2 — Nullable ve fail-closed.** `capacity_hours` `null` ya da `0` ise `monthly` dönemde saatlik
bedel **hesaplanamaz** → `our_amount` **`null`** (MK-1 K16). Uydurma 0 BASILMAZ, varsayılan 200
**enjekte edilmez** (varsayılan ekipman tablosunun işidir, faturanın değil).

**K3 — Yalnız `monthly` dönemde anlamlı, ama HER satırda doldurulur.** Faturanın `rate_period`i
sonradan `PATCH`le değişebilir (`draft`ta serbest); değer o an yoksa geriye dönük doldurmak için
canlı okumaya dönmek gerekirdi — tam da kapattığımız şey. Kolon her satırda doldurulur, yalnız
`monthly` yolunda okunur.

**K4 — Mevcut satırlar: migration `equipment`ten DOLDURUR.** Canlıda kira hakedişi verisi
muhtemelen yoktur ama varsa `NULL` bırakmak, bugüne kadar doğru hesaplanan bir faturayı
**bir anda `null` tutara** düşürürdü. Migration `UPDATE … FROM equipment` ile doldurur;
ekipmanı silinmişse (imkânsız — RESTRICT) `NULL` kalır.

**K5 — `reload` davranışı `rate_amount`la AYNI**: değer **boşken** doldurulur, **dolu değer
EZİLMEZ** (MK-2'nin son düzeltmesindeki ilke birebir).

---

## 4. 🔴 SINIF ARAMASI (bu dilimin asıl değeri)

Bu delik iki kez arka arkaya kaçtı. Üçüncüsü olup olmadığı **aranır, varsayılmaz.**

`equipment` modülünün **para/tutar üreten her okuma yolu** taranır ve her girdi için tek soru
sorulur: **"bu değer satırdan mı, yoksa canlı bir kayıttan mı geliyor?"**

- Kapsam: `rental_service.py` · `cost.py` · `summary`/`detail` yanıt kurucuları · export varsa o da.
- Her girdi için raporda **tablo**: girdi adı → kaynağı (satır kolonu / canlı kayıt) → canlıysa
  gerekçesi ve riski.
- Bulunan yeni canlı okuma **1-2 taneyse aynı desenle kapat**; daha fazlaysa **DUR ve raporla**.

⚠️ Not: her canlı okuma kusur değildir — ekipman **adı/plakası** gibi sunum alanları canlı olmalıdır
(fatura kartın adını dondurmaz). Ayrım şudur: **tutarı etkileyen girdi** donar, **sunum** donmaz.

---

## 5. Kabul kriterleri

1. Migration: kolon + mevcut satırların doldurulması; `upgrade`/`downgrade` turu testli
   (açık revizyon id'siyle). `down_revision` = **`f9a0b1c2d3e4`** (MK-2). `alembic heads` TEK satır.
2. 🔴 **Nüks testi:** `monthly` dönemli bir fatura onaylanır → `equipment.monthly_capacity_hours`
   değiştirilir → **faturanın toplamı DEĞİŞMEZ.** Snapshot kaldırılınca bu test **KIRMIZI** olduğu
   kanıtlanır (mutasyon).
3. K2 fail-closed yolu testli (`null`/`0` kapasite → `our_amount` `null`, 0 DEĞİL).
4. K5 testli (`reload` dolu değeri ezmez).
5. §4 sınıf araması tablosu raporda.
6. TDD: önce test, KIRMIZI GÖR. `ruff check .` + `ruff format --check .` tüm repo temiz.
7. Testler yalnız yerel DB'de (`TEST_DATABASE_URL` override) — canlıya DOKUNULMAZ.
