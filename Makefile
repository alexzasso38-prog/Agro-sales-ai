.PHONY: install backend frontend worker test build
AGRO_NPM_CACHE ?= $(CURDIR)/.cache/npm

install:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r backend/requirements.txt
	cd frontend && npm ci --cache "$(AGRO_NPM_CACHE)"

backend:
	cd backend && ../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev -- --host 127.0.0.1

worker:
	cd backend && ../.venv/bin/python -m app.worker

test:
	cd backend && ../.venv/bin/python -m pytest -q

build:
	cd frontend && npm run build
