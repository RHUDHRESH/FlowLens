# FlowLens RCA Lab — command contract
# Windows: if make is unavailable, every target is `python -m flowlens <subcommand>`.

PYTHON ?= python
FAULT ?= door_lock_bounce
SEED ?= 20260915

.PHONY: setup demo test benchmark inject incident-report offline-bundle generate-scenarios verify serve console-build lint typecheck

setup:
	$(PYTHON) -m pip install -e ".[dev]"
	cd apps/console && npm install

console-build:
	cd apps/console && npm install && npm run build

demo: console-build
	$(PYTHON) -m flowlens demo --seed $(SEED)

verify:
	$(PYTHON) -m flowlens verify --seed $(SEED)

test:
	$(PYTHON) -m pytest -q
	cd apps/console && npm run typecheck

benchmark:
	$(PYTHON) -m flowlens benchmark

inject:
	$(PYTHON) -m flowlens diagnose $(FAULT) --seed $(SEED)

incident-report:
	$(PYTHON) -m flowlens report $(FAULT) --seed $(SEED)

generate-scenarios:
	$(PYTHON) -m flowlens generate-scenarios --seed $(SEED)

offline-bundle:
	$(PYTHON) -m flowlens offline-bundle

serve: console-build
	$(PYTHON) -m flowlens serve --host 0.0.0.0 --port 8000

lint:
	$(PYTHON) -m ruff check flowlens apps tests benchmarks
	cd apps/console && npm run typecheck

typecheck:
	$(PYTHON) -m mypy flowlens apps
