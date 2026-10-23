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
| Paketleme | Dockerfile + `compose.yaml` (web + günlük yedek servisi) |
| Sunucu | `waitress` (Linux/macOS/Windows'ta çalışır), statik dosyalar WhiteNoise ile |
| Uzaktan erişim | Tailscale + `tailscale serve` (HTTPS) |

## Docker ile çalıştırma (önerilen, Windows dahil)

Docker Desktop kurulu olması yeterli; Python/venv gerekmez. Veritabanı `idealar-data` adlı Docker volume'unda, yedekler proje klasöründeki `backups/` içinde durur.

```powershell
git clone https://github.com/mifarosa/idealar.git
cd idealar
copy .env.example .env
```

`.env` içinde `SECRET_KEY` değerini bir anahtarla değiştir (Python kurulu olmadan üretmek için: `docker run --rm python:3.13-slim python -c "import secrets; print(secrets.token_urlsafe(50))"`). Anahtarda `$` olmasın. Sonra:

```powershell
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

- Uygulama `http://localhost:8000` adresinde; yalnızca bilgisayarın kendisine açıktır (`127.0.0.1`). Telefon erişimi için aşağıdaki Tailscale adımlarını **bilgisayarda (Docker'ın dışında)** uygula: `tailscale serve --bg 8000` konteynerdeki uygulamaya da aynen ulaşır.
- `backup` servisi her gün `backups/` klasörüne yedek yazar ve eski yedekleri siler; ayrıca cron/Task Scheduler gerekmez.
- Konteynerler `restart: unless-stopped` ile Docker Desktop açılınca kendiliğinden başlar. Docker Desktop ayarlarında "Start Docker Desktop when you sign in" açık olmalı.
- Güncelleme: `git pull` sonra `docker compose up -d --build`. Veri volume'da kaldığı için kaybolmaz; migration'lar açılışta otomatik uygulanır.
- Testler: `docker compose run --rm web python manage.py test`
- Durdurma: `docker compose down` (veriyi silmez; `-v` eklersen volume silinir, ekleme).
- Yedekten geri dönme: `docker compose stop`, sonra `docker compose cp backups/idealar-YYYY-MM-DD.sqlite3 web:/data/db.sqlite3`, sonra `docker compose up -d`.

## Docker olmadan kurulum

```bash
git clone https://github.com/mifarosa/idealar.git && cd idealar
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# SECRET_KEY üret ve .env içine yaz:
python -c "import secrets; print(secrets.token_urlsafe(50))"

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
