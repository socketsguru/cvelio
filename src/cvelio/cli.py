"""Cvelio command line. The Makefile wraps these commands; `make help` lists them."""
import argparse
import os
import random
import re
import shutil
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__, config, enrich, profile, render, report
from .llm import PROVIDERS, LLMError, available, pick_model, pick_provider
from .tailor import gap_policy, shorten, tailor
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


def ask(question: str, default: str, choices: tuple[str, ...] = ()) -> str:
    """Ask on the terminal; Enter keeps the default. Unattended runs keep the default too."""
    if not sys.stdin.isatty():
        return default
    hint = f" ({'/'.join(c or 'skip' for c in choices)})" if choices else ""
    while True:
        answer = input(f"{question}{hint} [{default or 'skip'}]: ").strip()
        if not answer:
            return default
        if answer == "skip":
            return ""
        if not choices or answer in choices:
            return answer
        say(f"  Please answer one of: {', '.join(c or 'skip' for c in choices)}")


def cmd_init(args) -> None:
    settings = dict(config.load())
    if sys.stdin.isatty():
        say("A few questions. Press Enter to keep the value in brackets.\n")
    settings["voice"] = ask(
        "Voice of the summary: 'implied' has no pronouns (\"Engineer with 9 years...\"), 'first' says \"I\"",
        settings.get("voice") or "implied", config.VOICES)
    gender = ask("Your grammatical gender, used only where a language needs it (Spanish: Ingeniero/Ingeniera)",
                 settings.get("gender") or "", config.GENDERS)
    settings.pop("gender", None)
    if gender:
        settings["gender"] = gender
    ssm = dict(settings.get("aws_ssm") or {})
    prefix = ask("AWS Parameter Store path holding your API keys (skip if you use env vars or .env)", ssm.get("prefix") or "")
    settings.pop("aws_ssm", None)
    if prefix:
        ssm["prefix"] = prefix
        region = ask("AWS region of that path", ssm.get("region") or os.getenv("AWS_REGION") or "")
        if region:
            ssm["region"] = region
        settings["aws_ssm"] = ssm
    config.save(settings)
    say(f"Settings written to {config.path()}")

    target = profile_path(args)
    if target.exists() and not args.force:
        say(f"Profile kept as it is: {target} (pass FORCE=1 to replace it)")
        return
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


def cmd_enrich(args) -> None:
    path = profile_path(args)
    data, profile_text = profile.load(path)
    provider = pick_provider(args.provider)
    model = pick_model(provider, args.model)
    contact = data.get("contact") if isinstance(data.get("contact"), dict) else {}
    url = args.linkedin or next((str(l) for l in contact.get("links") or [] if "linkedin.com/in/" in str(l)), "")
    sources = {"github": enrich.github}
    if url:
        sources["linkedin"] = lambda: enrich.linkedin(url if url.startswith("http") else "https://" + url)
    if args.only:
        sources = {k: v for k, v in sources.items() if k == args.only}
        if not sources:
            raise LLMError("No LinkedIn address. Pass LINKEDIN=https://www.linkedin.com/in/you or add it to your profile's links.")
    done = 0
    for name, fetch in sources.items():
        say(f"Reading {name}...")
        try:
            material = fetch()
            target, found = enrich.digest(name, material, profile_text, path, provider, model)
        except LLMError as error:
            say(f"  skipped: {error}")
            continue
        done += 1
        say(f"  {', '.join(f'{len(v)} {k}' for k, v in found.items()) or 'nothing new'} -> {target}")
    if not done:
        raise SystemExit("Nothing was gathered.")
    say("\nReview those files: every build reads them alongside your profile.")


def read_job(job: str) -> tuple[str, str]:
    if job != "-":
        return Path(job).expanduser().read_text(encoding="utf-8").strip(), Path(job).stem
    if sys.stdin.isatty():
        say("Paste the job posting. To finish, type EOF on a line of its own and press Enter.")
        lines = []
        for line in sys.stdin:
            if line.strip() == "EOF":
                break
            lines.append(line)
        return "".join(lines).strip(), "job"
    return sys.stdin.read().strip(), "job"


def plan(args) -> list[tuple]:
    """Which (template, provider, model) combinations to build.

    Naming a template or a provider builds exactly that one. Naming neither builds every
    template, each written by a provider drawn at random from the ones that have a key.
    """
    if args.template or args.provider or args.model:
        provider = pick_provider(args.provider)
        return [(TEMPLATES[args.template or DEFAULT_TEMPLATE], provider, pick_model(provider, args.model))]
    providers = [p for p in available() if p.default_model or os.getenv("CVELIO_MODEL")]
    if not providers:
        pick_provider()  # raises the helpful "no key" error
    random.shuffle(providers)
    return [(t, providers[i % len(providers)], pick_model(providers[i % len(providers)]))
            for i, t in enumerate(TEMPLATES.values())]


