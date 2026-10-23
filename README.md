# 💡 Idealar

Günlük uygulama fikirlerini hızlıca yakalamak için kişisel not defteri (PWA). Django tek süreçte hem sayfaları hem PWA dosyalarını sunar: tek adres, CORS yok.

**Durum:** Aşama 1 — kullanıcı girişi, fikir ekleme/listeleme/arama/düzenleme/silme, kurulabilir PWA arayüzü, günlük SQLite yedeği. (AI katmanı, puanlama ve haftalık liste sonraki aşamalar.)

## Mimari özet

| Konu | Karar |
|---|---|
| Backend | Python + Django 5.2, sunucu tarafı şablonlar |
| Auth | Django `User` + session cookie, şifreler **argon2** ile hashlenir |
| Veri | Her fikir bir kullanıcıya ait (`Idea.owner`); başka kullanıcının fikri 404 verir |
| DB | `DATABASE_URL` ile ayarlanır (başta SQLite, sonra Postgres) |
| PWA | `/manifest.webmanifest`, kökten sunulan `/sw.js`, çevrimdışı sayfa |
| Sunucu | `waitress` (Linux/macOS/Windows'ta çalışır), statik dosyalar WhiteNoise ile |
| Uzaktan erişim | Tailscale + `tailscale serve` (HTTPS) |

## Kurulum

```bash
git clone https://github.com/mifarosa/idealar.git && cd idealar
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# SECRET_KEY üret ve .env içine yaz:
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"

python manage.py migrate
python manage.py createsuperuser   # ilk (ve şimdilik tek) kullanıcı
```

Daha sonra başka kullanıcı eklemek için `python manage.py createsuperuser` veya `/admin/` kullanılabilir.

## Çalıştırma

Geliştirme (`DEBUG=true` ile `.env` gerekmez):

```bash
DEBUG=true python manage.py runserver
```

Günlük kullanım (bilgisayarda sürekli açık):

```bash
waitress-serve --listen=127.0.0.1:8000 config.wsgi:application
```

Sunucu yalnızca `127.0.0.1`'e bağlanır; dışarıya Tailscale açar (aşağıda).

## Testler

```bash
python manage.py test
```

Auth (giriş/çıkış/argon2/oturum), fikir CRUD'u, kullanıcılar arası izolasyon, PWA manifest/service worker ve yedek script'i test edilir.

## Telefondan erişim (Tailscale + HTTPS)

PWA'yı telefona "Ana ekrana ekle" ile kurabilmek için tarayıcının sayfayı **HTTPS** ile görmesi gerekir. Tailscale bunu ücretsiz çözer: Let's Encrypt sertifikasını makinenin `*.ts.net` adı için verir ve `tailscale serve` TLS'i sonlandırıp isteği Django'ya iletir. Aşağıdaki adımlar Tailscale'in resmi dokümanına göre yazıldı; bu geliştirme ortamında Tailscale kurulu olmadığı için sizin makinenizde ilk kez denenecek.

1. **Bilgisayara ve telefona Tailscale kur**, ikisini de aynı hesapla (aynı tailnet) giriş yaptır.
2. [Admin console → DNS](https://login.tailscale.com/admin/dns) sayfasında:
   - **MagicDNS**'i aç,
   - **HTTPS Certificates** → *Enable HTTPS*.
   > ⚠️ HTTPS açılınca makine adı ve tailnet adı sertifika şeffaflık kayıtlarında (herkese açık) görünür. Makine adında kişisel/hassas bir şey olmasın; gerekirse önce makineyi yeniden adlandır.
3. Tam adresi öğren (ör. `bilgisayarim.tailnet-adi.ts.net`):
   ```bash
   tailscale status --json | grep -m1 DNSName
   ```
4. `.env` dosyasını güncelle:
   ```
   ALLOWED_HOSTS=localhost,127.0.0.1,bilgisayarim.tailnet-adi.ts.net
   CSRF_TRUSTED_ORIGINS=https://bilgisayarim.tailnet-adi.ts.net
   BEHIND_HTTPS_PROXY=true
   ```
   `BEHIND_HTTPS_PROXY=true`, çerezleri `Secure` yapar ve `tailscale serve`'ün `X-Forwarded-Proto` başlığına güvenir.
5. Django'yu başlat (yukarıdaki `waitress-serve` komutu), sonra HTTPS'i aç:
   ```bash
   tailscale serve --bg 8000
   ```
   (Eski Tailscale sürümlerinde: `tailscale serve --bg --https=443 http://127.0.0.1:8000`.) Durumu görmek için `tailscale serve status`, kapatmak için `tailscale serve reset`.
6. Telefonda (Tailscale uygulaması açıkken) `https://bilgisayarim.tailnet-adi.ts.net` adresine git, giriş yap.
   - **Android/Chrome:** menü → *Uygulamayı yükle*.
   - **iOS/Safari:** Paylaş → *Ana Ekrana Ekle*.

`tailscale funnel` **kullanma**: o, uygulamayı internete açar. `serve` yalnızca tailnet cihazlarına açıktır.

Not: Bilgisayar kapalıysa veya Tailscale bağlı değilse uygulama "Çevrimdışısın" sayfasını gösterir; fikirler yalnızca sunucuda tutulur.

## Yedekleme

`scripts/backup_sqlite.py`, SQLite'ın çevrimiçi yedek API'sini kullanır (sunucu çalışırken güvenlidir), `backups/idealar-YYYY-MM-DD.sqlite3` dosyası yazar ve `BACKUP_KEEP_DAYS` (varsayılan 30) günden eski yedekleri siler.

```bash
python scripts/backup_sqlite.py
```

Her gün otomatik çalıştırmak için:

- **Linux/macOS (cron):** `crontab -e` ile
  ```
  30 3 * * * cd /yol/idealar && .venv/bin/python scripts/backup_sqlite.py >> backups/backup.log 2>&1
  ```
- **Windows:** Task Scheduler'da günlük görev; program `.venv\Scripts\python.exe`, argüman `scripts\backup_sqlite.py`, başlangıç dizini proje klasörü.

`backups/` git'e girmez. Önemli: yedekleri aynı diskte bırakma, ara sıra başka bir yere (harici disk, bulut klasörü) kopyala. Postgres'e geçince bu script yerine `pg_dump` kullanılır (script Postgres URL'sini bilerek reddeder).

## Gizli bilgiler

`SECRET_KEY` ve ileride eklenecek API anahtarları yalnızca `.env` dosyasında durur; `.env` `.gitignore`'dadır. `DEBUG` kapalıyken `SECRET_KEY` yoksa uygulama başlamaz.
