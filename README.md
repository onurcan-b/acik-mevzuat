# Açık Mevzuat

Türkiye'deki **kanunları resmî kaynaktan otomatik alan, makine tarafından okunabilir biçimde saklayan ve değişiklikleri Git geçmişiyle izleyen** açık veri deposu.

Veri kaynağı Adalet Bakanlığı'nın mevzuat servisidir. Depo resmî bir hukuk yayını değildir; doğrulama gereken durumlarda her zaman resmî kaynağa başvurulmalıdır.

## Nasıl çalışıyor?

Her gün GitHub Actions otomatik olarak:

1. Adalet Bakanlığı mevzuat API'sinden yürürlükteki (`KANUN`) ve mülga (`MULGA`) kanunların tamamını listeler.
2. Her kanunun güncel tam metnini indirir.
3. Metni kararlı bir metin/Markdown biçimine normalize eder.
4. SHA-256 özeti hesaplar.
5. Yalnızca resmî kaynaktaki içerik veya metadata gerçekten değişmişse dosyayı değiştirir.
6. Değişiklik varsa otomatik Git commit'i oluşturup `main` branch'ine gönderir.

Böylece bir kanunun geçmiş sürümleri ayrıca kopyalanmaz; **Git history zaten sürüm arşividir**.

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

`indeks.json`, depodaki otomatik senkronize edilen bütün dokümanların makine tarafından kolayca tüketilebilen listesidir.

## Günlük otomasyon

Workflow:

```text
.github/workflows/daily-sync.yml
```

Zamanlanmış çalışma her gün otomatik tetiklenir. Ayrıca GitHub arayüzünden `workflow_dispatch` ile manuel olarak da başlatılabilir.

Workflow doğrudan `main` branch'ine veri commit'i atabilmek için yalnızca:

```yaml
permissions:
  contents: write
```

yetkisini kullanır. Ek API anahtarı veya secret gerekmez.

## Yerelde çalıştırma

```bash
python -m pip install -r requirements.txt
python betikler/senkronize.py
python betikler/dogrula.py
```

Varsayılan senkronizasyon:

```bash
python betikler/senkronize.py --types KANUN,MULGA
```

Diğer mevzuat türleri de aynı altyapıyla desteklenir:

```bash
python betikler/senkronize.py --types KANUN,KHK,CB_KARARNAME,TUZUK
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

Bu sayede "bu kanunun metni ne zaman değişti?" sorusu doğrudan Git üzerinden incelenebilir.

## Doğrulama

Her push ve pull request'te:

- metadata JSON Schema doğrulaması,
- senkronizasyon yardımcı fonksiyonlarının unit testleri

otomatik çalışır.

```bash
python -m unittest discover -s tests -v
python betikler/dogrula.py
```

## Katkı

Kod, parser ve veri modeli katkıları pull request ile yapılabilir. Otomatik üretilen kanun metinlerinin elle düzenlenmesi önerilmez; bir veri sorunu varsa senkronizasyon/parsing katmanı düzeltilmelidir.

Ayrıntılar için `CONTRIBUTING.md` dosyasına bakın.

## Lisans

Bu depo, özgün proje kodu ile resmî kanun metinlerini ayrı değerlendirir.

- `betikler/`, `semalar/` ve `.github/` altındaki özgün kod, şema ve otomasyon dosyaları MIT lisansı altındadır. Bkz. `LICENSE-CODE`.
- `kanunlar/` altındaki resmî metinler için depo telif hakkı iddia etmez. Bkz. `LICENSE` ve `NOTICE.md`.
