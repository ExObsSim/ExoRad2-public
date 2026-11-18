"""Blind retrieval eval cases for the ExoRad knowledge base.

These cases were written from the user-facing documentation only
(``docs/source/user/*.rst`` and ``AGENTS.md``) BEFORE any retrieval result for
the tuned set in ``retrieval_cases.py`` had been looked at, and before
``exorad/mcp/retrieval.py`` had been read.

Rule (spec 5.2): a question here is never reworded after a miss. A miss is fixed
in the docs or the pattern list, or accepted and reported.

Each case is ``(question, expected path fragment)``.
"""

from __future__ import annotations

BLIND_CASES: list[tuple[str, str]] = [
    (
        "How do I generate per-target plots from an existing results HDF5 file?",
        "docs/source/user/quickstart_guide.rst",
    ),
    (
        "What does the error 'Phoenix path does not exist' mean and how do I fix it?",
        "docs/source/user/troubleshooting.rst",
    ),
    (
        "In which order are the pipeline tasks run for each target?",
        "docs/source/user/introduction.rst",
    ),
    (
        "How do I install ExoRad from a source checkout with uv?",
        "docs/source/user/installation.rst",
    ),
    (
        "Which columns does the channel table in the output file contain?",
        "docs/source/user/outputs.rst",
    ),
    (
        "How are blackbody emission and the solid angle used to compute the signal of an optical element?",
        "docs/source/user/prepare_optics.rst",
    ),
    (
        "Which detector keys must a channel give, such as read noise, dark current and well depth?",
        "docs/source/user/prepare_payload.rst",
    ),
    (
        "How does an XML unit attribute become an astropy quantity and what must I preserve when editing values?",
        "AGENTS.md",
    ),
    (
        "Can ExoRad simulate pointing jitter and time-domain detector systematics?",
        "AGENTS.md",
    ),
    (
        "How should I cite ExoRad in a paper?",
        "AGENTS.md",
    ),
]
