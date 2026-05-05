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
laws/
  4721-turk-medeni-kanunu/
    metadata.json
    law.md
    history/
      2024-01-01.md
```

## Format yaklaşımı

Her kanun klasöründe:

1. `metadata.json`
   - kanun numarası
   - resmi adı
   - kabul tarihi
   - yürürlük durumu
   - resmi gazete bilgisi
   - kaynak URL
2. `law.md`
   - Madde madde düzenlenmiş metin
3. `history/*.md`
   - Sürüm notları ve değişiklik açıklamaları

## İlk adım planı

1. Veri modeli üzerinde uzlaşma (`schemas/law.schema.json`)
2. İlk örnek kanunları ekleme
3. Doğrulama script'i (`scripts/validate.py`)
4. Otomatik CI doğrulama

## Katkı rehberi (taslak)

- Yeni kanun eklerken klasör adını `kanunno-kisa-ad` biçiminde verin
- Metni madde bazında tutarlı başlıklarla yazın
- Metadata alanlarını boş bırakmayın
- Kaynak URL ekleyin

## Lisans

Bu proje için lisans henüz netleştirilmemiştir. `LICENSE` dosyası eklenecektir.
