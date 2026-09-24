.PHONY: install test

install:
	poetry install --all-extras

test:
	poetry run pytest --benchmark-skip
