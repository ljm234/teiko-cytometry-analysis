# Build targets for the cytometry analysis pipeline.
#
# setup      install Python and Node dependencies
# pipeline   build the database and produce every table and figure
# dashboard  serve the interactive dashboard locally
#
# The Python targets run inside a virtual environment created under .venv, so the
# system interpreter is left untouched. Recent releases of pip refuse to install into
# an externally managed interpreter, which is the default on macOS under Homebrew and
# on several Linux distributions, and a project local environment avoids that entirely.

PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
DASHBOARD_DIR := dashboard
DASHBOARD_PORT ?= 5173

.PHONY: setup pipeline dashboard clean test help

help:
	@echo "Targets:"
	@echo "  make setup      install dependencies"
	@echo "  make pipeline   run the full analysis"
	@echo "  make dashboard  start the dashboard server"
	@echo "  make test       run the test suite"
	@echo "  make clean      remove generated artefacts"

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip

setup: $(VENV_PYTHON)
	$(VENV_PIP) install -r requirements.txt
	@if [ -f $(DASHBOARD_DIR)/package.json ]; then \
		cd $(DASHBOARD_DIR) && npm ci; \
	fi

pipeline: $(VENV_PYTHON)
	$(VENV_PYTHON) load_data.py
	$(VENV_PYTHON) -m analysis.frequencies
	$(VENV_PYTHON) -m analysis.statistics
	$(VENV_PYTHON) -m analysis.mixed_models
	$(VENV_PYTHON) -m analysis.subsets
	$(VENV_PYTHON) -m analysis.figures

test: $(VENV_PYTHON)
	@if [ -z "$$(ls tests/test_*.py 2>/dev/null)" ]; then \
		echo "No test modules found under tests/."; \
		exit 1; \
	fi
	$(VENV_PYTHON) -m pytest tests -q

dashboard:
	@if [ ! -f $(DASHBOARD_DIR)/package.json ]; then \
		echo "$(DASHBOARD_DIR)/package.json not found, so there is nothing to serve."; \
		exit 1; \
	fi
	@if [ ! -d $(DASHBOARD_DIR)/node_modules ]; then \
		echo "Dashboard dependencies are missing. Run 'make setup' first."; \
		exit 1; \
	fi
	cd $(DASHBOARD_DIR) && npm run dev -- --port $(DASHBOARD_PORT) --host

clean:
	rm -f cell-count.db
	rm -rf outputs/tables outputs/figures
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
