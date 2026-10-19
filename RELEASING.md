# Releasing ExoRad 2

Full guide: `docs/source/contributing/releasing.rst`
(rendered at <https://exorad2-public.readthedocs.io/> → Releasing).

## TL;DR

- **Versioning** is automatic (`setuptools-scm`, from git tags). Nothing to bump
  by hand. Every commit on `develop` is `X.Y.(Z+1).devN`.
- **Changelog**: when a piece of work is done, run `nox -s changelog-fragment`
  and describe it. Fragments live in `changelog.d/`.
- **Cut a release** from a clean, up-to-date `develop`:

  ```console
  nox -s release
  ```

  It asks major/minor/patch and a short release name (or pass `--title "..."`),
  folds the changelog fragments into `CHANGELOG.md` under `## [X.Y.Z] - <name>`,
  updates `CITATION.cff`, commits (`docs: release X.Y.Z — <name>`),
  fast-forwards `master` and pushes the `vX.Y.Z` tag.

- The tag triggers `.github/workflows/release.yml`:
  build → TestPyPI → verify install → PyPI → GitHub Release → mirror of the tag,
  release and wheels into `ExoRad2-public`.
  `sync-to-public.yml` mirrors the `master` code on every push.

## One-time setup

- Add a **PyPI trusted publisher** to the `exorad` project on both
  <https://pypi.org> and <https://test.pypi.org>:
  owner `ExObsSim`, repo `ExoRad2.0`, workflow `release.yml`,
  environment left **blank** (no GitHub environments: they are not available
  for private repositories on the free plan; OIDC works without them).
- Add the `PUBLIC_REPO_TOKEN` repository secret (fine-grained PAT with
  `contents: write` on `ExObsSim/ExoRad2-public`).
- Make sure the release author can fast-forward `master` (branch protection).
