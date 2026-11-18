"""MCP prompts: ready-made instructions for common ExoRad workflows.

Each prompt returns text the client can drop into a conversation. They tell the
model which ExoRad MCP tools to use and in what order, keeping answers grounded.
"""

from __future__ import annotations

_GROUNDING = (
    "Use the ExoRad MCP tools for every factual claim. Cite the file path and "
    "line range from search_knowledge_base or the manifest. If a tool returns "
    "insufficient_evidence, say so instead of guessing."
)


def new_simulation() -> str:
    """Guide the user from nothing to a finished radiometric run."""
    return (
        "Help me set up and run an ExoRad radiometric simulation from scratch.\n\n"
        "1. Call config_requirements for the payload (and again for the target "
        "list) to see the elements and columns that are needed, and list_examples "
        "for a real starting point.\n"
        "2. Ask me what I want to change from the bundled example (instrument "
        "channels, wavelength range, source spectrum, targets).\n"
        "3. Call draft_config with those changes as overrides; show me the "
        "applied and not_applied lists and fix the keys that missed.\n"
        "4. Call draft_target_list with my stars (name, M, Teff, R, D).\n"
        "5. Call validate_config on the drafted payload and on the target list "
        "and explain every finding.\n"
        "6. When both are valid, call run_pipeline and poll get_job_status until "
        "the job ends.\n"
        "7. On success, call explain_output on the result, then plot_output.\n\n"
        f"{_GROUNDING}"
    )


def set_up_channel(instrument: str = "spectrometer") -> str:
    """Guide the user through configuring a payload channel."""
    return (
        f"Help me configure a {instrument} channel of an ExoRad payload.\n\n"
        "draft_config can only change elements that already exist in the example "
        "payload; it cannot add a channel. So:\n"
        "1. Call list_examples and read the example payload to find the channel "
        f"whose class is closest to a {instrument}; search_knowledge_base for "
        "the channel parameters (Fnum, optics, detector, aperture or wavelength "
        "solution).\n"
        "2. Walk me through each element of that channel with its units, quoting "
        "the docs, and ask which values I want to change.\n"
        "3. Call draft_config with those changes as overrides (for example "
        "channel.<name>.targetR); show me the applied and not_applied lists. If "
        "I need an additional channel or an element the example lacks, say "
        "plainly that it must be added by editing the XML file by hand, then "
        "use validate_config on the edited file.\n"
        "4. Call validate_config on the draft and explain any finding.\n\n"
        f"{_GROUNDING}"
    )


def diagnose_failed_run() -> str:
    """Guide the user through diagnosing a failed pipeline run."""
    return (
        "My ExoRad run failed. Help me fix it.\n\n"
        "1. Call get_job_status for the failed job and read the log tail (or ask "
        "me for the error message).\n"
        "2. Call diagnose_error with that text.\n"
        "3. Call validate_config on my payload and on my target list.\n"
        "4. search_knowledge_base for the failing component and propose a fix, "
        "quoting the docs or source.\n\n"
        f"{_GROUNDING}"
    )


def explain_output(path: str = "output.h5") -> str:
    """Guide the user through understanding a generated output file."""
    return (
        f"Explain the ExoRad output file {path}.\n\n"
        "1. Call inspect_output on it.\n"
        "2. Call explain_output to annotate every group, the per-target "
        "tables and the noise budget; report anything listed as unexplained.\n"
        "3. For each top-level group, search_knowledge_base for what it "
        "contains and how it is produced.\n"
        "4. Summarise the tables, their units and the pipeline stage that "
        "wrote them.\n\n"
        f"{_GROUNDING}"
    )


ALL_PROMPTS = (new_simulation, set_up_channel, diagnose_failed_run, explain_output)
