.PHONY: format test

format:
	@poetry run black gyver tests
	@poetry run isort -ir gyver tests
	@poetry run autoflake --remove-all-unused-imports --remove-unused-variables --remove-duplicate-keys --expand-star-imports -ir gyver tests

test:
	@podman-compose up --build --abort-on-container-exit --exit-code-from app
	@podman-compose down


setup:
	@poetry install --all-extras
