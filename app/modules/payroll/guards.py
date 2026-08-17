"""Bordro korkulukları ve Türkçe hata METİNLERİ (İK-3).

`personnel/guards.py` deseninin aynısı: hata SINIFLARI `app/core/errors.py`de,
metinler modül içinde TEK KOPYA sabit olarak durur — aynı kuralı iki uçtan
farklı cümleyle anlatan bir modül, kullanıcıya iki farklı kural öğretir.
"""

#: 404 — görünmeyen ile var olmayan dönem AYIRT EDİLEMEZ (spec §6.8).
PERIOD_MISSING = "Bordro dönemi bulunamadı"

#: 409 — onaylanmış/ödenmiş dönemde yeniden hesap YOKTUR (spec §5).
PERIOD_LOCKED = "Onaylanmış veya ödenmiş dönem yeniden hesaplanamaz"

#: İzin anahtarı — `payroll` seed'de İLK GÜNDEN BERİ VARDIR
#: (`roles/seed_data.py:182`, `alembic/.../a477fdf00fdf...:88`). Yeni izin
#: modülü AÇILMAZ (spec S9, ST/`inventory` emsali) ve `seed_data.py`ye
#: DOKUNULMAZ. Okuma `view`, yazma `full`.
PERMISSION_MODULE = "payroll"

#: 404 — görünmeyen ile var olmayan satır AYIRT EDİLEMEZ (spec §6.8).
LINE_MISSING = "Bordro satırı bulunamadı"

#: 409 — bir ay için TEK bordro (UQ `(year, month)`, spec §4).
PERIOD_DUPLICATE = "Bu ay için bordro dönemi zaten açılmış"

#: 409 — S5 değişmezliği: ödeme izi geriye dönük düzeltilmez.
LINE_LOCKED = "Onaylanmış veya ödenmiş bordro satırı değiştirilemez"

#: 409 — S5'in dönem tarafı: onaylanmış dönemin toplamları raporlanmıştır.
PERIOD_LOCKED_FOR_EDIT = "Onaylanmış veya ödenmiş dönemin satırları değiştirilemez"

#: 409 — K2: taşeron satırı bordrodan ÖDENMEZ, bölüşümü de düzenlenmez.
LINE_EXCLUDED = (
    "Taşeron satırı bordrodan ödenmez: tutarı ve ödeme bölüşümü düzenlenemez, "
    "ödemesi taşeron hakedişi üzerinden yapılır"
)


#: 422 — S3 invariantı. Tutarlar metne KONUR: kullanıcı hangi kuruşun kaydığını
#: ekrandaki iki `input`a bakarak bulamaz.
def split_mismatch(bank: object, cash: object, net: object) -> str:
    return f"Banka ({bank}) + elden ({cash}) toplamı net tutara ({net}) eşit olmalıdır"


#: 422 — S4: neti hesaplanmamış satırda bölüşüm TANIMSIZDIR.
SPLIT_WITHOUT_NET = "Hesaplanamamış satırda ödeme bölüşümü yapılamaz; önce brüt tutarı girin"

#: 422 — ŞEF KARARI 2 (T2): kesintisi bilinmeyen brütten net türetilmez.
RATE_MISSING = "Bu personel tipi için dönemin yılına ait aktif kesinti oranı tanımlı değil"

#: 🔴 422 — IK3-GV K3 fail-closed: `income_tax_pct IS NULL` (dilimli rejim) ama
#: o yılın gelir vergisi tarifesi ya da brüt asgari ücreti tanımlı değil.
#: `NULL` sessizce "vergi yok" DEMEK DEĞİLDİR (NULL-EŞİK kanonu): 0 vergiyle
#: hesaplanmış bir satır, kullanıcının elle girdiği brütü vergisiz ödetirdi.
TAX_BRACKETS_MISSING = (
    "Dönemin yılına ait gelir vergisi tarifesi veya brüt asgari ücret tanımlı değil: "
    "dilimli gelir vergisi hesaplanamaz"
)


# --- T4: onay + ödeme yolu -------------------------------------------------

#: 409 — S5'in dönem tarafı, KARAR yüzeyinde: onaylanmış/ödenmiş dönemin
#: satırlarının durumu da donar. PATCH ile AYNI kapı, ayrı cümle: kullanıcı
#: burada tutarı değil ONAYI değiştirmeye çalışmaktadır.
PERIOD_LOCKED_FOR_DECISION = "Onaylanmış veya ödenmiş dönemin satır onayları değiştirilemez"

