"""Measure whether resumes are aimed at their posting or come out generic.

Tailors one profile to every posting in a folder and prints three things:

  fit        how the resume answers its own posting (must-haves and keyword coverage)
  cross-fit  each resume scored against every posting's keywords. A targeted resume scores
             clearly higher on its own posting (the diagonal) than on the others.
  overlap    how many bullets two resumes share word for word. High overlap means the
             model is reusing one generic resume.

Costs one model call per posting.

    uv run python evals/run.py                         # example profile, example jobs
    uv run python evals/run.py --profile ~/.config/cvelio/profile.yaml --pdf
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cvelio import profile, render, report
from cvelio.cli import load_dotenv
from cvelio.llm import pick_model, pick_provider
from cvelio.tailor import tailor
from cvelio.templates import DEFAULT_TEMPLATE, TEMPLATES

ROOT = Path(__file__).resolve().parent.parent


def bullets(resume: dict) -> set[str]:
    return {b for s in resume["sections"] for e in s["entries"] for b in e["bullets"]}


def cross_fit(results: dict, texts: dict) -> dict:
    """matrix[resume][posting] = share of that posting's keywords found in that resume."""
    matrix = {}
    for name, text in texts.items():
        matrix[name] = {}
        for other, result in results.items():
            keywords = result["analysis"]["keywords"]
            matrix[name][other] = sum(report.contains(text, k) for k in keywords) / max(len(keywords), 1)
    return matrix


def print_matrix(title: str, names: list[str], cell) -> None:
    width = max(map(len, names)) + 2
    print(f"\n{title}\n" + " " * width + "".join(f"{n[:11]:>12}" for n in names))
    for a in names:
        print(f"{a:<{width}}" + "".join(f"{cell(a, b):>12}" for b in names))


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", help="profile to use (default: the bundled fictional example)")
    ap.add_argument("--jobs", default=str(ROOT / "examples/jobs"), help="folder of job postings (*.txt)")
    ap.add_argument("-t", "--template", choices=list(TEMPLATES), default=DEFAULT_TEMPLATE)
    ap.add_argument("--provider")
    ap.add_argument("--model")
    ap.add_argument("--pdf", action="store_true", help="also render each resume to PDF")
    ap.add_argument("-o", "--out", default="output/evals")
    args = ap.parse_args()

    if args.profile:
        _, profile_text = profile.load(Path(args.profile).expanduser())
    else:
        import yaml

        profile_text = yaml.safe_dump(yaml.safe_load(profile.example()), sort_keys=False, allow_unicode=True, width=100)
    jobs = {p.stem: p.read_text(encoding="utf-8") for p in sorted(Path(args.jobs).glob("*.txt"))}
    if not jobs:
        sys.exit(f"No .txt postings in {args.jobs}")
    provider = pick_provider(args.provider)
    model = pick_model(provider, args.model)
    template = TEMPLATES[args.template]
    print(f"{len(jobs)} postings · {provider.name}/{model} · template {template.name}")

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {name: pool.submit(tailor, profile_text, job, template, provider, model) for name, job in jobs.items()}
        results = {name: future.result() for name, future in futures.items()}

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = list(results)
    texts = {n: report.resume_text(results[n]["resume"]) for n in names}
    print(f"\n{'posting':<14}{'headline':<58}{'must-haves':>12}{'keywords':>10}{'check':>7}{'words':>7}{'pages':>7}")
    for n in names:
        checks = report.check(results[n], profile_text)
        pages = "-"
        if args.pdf:
            pages = render.build_pdf(results[n]["resume"], template, out / f"{n}.pdf").pages
        (out / f"{n}.json").write_text(json.dumps(results[n], indent=2, ensure_ascii=False), encoding="utf-8")
        meta = {"template": template.name, "provider": provider.name, "model": model, "pages": pages}
        (out / f"{n}.md").write_text(report.markdown(results[n], checks, meta), encoding="utf-8")
        must = f"{checks['strong']}/{checks['partial']}/{checks['gap']}"
        print(f"{n:<14}{results[n]['resume']['headline'][:56]:<58}{must:>12}{checks['keyword_coverage']:>10.0%}"
              f"{len(checks['unverified']):>7}{checks['words']:>7}{pages:>7}")
    print("must-haves = strong/partial/gap · check = terms not word for word in the profile")

    matrix = cross_fit(results, texts)
    print_matrix("cross-fit: rows are resumes, columns are postings", names, lambda a, b: f"{matrix[a][b]:.0%}")
    own = sum(matrix[n][n] for n in names) / len(names)
    others = sum(matrix[a][b] for a in names for b in names if a != b) / max(len(names) * (len(names) - 1), 1)
    print(f"\nown posting {own:.0%} · other postings {others:.0%} · targeting margin {own - others:+.0%}")

    sets = {n: bullets(results[n]["resume"]) for n in names}
    print_matrix("overlap: bullets shared word for word", names,
                 lambda a, b: "-" if a == b else f"{len(sets[a] & sets[b]) / max(len(sets[a] | sets[b]), 1):.0%}")
    print(f"\nResults saved in {out}/")


if __name__ == "__main__":
    main()
