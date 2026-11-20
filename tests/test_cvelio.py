import shutil

import pytest
import yaml

from cvelio import config, profile, render, report
from cvelio.cli import slug
from cvelio.llm import PROVIDERS, LLMError, pick_model
from cvelio.tailor import fence_additions, gap_policy, normalize
from cvelio.templates import TEMPLATES

RAW = {
    "analysis": {"role": "Backend Engineer", "company": "Acme", "keywords": ["Go", "REST", "Kafka", "CI/CD"]},
    "resume": {
        "name": "Ana Torres",
        "headline": "Senior Engineer, R&D",
        "contact": ["Guadalajara, Mexico", "ana_t@example.com", "github.com/ana", "+52 55 5555 0101"],
        "sections": [
            {"heading": "Summary", "paragraphs": ["Built 100% of the Go & REST services for $5."]},
            {"heading": "Experience", "entries": [
                {"title": "Tech Lead", "subtitle": "Rutalia", "dates": "2022 – Present",
                 "bullets": ["Shipped x_y with CI/CD.", "", None]},
                {"title": "", "bullets": []},
            ]},
            {"heading": "Skills", "skills": [{"label": "Languages", "items": ["Go", "Rust"]}, {"label": "Empty", "items": []}]},
            {"heading": "Nothing here"},
        ],
    },
    "coverage": [{"requirement": "Go", "status": "strong", "evidence": "x"}, {"requirement": "Kafka", "status": "weird"}],
}
PROFILE = "Built Go services and REST APIs. Set up CI/CD pipelines."


def test_normalize_drops_empty_parts_and_fixes_statuses():
    result = normalize(RAW)
    sections = result["resume"]["sections"]
    assert [s["heading"] for s in sections] == ["Summary", "Experience", "Skills"]
    assert sections[1]["entries"] == [
        {"title": "Tech Lead", "subtitle": "Rutalia", "dates": "2022 – Present", "bullets": ["Shipped x_y with CI/CD."]}
    ]
    assert [s["label"] for s in sections[2]["skills"]] == ["Languages"]
    assert [c["status"] for c in result["coverage"]] == ["strong", "partial"]


def test_normalize_rejects_an_empty_resume():
    with pytest.raises(LLMError):
        normalize({"resume": {"name": "Ana", "sections": []}})


def test_tex_escapes_everything_latex_could_run():
    assert render.tex("50% of C# & $5 {x} a_b ~ ^ \\input") == (
        r"50\% of C\# \& \$5 \{x\} a\_b \textasciitilde{} \textasciicircum{} \textbackslash{}input"
    )


def test_contains_matches_whole_terms_only():
    assert report.contains("Built APIs in Go.", "go")
    assert not report.contains("Worked at Google.", "Go")
    assert report.contains("Wrote CI/CD pipelines", "CI/CD pipeline")
    assert report.contains("C++ and Node.js", "node.js")
    assert not report.contains("anything", "  ")


def test_check_reports_coverage_and_unverified_terms():
    checks = report.check(normalize(RAW), PROFILE)
    assert checks["covered"] == ["Go", "REST", "CI/CD"]
    assert checks["missing"] == ["Kafka"]
    assert checks["unverified"] == ["Rust"]  # in the resume, never in the profile
    assert checks["keyword_coverage"] == 0.75
    assert "Rust" in report.markdown(normalize(RAW), checks, {"template": "t", "provider": "p", "model": "m", "pages": 1})


