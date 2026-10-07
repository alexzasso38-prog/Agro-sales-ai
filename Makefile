.PHONY: install backend frontend worker demo test build
AGRO_NPM_CACHE ?= $(CURDIR)/.cache/npm
PYTHON ?= python3

install:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -r backend/requirements.txt
	cd frontend && npm ci --cache "$(AGRO_NPM_CACHE)"
	test -f .env || cp .env.example .env

backend:
	cd backend && ../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev -- --host 127.0.0.1 --port 5173 --strictPort

worker:
	cd backend && ../.venv/bin/python -m app.worker

demo:
	.venv/bin/python scripts/run-demo.py

test:
	cd backend && ../.venv/bin/python -m pytest -q

build:
	cd frontend && npm run build
