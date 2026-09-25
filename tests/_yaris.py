"""Eşzamanlılık (yarış) testlerinin ORTAK zaman tavanı — FIX-B3.

Tavan bir BEKLEME DEĞİLDİR: test yalnız bir şey ASILI kalırsa bu kadar bekler; normal
koşuda görev/olay çok daha önce tamamlanır. Bu yüzden geniş tutmak bekçiyi ZAYIFLATMAZ
(kilit alınmazsa ya da sıra bozulursa iddia yine düşer), yalnız yavaş makinede SAHTE
KIRMIZIYI önler. Dar tavanın (5 sn) CI yükünde yetmediği ölçüldü: MU-3A bariyeri
(EXPORT-XLSX turu) ve FIX-B3 (#130).

"Hâlâ bloke mi?" iddiaları (TimeoutError = başarı) bu sabiti KULLANMAZ — onlar kısa
kalmalıdır (`_BLOKE_TAVANI`), yoksa her koşu tavan kadar uzar.
"""

YARIS_TAVANI_SN = 30.0