def test_example_profile_is_valid(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text(profile.example(), encoding="utf-8")
    data, text = profile.load(path)
    assert data["name"] == "Ana Torres" and "#" not in text.splitlines()[0]
    assert yaml.safe_load(text) == data  # no evidence folder: the profile alone


@pytest.mark.parametrize("content", ["", "name: ''", "name: Ana", "- just\n- a list", "name: [unclosed"])
def test_bad_profiles_are_rejected(tmp_path, content):
    path = tmp_path / "profile.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(profile.ProfileError):
        profile.load(path)


def test_slug():
    assert slug("Lumen Health Señor Frontend Engineer!") == "lumen-health-senor-frontend-engineer"
    assert slug(" ", fallback="job") == "job"


@pytest.mark.parametrize("name", list(TEMPLATES))
def test_document_fills_every_placeholder(name):
    source = render.document(normalize(RAW)["resume"], TEMPLATES[name], "a4")
    assert "%%" not in source and "a4paper" in source
    assert r"\href{mailto:ana\_t@example.com}" in source and r"\mbox{+52 55 5555 0101}" in source


@pytest.mark.skipif(not shutil.which("tectonic"), reason="tectonic not installed")
@pytest.mark.parametrize("name", list(TEMPLATES))
def test_templates_compile_and_leave_no_intermediate_files(tmp_path, name):
    built = render.build_pdf(normalize(RAW)["resume"], TEMPLATES[name], tmp_path / "out" / "resume.pdf")
    assert built.pages == 1 and built.fits
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["resume.pdf"]


def test_watermark_only_when_asked():
    resume = normalize(RAW)["resume"]
    assert "draftwatermark" not in render.document(resume, TEMPLATES["corporate"])
    assert "UNVERIFIED CLAIMS" in render.document(resume, TEMPLATES["corporate"], watermark=True)


@pytest.mark.skipif(not shutil.which("tectonic"), reason="tectonic not installed")
def test_watermarked_pdf_compiles(tmp_path):
    built = render.build_pdf(normalize(RAW)["resume"], TEMPLATES["startup"], tmp_path / "w.pdf", watermark=True)
    assert built.pages == 1


def test_gap_policy_levels():
    assert [gap_policy(x) for x in (0, 0.2, 0.5, 0.74, 0.75, 1)] == ["strict", "strict", "adjacent", "adjacent", "free", "free"]
    with pytest.raises(LLMError):
        gap_policy(1.5)


def test_added_claims_reach_the_report():
    result = normalize({**RAW, "added": [{"claim": "Angular", "basis": "uses React and Vue"}, {"claim": ""}]})
    assert result["added"] == [{"claim": "Angular", "basis": "uses React and Vue"}]
    text = report.markdown(result, report.check(result, PROFILE), {"template": "t", "provider": "p", "model": "m", "pages": 1, "policy": "adjacent"})
    assert "Added beyond your profile" in text and "**Angular**: uses React and Vue" in text


def test_secret_prefers_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("CVELIO_SSM_PREFIX", raising=False)
    config.load.cache_clear(), config.secret.cache_clear()
    monkeypatch.setenv("SOME_KEY", " abc ")
    assert config.secret("SOME_KEY", "some") == "abc"
    assert config.secret("ABSENT_KEY", "absent") == ""  # no Parameter Store configured: no AWS call
    config.load.cache_clear(), config.secret.cache_clear()


def test_evidence_is_read_with_the_profile(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text(profile.example(), encoding="utf-8")
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "github.yaml").write_text("projects:\n- name: tarifa\n  visibility: private\n", encoding="utf-8")
    _, text = profile.load(path)
    assert "evidence_from_github" in text and "visibility: private" in text


def test_adjacent_additions_are_fenced_into_familiar_with():
    result = normalize({**RAW, "added": [{"claim": "Rust", "basis": "uses Go"}, {"claim": "CI/CD", "basis": ""},
                                         {"claim": "Never used anywhere", "basis": ""}]})
    fence_additions(result, "Spanish")
    skills = result["resume"]["sections"][2]["skills"]
    assert skills == [{"label": "Languages", "items": ["Go"]}, {"label": "Familiaridad con", "items": ["Rust"]}]
    added = {a["claim"]: a["basis"] for a in result["added"]}
    assert set(added) == {"Rust", "CI/CD", "Never used anywhere"} and "WARNING" in added["CI/CD"] and "WARNING" not in added["Rust"]


def test_model_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.load.cache_clear()
    for name in ("CVELIO_MODEL", "OPENROUTER_MODEL", "OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert pick_model(PROVIDERS["openrouter"]) == "openrouter/free"
    monkeypatch.setenv("CVELIO_MODEL", "global")
    monkeypatch.setenv("OPENROUTER_MODEL", "mine")
    assert pick_model(PROVIDERS["openrouter"]) == "mine"
    assert pick_model(PROVIDERS["anthropic"]) == "global"
    assert pick_model(PROVIDERS["openrouter"], "explicit") == "explicit"
    monkeypatch.delenv("CVELIO_MODEL")
    with pytest.raises(LLMError):
        pick_model(PROVIDERS["openai"])
    config.load.cache_clear()
