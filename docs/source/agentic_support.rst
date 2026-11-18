.. _agentic_support:

================
Agentic support
================

ExoRad 2 ships repository-local guidance for AI coding assistants and other
large language model tools. The guidance is plain text stored in the repository,
adds no runtime dependency, and is not tied to a single AI provider; an optional
:ref:`MCP server <mcp>` adds a live tool layer on top of it. Its purpose is to
help users and maintainers get **grounded** answers about the codebase and set
payload parameters from repository evidence rather than guesswork.

The shared guide
================

``AGENTS.md``
    The canonical shared guide (the `agents.md <https://agents.md>`__ standard).
    It covers the first-response protocol, what ExoRad is and is not, the
    repository layout, the architecture and data flow, the XML/units
    configuration model, the HDF5 output, an end-to-end example, the common
    commands, quality expectations, conventions and how to cite ExoRad, and it
    links to the detailed guides. Point any tool that does not pick it up
    automatically at this file.

``CLAUDE.md``
    A thin pointer to ``AGENTS.md`` for tools that look for this filename.

The detailed guides (``docs/ai-agents/``)
=========================================

``docs/ai-agents/codebase-map.md``
    A concise map of the package layout, the pipeline order, where things are
    configured, and the validation commands.

``docs/ai-agents/parameter-setup-guide.md``
    How the payload XML is parsed (units, ``__ConfigPath__``, data files,
    repeated tags) and the recommended workflow for answering a configuration
    question.

``docs/ai-agents/README.md``
    The index for these files.

The MCP server
==============

For clients that speak the Model Context Protocol, ExoRad also ships an optional
server, ``exorad-mcp``, installed with ``pip install "exorad[mcp]"``. Where the
files above are read once, the server lets an assistant *act*: search the
documentation with file-and-line citations, draft and validate a payload XML and
a target list with the real ExoRad rules, run the radiometric pipeline as a
supervised background job, and inspect, explain and plot the HDF5 output. It
serves the same ``AGENTS.md`` and ``docs/ai-agents/`` guides through its
``exorad_project_context`` tool. See :ref:`mcp` for installation, per-client
setup, the tools and the safety model.

How this helps users
====================

These files instruct an agent to:

* read ``examples/payload_example.xml`` and ``docs/source/user/`` before
  suggesting parameter edits;
* verify parser behaviour in ``exorad/tasks/loadOptions.py``;
* preserve ``__ConfigPath__`` and physical units in XML examples;
* separate observed facts from assumptions and open questions when a scientific
  value is missing;
* avoid committing generated HDF5 files, plots, caches or virtual environments.

How maintainers should update it
================================

Keep the guidance in step with the code:

* update ``parameter-setup-guide.md`` when configuration parsing changes;
* update ``codebase-map.md`` when tasks, CLI commands or examples change;
* update :ref:`the MCP page <mcp>` (and the output map in
  ``exorad/mcp/output_map.py``) when the output layout, the payload rules or the
  tool inventory change. Maintainers' internal planning notes are neither part
  of this documentation nor of the knowledge base the server answers from.