def cmd_build(args) -> None:
    settings = config.load()
    policy = gap_policy(args.fill)
    _, profile_text = profile.load(profile_path(args))
    job, stem = read_job(args.job)
    if not job:
        raise SystemExit("The job posting is empty.")
    variants = plan(args)
    watermark = policy == "free" and not args.force
    voice = settings.get("voice") if settings.get("voice") in config.VOICES else "implied"

    say(f"Writing {len(variants)} resume{'s' if len(variants) > 1 else ''} (gap filling: {policy}):")
    for template, provider, model in variants:
        say(f"  {template.name:<10} {provider.name} ({model})")

    def write(variant):
        template, provider, model = variant
        try:
            return tailor(profile_text, job, template, provider, model, lang=args.lang,
                          pages=args.pages or template.pages, fill=args.fill, voice=voice,
                          gender=settings.get("gender") or "")
        except (LLMError, KeyError, IndexError, TypeError) as error:
            return error

    with ThreadPoolExecutor(max_workers=len(variants)) as pool:
        results = list(pool.map(write, variants))
    first = next((r for r in results if isinstance(r, dict)), None)
    if first is None:
        raise LLMError("; ".join(f"{v[1].name}: {r}" for v, r in zip(variants, results)))
    folder = Path(args.out) / slug(f"{first['analysis']['company']} {first['analysis']['role']}", fallback=slug(stem))

    say()
    for (template, provider, model), result in zip(variants, results):
        label = f"{template.name}-{provider.name}"
        if not isinstance(result, dict):
            say(f"  {template.name} · {provider.name}: failed ({result})\n")
            continue
        pages = args.pages or template.pages
        pdf = folder / f"{slug(result['resume']['name'])}-{label}.pdf"
        try:
            built = render.build_pdf(result["resume"], template, pdf, args.paper, pages, watermark)
            for keep in (0.92, 0.8):  # two attempts: models rarely cut enough the first time
                if built.fits:
                    break
                say(f"  {template.name}: too long for {pages} clean page{'s' if pages > 1 else ''}; trimming...")
                result = shorten(result, int(built.room * keep), provider, model)
                built = render.build_pdf(result["resume"], template, pdf, args.paper, pages, watermark)
        except (LLMError, RuntimeError) as error:
            say(f"  {template.name} · {provider.name}: failed ({error})\n")
            continue
        checks = report.check(result, profile_text)
        if args.tex:
            pdf.with_suffix(".tex").write_text(built.source, encoding="utf-8")
        meta = {"template": template.name, "provider": provider.name, "model": model, "pages": built.pages, "policy": policy}
        (folder / f"report-{label}.md").write_text(report.markdown(result, checks, meta), encoding="utf-8")
        total = len(checks["covered"]) + len(checks["missing"])
        say(f"  {template.name} · {provider.name} ({model}) · {built.pages} page{'s' if built.pages > 1 else ''}")
        say(f"    Role        {result['analysis']['role']}" + (f" at {result['analysis']['company']}" if result["analysis"]["company"] else ""))
        say(f"    Must-haves  {checks['strong']} strong, {checks['partial']} partial, {checks['gap']} gap")
        say(f"    Keywords    {len(checks['covered'])}/{total} from the posting")
        if checks["added"]:
            say(f"    Added       {len(checks['added'])} claim(s) beyond your profile: {', '.join(a['claim'] for a in checks['added'])[:110]}")
        if built.pages > pages:
            say(f"    Length      {built.pages} pages, target was {pages}")
        say(f"    Report      {folder / f'report-{label}.md'}")
        print(pdf, flush=True)
        say()
    if watermark:
        say("These are aspirational drafts: they contain claims your profile does not support, and are\n"
            "watermarked so they are not sent by mistake. The reports list every added claim.\n")
    if len(variants) > 1:
        source = f"JOB={args.job} " if args.job != "-" else ""
        say(f"Like one? Build exactly that again: make cv {source}TEMPLATE=<template> PROVIDER=<provider>")


def cmd_templates(_args) -> None:
    for t in TEMPLATES.values():
        default = "  (default)" if t.name == DEFAULT_TEMPLATE else ""
        print(f"{t.name:<10} {t.audience}. {t.pages} page{'s' if t.pages > 1 else ''}.{default}")


