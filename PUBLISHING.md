# Publishing guide

## Pre-publish checklist

1. Run the release gate locally:

```bash
python -m pytest -q
python -m ruff check .
python -m mypy src/hermes_tescmd_plugin
python -m vulture src tests --min-confidence 90
python -m compileall -q src tests scripts
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
python -m twine check dist/*
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
from pathlib import Path
wheel = sorted(Path('dist').glob('hermes_tescmd_plugin-*.whl'))[-1]
print(wheel)
PY
```

## Release expectations for 0.5.x+

Before publishing, confirm:

- the package has **no runtime dependency on `tescmd`**
- the wheel exposes the `hermes_agent.plugins` entry point
- the bundled `tescmd-operator` skill file is present in the wheel
- docs describe the plugin as a **native Tesla Fleet API plugin**, not a CLI wrapper
- docs describe configuration as manual/docs-only; there is no setup wizard/tool
- runtime tool registration exposes the full native Tesla Fleet command set
- side-effecting operations are confirmation-gated and fail closed before network when denied

## GitHub release publishing

The repository includes `.github/workflows/publish-to-pypi.yml`.

The workflow triggers when a GitHub Release is published:

```text
on:
  release:
    types: [published]
```

It then:

1. checks out the release tag
2. verifies the tag name matches `project.version` in `pyproject.toml` (`v0.5.0a15` or `0.5.0a15` are accepted)
3. builds the sdist and wheel
4. runs `twine check dist/*`
5. uploads the distributions as a GitHub Actions artifact
6. publishes to PyPI with PyPI Trusted Publishing via OIDC (`pypa/gh-action-pypi-publish@release/v1`)

No PyPI API token or GitHub Actions secret is needed.

## PyPI Trusted Publishing setup

PyPI must be configured once outside this repository. In the PyPI project settings for `hermes-tescmd-plugin`, add a GitHub Trusted Publisher with:

```text
Owner: Oceanswave
Repository name: hermes-tescmd-plugin
Workflow name: publish-to-pypi.yml
Environment name: pypi
```

If the project does not exist on PyPI yet, create it from the PyPI publishing page by adding the same pending trusted publisher details before publishing the first release.

The GitHub workflow uses the `pypi` environment. GitHub will create that environment automatically on first use, but repository admins may optionally configure environment protection rules in GitHub settings.

## Recommended release flow

1. Bump version in:
   - `pyproject.toml`
   - `uv.lock`
   - `src/hermes_tescmd_plugin/__init__.py`
   - `src/hermes_tescmd_plugin/skills/tescmd-operator/SKILL.md`
   - `CHANGELOG.md`
2. Run the local release gate.
3. Commit and push to `main`.
4. Create and push a matching tag, usually prefixed with `v`:

```bash
git tag v0.5.0a15
git push origin main --tags
```

5. Publish a GitHub Release from that tag:

```bash
gh release create v0.5.0a15 --title "v0.5.0a15" --generate-notes --prerelease
```

Publishing the release triggers the PyPI workflow automatically.
