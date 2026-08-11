PYTHON ?= python
export PYTHONNOUSERSITE := 1

.PHONY: quality lint typecheck test

quality: lint typecheck test

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest
