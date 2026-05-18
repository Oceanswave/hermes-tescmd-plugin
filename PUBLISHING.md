# Publishing guide

## Pre-publish checklist

1. Run tests:

```bash
pytest -q
```

2. Clean old build artifacts:

```bash
rm -rf dist build *.egg-info
```

3. Build distributions:

```bash
python -m build --sdist --wheel
```

4. Validate distributions:

```bash
twine check dist/*
```

If `twine` is not installed in the current environment, use an isolated verifier environment instead of skipping validation:

```bash
python -m venv .tmp-twine-check
. .tmp-twine-check/bin/activate
python -m ensurepip --upgrade
python -m pip install -U twine
twine check dist/*
deactivate
rm -rf .tmp-twine-check
```

5. Sanity-check the wheel metadata and contents:

```bash
python -m zipfile -l dist/hermes_tescmd_plugin-*.whl | grep hermes_tescmd_plugin
python - <<'PY'
from importlib.metadata import metadata
from pathlib import Path
wheel = sorted(Path('dist').glob('hermes_tescmd_plugin-*.whl'))[-1]
print(wheel)
PY
```

## Release expectations for 0.3.x+

Before publishing, confirm:

- the package has **no runtime dependency on `tescmd`**
- the wheel exposes the `hermes_agent.plugins` entry point
- the bundled skill file is present in the wheel
- docs describe the plugin as a **native Tesla Fleet API plugin**, not a CLI wrapper
- docs explain intentional differences from upstream `tescmd` where Hermes uses compatibility/info tools instead of CLI daemons or TUI flows

## Upload to PyPI

Only upload the freshly built artifacts from the cleaned `dist/` directory:

```bash
twine upload dist/*
```

## Recommended release flow

1. Bump version in:
   - `pyproject.toml`
   - `src/hermes_tescmd_plugin/__init__.py`
   - `CHANGELOG.md`
2. Run `rm -rf dist build *.egg-info`
3. Run tests and build
4. Run `twine check dist/*`
5. Tag release and upload artifacts
