"""Resume templates: a LaTeX file for the look plus a style brief for the writing."""
from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class Template:
    name: str
    audience: str
    pages: int
    fontsize: float
    brief: str

    def tex(self) -> str:
        return resources.files(__package__).joinpath(f"{self.name}.tex").read_text(encoding="utf-8")


TEMPLATES = {
    t.name: t
    for t in (
        Template(
            "corporate",
            "Large enterprises, banks, consultancies, government",
            2,
            11,
            "Audience: recruiters and hiring managers at a large, formal organisation. "
            "Tone: formal and measured, no contractions. Emphasise scale, "
            "reliability, compliance, security, process and work across teams and stakeholders. "
            "Section order: Professional Summary, Experience, Skills, Education, Certifications.",
        ),
        Template(
            "startup",
            "Startups and product companies",
            2,
            10,
            "Audience: a founder or engineering lead at a small, fast company. Tone: direct, "
            "plain and warm, like a sharp colleague describing their work. Emphasise ownership, "
            "things shipped end to end, speed, breadth and product impact. "
            "Section order: Summary, Skills, Experience, Projects (only if the profile has "
            "relevant ones), Education.",
        ),
        Template(
            "academic",
            "Universities, research labs, grants, graduate programmes",
            2,
            11,
            "Audience: a faculty or research hiring committee. Tone: precise and sober, no sales "
            "language. Emphasise methods, rigour, research, publications, teaching and mentoring "
            "where the profile has them; never invent academic output. "
            "Section order: Research Interests or Summary, Education, Research and Professional "
            "Experience, Publications, Teaching, Skills, Awards. Include only sections the "
            "profile can fill.",
        ),
    )
}
DEFAULT_TEMPLATE = "corporate"
