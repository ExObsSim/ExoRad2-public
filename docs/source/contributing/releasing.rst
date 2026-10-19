.. _releasing:

Releasing ExoRad 2
==================

Versioning
----------

Versions are **derived from git tags** by ``setuptools-scm``. There is no
version string to bump by hand: ``pyproject.toml`` declares ``dynamic =
["version"]`` and the build writes ``exorad/_version.py`` (git-ignored).

- on a release tag ``vX.Y.Z`` the version is ``X.Y.Z``
- ``N`` commits after the latest tag on ``develop`` it is ``X.Y.(Z+1).devN``

The scheme follows `Semantic Versioning <https://semver.org/>`__ and PEP 440.

Changelog fragments
-------------------

Unreleased changes are **not** written straight into ``CHANGELOG.md``. When a
unit of work is finished, add a fragment:

.. code-block:: console

   $ nox -s changelog-fragment

This drops a timestamped Markdown file in ``changelog.d/``. Fill it in using the
Keep a Changelog categories as level-3 headings (``### Added``, ``### Changed``,
``### Fixed`` …). Fragments are collected into ``CHANGELOG.md`` at release time,
so they keep merge conflicts out of the changelog.

Cutting a release
-----------------

From a clean, up-to-date ``develop`` checkout:

.. code-block:: console

   $ nox -s release            # interactive
   $ nox -s release -- minor   # skip the bump prompt
   $ nox -s release -- minor --title "Python 3.12+"   # fully non-interactive

The script (``scripts/release.py``):

#. checks the working tree, branch and sync with ``origin/develop``;
#. runs the quality gate (``ruff format --check`` + ``pytest``);
#. asks for the bump (major / minor / patch) and computes the next ``X.Y.Z``
   from the latest ``vX.Y.Z`` tag;
#. asks for a short **release name** (or takes ``--title``), e.g.
   ``Python 3.12+``;
#. folds the ``changelog.d/`` fragments into ``CHANGELOG.md`` with scriv, under
   the heading ``## [X.Y.Z] - <name>``;
#. sets ``version`` and ``date-released`` in ``CITATION.cff``;
#. commits on ``develop`` (``docs: release X.Y.Z — <name>``), fast-forwards
   ``master`` and pushes the ``vX.Y.Z`` tag (annotated ``X.Y.Z — <name>``).

The release name also becomes the GitHub Release title (``X.Y.Z — <name>``).

Pushing the tag triggers ``.github/workflows/release.yml``:

.. code-block:: text

   build  →  TestPyPI  →  verify install  →  PyPI  →  GitHub Release
                                                          │
                                          mirror tag + release + wheels
                                                into ExoRad2-public

``sync-to-public.yml`` mirrors the ``master`` code to
`ExObsSim/ExoRad2-public <https://github.com/ExObsSim/ExoRad2-public>`__ on every
push. PyPI publishing uses `trusted publishing
<https://docs.pypi.org/trusted-publishers/>`__ (OIDC), so no API tokens are
stored.

One-time setup
--------------

- Add a **PyPI trusted publisher** to the ``exorad`` project on both
  `pypi.org <https://pypi.org/manage/account/publishing/>`__ and
  `test.pypi.org <https://test.pypi.org/manage/account/publishing/>`__:
  owner ``ExObsSim``, repository ``ExoRad2.0``, workflow ``release.yml``,
  environment left **blank**. No GitHub deployment environments are used (they
  are not available for private repositories on the free plan); OIDC trusted
  publishing works without them.
- Add a repository secret ``PUBLIC_REPO_TOKEN`` — a fine-grained PAT with
  ``contents: write`` on ``ExObsSim/ExoRad2-public`` — used by
  ``sync-to-public.yml`` and the ``mirror-release`` job.
- Make sure the release author can fast-forward ``master`` (branch protection).
