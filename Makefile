# RepoMind. Run `make setup` once, then `make check-06` whenever you like.

PY ?= .venv/bin/python

.PHONY: setup test ping audit reset check-06 bounds-smoke review

setup:
	python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt
	@echo "ready. Next: copy your earlier model into settings.yaml and its price line into pricing.yaml, set your key, then make ping."

test:            ## the harness's own tests; they spend no tokens
	$(PY) -m unittest discover -s tests -t .

ping:            ## your key, your model, tool calling, its price line, and your tool definitions in one request
	$(PY) -m harness.ping

audit:           ## Assignment 3's schema audit of tools/*.json; no model
	$(PY) tools/audit_schemas.py

reset:           ## archive the tracker's database to tracker/archive/ and start it empty; runs/ and logs/ stay
	$(PY) -m harness.tracker reset

bounds-smoke:    ## the agent way against the model that never stops; free
	$(PY) run.py --way agent --backend never-stops --set dev --runs 1

review:          ## the reviewer console, in a second terminal while REVIEWER=human runs
	$(PY) bin/review

check-06:        ## the Assignment 6 checker, on main (the guards from the tag lab-06-split-final)
	$(PY) checks/check_06.py
