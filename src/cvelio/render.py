"""Turn tailored resume data into LaTeX and compile it to a PDF with Tectonic."""
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .templates import Template

_ESCAPES = {c: "\\" + c for c in "#$%&_{}"}
_ESCAPES.update({"\\": r"\textbackslash{}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"})
_EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")
_URL = re.compile(r"^(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?$")


def tex(value) -> str:
    """Escape text coming from the model so it can never run as LaTeX."""
    return "".join(_ESCAPES.get(c, c) for c in " ".join(str(value).split()))


def _contact(item: str) -> str:
    """Make e-mails and web addresses clickable; everything else stays plain."""
    item = item.strip()
    if _EMAIL.match(item):
        return rf"\href{{mailto:{tex(item)}}}{{\mbox{{{tex(item)}}}}}"
    if _URL.match(item):
        url = item if item.startswith("http") else "https://" + item
        return rf"\href{{{tex(url)}}}{{\mbox{{{tex(item)}}}}}"
    return rf"\mbox{{{tex(item)}}}"


def body(resume: dict) -> str:
    out = [
        r"\cvheader{%s}{%s}{%s}"
        % (tex(resume["name"]), tex(resume["headline"]), r"\cvsep ".join(map(_contact, resume["contact"])))
    ]
    for section in resume["sections"]:
        out.append(r"\cvsection{%s}" % tex(section["heading"]))
        out += [r"\cvpara{%s}" % tex(p) for p in section["paragraphs"]]
        for entry in section["entries"]:
            out.append(r"\cventry{%s}{%s}{%s}" % (tex(entry["title"]), tex(entry["subtitle"]), tex(entry["dates"])))
            if entry["bullets"]:
                out.append(r"\begin{cvbullets}")
                out += [r"\item " + tex(b) for b in entry["bullets"]]
                out.append(r"\end{cvbullets}")
        out += [r"\cvskill{%s}{%s}" % (tex(s["label"]), tex(", ".join(s["items"]))) for s in section["skills"]]
    return "\n".join(out)


# Each step is (font size reduction in pt, tighter margins?). Tried in order when fitting.
FIT_STEPS = ((0, False), (0.5, False), (1, False), (1, True))
TIGHT = r"\geometry{left=.65in,right=.65in,top=.55in,bottom=.55in}"
WATERMARK = (r"\usepackage{draftwatermark}"
             r"\DraftwatermarkOptions{text={DRAFT\\UNVERIFIED CLAIMS},fontsize=44pt,color={[gray]{0.86}},angle=50}")


def document(resume: dict, template: Template, paper: str = "letter", shrink: float = 0,
             tight: bool = False, watermark: bool = False) -> str:
    replacements = {
        "%%PAPER%%": {"letter": "letterpaper", "a4": "a4paper"}[paper],
        "%%FONTSIZE%%": f"{template.fontsize - shrink:g}",
        "%%FIT%%": TIGHT if tight else "",
        "%%WATERMARK%%": WATERMARK if watermark else "",
        "%%PDFTITLE%%": tex(f"{resume['name']} - Resume"),
        "%%PDFAUTHOR%%": tex(resume["name"]),
        "%%BODY%%": body(resume),
    }
    source = template.tex()
    for placeholder, value in replacements.items():
        source = source.replace(placeholder, value)
    return source


@dataclass
class Built:
    pages: int
    source: str
    fits: bool  # within the page target, with no near-empty last page
    room: int   # words that fit on the pages the resume should occupy


def _compile(source: str, target: Path) -> list[int]:
    """Compile in a throwaway directory so no .aux/.log files are left behind.

    Returns the number of words on each page of the PDF written to `target`.
    """
    from pypdf import PdfReader

    if not shutil.which("tectonic"):
        raise RuntimeError("Tectonic is not installed. See https://tectonic-typesetting.github.io (macOS: brew install tectonic).")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "resume.tex"
        path.write_text(source, encoding="utf-8")
        run = subprocess.run(["tectonic", "--untrusted", str(path)], capture_output=True, text=True)
        if run.returncode:
            raise RuntimeError("LaTeX compilation failed:\n" + run.stderr.strip()[-1500:])
        pdf = path.with_suffix(".pdf")
        words = [len((page.extract_text() or "").split()) for page in PdfReader(pdf).pages]
        if not sum(words):
            raise RuntimeError("The generated PDF has no extractable text.")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, target)
        return words


def build_pdf(resume: dict, template: Template, target: Path, paper: str = "letter",
              pages: int | None = None, watermark: bool = False) -> Built:
    """Write the PDF, nudging type size and margins so the text fits its pages.

    Two cases are corrected: the resume runs past the target page count, or its last page
    holds only a few stray lines. If typography alone cannot fix it, `fits` is False and
    `room` says how many words would fit, so the caller can ask for a shorter text.
    """
    goal = pages or template.pages
    source = document(resume, template, paper, watermark=watermark)
    words = _compile(source, target)
    leftover = len(words) > 1 and words[-1] < 0.35 * (sum(words[:-1]) / len(words[:-1]))
    if len(words) <= goal and not leftover:
        return Built(len(words), source, True, sum(words))
    wanted = goal if len(words) > goal else len(words) - 1
    scratch = target.with_name(target.name + ".fit")
    try:
        for shrink, tight in FIT_STEPS[1:]:
            candidate = document(resume, template, paper, shrink, tight, watermark)
            fitted = _compile(candidate, scratch)
            if len(fitted) <= wanted:
                scratch.replace(target)
                return Built(len(fitted), candidate, True, sum(fitted))
    finally:
        scratch.unlink(missing_ok=True)
    return Built(len(words), source, False, sum(words[:wanted]))
