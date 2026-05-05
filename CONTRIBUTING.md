# Katkı Rehberi

Katkılar pull request ile yapılmalıdır.

## Akış

1. Depoyu fork edin.
2. Fork'unuzda açıklayıcı isimli bir branch oluşturun.
3. Değişikliklerinizi commit edin.
4. Ana repoya pull request açın.

`main` branch'ine doğrudan push etmeyin. Yazma yetkiniz olsa bile değişiklikler
PR incelemesinden geçmelidir.

## Kaynak Kuralları

- Kanun metinleri ve hukuki metadata resmi kaynaklara dayanmalıdır.
- Birincil kaynak olarak mümkün olduğunda https://www.mevzuat.gov.tr/ kullanın.
- Resmi olmayan blog, haber, PDF kopyası veya arşiv sitelerini ana kaynak olarak
  kullanmayın.
- Hukuki metin değişikliklerinde PR açıklamasına resmi kaynak URL'sini ve kaynağı
  kontrol ettiğiniz tarihi ekleyin.
- Kaynak tarihi `YYYY-MM-DD` biçiminde yazın.

## Metadata ve Şema Doğrulaması

Her kanun klasöründeki `ustveri.json`, `semalar/kanun.schema.json` şemasına
uymalıdır. PR açmadan önce doğrulama çalıştırın:

```bash
python betikler/dogrula.py
```

Eksik `source_url`, hatalı tarih biçimi veya şemaya uymayan metadata kabul
edilmez.

## Kanun Metni Değişiklikleri

- `kanunlar/` altındaki metin değişiklikleri resmi kaynakla birebir
  karşılaştırılabilir olmalıdır.
- Değişiklik gerekçesini PR açıklamasında kısa ve somut yazın.
- İlgili `ustveri.json` içindeki `source_url` alanını güncel tutun.
- Gerekliyse `gecmis/` altında değişiklik tarihini ve notunu ekleyin.

## Kod, Şema ve Betik Değişiklikleri

- Kod, şema ve otomasyon değişiklikleri kanun metni değişikliklerinden ayrı
  commit veya PR olarak tutulmalıdır.
- `betikler/`, `semalar/` ve `.github/` altındaki özgün proje kodu MIT lisansı
  altındadır. Ayrıntılar için `LICENSE-CODE` dosyasına bakın.

## PR Kontrol Listesi

- [ ] Değişiklikler resmi kaynakla doğrulandı.
- [ ] Hukuki metin değişiklikleri için kaynak URL ve kontrol tarihi eklendi.
- [ ] `python betikler/dogrula.py` başarılı çalıştı.
- [ ] `main` branch'ine doğrudan push yapılmadı.
