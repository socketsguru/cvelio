"""Cvelio command line: init, build, templates, doctor."""
import argparse
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

from . import __version__, profile, render, report
from .llm import PROVIDERS, LLMError, pick_model, pick_provider
from .tailor import shorten, tailor
from .templates import DEFAULT_TEMPLATE, TEMPLATES


def say(message: str = "") -> None:
    print(message, file=sys.stderr, flush=True)


def load_dotenv(path: Path = Path(".env")) -> None:
    """Read KEY=VALUE lines from ./.env without overriding the real environment."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().removeprefix("export ").partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def slug(text: str, fallback: str = "resume") -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:60].strip("-") or fallback


def profile_path(args) -> Path:
    return Path(args.profile).expanduser() if args.profile else profile.default_path()


def cmd_init(args) -> None:
    target = profile_path(args)
    if target.exists() and not args.force:
        raise SystemExit(f"{target} already exists. Edit it, or pass --force to replace it.")
    if args.sources:
        sources = [Path(s).expanduser() for s in args.sources]
        provider = pick_provider(args.provider)
        model = pick_model(provider, args.model)
        say(f"Reading {', '.join(p.name for p in sources)} with {provider.name} ({model})...")
        content = profile.import_from(sources, provider, model)
    else:
        content = profile.example()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    say(f"Profile written to {target}")
    say("Review it and add detail: the more facts it holds, the better each resume is aimed."
        if args.sources else "It holds a fictional example. Replace it with your own career.")


def cmd_build(args) -> None:
    template = TEMPLATES[args.template]
    _, profile_text = profile.load(profile_path(args))
    if args.job == "-":
        job, stem = sys.stdin.read().strip(), "job"
    else:
        job, stem = Path(args.job).expanduser().read_text(encoding="utf-8").strip(), Path(args.job).stem
    if not job:
        raise SystemExit("The job posting is empty.")
    provider = pick_provider(args.provider)
    model = pick_model(provider, args.model)

    say(f"Tailoring with {provider.name} ({model}), template '{template.name}'...")
    pages = args.pages or template.pages
    result = tailor(profile_text, job, template, provider, model, lang=args.lang, pages=pages)
    checks = report.check(result, profile_text)
    analysis = result["analysis"]
    folder = Path(args.out) / slug(f"{analysis['company']} {analysis['role']}", fallback=slug(stem))
    pdf = folder / f"{slug(result['resume']['name'])}-resume.pdf"
    built = render.build_pdf(result["resume"], template, pdf, args.paper, pages)
    if not built.fits:
        say(f"Too long for {pages} clean page{'s' if pages > 1 else ''}; trimming the least relevant content...")
        result = shorten(result, int(built.room * 0.95), provider, model)
        checks = report.check(result, profile_text)
        built = render.build_pdf(result["resume"], template, pdf, args.paper, pages)
    actual_pages = built.pages
    if args.tex:
        pdf.with_suffix(".tex").write_text(built.source, encoding="utf-8")
    meta = {"template": template.name, "provider": provider.name, "model": model, "pages": actual_pages}
    (folder / "report.md").write_text(report.markdown(result, checks, meta), encoding="utf-8")

    total = len(checks["covered"]) + len(checks["missing"])
    say()
    say(f"  Role        {analysis['role']}" + (f" at {analysis['company']}" if analysis["company"] else ""))
    say(f"  Must-haves  {checks['strong']} strong, {checks['partial']} partial, {checks['gap']} gap")
    say(f"  Keywords    {len(checks['covered'])}/{total} from the posting appear in the resume")
    if checks["unverified"]:
        say(f"  Check       {len(checks['unverified'])} term(s) not word for word in your profile (see report)")
    if actual_pages > pages:
        say(f"  Length      {actual_pages} pages, target was {pages}. Rebuild, or pass --pages {actual_pages}.")
    say(f"  Report      {folder / 'report.md'}")
    say()
    print(pdf)


def cmd_templates(_args) -> None:
    for t in TEMPLATES.values():
        default = "  (default)" if t.name == DEFAULT_TEMPLATE else ""
        print(f"{t.name:<10} {t.audience}. {t.pages} page{'s' if t.pages > 1 else ''}.{default}")


def cmd_doctor(args) -> None:
    ok = True

    def line(good: bool, label: str, detail: str, required: bool = True) -> None:
        nonlocal ok
        ok = ok and (good or not required)
        print(f"  {'ok ' if good else ('MISSING' if required else '-  ')}  {label:<12} {detail}")

    tectonic = shutil.which("tectonic")
    line(bool(tectonic), "tectonic", tectonic or "not found. macOS: brew install tectonic. Others: https://tectonic-typesetting.github.io")
    path = profile_path(args)
    try:
        data, _ = profile.load(path)
        line(True, "profile", f"{path} ({data['name']}, {len(data.get('experience') or [])} roles)")
    except profile.ProfileError as error:
        line(False, "profile", str(error))
    try:
        chosen = pick_provider(args.provider)
        line(True, "provider", f"{chosen.name} (model: {pick_model(chosen, args.model)})")
    except LLMError as error:
        line(False, "provider", str(error))
    for p in PROVIDERS.values():
        line(bool(os.getenv(p.key_env)), p.key_env, "set" if os.getenv(p.key_env) else "not set", required=False)
    print("\nReady to build." if ok else "\nFix the MISSING items above, then run: cvelio doctor")
    if not ok:
        raise SystemExit(1)


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="path to your profile (default: ~/.config/cvelio/profile.yaml or $CVELIO_PROFILE)")
    common.add_argument("--provider", choices=list(PROVIDERS), help="model provider (default: the first one with an API key set)")
    common.add_argument("--model", help="model name (default: the provider's default)")

    main = argparse.ArgumentParser(prog="cvelio", description="Turn one profile into a resume aimed at each job posting.")
    main.add_argument("--version", action="version", version=f"cvelio {__version__}")
    sub = main.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("init", parents=[common], help="create your profile (once)",
                       description="Create your profile. With no files, writes a commented example to edit. "
                                   "With files (a resume PDF, a LinkedIn export, notes), a model converts them.")
    p.add_argument("sources", nargs="*", metavar="FILE", help="existing resume or notes to import (pdf, txt, md)")
    p.add_argument("--force", action="store_true", help="replace an existing profile")
    p.set_defaults(run=cmd_init)

    p = sub.add_parser("build", parents=[common], help="write a resume for one job posting",
                       description="Write a PDF resume aimed at one job posting, plus a fit report.")
    p.add_argument("job", metavar="JOB", help="text file with the job posting, or - to read it from stdin")
    p.add_argument("-t", "--template", choices=list(TEMPLATES), default=DEFAULT_TEMPLATE, help="style (see: cvelio templates)")
    p.add_argument("--lang", default="English", help="language of the resume (default: English)")
    p.add_argument("--pages", type=int, choices=[1, 2], help="target length (default: the template's)")
    p.add_argument("--paper", choices=["letter", "a4"], default="letter", help="paper size (default: letter)")
    p.add_argument("-o", "--out", default="output", help="output folder (default: ./output)")
    p.add_argument("--tex", action="store_true", help="also keep the LaTeX source next to the PDF")
    p.set_defaults(run=cmd_build)

    p = sub.add_parser("templates", help="list the available styles")
    p.set_defaults(run=cmd_templates)

    p = sub.add_parser("doctor", parents=[common], help="check that everything is set up")
    p.set_defaults(run=cmd_doctor)
    return main


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    args = parser().parse_args(argv)
    try:
        args.run(args)
    except KeyboardInterrupt:
        raise SystemExit("Cancelled.") from None
    except (LLMError, profile.ProfileError, RuntimeError, OSError) as error:
        raise SystemExit(f"cvelio: {error}") from None
