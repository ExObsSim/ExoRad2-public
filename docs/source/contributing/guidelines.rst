.. _guidelines:

==========
Guidelines
==========

Found a bug? Open an issue on the
`GitHub repository <https://github.com/ExObsSim/ExoRad2-public/issues>`__.

The rest of this page is for anyone changing the code.

Coding conventions
==================

The code follows :pep:`8` and the Zen of Python (``import this``). Formatting
and linting are done by `ruff <https://docs.astral.sh/ruff/>`__ and run through
``pre-commit``; the CI gates ``ruff check`` and ``ruff format --check`` on
``exorad/`` and ``tests/``.

Some ``pep8-naming`` rules are switched off on purpose: the public API and the
payload keys use camelCase and PascalCase to match the XML and the science
conventions, and renaming them would break configuration files.

New or reworked modules should carry type annotations. ``nox -s type-check``
runs mypy — lenient on the untyped legacy code, strict on the modules listed in
``pyproject.toml``.

Install the hooks once:

.. code-block:: console

   pip install pre-commit && pre-commit install

Documentation
=============

Public functions and classes are documented with numpydoc_ docstrings; the API
reference is generated from them by `sphinx-autoapi
<https://sphinx-autoapi.readthedocs.io/>`__. The narrative pages are
reStructuredText_ (Markdown is also accepted via MyST). Two nox sessions help:

.. code-block:: console

   nox -s docs          # build once, into build/
   nox -s docs-live     # build and serve with live reload at http://127.0.0.1:8000/

Testing
=======

The suite lives in ``tests/`` and runs with pytest_. Coverage must stay at or
above 92% (``--cov-fail-under=92``). Add a test with every change.

.. code-block:: console

   nox -s test          # on Python 3.12, 3.13 and 3.14
   nox -s coverage      # with the coverage report
   uv run pytest        # directly

Tests must not depend on network access or open figure windows
(``tests/conftest.py`` forces the ``Agg`` backend).

Versioning and releases
=======================

Versions are derived from ``vX.Y.Z`` git tags by ``setuptools-scm`` — there is
nothing to bump by hand. A commit on ``develop`` reports as
``X.Y.(Z+1).devN``.

The scheme is `Semantic Versioning <semver_>`__ (PEP 440 compliant):

- **major** — the code is no longer compatible with the previous release;
- **minor** — a new feature that may change the results;
- **patch** — a bug fix or a small change that does not affect the user.

Releases are cut with ``nox -s release``. The full workflow — changelog
fragments, the publish pipeline and the one-time PyPI / GitHub setup — is in
:ref:`releasing`.

Source control
==============

The code is developed on the private ``ExObsSim/ExoRad2.0`` repository and
mirrored to the public
`ExObsSim/ExoRad2-public <https://github.com/ExObsSim/ExoRad2-public>`__. Two
branches matter:

- ``master`` — stable, tagged releases; mirrored to the public repository;
- ``develop`` — the integration branch for new work.

Contributors without write access use the `fork-and-pull <Fork-and-Pull_>`__
model: fork the repository, implement the change on a branch, and open a pull
request against ``develop``.

.. _Fork-and-Pull: https://en.wikipedia.org/wiki/Fork_and_pull_model
.. _reStructuredText: https://docutils.sourceforge.io/rst.html
.. _numpydoc: https://numpydoc.readthedocs.io/en/latest/
.. _semver: https://semver.org/spec/v2.0.0.html
.. _pytest: https://docs.pytest.org/
