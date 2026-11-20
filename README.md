# Cvelio

Cvelio writes a resume aimed at one job posting. You keep a single profile with everything true about your career; for each posting, a language model picks and reframes the facts that matter for that job, and LaTeX typesets the PDF.

It never adds facts that are not in your profile. When a posting asks for something you have no evidence for, Cvelio leaves it out and tells you.

## Install

You need [uv](https://docs.astral.sh/uv/) and [Tectonic](https://tectonic-typesetting.github.io) (the LaTeX engine; on macOS, `brew install tectonic`).

```sh
uv tool install git+https://github.com/socketsguru/cvelio
```

Then give it one API key. Cvelio reads it from the environment or from a `.env` file in the current folder (see [.env.example](.env.example)):

```sh
export ANTHROPIC_API_KEY=...      # or GEMINI_API_KEY, OPENROUTER_API_KEY, OPENAI_API_KEY
```

## Use

There are four commands.

| Command | What it does | When |
| --- | --- | --- |
| `cvelio init` | Creates your profile | Once |
| `cvelio build JOB` | Writes a resume and a fit report for one posting | Every application |
| `cvelio templates` | Lists the styles | When choosing a look |
| `cvelio doctor` | Checks Tectonic, your profile and your API key | When something fails |

### 1. Create your profile

```sh
cvelio init resume.pdf linkedin.txt   # a model converts your existing documents
cvelio init                           # or start from a commented example
```

The profile is a YAML file at `~/.config/cvelio/profile.yaml`, outside any repository. Open it and add detail. It should hold more than fits on a resume: every project, number and technology you might want to mention. Each build chooses from it, so a richer profile gives better-aimed resumes. [The example](src/cvelio/profile.example.yaml) shows the format.

### 2. Build a resume for a posting

Save the posting as a text file, or pipe it in:

```sh
cvelio build posting.txt
pbpaste | cvelio build - --template startup
```

```
  Role        Senior DevOps Engineer at Northwind Freight
  Must-haves  3 strong, 4 partial, 1 gap
  Keywords    11/20 from the posting appear in the resume
  Check       2 term(s) not word for word in your profile (see report)
  Report      output/northwind-freight-senior-devops-engineer/report.md

output/northwind-freight-senior-devops-engineer/ana-torres-resume.pdf
```

Each build writes two files into `output/<company-role>/`:

- the PDF resume;
- `report.md`, which lists each requirement of the posting with the evidence found in your profile, the requirements you have no evidence for, and any term in the resume that does not appear word for word in your profile, so you can confirm it before sending.

If the text runs past its page target, Cvelio first tightens type size and margins, then asks the model to cut the content least relevant to the posting.

Options for `build`:

| Option | Meaning | Default |
| --- | --- | --- |
| `-t`, `--template` | `corporate`, `startup` or `academic` | `corporate` |
| `--lang` | Language of the resume, for example `Spanish` | `English` |
| `--pages` | Target length, `1` or `2` | the template's |
| `--paper` | `letter` or `a4` | `letter` |
| `-o`, `--out` | Output folder | `./output` |
| `--tex` | Also keep the LaTeX source | off |
| `--provider`, `--model` | Which model to use | first provider with a key |
| `--profile` | Use another profile file | `~/.config/cvelio/profile.yaml` |

## Templates

A template sets the look of the page and also the tone, section order and length of the writing.

| Template | For | Look | Writing |
| --- | --- | --- | --- |
| `corporate` | Large enterprises, banks, consultancies, government | Serif, black, ruled headings, up to 2 pages | Formal; scale, compliance, process, work across teams |
| `startup` | Startups and product companies | Sans serif, one accent colour, 1 page | Direct; ownership, things shipped, product impact |
| `academic` | Universities, research labs, graduate programmes | Book serif, small caps, up to 2 pages | Sober; education first, methods, publications, teaching |

## Models

| Provider | Key | Default model |
| --- | --- | --- |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-opus-5-5` |
| `gemini` | `GEMINI_API_KEY` | `gemini-3.8-flash` |
| `openrouter` | `OPENROUTER_API_KEY` | `openrouter/free` |
| `openai` | `OPENAI_API_KEY` | none; pass `--model` |

The `openai` provider works with any OpenAI-compatible endpoint. Set `OPENAI_BASE_URL` to use a local model, for example `http://localhost:11434/v1` for Ollama; in that case your profile never leaves your machine. Each provider's endpoint can be changed with `<PROVIDER>_BASE_URL`.

With a hosted provider, each build sends your profile and the posting to that provider.

## How well does it aim?

`evals/run.py` tailors one profile to the five postings in [examples/jobs](examples/jobs) (DevOps, frontend, data analyst, backend, tech lead) and checks each resume against every posting's keywords. A resume that is aimed scores higher on its own posting than on the others.

```sh
uv run python evals/run.py                                          # fictional example profile
uv run python evals/run.py --profile ~/.config/cvelio/profile.yaml  # your own
```

One run with the example profile and `claude-opus-5-5`: resumes contained 57% of their own posting's keywords and 36% of the other postings', and shared about 10% of their bullets word for word. Results vary from run to run and depend on what the profile contains: where it has no evidence for a role, coverage stays low on purpose.

## Develop

```sh
git clone https://github.com/socketsguru/cvelio && cd cvelio
uv sync
uv run pytest
uv run cvelio doctor
```

The code is in `src/cvelio`: `tailor.py` holds the prompt, `report.py` the checks that involve no model, `render.py` the LaTeX output, and `templates/` one `.tex` file per style plus its writing brief. To add a template, add a `.tex` file that defines the same six macros and an entry in `templates/__init__.py`.

## License

Public domain, under [the Unlicense](LICENSE).
