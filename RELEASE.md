# Release handbook

How a backspin release gets from a commit to PyPI and npm. Run it in order.

## 0. One-time setup

- **PyPI trusted publishing**: on pypi.org → (project) → *Publishing*, add a
  GitHub publisher for `zaibuchihuoji/backspin`, workflow `release.yml`,
  environment `pypi`. No API tokens needed after that.
- **GitHub environment**: repo → Settings → Environments → create `pypi`
  (the release workflow references it).
- **npm** (for `@backspin/sdk`): create the `backspin` org on npmjs.com and
  `npm login` locally. Publishing stays a manual step.

## 1. Prepare the release

1. All changes merged to `main`, CI green (lint / typecheck / tests / TS).
2. Sync versions in **three places**:
   - `pyproject.toml` → `version`
   - `backspin/__init__.py` → `__version__`
   - `sdks/typescript/package.json` → `version` **and**
     `sdks/typescript/src/runfile.ts` → `VERSION`
3. Add the version's section to `CHANGELOG.md` (move "Unreleased" items in).

## 2. Tag and publish (automatic)

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

The `release.yml` workflow then:

1. runs ruff + mypy + the full pytest suite,
2. builds sdist + wheel (`python -m build`),
3. publishes to PyPI via trusted publishing.

Watch it under Actions → Release. When it finishes, verify:

```bash
pip install --upgrade backspin && backspin --version
python -c "from backspin.share import build_share_html"   # UI assets shipped
```

## 3. npm (manual, until an NPM_TOKEN secret exists)

```bash
cd sdks/typescript
npm ci && npm test && npm run build
npm publish --access public
```

## 4. GitHub Release

Create a release on the tag; paste the CHANGELOG section for that version.

## Sanity checklist

- [ ] wheel contains `backspin/ui/` and `py.typed`
- [ ] versions agree in all three places
- [ ] CHANGELOG date is today
- [ ] `load_run` still reads a run file recorded by the previous release
