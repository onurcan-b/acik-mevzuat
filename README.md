# Açık Mevzuat

Türkiye mevzuatını makine tarafından okunabilir, sürümlenebilir ve doğrulanabilir
JSON/Markdown formatında tutmayı amaçlayan açık veri deposu.

İlham:
- Bundestag Gesetze: https://github.com/bundestag/gesetze
- USA Constitution repo örneği: https://github.com/JesseKPhillips/USA-Constitution

## Hedefler

- Kanun metinlerini tek tip bir dizin yapısıyla saklamak
- Her kanun için zengin metadata sağlamak
- Değişiklik geçmişini git üzerinden takip etmek
- Arama, karşılaştırma ve analiz için uygun JSON/Markdown kaynakları sunmak

## Önerilen klasör yapısı

```text
kanunlar/
  4721-turk-medeni-kanunu/
    ustveri.json
    metin.md
    gecmis/
      2024-01-01.md
```

## Format yaklaşımı

Her kanun klasöründe:

1. `ustveri.json`
   - kanun numarası
   - resmi adı
   - kabul tarihi
   - yürürlük durumu
   - resmi gazete bilgisi
   - kaynak URL
2. `metin.md`
   - Madde madde düzenlenmiş metin
3. `gecmis/*.md`
   - Sürüm notları ve değişiklik açıklamaları

## İlk adım planı

1. Veri modeli üzerinde uzlaşma (`semalar/kanun.schema.json`)
2. İlk örnek kanunları ekleme
3. Doğrulama script'i (`betikler/dogrula.py`)
4. Otomatik CI doğrulama

## Katkı

Katkılar pull request ile yapılır. Yeni kanun veya metin değişikliği eklerken
resmi kaynak URL'si ve kaynağı kontrol ettiğiniz tarih belirtilmelidir.

Ayrıntılar için `CONTRIBUTING.md` dosyasına bakın.

## Lisans

Bu depo, özgün proje kodu ile resmi kanun metinlerini ayrı değerlendirir.

- `betikler/`, `semalar/` ve `.github/` altındaki özgün kod, şema ve otomasyon
  dosyaları MIT lisansı altındadır. Bkz. `LICENSE-CODE`.
- `kanunlar/` altındaki kanun metinleri resmi kamu kaynaklarından alınır. Bu
  depo resmi kanun metinleri üzerinde telif hakkı iddia etmez. Bkz. `LICENSE`
  ve `NOTICE.md`.


## Tam metinleri güncelleme

Resmi kaynaklardan tam metinleri çekmek için:

```bash
python betikler/kanun_metinlerini_indir.py
```

Bu komut her kanun klasöründeki `source_url` alanını kullanarak PDF indirir ve `metin.md` dosyasını günceller.

PDF metni çıkarmak için sistemde `pdftotext` varsa kullanılır. Yoksa Python fallback'i için:

```bash
python -m pip install -r requirements.txt
```
