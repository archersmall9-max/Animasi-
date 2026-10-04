.PHONY: help setup doctor test lint clean demo

help:
	@echo "setup   - install dependencies (core + optional + dev)"
	@echo "doctor  - verify the local toolchain"
	@echo "lint    - ruff"
	@echo "test    - pytest"
	@echo "demo    - render a synthetic clip end to end into work/"
	@echo "clean   - remove caches and the working folder"

setup:
	pip install -r requirements.txt
	pip install -r requirements-optional.txt
	pip install -e ".[dev]"

doctor:
	python -m viralcut doctor

lint:
	ruff check .

test:
	pytest -q

demo:
	python scripts/make_test_clip.py --preset landscape --duration 6 -o work/demo_src.mp4
	python -m viralcut edit work/demo_src.mp4 -o work/demo_out.mp4 --preset shorts

clean:
	rm -rf work .pytest_cache .ruff_cache **/__pycache__ __pycache__
