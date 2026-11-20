# Cvelio

Cvelio writes a resume aimed at one job posting. You keep a single profile with everything true about your career; for each posting, a language model picks and reframes the facts that matter for that job, and LaTeX typesets the PDF in Latin Modern, the classic LaTeX typeface.

## Install

You need [uv](https://docs.astral.sh/uv/), GNU Make and [Tectonic](https://tectonic-typesetting.github.io) (the LaTeX engine; on macOS, `brew install tectonic`).

```sh
git clone https://github.com/socketsguru/cvelio && cd cvelio
make help
```

Cvelio needs one API key: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY` or `OPENAI_API_KEY`. It looks in the environment, then in a `.env` file in the project folder (see [.env.example](.env.example)), then in AWS Parameter Store if you set that up during `make init`.

## Use

| Command | What it does | When |
| --- | --- | --- |
| `make init` | Asks your preferences and creates your profile | Once |
| `make enrich` | Adds evidence from your GitHub and LinkedIn | Now and then |
| `make cv JOB=posting.txt` | Writes resumes and fit reports for one posting | Every application |
| `make doctor` | Checks LaTeX, your profile and your keys | When something fails |
| `make clean` | Deletes generated files; keeps your profile | Whenever |

`make help` lists every command and option.

### 1. Set up

```sh
make init FROM="resume.pdf notes.txt"   # a model converts your existing documents
make init                               # or start from a commented example
```

`make init` asks three things. Press Enter to keep the value shown.

- **Voice.** `implied` writes without pronouns ("Backend engineer with nine years in payments. Built..."), the usual convention for resumes. `first` writes the summary with "I"; bullets keep the implied subject either way.
- **Grammatical gender.** Used only where a language needs agreement, such as "Ingeniero" or "Ingeniera" in Spanish. Cvelio never guesses it from your name.
- **Where your API keys live.** Skip this if you use environment variables or `.env`. If you keep keys in AWS Parameter Store, give the path (for example `/myteam/keys/`); Cvelio then reads `<path>/anthropic`, `<path>/gemini`, `<path>/openrouter`, `<path>/openai` and `<path>/apify` with your own AWS session.

Your answers go to `~/.config/cvelio/config.yaml` and your profile to `~/.config/cvelio/profile.yaml`, both outside the repository. Open the profile and add detail. It should hold more than fits on a resume: every project, number and technology you might want to mention. [The example](src/cvelio/profile.example.yaml) shows the format.

### 2. Add evidence from GitHub and LinkedIn (optional)

```sh
make enrich
```

This reads two sources and saves what they show about you in `~/.config/cvelio/evidence/`:

- **GitHub**: the description, languages, topics and README of each repository your token can see, public and private, yours and your organisations'. It never reads source code. The token comes from `GITHUB_TOKEN`, the `gh` CLI or git's credential helper.
- **LinkedIn**: your profile and recent posts, fetched through [Apify](https://apify.com) (needs `APIFY_TOKEN`; Apify charges a few cents per run). The address comes from your profile's links or `LINKEDIN=...`.

The material is sent to your model provider to be summarised. Your profile is not modified: evidence is kept in separate files that every build reads alongside it. Review them and delete anything wrong or anything you would not put on a resume. Private repositories are described in general terms and never named in a resume.

### 3. Write resumes for a posting

```sh
make cv JOB=posting.txt
pbpaste | make cv
```

With no template or provider named, Cvelio writes three resumes, one per template, each by a provider drawn at random from those you have keys for. Compare them, then build the combination you prefer:

```sh
make cv JOB=posting.txt TEMPLATE=startup PROVIDER=gemini
```

Each resume lands in `output/<company-role>/` with a report that lists every requirement of the posting with the evidence found for it, the requirements you have no evidence for, anything added beyond your profile, and any term to double-check before sending.

Every template allows two pages; pass `PAGES=1` if you want one. Only when the text runs past the target does Cvelio step in: it first tightens type size and margins, then asks the model to cut the content least relevant to the posting.

| Option | Meaning | Default |
| --- | --- | --- |
| `TEMPLATE` | `corporate`, `startup` or `academic` | all three |
| `PROVIDER`, `MODEL` | Which model writes it | random per template |
| `FILL` | How freely to fill gaps, from 0 to 1 (see below) | `0.5` |
| `CV_LANG` | Language of the resume, for example `Spanish` | `English` |
| `PAGES` | Target length, `1` or `2` | the template's |
| `PAPER` | `letter` or `a4` | `letter` |
| `OUT` | Output folder | `./output` |
| `TEX=1` | Also keep the LaTeX source | off |
| `PROFILE` | Use another profile file | `~/.config/cvelio/profile.yaml` |

### Filling gaps

A posting usually asks for something your profile does not mention. `FILL` sets what Cvelio may do about it.

| `FILL` | Policy | What it does |
| --- | --- | --- |
| `0` | strict | Adds nothing. Missing requirements are left out and reported as gaps. |
| `0.5` | adjacent | May list up to five technologies that are close siblings of ones you use (you use React and Vue; the posting asks for Angular) in a separate "Familiar with" skills group. They never appear in the summary or in experience bullets. |
| `1` | aspirational | Drafts what a winning profile for this job would look like, adding missing skills to the text. The PDF is watermarked because it holds unverified claims. Use it to see what to learn or what to add to your profile. |

At every level, employers, job titles, dates, degrees, certifications and numbers come only from your profile, and the report lists each added claim with its basis.

## Templates

A template sets the look of the page and also the tone, section order and length of the writing. All three use Latin Modern.

| Template | For | Look | Writing |
| --- | --- | --- | --- |
| `corporate` | Large enterprises, banks, consultancies, government | Serif, black, ruled headings, up to 2 pages | Formal; scale, compliance, process, work across teams |
| `startup` | Startups and product companies | Sans serif, one accent colour, up to 2 pages | Direct; ownership, things shipped, product impact |
| `academic` | Universities, research labs, graduate programmes | Serif, small caps, up to 2 pages | Sober; education first, methods, publications, teaching |

## Models

| Provider | Key | Default model |
| --- | --- | --- |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-opus-5-5` |
| `gemini` | `GEMINI_API_KEY` | `gemini-3.8-flash` |
| `openrouter` | `OPENROUTER_API_KEY` | `openrouter/free` |
| `openai` | `OPENAI_API_KEY` | none; pass `MODEL=` |

To change a provider's model for good, set `<PROVIDER>_MODEL` (for example `OPENROUTER_MODEL=openai/gpt-6-luna`) in the environment, in `.env`, or under `env:` in `config.yaml`. `MODEL=` on the command line overrides it for one build.

The `openai` provider works with any OpenAI-compatible endpoint. Set `OPENAI_BASE_URL` to use a local model, for example `http://localhost:11434/v1` for Ollama; in that case your profile never leaves your machine. Each provider's endpoint can be changed with `<PROVIDER>_BASE_URL`, in the environment or under `env:` in `config.yaml`.

With a hosted provider, each build sends your profile, your evidence files and the posting to that provider. Smaller and free models follow the writing rules less closely than large ones; read their reports with more care.

## How well does it aim?

`make eval` tailors one profile to the five postings in [examples/jobs](examples/jobs) (DevOps, frontend, data analyst, backend, tech lead) and checks each resume against every posting's keywords. A resume that is aimed scores higher on its own posting than on the others.

```sh
make eval                                         # fictional example profile
make eval PROFILE=~/.config/cvelio/profile.yaml   # your own
```

One run with the example profile, `claude-opus-5-5` and strict gap filling: resumes contained 57% of their own posting's keywords and 36% of the other postings', and shared about 10% of their bullets word for word. Results vary from run to run and depend on what the profile contains.

## Develop

```sh
make test
```

The Makefile wraps a Python command line (`uv run cvelio --help`). The code is in `src/cvelio`: `tailor.py` holds the prompt and gap policies, `report.py` the checks that involve no model, `render.py` the LaTeX output, `enrich.py` the GitHub and LinkedIn readers, `config.py` settings and secrets, and `templates/` one `.tex` file per style plus its writing brief. To add a template, add a `.tex` file that defines the same six macros and an entry in `templates/__init__.py`.

## License

Public domain, under [the Unlicense](LICENSE).
