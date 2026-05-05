# Türk Hukuku Metin Deposu (turk-hukuku)

Bu depo, Türkiye'deki kanun metinlerini **makine tarafından işlenebilir**, **sürümlenebilir** ve **avukatların doğrudan kullanabileceği** bir formatta tutmak için tasarlanmıştır.

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

## Katkı rehberi (taslak)

- Yeni kanun eklerken klasör adını `kanunno-kisa-ad` biçiminde verin
- Metni madde bazında tutarlı başlıklarla yazın
- Metadata alanlarını boş bırakmayın
- Kaynak URL ekleyin

## Lisans

Bu proje için lisans henüz netleştirilmemiştir. `LICENSE` dosyası eklenecektir.


## Tam metinleri güncelleme

Resmi kaynaklardan tam metinleri çekmek için:

```bash
python betikler/kanun_metinlerini_indir.py
```

Bu komut her kanun klasöründeki `source_url` alanını kullanarak PDF indirir ve `metin.md` dosyasını günceller.