def cmd_doctor(args) -> None:
    ok = True

    def line(good: bool, label: str, detail: str, required: bool = True) -> None:
        nonlocal ok
        ok = ok and (good or not required)
        print(f"  {'ok ' if good else ('MISSING' if required else '-  ')}  {label:<10} {detail}")

    settings = config.load()
    tectonic = shutil.which("tectonic")
    line(bool(tectonic), "tectonic", tectonic or "not found. macOS: brew install tectonic. Others: https://tectonic-typesetting.github.io")
    path = profile_path(args)
    try:
        data, _ = profile.load(path)
        files = sorted(p.stem for p in enrich.folder(path).glob("*.yaml")) if enrich.folder(path).is_dir() else []
        line(True, "profile", f"{path} ({data['name']}, {len(data.get('experience') or [])} roles)")
        line(bool(files), "evidence", ", ".join(files) if files else "none yet (optional: make enrich)", required=False)
    except profile.ProfileError as error:
        line(False, "profile", str(error))
    ssm = settings.get("aws_ssm") or {}
    line(True, "settings", f"voice: {settings.get('voice') or 'implied'}, gender: {settings.get('gender') or 'not set'}, "
                           f"keys: {'AWS Parameter Store ' + ssm['prefix'] if ssm.get('prefix') else 'environment / .env'}")
    ready = available()
    line(bool(ready), "providers", ", ".join(f"{p.name} ({p.default_model or 'set MODEL'})" for p in ready)
         or "no API key found. Set one in the environment or .env, or run: make init")
    apify, github = bool(config.secret("APIFY_TOKEN", "apify")), bool(config.github_token())
    line(apify, "apify", "token found (LinkedIn for make enrich)" if apify else "no token (only needed to read LinkedIn)", required=False)
    line(github, "github", "token found (repositories for make enrich)" if github else "no token (only needed to read GitHub)", required=False)
    print("\nReady to build." if ok else "\nFix the MISSING items above, then run: make doctor")
    if not ok:
        raise SystemExit(1)


def fill_level(value: str) -> float:
    level = float(value)
    if not 0 <= level <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return level


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="path to your profile (default: ~/.config/cvelio/profile.yaml or $CVELIO_PROFILE)")
    common.add_argument("--provider", choices=list(PROVIDERS), help="model provider")
    common.add_argument("--model", help="model name (default: the provider's default)")

    main = argparse.ArgumentParser(prog="cvelio", description="Turn one profile into a resume aimed at each job posting.")
    main.add_argument("--version", action="version", version=f"cvelio {__version__}")
    sub = main.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("init", parents=[common], help="set your preferences and create your profile",
                       description="Ask a few preference questions, then create your profile if you have none. "
                                   "With files (a resume PDF, a LinkedIn export, notes), a model converts them.")
    p.add_argument("sources", nargs="*", metavar="FILE", help="existing resume or notes to import (pdf, txt, md)")
    p.add_argument("--force", action="store_true", help="replace an existing profile")
    p.set_defaults(run=cmd_init)

    p = sub.add_parser("enrich", parents=[common], help="gather evidence from GitHub and LinkedIn",
                       description="Read your GitHub repositories (descriptions and READMEs, never source code) and "
                                   "your LinkedIn profile and posts, and save what they show as evidence files.")
    p.add_argument("--linkedin", metavar="URL", help="LinkedIn profile address (default: the one in your profile's links)")
    p.add_argument("--only", choices=["github", "linkedin"], help="read just one source")
    p.set_defaults(run=cmd_enrich)

    p = sub.add_parser("build", parents=[common], help="write resumes for one job posting",
                       description="Write PDF resumes aimed at one job posting, each with a fit report. With no "
                                   "template or provider named, writes one per template, each by a random provider.")
    p.add_argument("job", metavar="JOB", nargs="?", default="-", help="text file with the job posting (default: read stdin)")
    p.add_argument("-t", "--template", choices=list(TEMPLATES), help="build only this style (see: cvelio templates)")
    p.add_argument("--fill", type=fill_level, default=0.5, metavar="0..1",
                   help="how freely to fill gaps: 0 adds nothing, 0.5 lists closely related technologies as "
                        "'Familiar with', 1 drafts an aspirational, watermarked resume (default: 0.5)")
    p.add_argument("--force", action="store_true", help="with --fill 1: leave the watermark off")
    p.add_argument("--lang", default="English", help="language of the resume (default: English)")
    p.add_argument("--pages", type=int, choices=[1, 2], help="target length (default: the template's)")
    p.add_argument("--paper", choices=["letter", "a4"], default="letter", help="paper size (default: letter)")
    p.add_argument("-o", "--out", default="output", help="output folder (default: ./output)")
    p.add_argument("--tex", action="store_true", help="also keep the LaTeX source next to each PDF")
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
    except (KeyboardInterrupt, EOFError):
        raise SystemExit("\nCancelled.") from None
    except (LLMError, profile.ProfileError, RuntimeError, OSError) as error:
        raise SystemExit(f"cvelio: {error}") from None
