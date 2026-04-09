.PHONY: install test lint typecheck docker-build docker-run clean

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

typecheck:
	mypy src/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

docker-build:
	docker build -t mirofish-forecast .

docker-run:
	docker compose up --build

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf .mypy_cache .ruff_cache htmlcov .coverage
