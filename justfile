set shell := ["bash", "-euo", "pipefail", "-c"]
set quiet

_ := require("uv")
python := "uv run python"
uv_dev := "uv run --extra=dev"
src_dir := "src"

[private]
default:
    just --list

# Install dependencies
[group('development')]
install *args:
    uv lock --upgrade
    uv sync {{ args }}

# Install all dependencies
[group('development')]
install-all:
    uv lock --upgrade
    uv sync --all-extras

# Run the development server or other commands, e.g. `just run makemigrations`
[group('development')]
[working-directory("src")]
run *args="runserver --skip-checks":
    {{ python }} manage.py {{ args }}

# Open Django shell
[group('development')]
[no-exit-message]
[working-directory("src")]
python *args:
    {{ python }} manage.py shell "$@"

# Mint an API token for a claude-code instance (name used as assignee)
[group('development')]
[working-directory("src")]
mktoken name:
    {{ python }} manage.py mktoken {{ name }}

# Check for outdated dependencies
[group('development')]
[script('python3')]
deps-outdated:
    import json, subprocess, tomllib
    from packaging.requirements import Requirement

    result = subprocess.run(['uv', 'pip', 'list', '--outdated', '--format=json'], capture_output=True, text=True)
    outdated = {p['name'].lower(): p for p in json.loads(result.stdout)}
    deps = tomllib.load(open('pyproject.toml', 'rb')).get('project', {}).get('dependencies', [])
    direct = {Requirement(d).name.lower() for d in deps}

    for name in sorted(outdated.keys() & direct):
        p = outdated[name]
        print(f"{p['name']}: {p['version']} → {p['latest_version']}")

# Bump a dependency version
[group('development')]
[script('python3')]
deps-bump package version:
    import subprocess, tomllib
    from pathlib import Path
    from packaging.requirements import Requirement

    p = Path('pyproject.toml')
    deps = tomllib.load(open('pyproject.toml', 'rb')).get('project', {}).get('dependencies', [])
    old = next((d for d in deps if Requirement(d).name.lower() == '{{ package }}'.lower()), None)
    if old:
        p.write_text(p.read_text().replace(old, f'{Requirement(old).name}~={{ version }}'))
    subprocess.run(['uv', 'lock', '--upgrade-package', '{{ package }}'])

# Remove Python caches, build artifacts, and coverage reports
[group('development')]
clean:
    -find . -type d -name __pycache__ -exec rm -rf {} +
    -find . -type f -name "*.pyc" -delete
    -find . -type d -name "*.egg-info" -exec rm -rf {} +
    -rm -rf .pytest_cache .coverage htmlcov dist build

# Run ruff format
[group('linting')]
format *args="":
    {{ uv_dev }} ruff format {{ args }}

# Run ruff check
[group('linting')]
check *args="":
    {{ uv_dev }} ruff check {{ args }}

# Run all formatters and linters
[group('linting')]
fmt: format (check "--fix")

# Run all code quality checks (no fix)
[group('linting')]
fmt-check: (format "--check") check

# Collect static files for production
[group('operations')]
[working-directory("src")]
collectstatic:
    {{ python }} manage.py collectstatic --noinput

# Run production server via gunicorn
[group('operations')]
[working-directory("src")]
serve *args="--bind 0.0.0.0:8000 --workers 2":
    uv run gunicorn pxtx.wsgi {{ args }}

# Periodic sync: check for new github issues/PRs referenced by issues
[group('operations')]
[working-directory("src")]
runperiodic:
    {{ python }} manage.py runperiodic

# Run the test suite
[group('tests')]
[positional-arguments]
test *args:
    {{ uv_dev }} pytest --cov=src --cov-report=term-missing:skip-covered --cov-config=pyproject.toml "$@"

# Run tests in parallel (requires pytest-xdist)
[group('tests')]
[positional-arguments]
test-parallel n="auto" *args:
    shift; just test -n {{ n }} "$@"
