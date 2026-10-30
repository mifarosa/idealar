"""What the landing page shows as "what's new". Add one entry at the top whenever a user-visible feature ships."""
from dataclasses import dataclass
from datetime import date, timedelta
from django.utils.translation import gettext_lazy

TIMELINE_PREVIEW = 4  # entries shown on the landing page; the rest opens in a dialog
NEW_FOR_DAYS = 10  # entries newer than this get a "Yeni" badge


@dataclass(frozen=True)
class Feature:
    day: date
    title: str
    text: str

    @property
    def is_new(self) -> bool:
        return date.today() - self.day <= timedelta(days=NEW_FOR_DAYS)


TIMELINE = (
    Feature(date(2026, 10, 30), gettext_lazy("Verilerin sende"), gettext_lazy("Tüm verilerini JSON olarak indir, istediğin an hesabını ve her şeyini sil. Neyin saklandığı gizlilik sayfasında açıkça yazıyor.")),
    Feature(date(2026, 10, 30), gettext_lazy("Türkçe ve İngilizce"), gettext_lazy("Arayüz iki dilde: logonun yanındaki TR/EN düğmesiyle istediğin dili seç. Yeni bir logo da geldi.")),
    Feature(date(2026, 10, 30), gettext_lazy("Kanban: kişisel ve proje panoları"), gettext_lazy("Yapılacak, yapılıyor, bitti. Projeye bağlı fikirler panoda kendiliğinden kart olur; kartları sürükleyip bırak. Kişisel pano evdeki küçük işler için serbest, istersen oraya fikir de ekleyebilirsin.")),
    Feature(date(2026, 10, 30), gettext_lazy("Öneri ve şikayet kutusu"), gettext_lazy("Bir şey bozuksa ya da bir fikrin varsa yaz; yanıtı ve durumu (açık, inceleniyor, çözüldü) aynı yerden takip et.")),
    Feature(date(2026, 10, 30), gettext_lazy("Sohbetten projeye ekle"), gettext_lazy("AI ile konuşurken “bu fikri şu projeye bağla” de; öneriyi tek tıkla onaylarsın.")),
    Feature(date(2026, 10, 30), gettext_lazy("Tüm notlarını okuyan öneriler"), gettext_lazy("Yeni bir fikir yazınca AI diğer bütün notlarına bakar: ilgili notlar, birleştirilebilecekler, ödünç alınabilecek özellikler, yeni fikirler.")),
    Feature(date(2026, 10, 30), gettext_lazy("Kendi yapay zekânı getir"), gettext_lazy("Claude, ChatGPT, Gemini, Groq ve daha fazlası. Anahtarın şifrelenerek saklanır, kimse görmez.")),
    Feature(date(2026, 10, 30), gettext_lazy("Google ile giriş"), gettext_lazy("Şifre yok: tek tıkla gir.")),
    Feature(date(2026, 10, 26), gettext_lazy("GitHub projelerini içe aktar"), gettext_lazy("Depolarını seç, proje olarak eklensin; AI depoyu inceleyip neyin yapıldığını söylesin.")),
    Feature(date(2026, 10, 26), gettext_lazy("Claude için hazır prompt"), gettext_lazy("Bir fikri tek tıkla, yapay zekâya yapıştırılacak hazır bir plana çevir.")),
    Feature(date(2026, 10, 26), gettext_lazy("Yeni arayüz"), gettext_lazy("Açık, gri ve koyu tema; klavye kısayolları; bilgisayarda ve telefonda rahat.")),
    Feature(date(2026, 10, 23), gettext_lazy("Benzer fikir uyarısı"), gettext_lazy("Zaten bir şeyin varsa söyler, yeni proje açmak yerine ona eklemeni önerir.")),
    Feature(date(2026, 10, 23), gettext_lazy("AI ile sohbet"), gettext_lazy("Fikirlerinle yazışır gibi konuş; öneriler kartlarla gelir, sen onaylarsın.")),
    Feature(date(2026, 10, 23), gettext_lazy("Otomatik başlık, özet ve etiket"), gettext_lazy("Aklına geleni yaz; gerisini AI toparlasın.")),
    Feature(date(2026, 10, 23), gettext_lazy("Fikirler, projeler, özellik listeleri"), gettext_lazy("Yapılan ve yapılmayanı işaretle, fikirleri projelere bağla. Telefona uygulama gibi kurulur.")),
)
