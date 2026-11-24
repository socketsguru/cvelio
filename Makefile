# Cvelio. Run `make help` for the list of commands.
.DEFAULT_GOAL := help
.PHONY: help init enrich cv templates doctor test eval clean

RUN := uv run --quiet cvelio

# Each make variable becomes a command-line option only when it is set.
COMMON := $(if $(PROFILE),--profile "$(PROFILE)") $(if $(PROVIDER),--provider $(PROVIDER)) $(if $(MODEL),--model "$(MODEL)")
BUILD  := $(if $(TEMPLATE),--template $(TEMPLATE)) $(if $(FILL),--fill $(FILL)) $(if $(FORCE),--force) \
          $(if $(CV_LANG),--lang "$(CV_LANG)") $(if $(PAGES),--pages $(PAGES)) $(if $(PAPER),--paper $(PAPER)) \
          $(if $(OUT),--out "$(OUT)") $(if $(TEX),--tex)

help:
	@printf '%s\n' \
	'Cvelio: one profile, one resume aimed at each job posting.' \
	'' \
	'First time' \
	'  make init                      Answer a few questions (voice, gender, where your API keys live)' \
	'                                 and create an example profile to edit.' \
	'  make init FROM="cv.pdf notes.txt"   Same, but build the profile from your existing documents.' \
	'  make enrich                    Add evidence from your GitHub repositories (descriptions and READMEs,' \
	'                                 public and private, never source code) and your LinkedIn profile and posts.' \
	'                                 Options: ONLY=github|linkedin  LINKEDIN=https://www.linkedin.com/in/you' \
	'  make doctor                    Check LaTeX, your profile and your keys.' \
	'' \
	'Every application' \
	'  make cv JOB=posting.txt        Write three resumes (corporate, startup, academic), each by a provider' \
	'                                 chosen at random, so you can compare. Each comes with a fit report.' \
	'  pbpaste | make cv              Same, with the posting from the clipboard. Plain `make cv` lets you paste it.' \
	'  make cv JOB=posting.txt TEMPLATE=startup PROVIDER=gemini' \
	'                                 Write exactly one: the template and provider you liked.' \
	'' \
	'Options for make cv' \
	'  TEMPLATE=corporate|startup|academic     PROVIDER=anthropic|gemini|openrouter|openai     MODEL=name' \
	'  CV_LANG=Spanish   Language of the resume (default: English)' \
	'  PAGES=1|2   PAPER=letter|a4   OUT=folder   TEX=1 (keep the LaTeX source)   PROFILE=other.yaml' \
	'  FILL=0..1   How freely to fill gaps between your profile and the posting (default: 0.5)' \
	'                0    strict: nothing that is not in your profile' \
	'                0.5  adds closely related technologies as "Familiar with" (you use React and Vue: Angular)' \
	'                1    aspirational draft of a winning profile; watermarked only above 0.55,' \
	'                     since it holds unverified claims (change watermark_fill in config.yaml)' \
	'  FORCE=1     Leave the watermark off even above that level. Every added claim is still listed in the report,' \
	'              and you are the one who signs the resume.' \
	'' \
	'Other' \
	'  make templates                 List the styles.' \
	'  make test                      Run the test suite.' \
	'  make eval                      Measure how well resumes are aimed (one model call per example posting).' \
	'  make clean                     Delete generated resumes, caches and LaTeX leftovers. Your profile is kept.'

init:
	@$(RUN) init $(COMMON) $(if $(FORCE),--force) $(FROM)

enrich:
	@$(RUN) enrich $(COMMON) $(if $(ONLY),--only $(ONLY)) $(if $(LINKEDIN),--linkedin "$(LINKEDIN)")

cv:
	@$(RUN) build $(COMMON) $(BUILD) $(if $(JOB),"$(JOB)",-)

templates:
	@$(RUN) templates

doctor:
	@$(RUN) doctor $(COMMON)

test:
	@uv run --quiet pytest -q

eval:
	@uv run --quiet python evals/run.py $(COMMON) $(if $(TEMPLATE),--template $(TEMPLATE)) $(if $(FILL),--fill $(FILL))

clean:
	@rm -rf output dist build .pytest_cache .ruff_cache
	@find . -name __pycache__ -type d -not -path './.venv/*' -prune -exec rm -rf {} +
	@find . -type f \( -name '*.aux' -o -name '*.log' -o -name '*.out' -o -name '*.fls' -o -name '*.fdb_latexmk' \
	    -o -name '*.synctex.gz' -o -name '*.xdv' -o -name '*.toc' -o -name '*.fit' -o -name '.DS_Store' \) \
	    -not -path './.venv/*' -delete
	@echo "Clean. Your profile and settings in ~/.config/cvelio were not touched."
