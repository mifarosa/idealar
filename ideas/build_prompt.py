"""Turns an idea into a ready-to-paste prompt that starts (or continues) the build in a coding assistant."""
from ai.brief import Brief

from .models import SUGGESTION_PENDING, Idea

MODE_NEW, MODE_EXTEND = "yeni", "ekle"

# The working agreements the developer asks for in every project; one place to change them.
WORKING_RULES = [
    "Bana Türkçe cevap ver; kod yorumları ve commit mesajları İngilizce olsun.",
    "Önemli bir mimari karar gerekirse yapmadan önce bana sor. Küçük kararları kendin ver ve söyle.",
    "İşi aşamalara böl; her aşamanın sonunda dur ve bana göster.",
    "Temiz kod yaz: küçük fonksiyonlar, anlamlı isimler, tek sorumluluk, hataları yutma.",
    "Önemli kısımlar için test yaz, çalıştır ve sonucu söyle.",
    "README'ye kurulum ve çalıştırma adımlarını yaz. Gizli bilgiler (anahtarlar, secret key) .env dosyasında dursun, git'e girmesin.",
]


def default_mode(idea: Idea) -> str:
    """Extend an existing project when the idea belongs to one that already has a repository."""
    has_repo = any(project.github_url for project in idea.projects.all())
    return MODE_EXTEND if has_repo else MODE_NEW


def _section(title: str, lines: list[str]) -> str:
    return "\n".join([title, *lines]) if lines else ""


def _same_text(first: str, second: str) -> bool:
    """Equal ignoring case and trailing punctuation, so a note that merely repeats the summary is not listed twice."""
    return first.strip().rstrip(".!?…").casefold() == second.strip().rstrip(".!?…").casefold()


def _goal(idea: Idea) -> list[str]:
    parts = [idea.ai_summary] if idea.ai_summary else []
    if idea.has_note and not (parts and _same_text(parts[0], idea.body)):
        parts.append(idea.body.strip())
    return parts or [idea.display_title]


def _features(idea: Idea) -> list[str]:
    todo = [f"- [ ] {feature.text}{_platform_suffix(feature)}" for feature in idea.features.all() if not feature.is_done]
    done = [f"- [x] {feature.text}{_platform_suffix(feature)}" for feature in idea.features.all() if feature.is_done]
    lines = ["Yapılacak:", *todo] if todo else []
    lines += ["Yapılmış:", *done] if done else []
    return lines


def _platform_suffix(feature) -> str:
    return f" ({feature.get_platform_display()})" if feature.platform else ""


def _project_context(idea: Idea, mode: str) -> list[str]:
    projects = list(idea.projects.all())
    names = ", ".join(project.name for project in projects)
    repo = next((project.github_url for project in projects if project.github_url), "")
    if mode == MODE_EXTEND and repo:
        return [
            f"Bu fikir mevcut bir projeye ekleniyor. Proje: {names}. Depo: {repo}",
            "Önce depoyu incele (yapı, kullanılan teknolojiler, mevcut özellikler, kod stili), sonra bunu mevcut yapıya uygun biçimde ekle; kodu gereksiz yere yeniden yazma.",
        ]
    lines = ["Sıfırdan başlıyoruz. Depo boşsa git init ile başla."]
    if projects:
        lines.append(f"İlgili proje: {names}" + (f" ({repo})" if repo else ""))
    return lines


def _similar(idea: Idea) -> list[str]:
    hints = [h for h in idea.similar if h["status"] == SUGGESTION_PENDING and h["verdict"] != "related"]
    return [f"- {'Proje' if h['kind'] == 'project' else 'Fikir'} “{h['title']}”: {h['reason']}".rstrip(": ") for h in hints]


def _brief(brief: Brief | None) -> list[str]:
    if brief is None:
        return []
    lines = [f"Teknoloji: {brief.stack}"] if brief.stack else []
    for title, items in (("MVP kapsamı", brief.mvp), ("Önerilen aşamalar", brief.phases), ("Riskler", brief.risks)):
        lines += [f"{title}:", *[f"- {item}" for item in items]] if items else []
    return lines


def build_prompt(idea: Idea, mode: str, brief: Brief | None = None) -> str:
    meta = []
    if idea.platform_labels:
        meta.append(f"Platformlar: {', '.join(idea.platform_labels)}")
    if idea.ai_tags:
        meta.append(f"Etiketler: {', '.join(idea.ai_tags)}")
    sections = [
        f"# {idea.display_title}\n\nBir uygulama geliştireceğiz.",
        _section("AMAÇ", _goal(idea) + meta),
        _section("ÖZELLİKLER", _features(idea)),
        _section("PROJE", _project_context(idea, mode)),
        _section("BENZER KAYITLAR (aynı işi iki kez yapmamak için bak)", _similar(idea)),
        _section("ÖNERİLEN YAKLAŞIM (AI taslağı, tartışmaya açık)", _brief(brief)),
        _section("ÇALIŞMA ŞEKLİ", [f"- {rule}" for rule in WORKING_RULES]),
    ]
    return "\n\n".join(section for section in sections if section) + "\n"
