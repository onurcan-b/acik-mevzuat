# Açık Mevzuat

Türkiye'deki **kanunları resmî kaynaktan otomatik alan, makine tarafından okunabilir biçimde saklayan ve değişiklikleri Git geçmişiyle izleyen** açık veri deposu.

Veri kaynağı Adalet Bakanlığı'nın UYAP/Bedesten mevzuat servisidir. Depo resmî bir hukuk yayını değildir; hukuki doğrulama gereken durumlarda her zaman resmî kaynağa başvurulmalıdır.

## Nasıl çalışıyor?

Her gün GitHub Actions otomatik olarak:

1. yürürlükteki (`KANUN`) ve mülga (`MULGA`) kanunların resmî kataloğunun tamamını tarar,
2. katalog metadata'sı değişen kayıtları hemen yeniler,
3. eksik kayıtları kontrollü biçimde backfill eder,
4. katalog değişmese bile metin değişikliklerini yakalamak için kanun metinlerini **7 günlük dönen doğrulama kovasıyla** yeniden indirir,
5. metni kararlı Markdown biçimine normalize eder ve SHA-256 özeti hesaplar,
6. metadata ve test doğrulamalarını çalıştırır,
7. gerçek bir veri değişikliği varsa otomatik bir veri PR'ı oluşturur, squash-merge eder ve çalışma branch'ini temizler.

Böylece tüm corpus her gün gereksiz yere yeniden indirilmez; buna rağmen her kanun metni en geç yaklaşık bir hafta içinde yeniden doğrulanır. Git geçmişi, mevzuat sürümlerinin değişiklik arşividir.

## Veri yapısı

```text
kanunlar/
  5237-turk-ceza-kanunu/
    ustveri.json
    metin.md
indeks.json
```

`ustveri.json` örneği:

```json
{
  "law_number": "5237",
  "title": "Türk Ceza Kanunu",
  "slug": "5237-turk-ceza-kanunu",
  "accepted_date": "2004-09-26",
  "effective_status": "in_force",
  "official_gazette": {
    "date": "2004-10-12",
    "number": "25611"
  },
  "source_url": "https://...",
  "language": "tr",
  "tags": [],
  "source_mevzuat_id": "...",
  "source_type": "KANUN",
  "content_sha256": "...",
  "retrieval_api": "https://bedesten.adalet.gov.tr/mevzuat"
}
```

`indeks.json`, otomatik senkronize edilen dokümanların makine tarafından kolayca tüketilebilen listesidir.

## Günlük otomasyon

Ana workflow:

```text
.github/workflows/daily-sync.yml
```

Her gün:

```text
07:30 UTC
```

çalışır. GitHub Actions yoğunluk nedeniyle planlanan başlangıç saatinden birkaç dakika sapabilir. Workflow ayrıca GitHub arayüzünden `workflow_dispatch` ile manuel tetiklenebilir.

Pipeline:

```text
unit tests
  ↓
resmî katalog taraması
  ↓
katalog farkı + eksik backfill + 7 günlük metin rotasyonu
  ↓
metadata doğrulaması
  ↓
diff kontrolü
  ↓
varsa otomatik veri PR'ı
  ↓
squash merge + branch cleanup
```

Workflow yalnızca gerekli GitHub izinlerini kullanır:

```yaml
permissions:
  contents: write
  pull-requests: write
```

Ek API anahtarı veya repository secret'ı gerekmez.

## Güvenilirlik

- Bedesten istekleri retry/backoff ve timeout ile yapılır.
- GitHub-hosted runner'larda askıda kalan keep-alive bağlantılarını azaltmak için resmî API istemcisi `Connection: close` kullanır.
- Katalog beklenenden eksik dönerse çalışma başarısız olur; eksik katalog sessizce kabul edilmez.
- Her senkronizasyonda unit testler, metadata doğrulaması ve `git diff --check` çalışır.
- `main` branch'i korumalıdır; otomatik veri güncellemeleri PR üzerinden merge edilir.

## Yerelde çalıştırma

Python 3.12+ önerilir.

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python betikler/resmi_api.py --mode daily --types KANUN,MULGA --rotation-buckets 7
python betikler/dogrula.py
```

Tam senkronizasyon ve diğer mevzuat türleri için temel istemci de kullanılabilir:

```bash
python betikler/senkronize.py --types KANUN,MULGA
```

Desteklenen türler:

- `KANUN`
- `MULGA`
- `KHK`
- `CB_KARARNAME`
- `TUZUK`
- `YONETMELIK`
- `CB_YONETMELIK`
- `CB_KARAR`
- `CB_GENELGE`
- `KKY`
- `UY`
- `TEBLIGLER`

## Değişiklik geçmişini görmek

Örneğin Türk Ceza Kanunu için:

```bash
git log -- kanunlar/5237-turk-ceza-kanunu/
git diff <eski-commit> <yeni-commit> -- kanunlar/5237-turk-ceza-kanunu/metin.md
```

## Doğrulama

Her push ve pull request'te ayrı validation workflow'u da çalışır:

```text
.github/workflows/validate.yml
```

Kontroller:

```bash
python -m unittest discover -s tests -v
python betikler/dogrula.py
```

## Katkı

Kod, parser ve veri modeli katkıları pull request ile yapılabilir. Otomatik üretilen kanun metinlerinin elle düzenlenmesi yerine problemi üreten senkronizasyon/parsing katmanının düzeltilmesi tercih edilir.

Ayrıntılar için [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Lisans

Bu depo özgün proje kodu ile resmî kanun metinlerini ayrı değerlendirir.

- `betikler/`, `semalar/` ve `.github/` altındaki özgün kod, şema ve otomasyon dosyaları MIT lisansı altındadır: [`LICENSE-CODE`](LICENSE-CODE).
- `kanunlar/` altındaki resmî metinler için depo telif hakkı iddia etmez: [`LICENSE`](LICENSE) ve [`NOTICE.md`](NOTICE.md).

## Proje sahibi

**Onurcan Büyükkalkan**  
[buyukkalkan.net](https://buyukkalkan.net/)
