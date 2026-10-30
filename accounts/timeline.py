"""What the landing page shows as "what's new". Add one entry at the top whenever a user-visible feature ships."""
from dataclasses import dataclass
from datetime import date, timedelta

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
    Feature(date(2026, 10, 30), "Kanban: kişisel ve proje panoları", "Yapılacak, yapılıyor, bitti. Kartları sürükleyip bırak; her projenin ve kendi işlerinin ayrı panosu var."),
    Feature(date(2026, 10, 30), "Öneri ve şikayet kutusu", "Bir şey bozuksa ya da bir fikrin varsa yaz; yanıtı ve durumu (açık, inceleniyor, çözüldü) aynı yerden takip et."),
    Feature(date(2026, 10, 30), "Sohbetten projeye ekle", "AI ile konuşurken “bu fikri şu projeye bağla” de; öneriyi tek tıkla onaylarsın."),
    Feature(date(2026, 10, 30), "Tüm notlarını okuyan öneriler", "Yeni bir fikir yazınca AI diğer bütün notlarına bakar: ilgili notlar, birleştirilebilecekler, ödünç alınabilecek özellikler, yeni fikirler."),
    Feature(date(2026, 10, 30), "Kendi yapay zekânı getir", "Claude, ChatGPT, Gemini, Groq ve daha fazlası. Anahtarın şifrelenerek saklanır, kimse görmez."),
    Feature(date(2026, 10, 30), "Google ile giriş", "Şifre yok: tek tıkla gir."),
    Feature(date(2026, 10, 26), "GitHub projelerini içe aktar", "Depolarını seç, proje olarak eklensin; AI depoyu inceleyip neyin yapıldığını söylesin."),
    Feature(date(2026, 10, 26), "Claude için hazır prompt", "Bir fikri tek tıkla, yapay zekâya yapıştırılacak hazır bir plana çevir."),
    Feature(date(2026, 10, 26), "Yeni arayüz", "Açık, gri ve koyu tema; klavye kısayolları; bilgisayarda ve telefonda rahat."),
    Feature(date(2026, 10, 23), "Benzer fikir uyarısı", "Zaten bir şeyin varsa söyler, yeni proje açmak yerine ona eklemeni önerir."),
    Feature(date(2026, 10, 23), "AI ile sohbet", "Fikirlerinle yazışır gibi konuş; öneriler kartlarla gelir, sen onaylarsın."),
    Feature(date(2026, 10, 23), "Otomatik başlık, özet ve etiket", "Aklına geleni yaz; gerisini AI toparlasın."),
    Feature(date(2026, 10, 23), "Fikirler, projeler, özellik listeleri", "Yapılan ve yapılmayanı işaretle, fikirleri projelere bağla. Telefona uygulama gibi kurulur."),
)
