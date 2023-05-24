import argparse

import nox


@nox.session
def lint(session):
    """
    Run the linters.
    """
    session.install("pre-commit")
    session.run("pre-commit", "run", "-a")


@nox.session(reuse_venv=True)
def docs(session):
    session.install(".")
    session.run("sphinx-build", "-b", "html", "docs/source", "build")


@nox.session(name="docs-live", reuse_venv=True)
def docs_live(session):
    session.install(".")
    session.run(
        "sphinx-autobuild",
        "-b",
        "html",
        "docs/source",
        "build",
        *session.posargs,
    )
