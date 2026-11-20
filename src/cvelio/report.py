"""Deterministic checks on a tailored resume: no model involved, so they can be trusted."""
import re


def resume_text(resume: dict) -> str:
    parts = [resume["headline"]]
    for section in resume["sections"]:
        parts.append(section["heading"])
        parts += section["paragraphs"]
        for entry in section["entries"]:
            parts += [entry["title"], entry["subtitle"], *entry["bullets"]]
        for skill in section["skills"]:
            parts += [skill["label"], *skill["items"]]
    return "\n".join(parts)


def contains(text: str, term: str) -> bool:
    """Whole-term, case-insensitive match that tolerates a plural: 'Go' never matches 'Google'."""
    term = " ".join(term.lower().split())
    if not term:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(term).replace(r"\ ", r"\s+") + r"(?:s|es)?(?![a-z0-9])"
    return re.search(pattern, text.lower()) is not None


def check(result: dict, profile_text: str) -> dict:
    """Compare the resume with the posting's keywords and with the profile.

    covered     posting keywords that appear in the resume
    missing     posting keywords that do not
    unverified  skills or keywords in the resume that never appear literally in the profile;
                usually a harmless rewording, occasionally an invented claim worth a look
    """
    text = resume_text(result["resume"])
    keywords = list(dict.fromkeys(result["analysis"]["keywords"]))
    covered = [k for k in keywords if contains(text, k)]
    skills = [i for s in result["resume"]["sections"] for skill in s["skills"] for i in skill["items"]]
    unverified = [t for t in dict.fromkeys(covered + skills) if not contains(profile_text, t)]
    statuses = [c["status"] for c in result["coverage"]]
    return {
        "covered": covered,
        "missing": [k for k in keywords if k not in covered],
        "unverified": unverified,
        "keyword_coverage": len(covered) / len(keywords) if keywords else 0.0,
        "strong": statuses.count("strong"), "partial": statuses.count("partial"), "gap": statuses.count("gap"),
        "words": len(text.split()),
        "added": result.get("added", []),
    }


def markdown(result: dict, checks: dict, meta: dict) -> str:
    a = result["analysis"]
    lines = [
        f"# Fit report: {a['role'] or 'role'}" + (f" at {a['company']}" if a["company"] else ""),
        "",
        f"- Template: {meta['template']} · Gap filling: {meta.get('policy', 'strict')} · Model: {meta['provider']}/{meta['model']} · Pages: {meta['pages']} · Words: {checks['words']}",
        f"- Must-haves: {checks['strong']} strong, {checks['partial']} partial, {checks['gap']} gap",
        f"- Posting keywords in the resume: {len(checks['covered'])}/{len(checks['covered']) + len(checks['missing'])} ({checks['keyword_coverage']:.0%})",
        "",
        "## Must-have requirements",
        "",
        "| Requirement | Status | Evidence in your profile |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {c['requirement']} | {c['status']} | {c['evidence'] or '-'} |".replace("\n", " ") for c in result["coverage"]]
    lines += ["", "## Keywords", "", "- In the resume: " + (", ".join(checks["covered"]) or "none"),
              "- Not in the resume: " + (", ".join(checks["missing"]) or "none")]
    if checks["unverified"]:
        lines += ["", "## Check these by hand", "",
                  "These terms are in the resume but not word for word in your profile. Most are "
                  "rewordings; make sure none is a claim you cannot back up.", "",
                  "- " + ", ".join(checks["unverified"])]
    if checks["added"]:
        lines += ["", "## Added beyond your profile", "",
                  "Your profile does not state these. They were added under the gap-filling level "
                  "you chose. Remove any you could not discuss in an interview, or build with FILL=0.", ""]
        lines += [f"- **{a['claim']}**: {a['basis'] or 'no basis given'}" for a in checks["added"]]
    gaps = [c["requirement"] for c in result["coverage"] if c["status"] == "gap"]
    if gaps:
        lines += ["", "## Gaps", "",
                  "The posting asks for these and your profile shows no evidence. They were left "
                  "out on purpose. If you do have the experience, add it to your profile and rebuild.", ""]
        lines += [f"- {g}" for g in gaps]
    return "\n".join(lines) + "\n"
