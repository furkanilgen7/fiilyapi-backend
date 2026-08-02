"""Taşeron hakedişi korkulukları ve Türkçe hata metinleri (spec §2, §5, §6).

## Neden metinlerin çoğu İŞVEREN modülünden İMPORT ediliyor?

İki hakediş ailesi AYNI izin modülünü (`progress_payments`) ve AYNI dört durumlu
makineyi paylaşır (spec §5). Aşağıdaki dört metin iki modülde de KELİMESİ KELİMESİNE
aynı olmak zorundadır — kullanıcı aynı ekran ailesinde iki farklı cümle görmemeli.
`progress_payments/guards.py` bu metinleri iki modülün (contracts/sites) bilinçli
tekrarı gerekçesiyle kopyalamıştı; burada gerekçe TERSİDİR: bağımsız iki sözleşme
değil, TEK ekran ailesinin iki evrağı söz konusudur, bu yüzden metin TEK KOPYA
paylaşılır (plan T2: "kopya kod yazma, paylaşım tercih et").

Bu modüle ÖZGÜ kurallar (`ITEM_PRICE_REQUIRED`, `SECTION_MISMATCH`) burada tanımlanır.
"""

from app.modules.progress_payments.guards import (
    DELETE_NOT_ALLOWED,
    INVALID_STATUS_TRANSITION,
    OPEN_PAYMENT_EXISTS,
    PAYMENT_MISSING,
    PAYMENT_NOT_DELETABLE,
)

__all__ = [
    "DELETE_NOT_ALLOWED",
    "INVALID_STATUS_TRANSITION",
    "ITEM_PRICE_REQUIRED",
    "OPEN_PAYMENT_EXISTS",
    "PAYMENT_MISSING",
    "PAYMENT_NOT_DELETABLE",
    "SECTION_MISMATCH",
]

# 422 (spec §2 guard'ı): "girilmedi ≠ 0 TL" — fiyatı girilmemiş sözleşme kalemi
# hakedişe alınamaz, çünkü NULL'u 0 saymak taşerona sessizce bedelsiz iş yazardı.
ITEM_PRICE_REQUIRED = (
    "Sözleşmede birim fiyatı girilmemiş kalem var; hakediş oluşturmadan önce fiyatları girin."
)

# 422 (spec §8 S2): `section_id` bilgi alanıdır ama SAHİPSİZ olamaz — sözleşmenin
# şantiyesine (şantiye bağı yoksa projesinin herhangi bir şantiyesine) ait olmalıdır.
# Var olmayan bölüm de AYNI 422'yi alır: bölüm bir alan DEĞERİDİR, kaynak değil
# (`contracts/subcontracts.py._resolve_subcontractor_name` deseninin aynısı).
SECTION_MISMATCH = "Seçilen bölüm bu sözleşmenin şantiyesine ait değil"
