PYTHON ?= .venv/bin/python

.PHONY: ranklab-check ranklab-smoke ranklab-gatec livelab

ranklab-check:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v
	$(PYTHON) scripts/verify_ranklab_release.py
	$(PYTHON) scripts/check_public_release.py
	python3 -m unittest discover -s apps/livelab/tests -v
	node --check apps/livelab/app.js

ranklab-smoke:
	$(PYTHON) scripts/run_ranklab_reproduction.py --profile smoke

ranklab-gatec:
	$(PYTHON) scripts/run_ranklab_reproduction.py --profile gatec

livelab:
	cd apps/livelab && python3 -m http.server 4187
