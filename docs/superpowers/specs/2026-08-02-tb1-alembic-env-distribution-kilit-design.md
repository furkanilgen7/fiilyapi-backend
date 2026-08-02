# TB1 — Teknik Borç: alembic/env.py model importları + dağıtım ucu kilidi (spec)

Tarih: 2026-08-02 · Durum: **ONAYLI** · Dal: `chore/alembic-env-borcu` (main'den; P6 dalına dokunulmaz)
Davranış değişikliği YOK; migration üretilMEZ. Kaynak borçlar: `ROADMAP-BACKEND.md §3` satır 1 ve
"P5'ten devreden 4 bulgu" içindeki FOR UPDATE maddesi.

## 1. Sorun A — `alembic/env.py` model import eksiği
`env.py` yalnız bazı modüllerin models.py'sini import ediyor; `boq_*` ve `progress_payment_*` tabloları
`Base.metadata`'ya girmiyor → `alembic check` sahte "tablo silinecek" diff'i üretiyor, autogenerate riskli.

**Çözüm:** `env.py`'de TÜM modüllerin `models` modüllerini kapsayan kalıcı import bloğu
(`app.modules.*.models` açıkça listelenir; "yeni modülde buraya da ekle" yorumu konur).
**Kabul:** yerel DB'de (`DATABASE_URL` override) HEAD'e upgrade sonrası `alembic check` ÇIKTISI TEMİZ.
Migration dosyası ÜRETİLMEZ; temizlik bunun kanıtıdır. Not: main'de HEAD `c3d4e5f6a7b8`
(P6 merge edilmedi) — check o HEAD'e karşı koşulur, P6 dalı beklenmez.

## 2. Sorun B — dağıtım ucunda eşzamanlılık kilidi yok (P5 bulgusu)
`PUT /projects/{id}/contract/distribution` (`contracts/distribution.py::save_distribution`) satır
kilidi almadan okuyup yazıyor → iki eşzamanlı istek kota/miktar doğrulamasını yarışla aşabilir (TOCTOU).

**Çözüm:** hakediş deseni örnek alınır (`progress_payments/repository.py::get_contract_locked` —
`SELECT … FOR UPDATE`): dağıtım yazımı başlamadan ilgili sözleşme kalemi/BOQ satır kümesi kilitlenir.
**Kabul:** yarış testi (kilitsiz halde aşım üretebilen eşzamanlı senaryo, kilitli halde 422/doğru sıra).
API sözleşmesi, şemalar, yanıtlar DEĞİŞMEZ.

## 3. Kapsam DIŞI
`Base`'e `naming_convention` (riskli, ayrı dilim) · P5'in diğer 3 bulgusu (karar gerektirir) ·
her türlü migration · P6 dalındaki kod.
