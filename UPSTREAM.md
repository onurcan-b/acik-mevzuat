# Upstream veri akışı

Açık Mevzuat'ın günlük corpus senkronizasyonu, GitHub Actions üzerinde resmi mevzuat servislerinin zaman zaman rate-limit veya connection timeout üretmesi nedeniyle taşıma/fallback katmanı olarak [OpenMevzuat](https://github.com/openmevzuat/openmevzuat) projesinin güncel canonical snapshot'ını kullanır.

Akış:

1. OpenMevzuat resmi kamu kaynaklarından güncel mevzuat snapshot'ını üretir.
2. Açık Mevzuat günlük workflow'u upstream repoyu shallow-clone eder.
3. `betikler/upstream_senkronize.py`, canonical kanun ve Anayasa metinlerini bu reponun `ustveri.json + metin.md` formatına dönüştürür.
4. Yalnızca gerçek dosya değişiklikleri otomatik PR'a girer; kontroller geçince bot PR'ı kendisi merge eder.
5. Her veri commit'i upstream commit SHA'sını `.openmevzuat-upstream.json` ve `indeks.json` içinde kaydeder.

Nihai ve bağlayıcı hukuki kaynak OpenMevzuat veya bu repo değil; ilgili resmi kamu kaynağıdır. Üretilen her `ustveri.json` dosyasında mümkün olduğunda resmi PDF URL'si tutulur.

OpenMevzuat kaynak kodu AGPL-3.0-only lisanslıdır. Bu repo OpenMevzuat kaynak kodunu kopyalamaz veya çalıştırmaz; günlük snapshot'taki resmi hukuk metinlerini ve kaynak metadata'sını dönüştürür. OpenMevzuat'ın proje-özel metadata/normalizasyon çıktılarının yeniden kullanımında upstream lisans ve veri notları ayrıca dikkate alınmalıdır.
