# 💡 Idealar

Günlük uygulama fikirlerini hızlıca yakalamak için kişisel not defteri (PWA). Django tek süreçte hem sayfaları hem PWA dosyalarını sunar: tek adres, CORS yok.

**Durum:** Aşama 1 + fikir/özellik/proje yapısı + Aşama 2 (AI ile başlık/özet/etiket/özellik önerisi) + AI ile sohbet. Puanlama, benzerlik uyarısı ve haftalık liste sonraki aşamalar.

## Kavramlar

- **Fikir:** başlık (isteğe bağlı), açıklama, platformlar (PWA / Android / iOS). Hızlı eklemede yalnızca metin yazılır.
- **Özellik:** bir fikrin işaretlenebilir (yapıldı / yapılmadı) maddesi; isteğe bağlı platformu olur. Kartı açıp kutucuğu işaretlemek anında kaydeder.
- **Özelliği kopyalama:** ortak noktalar için özelliği başka fikirlere kopyalarsın. Kopya bağımsızdır ve işaretsiz başlar.
- **Biten fikir:** tüm özellikleri işaretli olan (en az bir özelliği bulunan) fikirdir. Listede *Hepsi / Devam eden / Biten* filtreleri vardır.
- **Proje:** fikirlerden ayrı bir kayıt. Fikirler projelere, projeler fikirlere (iki yönden de, çoka-çok) bağlanır. Projenin ilerlemesi bağlı fikirlerin özelliklerinden hesaplanır. Proje silinince fikirler silinmez.

## Mimari özet

