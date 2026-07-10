set shell := ["bash", "-euo", "pipefail", "-c"]
set quiet
set fallback
set default-list

python := "uv run python"
uv_dev := "uv run --extra=dev"

# Install dependencies (use --extras to include dev)
[group('dependencies')]
install *args:
    uv sync {{ args }}

# Install all dependencies
[group('dependencies')]
install-all:
    uv sync --all-extras

# Upgrade locked dependencies to their latest compatible versions
[group('dependencies')]
deps-upgrade:
    uv lock --upgrade
    uv sync --all-extras

# Check for outdated dependencies
[group('dependencies')]
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
[group('dependencies')]
[script('python3')]
deps-bump package version:
    import subprocess, tomllib
    from pathlib import Path
    from packaging.requirements import Requirement

    p = Path('pyproject.toml')
    deps = tomllib.load(open('pyproject.toml', 'rb')).get('project', {}).get('dependencies', [])
    old = next((d for d in deps if Requirement(d).name.lower() == '{{ package }}'.lower()), None)
    if old:
        req = Requirement(old)
        extras = f"[{','.join(sorted(req.extras))}]" if req.extras else ""
        p.write_text(p.read_text().replace(old, f'{req.name}{extras}~={{ version }}'))
    else:
        print("{{ package }} is not a direct dependency; updating the lock only.")
    subprocess.run(['uv', 'lock', '--upgrade-package', '{{ package }}'])

# Run the development server or other commands, e.g. `just run makemigrations`
[group('development')]
[working-directory("src")]
run *args="runserver --skip-checks":
    {{ python }} manage.py {{ args }}

# Open Django shell
[group('development')]
[no-exit-message]
[positional-arguments]
[working-directory("src")]
python *args:
    {{ python }} manage.py shell "$@"

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
fmt: format (check "--fix") && fmt-done

[private]
fmt-done:
    echo '{{ GREEN }}Formatting complete{{ NORMAL }}'

# Run all code quality checks (no fix)
[group('linting')]
fmt-check: (format "--check") check && check-done

[private]
check-done:
    echo '{{ GREEN }}All checks passed{{ NORMAL }}'

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

# Spec worker: process queued spec turns via claude -p (needs [spec] config)
[group('operations')]
[working-directory("src")]
runworker *args:
    {{ python }} manage.py runworker {{ args }}

# Run the test suite
[group('tests')]
[positional-arguments]
test *args:
    {{ uv_dev }} pytest "$@"

# Run tests in parallel (requires pytest-xdist)
[group('tests')]
[positional-arguments]
test-parallel *args:
    just test -n auto "$@"

# Run tests with coverage report
[group('tests')]
[positional-arguments]
test-coverage *args:
    just test --cov=src --cov-report=term-missing:skip-covered --cov-config=pyproject.toml "$@"

# Show test coverage report in browser
[group('tests')]
[script('bash')]
test-coverage-report: test-coverage
    set -euo pipefail
    if [ -f "htmlcov/index.html" ]; then
        open htmlcov/index.html 2>/dev/null || \
        xdg-open htmlcov/index.html 2>/dev/null || \
        echo "Coverage report: htmlcov/index.html"
    else
        echo "No coverage report found. Run just test-coverage first."
    fi

# Install the CLI package's dev environment
[group('cli')]
[working-directory("cli")]
cli-install:
    uv sync --all-extras

# Upgrade the CLI's locked dependencies
[group('cli')]
[working-directory("cli")]
cli-deps-upgrade:
    uv lock --upgrade
    uv sync --all-extras

# Run the CLI test suite (with coverage)
[group('cli')]
[positional-arguments]
[working-directory("cli")]
cli-test *args:
    {{ uv_dev }} pytest --cov=src --cov-report=term-missing:skip-covered --cov-config=pyproject.toml "$@"

# Run ruff format + check --fix on the CLI
[group('cli')]
[working-directory("cli")]
cli-fmt:
    {{ uv_dev }} ruff format
    {{ uv_dev }} ruff check --fix

# Ruff check the CLI without applying fixes
[group('cli')]
[working-directory("cli")]
cli-fmt-check:
    {{ uv_dev }} ruff format --check
    {{ uv_dev }} ruff check

# Build the CLI sdist + wheel into cli/dist/
[group('cli')]
[working-directory("cli")]
cli-build:
    rm -rf dist build
    uv build

# Publish the CLI to PyPI
[group('cli')]
[working-directory("cli")]
cli-publish: cli-build
    uvx twine upload --non-interactive --config-file "${PYPIRC:-$HOME/.config/pypirc}" dist/*

# Bump CLI __version__, commit, tag vX.Y.Z, push branch + tag
[group('cli')]
[script('bash')]
cli-release version:
    set -euo pipefail
    version="{{ version }}"
    if ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "error: version must be X.Y.Z (got: $version)" >&2
        exit 1
    fi
    if ! git diff --quiet HEAD --; then
        echo "error: working tree has uncommitted changes" >&2
        exit 1
    fi
    if git rev-parse -q --verify "refs/tags/v$version" >/dev/null; then
        echo "error: tag v$version already exists" >&2
        exit 1
    fi
    printf '__version__ = "%s"\n' "$version" > cli/src/pxtx/__init__.py
    git add cli/src/pxtx/__init__.py
    git commit -m "Release CLI v$version"
    git tag "v$version"
    git push origin HEAD "v$version"