#: 409 — S4 fail-closed: brütü `null` olan satırda onaylanacak bir tutar YOKTUR.
#: "Ödenecek bir şey yok" yalanı ödeme listesine damgalanmaz; doğru yol brütü
#: elle girmektir (K3 override'ı).
LINE_UNCOMPUTED = (
    "Hesaplanamamış satır onaylanamaz: önce brüt tutarı girin (personelin ücret tanımı eksik)"
)

#: 409 — geri alınacak bir onay yoksa red anlamsızdır. Kaynak durumu AÇIKÇA
#: `approved` olmalıdır: geçiş tablosundaki `uncomputed → pending` çifti K3
#: override'ının çıkışıdır ve red yolundan kullanılırsa S4 arkadan dolanılır.
LINE_NOT_APPROVED = "Yalnız onaylanmış bir satırın onayı geri alınabilir"

#: 409 — dönem onay ucunun ilerletecek adımı yok: `approved` (sıradaki adım
#: ÖDEMEDİR, onay ucundan basılmaz) ya da `paid`.
PERIOD_NOT_APPROVABLE = "Bordro dönemi onay adımına geçirilemez"

#: 409 — T4b: onaylanmış/ödenmiş dönemin ÖDEME TAKVİMİ değişmez. `paid`te
#: gerçekleşmiş bir olayın kaydını sonradan düzeltmek para izini bozardı;
#: `approved`ta ise onaylanmış bordronun takvimi tek taraflı kaymamalıdır —
#: değişmesi gerekiyorsa dönem `pending_approval`a geri alınır (S8'in zaten
#: izin verdiği yol; yeni bir yol icat EDİLMEZ).
PERIOD_LOCKED_FOR_SCHEDULE = "Onaylanmış veya ödenmiş dönemin ödeme tarihi değiştirilemez"

#: 409 — T5: SGK damgası TEKRAR BASILMAZ (idempotent DEĞİL). Damga bir OLAYIN
#: zamanıdır ve SGK 46'daki son bildirim tarihiyle karşılaştırılır; sessizce
#: yeniden yazılsaydı geç kalınmış bir bildirim ikinci bir tıklamayla zamanında
#: yapılmış gibi görünürdü — uyum izi bozulurdu.
SGK_ALREADY_SUBMITTED = "Bu dönemin SGK bildirimi zaten gönderildi olarak işaretlenmiş"

#: 🔴 409 — T5 PARA KORKULUĞU: bir yılda `approved`/`paid` dönem varsa O YILIN
#: oran setine YAZILAMAZ (ne güncelleme ne yeni tip).
#:
#: Gerekçe: K1 gereği oran satıra KOPYALANMAZ, tek gerçek kaynak `payroll_rates`
#: tablosudur; `summary.py` ve `sgk.py` işveren tarafını DÖNEMİN YILINA ait
#: CANLI setten türetir. Yazmaya izin verilseydi 2026 oranını değiştirmek
#: ONAYLANMIŞ bir 2026 döneminin raporlanmış "toplam maliyet"/"SGK işveren"
#: sayılarını ve SGK bildiriminin TAMAMINI geriye dönük değiştirirdi. Kapı
#: GÜNCELLEMEYE değil YILA kapanır: oran satırı olmayan bir tip için yeni set
#: açmak da o tipin satırlarını `unknown_cost_count`tan çıkarıp maliyete
#: eklerdi. Kural bordroyu TIKAMAZ — başka yıl serbesttir, `draft`/
#: `pending_approval` dönemli yıl serbesttir.
RATES_LOCKED_BY_PERIOD = (
    "Bu yılda onaylanmış veya ödenmiş bordro dönemi var: geçmiş hesabı değiştirmemek için "
    "yılın kesinti oranları güncellenemez"
)

#: 409 — fail-closed (NULL-EŞİK kanonu): onaylı görünse de tutarı bilinmeyen bir
#: satır ÖDENMEZ. Bilinmeyeni 0 sayıp geçmek, eksik ödemeyi banka ekstresine
#: bırakırdı.
PAID_WITHOUT_NET = "Net tutarı hesaplanmamış onaylı satır var: bordro ödenemez"