| Konu | Karar |
|---|---|
| Backend | Python + Django 5.2, sunucu tarafı şablonlar |
| Auth | Django `User` + session cookie, şifreler **argon2** ile hashlenir |
| Veri | Her fikir bir kullanıcıya ait (`Idea.owner`); başka kullanıcının fikri 404 verir |
| DB | `DATABASE_URL` ile ayarlanır (başta SQLite, sonra Postgres) |
| PWA | `/manifest.webmanifest`, kökten sunulan `/sw.js`, çevrimdışı sayfa |
| Paketleme | Dockerfile + `compose.yaml` (web + günlük yedek servisi) |
| AI | `ai/` paketi: tek arayüz (`LLMClient`), Groq → Ollama fallback, OpenAI uyumlu API |
| Sunucu | `waitress` (Linux/macOS/Windows'ta çalışır), statik dosyalar WhiteNoise ile |
| Uzaktan erişim | Tailscale + `tailscale serve` (HTTPS) |

## Yapay zeka (ücretsiz)

Fikir kaydedilince sayfa hemen açılır, AI arkadan başlık, kısa özet, etiketler ve **önerilen özellikler** üretir. Öneriler kartta çıkar: **＋ Ekle** ile özellik listesine eklenir, ✕ ile yoksayılır. Kendi yazdığın başlık AI başlığının önüne geçer.

- **Birincil: Groq** (ücretsiz katman, kart gerekmez). **Yedek: Ollama** (kendi bilgisayarında küçük model). Groq limit doldurursa, kapalıysa veya bozuk cevap verirse otomatik Ollama denenir.
- **AI hata verirse fikir yine kaydedilir.** Kartta "✨ AI ile doldur" düğmesi çıkar. Toplu doldurmak için: `docker compose exec web python manage.py enrich_ideas`
- Sağlayıcı sırası ve ayarları `.env` içindedir (`AI_PROVIDERS=groq,ollama`). Yeni sağlayıcı eklemek veya değiştirmek tek dosyadır: `ai/providers.py`.
- **Gizlilik:** Groq'a fikirlerinin metni gönderilir. Bunu istemiyorsan `.env`'de `AI_PROVIDERS=ollama` yap; o zaman her şey bilgisayarından çıkmaz.

### Groq anahtarı
1. https://console.groq.com/keys adresinden ücretsiz hesap aç ve bir API anahtarı oluştur.
2. `.env` içine `GROQ_API_KEY=...` yaz (anahtarı kimseyle paylaşma, git'e girmez).
3. `docker compose up -d` (ayar değişince konteyner yeniden oluşur).

Ücretsiz limitler zamanla değişir; güncel limitler için Groq konsolundaki *Limits* sayfasına bak. Model adı `GROQ_MODEL` ile değiştirilebilir. Groq modelleri zamanla kaldırır (`llama-3.3-70b-versatile` kaldırıldı); log'da `model_not_found` görürsen `docker compose exec web python manage.py ai_models` ile anahtarının kullanabildiği modelleri listele ve birini `.env`'e yaz.

### Gemini / Google AI Studio (isteğe bağlı)
1. https://aistudio.google.com/apikey adresinden anahtar al.
2. `.env`: `GEMINI_API_KEY=...` ve `AI_PROVIDERS=groq,gemini,ollama` (sıra = öncelik). Model adı yazmak zorunda değilsin; varsayılan `gemini-flash-lite-latest` (Google'ın güncel hafif modeline işaret eden takma ad). Başka model istersen `GEMINI_MODEL=` yaz; geçerli adları `docker compose exec web python manage.py ai_models` listeler.
3. Ücretsiz katmanda gönderdiğin içeriğin Google'ın ürünlerini geliştirmek için kullanılabildiği belirtiliyor; fikirlerin gizliyse bunu göz önünde bulundur. Ayrıca günlük istek limiti modele göre çok değişiyor; kendi limitlerini aistudio.google.com/rate-limit sayfasında gör.

### Claude / Anthropic (isteğe bağlı, ücretli)
1. https://console.anthropic.com/settings/keys adresinden anahtar oluştur (kullandıkça ödenir, ücretsiz katman yok; kullanım limitini konsoldan koyabilirsin).
2. `.env`: `ANTHROPIC_API_KEY=...` ve `AI_PROVIDERS=groq,anthropic,ollama` (sıra = öncelik; Claude'u ilk yazarsan öncelikli olur, ya da sohbetteki AI seçiciden seç).
3. Varsayılan model `claude-opus-5-5`. Not almak için daha ucuz bir model yeterliyse `ANTHROPIC_MODEL=claude-haiku-5-5` yaz; geçerli adları `docker compose exec web python manage.py ai_models` listeler.
4. Claude bir isteği reddederse veya hata verirse zincir otomatik olarak sıradaki sağlayıcıya geçer; fikrin kaybolmaz.

### Ollama (yedek, isteğe bağlı)
1. https://ollama.com/download adresinden Windows sürümünü kur.
2. Modeli indir: `ollama pull qwen2.5:3b` (yaklaşık 2 GB; Türkçe için makul bir küçük model).
3. Docker konteyneri Ollama'ya `host.docker.internal:11434` üzerinden ulaşır (`compose.yaml` bunu ayarlar). Bağlanamazsa Ollama'yı `OLLAMA_HOST=0.0.0.0` ortam değişkeniyle başlatmayı dene.

Küçük yerel modelin çıktısı Groq'unkinden zayıf ve yavaştır; yalnızca yedek olarak düşünüldü.

## AI ile sohbet

AI ile projeni, fikirlerini ve özelliklerini konuşabilirsin. Her kapsamda **birden çok sohbet (oturum)** açabilirsin: kapsamın sohbet sayfasında geçmiş sohbetler başlıklarıyla listelenir, alttaki kutu yeni bir sohbet başlatır, bir sohbeti açıp devam edebilir veya silebilirsin. Üç yerden açılır:

- **Proje sayfası → "💬 Proje hakkında konuş":** AI projeyi, bağlı fikirleri ve özelliklerin yapıldı/yapılmadı durumunu görür.
- **Fikir kartı → "💬 Sohbet":** yalnızca o fikir hakkında.
- **Üst menüde 💬:** genel sohbet; tüm fikirlerinin başlık ve özetini görür.

AI fikir verir, risk ve alternatif söyler. Somut bir şey önerdiğinde cevabın altında düğmeli kart çıkar: *"＋ Şu fikre özellik: …"* veya *"＋ Yeni fikir: …"*. **Sen "Ekle"ye basmadan hiçbir şey değişmez.** Proje sohbetinde önerilen yeni fikir otomatik olarak projeye bağlanır. Sohbetler veritabanında kalır; istediğin sohbeti "Sil" ile kaldırırsın. Bir sohbetin geçmişi diğerine karışmaz. AI yanıt veremezse mesajın kaybolmaz, "Tekrar dene" düğmesi çıkar.

Sohbette AI'a gönderilenler: konuşma (son 10 mesaj) ve o sohbetin kapsamındaki fikirlerin metni (en fazla yaklaşık 6000 karakter). Başka kullanıcıların verisi hiçbir zaman gönderilmez.

## Arayüz

Tasarım dili işlevsel ve sadedir (Dieter Rams/Braun'dan esinli): ince çizgiler, keskin köşeler, gölge yok; tek turuncu vurgu yalnızca seçili satır, ilerleme çubuğu ve odak halkası gibi işlevsel yerlerde kullanılır.

- **Masaüstü:** solda menü (sayaçlarla), ortada fikir listesi, sağda seçilen fikrin tamamı (özet, platform, proje, etiket, benzerlik uyarısı, özellikler, AI önerileri). Kart açıp kapatmak yok.
- **Telefon:** tek sütun. Alttaki sabit kutu hızlı fikir ekler, fikre dokununca detay ayrı ekran olarak açılır, altta Fikirler/Projeler/Sohbet/Ayarlar sekmeleri bulunur.
- **Liste:** Hepsi / Devam eden / Biten sekmeleri (sayaçlı), proje filtresi, sıralama (yeni, eski, son güncellenen, ilerleme) ve arama birlikte çalışır.
- **Özellikler:** kutucuğa tıklamak anında kaydeder ve ilerlemeyi güncel tutar; kalem simgesi adı yerinde değiştirir.
- **Tema:** Açık / Gri / Koyu. Bilgisayarda sol menünün altında, telefonda *Ayarlar* sekmesinde. Seçimin cihazda hatırlanır; seçmediysen cihazın açık-koyu ayarını izler.
- **Klavye (bilgisayar):** `N` yeni fikir, `/` arama, `J`/`K` veya ↑/↓ listede gezinme. Mesaj kutularında **Enter gönderir, Shift+Enter yeni satır açar** (telefonda Enter yeni satırdır, ➤ gönderir).

## Claude için prompt

Fikir sayfasındaki **"Claude için prompt"** düğmesi, o fikirden Claude'a yapıştırıp işe başlayabileceğin bir prompt hazırlar: amaç, platformlar, etiketler, **yapılacak ve yapılmış özellikler**, bağlı proje, benzerlik uyarıları ve çalışma şeklin (Türkçe cevap, İngilizce kod yorumu ve commit, mimari kararları önce sor, aşama sonunda dur, testleri çalıştır). **Kopyala** ile panoya alırsın; kutuda düzenleyebilirsin.

- **İki mod:** *Sıfırdan yeni uygulama* ya da *Mevcut projeye ekle* (fikir GitHub adresi olan bir projeye bağlıysa varsayılan odur; prompt Claude'a önce depoyu incelemesini ve mevcut yapıya uymasını söyler).
- **AI ile detaylandır:** MVP kapsamı, teknoloji önerisi, aşamalar ve riskleri prompt'a ekler (AI zincirini kullanır, birkaç saniye sürer). AI yanıt vermezse sade prompt kalır. Mod değiştirince AI planı sıfırlanır, tekrar istersin.
- Prompt'taki "çalışma şekli" maddeleri `ideas/build_prompt.py` içindeki `WORKING_RULES` listesindedir; kendi tercihlerine göre değiştirebilirsin.

## Benzerlik uyarısı

Yeni bir fikir kaydedilince AI, onu **tüm fikirlerin ve projelerinle** karşılaştırır (yeni fikir hazırlanırken kartta "AI düşünüyor" aşamasında, ayrıca "🔎 Benzerleri ara" düğmesiyle istediğin zaman).

- Karar **amaca göre** verilir, kelimelere göre değil: farklı kelimelerle (hatta farklı dilde) yazılmış aynı fikir de yakalanır. Sadece "ikisi de mobil uygulama" gibi genel benzerlikler eşleşme sayılmaz. Her eşleşmenin yanında gerekçe cümlesi ve "aynısı / benzer / ilgili" etiketi görürsün.
- Çok az fikrin varsa hepsi AI'a verilir. Çok fikrin olunca önce kelime örtüşmesiyle en olası adaylar ve en yeni fikirler seçilir.
- Benzer bir **proje** bulunursa **"＋ Bu projeye bağla"**, benzer bir **fikir** bulunursa **"＋ O fikre özellik olarak ekle"** düğmesi çıkar; ✕ ile "farklı, yoksay" dersin. Sen basmadan hiçbir şey değişmez.
- AI çalışmazsa güçlü kelime örtüşmesi gösterilir ve kartta açıkça "AI kontrolü yapılamadı; yalnızca kelime benzerliğine baktım" yazar. Sessizce eksik sonuç göstermez.

## GitHub'dan projeleri içe aktarma

**Projeler → GitHub'dan içe aktar** sayfasında GitHub kullanıcı adını yazıp depolarını listelersin, hangilerini proje yapmak istediğini işaretlersin. Hiçbir şey kendiliğinden eklenmez.

- Projeye depo adı, açıklaması ve GitHub adresi aktarılır; depoların içeriği okunmaz (içerik incelemesi ayrı bir düğmedir, bkz. aşağıdaki bölüm).
- Fork'lar ve arşivlenmiş depolar işaretsiz gelir. Daha önce eklediğin depolar "zaten ekli" yazar ve tekrar eklenmez, bu yüzden listeyi istediğin zaman yeniden çekebilirsin.
- **Herkese açık depolar** için token gerekmez (GitHub saatte 60 isteğe izin verir; 100 depo = 1 istek). **Özel depolar** için `.env`'ye `GITHUB_TOKEN` ekle ve kullanıcı adını boş bırak; token'ın sahibinin tüm depoları (özel olanlar dahil) listelenir. Kullanıcı adını her seferinde yazmamak için `GITHUB_USERNAME=` da ayarlayabilirsin.
- En fazla 500 depo listelenir. Kullanıcı adı yalnızca harf, rakam ve tire içerebilir; sunucu yalnızca GitHub API'sine bağlanır.

## GitHub projesini AI ile inceleme

Projeye bir GitHub adresi eklersen (Düzenle → *GitHub adresi*), proje sayfasında **🔍 Projeyi incele** düğmesi çıkar. Sunucu GitHub API'sinden depoyu okur ve AI'a inceletir. Sonuç: kısa özet, kullanılan teknolojiler, **çözülmüş/yapılmış görünenler**, **eksik veya belirsiz olanlar**. Ayrıca projeye bağlı fikirlerdeki özellik listendeki maddelerden kodda yapılmış görünenler için **"✓ Yapıldı olarak işaretle"** düğmesi çıkar (sen basmadan işaretlenmez).

- İnceleme için **Gemini** tercih edilir (büyük içerik); kurulu değilse veya hata verirse diğer AI'lara düşer.
- **Sınır:** AI depodaki tüm kodu görmez; yalnızca README, dosya listesi, birkaç manifest/ana dosya ve son 30 commit mesajı gönderilir (varsayılan en fazla 24.000 karakter, `REPO_ANALYSIS_MAX_CHARS`). Sonuç bir tahmindir; "yapılmış" iddiası kanıt (dosya/commit) gösterir, emin olunamayan için "belirsiz" yazılır.
- **Gizlilik:** Depodaki metin seçilen AI sağlayıcısına gönderilir. Ücretsiz Gemini katmanında içeriğin Google'ın ürünlerini geliştirmek için kullanılabildiği belirtiliyor; **özel depolarını incelemeden önce bunu düşün.** İstersen `AI_PROVIDERS=ollama` ile her şeyi kendi bilgisayarında tut.
- **Herkese açık depolar** token olmadan okunur (saatte 60 istek sınırı). Özel depo için `.env`'ye `GITHUB_TOKEN` ekle (yalnızca okuma izinli, ayrıntı `.env.example`'da).
- Yalnızca `https://github.com/sahip/depo` biçimindeki adresler kabul edilir; sunucu başka adreslere istek atmaz.

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
