.. _mcp:

==========
MCP server
==========

ExoRad ships an optional **Model Context Protocol (MCP)** server. MCP is an open
standard for connecting AI assistants to external tools and data; through it an
MCP-compatible client (a desktop app, an IDE extension, an orchestrator) can:

- ask questions about ExoRad grounded in its documentation and source code,
  instead of guessing;
- draft and validate a payload XML and a target list with the real ExoRad
  loader and rules;
- run the radiometric pipeline as a supervised background job (see
  `Safety model`_);
- inspect, explain and plot the HDF5 output file.

It is an **access layer around the existing ExoRad API and CLI**. It adds no
scientific capability and does not replace the Python API or the ``exorad``
command: a run started through the server is ``exorad.standard_pipeline`` in a
separate process.

The server is the runtime half of ExoRad's :ref:`agentic_support`; the static
half is ``AGENTS.md`` and the guides under ``docs/ai-agents/``, which the server
also serves through ``exorad_project_context()``.

.. contents::
   :local:
   :depth: 1


Quickstart
==========

#. Install the extra. The install is self-contained: the wheel ships the
   knowledge base, the example payload and target list and their data tables
   (about 1.2 MB unpacked), so no ExoRad checkout is needed:

   .. code-block:: bash

       pip install "exorad[mcp]"

#. Check the install. ``exorad-mcp --help`` and ``--version`` work without the
   SDK, so they prove nothing about it; this command imports the SDK and builds
   the server, and prints nothing when all is well:

   .. code-block:: bash

       python -c "from exorad.mcp.server import build_server; build_server()"

   If the SDK is missing or broken, ``exorad-mcp`` itself exits with one line that
   names the cause (not installed, a version outside ``>=2,<3``, or the import
   error of the SDK).

#. Tell your MCP client to launch it. Most clients read a JSON file listing MCP
   servers; add an ``exorad`` entry:

   .. code-block:: json

       {
         "mcpServers": {
           "exorad": {
             "command": "exorad-mcp",
             "args": ["--work-dir", "/path/to/exorad-runs"]
           }
         }
       }

   ``--work-dir`` is where drafts, outputs, logs and plots go. Without it the
   server uses ``mcp-runs`` in the checkout (an editable install or a checkout)
   or in *its* working directory (packaged content). A desktop client may start
   the server in ``/``: if the default cannot be created, the server falls back to
   ``~/.exorad/mcp-runs`` and logs one warning on stderr. A ``--work-dir`` that
   cannot be used is an error, never replaced: one line on stderr and a non-zero
   exit status.

#. Ask your assistant something like *"Using the exorad tools, which payload
   elements does a spectrometer channel need?"*. It should call
   ``search_knowledge_base`` or ``config_requirements`` and answer with
   file-and-line citations.

For a question-only server that cannot run anything, add ``--no-exec``. Read
`Safety model`_ before enabling execution.

The ``mcp`` extra needs the ``mcp`` Python SDK **2.x** (``mcp>=2,<3``). With the
1.x SDK installed ``exorad-mcp`` stops with an error asking for ``mcp>=2``:
upgrade with ``pip install -U "exorad[mcp]"``. ``capabilities()`` reports the SDK
version in use. Execution is supported on Linux and macOS only (the supervision
of the job processes uses POSIX process groups); on Windows use ``--no-exec``.
`Known limits`_ lists what the server does not do.


Connecting a client
===================

The JSON above is the common shape. What varies between clients is the **file it
lives in** and the **top-level key** (``mcpServers``, ``servers``, ``mcp`` ...).
The command is always ``exorad-mcp``; the recipes below fill in the rest.

Making ``exorad-mcp`` findable
------------------------------

A client launches ``exorad-mcp`` as a subprocess, so it has to be on the path it
runs with. If

.. code-block:: bash

    which exorad-mcp

prints nothing (usually because ExoRad lives in a virtual environment), give the
client the **absolute path** to the console script instead of the bare name, for
example ``/path/to/venv/bin/exorad-mcp``. ``python -c "import exorad.mcp"`` in
that environment should succeed.

Where the content comes from
----------------------------

A stdio client starts the server with an arbitrary working directory. The server
picks its **content root** (the documentation, examples and source files it
answers from) in this order:

#. ``--repo-root`` / ``EXORAD_MCP_REPO_ROOT``, if given (an override);
#. the current directory, if it is an ExoRad checkout;
#. the checkout the ``exorad`` package was imported from (an editable install);
#. the content packaged inside the wheel (``exorad/mcp/_data``).

So ``--repo-root`` is only needed to serve a checkout other than the one you
installed from. ``capabilities()["sandbox"]["content"]`` reports which was
chosen: ``source`` (``override`` / ``checkout`` / ``packaged``), ``root``,
``knowledge_base_files``, ``example_configs`` and ``warnings``. An empty
knowledge base is also warned about on stderr at startup. The root doubles as the
read-only part of the sandbox; see `Safety model`_.

The packaged example differs from the repository one in a single respect: the
repository payload reads the 21 MB ``examples/customsed.csv``, which is not
shipped. The wheel carries a reduced-resolution ``examples/customsed_demo.csv``
(about 0.4 MB) and its copy of ``payload_example.xml`` points at that file, so
the packaged example runs end to end. The star signal agrees with the full SED to
within 0.5 % per bin (measured about 0.15 %); for production work use your own
SED.

.. _mcp-per-client-setup:

Per-client setup
----------------

Each recipe adds one ``exorad`` server. Restart or reload the client afterwards,
then check `Verifying the connection`_.

**Claude Desktop** - edit ``claude_desktop_config.json`` (macOS
``~/Library/Application Support/Claude/``, Windows ``%APPDATA%\Claude\``, Linux
``~/.config/Claude/``); merge into ``mcpServers``:

.. code-block:: json

    {
      "mcpServers": {
        "exorad": {
          "command": "exorad-mcp",
          "args": ["--work-dir", "/path/to/exorad-runs"]
        }
      }
    }

Fully quit and reopen the app; the tools appear under the tools icon.

**Claude Code** - from any directory (without ``--work-dir`` runs go to
``<checkout>/mcp-runs`` for a checkout or editable install, else ``./mcp-runs``):

.. code-block:: bash

    claude mcp add exorad -- exorad-mcp --work-dir /path/to/exorad-runs

Add ``--scope user`` to make it available in every project, or commit a project
``.mcp.json`` carrying the same ``mcpServers`` block. ``claude mcp list`` shows
the connection state.

**VS Code** (GitHub Copilot, agent mode) - a workspace ``.vscode/mcp.json``, or
*MCP: Open User Configuration* for every workspace. The key is ``servers`` and
each entry names its transport:

.. code-block:: json

    {
      "servers": {
        "exorad": {
          "type": "stdio",
          "command": "exorad-mcp",
          "args": ["--work-dir", "${workspaceFolder}/mcp-runs"]
        }
      }
    }

Open the Chat view, switch to *Agent* mode, and tick ``exorad`` in the tools
picker.

**Cursor** - ``~/.cursor/mcp.json`` (global) or ``.cursor/mcp.json`` (project);
key ``mcpServers``, same shape as Claude Desktop. Enable it under
*Settings > MCP*.

**Cline** - the extension's *MCP Servers* panel writes
``cline_mcp_settings.json``; key ``mcpServers``, same shape as Claude Desktop.

**Other clients** - any client that speaks MCP over stdio can launch
``exorad-mcp``: use the generic JSON block at the top of this page in whatever
file and under whatever key the client documents.

Verifying the connection
------------------------

Ask the assistant to *call the exorad* ``capabilities()`` *tool*. A healthy
connection returns the ExoRad and ``mcp`` SDK versions, ``execution_enabled``,
the limits, the content report, the retrieval backend and the lists of
available, disabled and unavailable tools. If the client never sees the tool,
run the server by hand with the inspector (see `Debugging`_).

Troubleshooting
---------------

The client lists ``exorad`` but no tools
    The ``mcp`` extra is missing or the package fails to import. Run
    ``exorad-mcp`` in the same environment (or the check command of
    `Quickstart`_) and fix the error line it prints.

``run_pipeline`` is absent
    The server was started with ``--no-exec`` (or ``EXORAD_MCP_NO_EXEC``).
    ``capabilities()`` lists it under ``tools.disabled``.

A tool call fails with ``Error executing tool X: ... is outside the directories this MCP server may read``
    The path is outside the sandbox (a ``PathNotAllowedError`` on the server).
    Tool errors reach the client as ``Error executing tool X: <message>``, where
    the message says what went wrong. Expected failures (``OSError``,
    ``ValueError`` including ``PathNotAllowedError`` and the configuration rule
    errors, ``ImportError``, ``KeyError``, ``LookupError``, and the
    missing-content and missing-embeddings errors) carry their own text; an
    unexpected internal error stays a generic ``Error executing tool X`` and its
    traceback is on the server's stderr. For a path problem, add the directory
    with ``--allow-dir`` or ``EXORAD_MCP_ALLOW_DIRS`` (see `Safety model`_).

The knowledge base is empty
    ``capabilities()["sandbox"]["content"]["warnings"]`` says so, and so does
    stderr at startup. Reinstall ``exorad[mcp]``, or point ``--repo-root`` at a
    checkout.

A run is refused or fails at once
    Read the ``findings`` or the error text: the payload or target list broke a
    rule of ``validate_config``. ``status="refused"`` means the concurrent-job
    cap was reached; see `Running simulations`_. The finding codes that stop a
    run are listed under `Finding codes`_.

Nothing happens after moving the checkout
    A client config that pins ``command`` or ``--repo-root`` still has the old
    path. Update it and reload.

Finding codes
-------------

Each finding of ``validate_config`` (and of the checks that ``draft_config``,
``compare_configs`` and ``run_pipeline`` run first) has a ``code``. An
``error`` finding makes ``valid`` false and blocks a run; a ``warning`` does not.
The codes you meet most often:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Code
     - Meaning
   * - ``PICKLE_REFUSED``
     - A ``<datadict>`` or ``<config_dict>`` points at a ``.pickle``, ``.pkl`` or
       ``.py`` file, which would run code when loaded. Use an ``.h5`` file. Any
       other suffix there is ``UNSUPPORTED_FORMAT``.
   * - ``CONFIG_DICT_REFUSED``
     - A ``<config_dict>`` element, anywhere (comments included). The loader
       replaces the element that holds it with the content of a file, so the
       limits that are computed from the XML (``working_R``, channels, optical
       elements, ``targetR``) would no longer describe the run, and the static
       scan could not see the replacement. Write the values in the payload.
   * - ``CONFIGPATH_MULTIPLE``
     - More than one ``<ConfigPath>``. The loader keeps the last one, the
       normalised copy sets one: a payload has exactly one.
   * - ``HDF5_LINK_REFUSED``
     - An HDF5 input (``.h5``/``.hdf5``, any file that starts with the HDF5
       signature whatever its suffix, and every ``<PSF>`` with
       ``<format>paos</format>``) holds an external link, a virtual dataset or
       external raw storage. The file is scanned without following anything.
   * - ``ATTRIBUTE_REFUSED``
     - An XML attribute other than ``unit``. The loader turns every attribute
       into a key, so it could carry a path the scan does not check; write the
       value as a child element or as the element text.
   * - ``PATH_OUTSIDE_SANDBOX``
     - A referenced file lies outside the content root, the working directory and
       the allowed directories, or the value is a URL or contains a NUL
       character.
   * - ``FILE_MISSING``
     - A referenced table does not exist (often a relative ``<ConfigPath>``
       resolved against the wrong directory).
   * - ``NOT_REGULAR_FILE``
     - A referenced path is a FIFO, a device or another file that is not a
       regular file; it is refused from its ``stat`` without being opened. In a
       ``<PSF>`` or ``<StellarModels>`` directory this applies to every file the
       library's glob can return (symbolic links are refused too). It is also
       the code of the re-check when a job starts: a file that became a symbolic
       link, or is now reached through one, since the payload was validated.
   * - ``SOURCE_SED_BLOCKED``
     - ``sourceSpectrum`` is ``sed``, which downloads from the network.
   * - ``XML_DOCTYPE`` / ``XML_PARSE``
     - A ``DOCTYPE`` declaration (refused) or XML that does not parse.
   * - ``MISSING_ELEMENT``, ``UNIT_INVALID``, ``LIMIT_EXCEEDED``, ``VALUE_INVALID``
     - A required element is absent, a unit does not parse, a value is above a
       limit of the table below, or a value the library cannot use.
       ``LIMIT_EXCEEDED`` also covers an HDF5 input that declares more than
       8 x ``EXORAD_MCP_MAX_DATA_MB`` uncompressed (dataset shapes times item
       sizes, read from the metadata only) and a text table with more than
       5 000 000 lines, a line longer than 1 MiB or more than 1000 columns.
   * - ``DEEP_BUILD_FAILED``
     - ``validate_config(deep=True)`` could not build the channels, including the
       case where the cap on one-shot children was reached (see
       `Running simulations`_).

``capabilities()`` and ``exorad.mcp.rules.FINDING_CODES`` hold the full set.

Transports
----------

``exorad-mcp`` speaks three transports:

``--transport stdio`` (default)
    The server runs as a child process of one client over stdin/stdout. This is
    what a ``"command": "exorad-mcp"`` entry uses. Nothing is on the network, and
    the server installs a guard that refuses any internet connection from its own
    process.

``--transport sse`` / ``--transport http`` (with ``--host`` / ``--port``)
    The server listens on a socket (default ``127.0.0.1:8000``) so several
    clients share one instance:

    .. code-block:: bash

        exorad-mcp --transport http --host 127.0.0.1 --port 8000 --no-exec

    Clients then point at the URL instead of a command:

    .. code-block:: json

        {"mcpServers": {"exorad": {"url": "http://127.0.0.1:8000/mcp"}}}

    The HTTP and SSE transports have **no authentication**. The bind address is
    loopback unless ``--host`` says otherwise; do not bind to ``0.0.0.0`` on a
    network you do not trust, and put an authenticating proxy in front of any
    shared instance. A shared instance almost always wants ``--no-exec`` (see
    `Safety model`_). When bound to a loopback address the SDK checks the
    ``Host`` and ``Origin`` headers (HTTP 421 / 403) against DNS rebinding; that
    protection is not enabled for other bind addresses. (The in-process network
    guard is not installed for these transports, because binding a socket
    resolves a host name; the job processes keep it.)

Debugging
---------

Try the tools by hand with the official inspector:

.. code-block:: bash

    npx @modelcontextprotocol/inspector exorad-mcp --no-exec

Drop ``--no-exec`` to inspect the execution tools too. In the MCP server,
ExoRad's console logging goes to stderr, never stdout, which carries the
protocol. ``EXORAD_MCP_LOG_LEVEL`` (default ``INFO``) sets the level of the
``exorad.mcp`` logger.


The tools
=========

The server registers 21 tools. Five of them are *execution tools* and exist
only when execution is enabled (see `Safety model`_).

Response conventions
--------------------

Every tool answers in one of five ways; look for the key, not for prose.

.. list-table::
   :header-rows: 1
   :widths: 16 34 50

   * - Kind
     - How it looks
     - Meaning and what to do
   * - Tool error
     - The call fails with ``Error executing tool X: <message>``
     - A bad argument, a missing file or a path outside the sandbox. Fix the
       call; nothing was started.
   * - Refused
     - ``status: "refused"`` (``limit``, ``running_jobs``, or ``reason:
       "output_in_use"`` with ``conflicting_job``)
     - ``run_pipeline`` could not start now: too many jobs, or a running job
       uses the output or its directory. Wait, cancel, or choose another output.
   * - Busy
     - ``status: "busy"`` with ``valid: null`` or ``plottable: null``
     - Every one-shot child was taken for 20 seconds. The input was NOT judged;
       retry in a moment.
   * - Finding
     - ``valid: false`` and ``findings`` (``severity``, ``code``, ``path``,
       ``message``)
     - A verdict on the payload or target list. Fix the file.
   * - Unknown
     - ``status: "unknown"`` with ``error``
     - ``get_job_status`` / ``cancel_job`` were given an id this server does
       not know (jobs do not survive a restart).

Information and grounding
-------------------------

``capabilities()``
    What this server can do right now: the ExoRad, ``mcp`` SDK, astropy, h5py
    and Python versions, the sandbox roots and limits, the content report
    (``sandbox.content``), whether execution is enabled, the network policy, the
    retrieval backend, the pipelines, any ``discovery_errors`` and which tools
    are ``always_available``, ``execution_only``, ``disabled`` or
    ``unavailable``. Call it first so the model does not attempt a disabled
    operation. It never raises.

``search_knowledge_base(query, max_results=5, max_chars=0)``
    Ranked passages over a curated set of ExoRad files, each with its file path
    and line range (see `How grounding works`_). Returns
    ``status="insufficient_evidence"`` and no passages when nothing reaches the
    gate: the signal to *not* answer from general knowledge. ``max_results`` is
    clamped to 1..20. ``max_chars`` caps the total passage text for small-context
    clients; a passage cut short is flagged ``truncated`` and keeps its path so
    the full text can be fetched from the ``exorad://kb/<path>`` resource.

``knowledge_base_manifest()``
    The approved source patterns, the matched files, the retrieval backend and
    the minimum score used to decide "insufficient evidence".

``exorad_project_context()``
    The curated agent-guidance files (``AGENTS.md``, ``docs/ai-agents/*``).

``customisation_guide(topic)``
    Grounded passages on customising a payload (noise, spectra, foregrounds,
    optics) for a topic such as ``"add a custom noise source"``.

``list_pipelines()`` / ``describe_pipeline(pipeline="standard")``
    The one pipeline the server exposes, ``standard`` (it wraps
    ``exorad.standard_pipeline``; the equivalent command is
    ``exorad -p payload.xml -t targets.csv -o out.h5``), and its parameters:
    name, type, required, default, description and which ``run_pipeline``
    argument fills each.

``list_examples()``
    The bundled example inputs (payload XML, target list, data tables), what
    each references, whether it is runnable and whether it ships in the wheel.

``diagnose_error(error_message, context="", traceback_text="")``
    Extracts the exception type and failing frame from a traceback or log tail,
    classifies the problem (for example ``network_blocked``, ``pickle_refused``,
    ``skipped_target``, ``configpath``, ``missing_file``, ``missing_element``,
    ``unit``, ``output_exists``) and links related docs.

Configuration
-------------

``config_requirements(kind="payload", configuration=None)``
    What an ExoRad payload XML (``kind="payload"``) or target-list CSV
    (``kind="target_list"``) needs: each element or column with its unit,
    allowed values, whether it is required to ``build`` the instrument, to
    ``observe`` a target or only ``optional``, and the documentation page that
    explains it. The table is derived from what the library really requires.
    Pass a ``configuration`` to also get ``present``, ``missing``, ``extra`` and
    ``findings`` for that file, turning "invalid" into "here is what to add".

``draft_config(overrides=None, overwrite=False, name="payload")``
    Produce a working payload: it starts from ``examples/payload_example.xml``
    (with ``<ConfigPath>`` pinned to the content root), applies
    ``{"section.key": "value [unit]"}`` overrides (for example
    ``"common.wl_min": "0.6 micron"`` or
    ``"channel.Spec.detector.read_noise": "20"``), writes
    ``drafts/<name>_draft.xml`` in the working directory and validates it.
    Only **existing** elements can be changed: an override that finds nothing is
    reported under ``not_applied`` with the keys that *are* available there, and
    new elements cannot be added. XML comments of the example are not kept. An
    existing draft is not replaced unless ``overwrite=True``. A value that would
    read a file outside the sandbox, a URL, a pickle or Python file,
    ``sourceSpectrum`` ``sed`` or a value beyond the limits (for example
    ``working_R`` above 30000) is refused and nothing is written.

``draft_target_list(targets, overwrite=False, name="targets")``
    Write ``drafts/<name>.csv`` from a list of star dictionaries (``name``,
    ``M`` in solar masses, ``Teff`` in K, ``R`` in solar radii, ``D`` in parsec,
    and optionally ``magk``, ``ra``, ``dec``) and validate it. Target names are
    letters, digits, spaces and ``_ . + - ( )``, unique, at most 64 characters.

``validate_config(configuration, kind="auto", deep=False)``
    Validates a payload XML or a target-list CSV without running the pipeline:
    size, XML structure, required elements, units, limits, that every referenced
    table exists and lies in an allowed directory (the scan covers ``<comment>``
    subtrees and refuses XML attributes other than ``unit``; see
    `Safety model`_), then a parse with ExoRad. A
    problem is *returned* (``valid: false`` with ``findings``, each with
    ``severity``, ``code``, ``path`` and ``message``), not raised. The payload is
    checked through a normalised copy with absolute paths, the same one a run
    uses, so a relative ``<ConfigPath>`` is resolved against the payload's own
    directory (``.`` is the content root for the shipped ``examples/``).
    ``deep=True`` also builds the channels in a child process and returns the
    channels with their bin counts (when every one-shot child is busy for 20
    seconds the result is ``valid: null`` with ``status="busy"``: the payload
    was NOT found invalid, retry); it is an execution feature and is refused
    under ``--no-exec``. Deep builds share a cap with ``plot_output``: at most
    ``EXORAD_MCP_MAX_JOBS`` run at once, separately from the background jobs. A
    build over the cap waits briefly and is then *returned* as ``status="busy"``
    (never as a finding about the payload).

``compare_configs(config1, config2)``
    Differences between two payloads: ``identical``, ``differences`` (each with
    ``left``, ``right`` and a ``summary``), ``only_in_first`` and
    ``only_in_second``. Numbers are compared with an absolute tolerance of 1e-9,
    data tables column by column, referenced files by name. Both inputs are
    scanned before either is loaded (if one has an error, neither is parsed and
    the errors are listed per file), and the text of ``<comment>`` elements is
    not compared: two payloads that differ only in their comments are
    ``identical``.

Pipeline and jobs
-----------------

``run_pipeline(payload, target_list, output="", n_threads=1, plot=False, full_contrib=False, overwrite=False, wait_seconds=30, max_runtime_seconds=None, pipeline="standard")``
    Runs the radiometric pipeline in a supervised background process (see
    `Running simulations`_). Everything is checked before a process starts. It
    returns the final status for a quick run, a ``job_id`` to poll when the
    run outlives ``wait_seconds`` (at most 50: client tool-call timeouts are short,
    so poll with ``get_job_status``), or ``status="refused"`` when too many runs
    are active or a running job already uses the same output or output
    directory. An empty ``output`` writes
    ``runs/<time>-<id>/output.h5`` under the working directory. Execution tool.

``get_job_status(job_id)`` / ``cancel_job(job_id)`` / ``list_jobs()``
    Poll, stop or list background runs. A status reports ``targets_started``
    (targets whose observation began) and ``targets_done`` (targets that finished
    observing, which is a little before they are saved). Non-success statuses
    carry a redacted ``log_tail`` and a ``reason``; a finished job lists its
    ``files`` and a ``summary``. An unknown id returns ``status="unknown"``.
    Execution tools.

Outputs
-------

``inspect_output(path, max_items=80)``
    Structural summary of an HDF5 / ECSV / CSV output (a table is read as ECSV
    first, so an ECSV table named ``.csv``, as the shipped example tables are,
    shows its columns and metadata): groups, datasets, shapes,
    dtypes and attributes, listed breadth first. Recognised nodes carry a
    one-line ``meaning``. For an ExoRad file the result also has an ``exorad``
    block with the version, target names, each channel (class, number of bins,
    wavelength range) and the columns of the result table. A relative ``path``
    is looked up in the working directory first, then in the content root.

``explain_output(path, max_items=200, target=None)``
    The structure *plus* the science: every node is matched against a built-in
    output map and annotated with its meaning, units, the code that wrote it and
    the doc page; nodes with no entry are listed under ``unexplained``. It also
    describes every column of the result table and, per target and channel, a
    ``noise_budget``: the minimum, median and maximum of each noise component in
    sqrt(hr), the dominant component at the band centre, the total noise and a
    reconstruction of it from the documented formula. By default the first five
    targets are explained; ``target`` picks one.

``plot_output(path, target=None, kind="table")``
    Draws PNG figures from an HDF5 output into ``<work dir>/plots/<name>/`` for a
    vision-capable client to look at. ``kind="table"`` draws the signal and noise
    panels of a target (the first five, or the one named by ``target``);
    ``kind="efficiency"`` draws the transmission, quantum efficiency and their
    product for every channel (``target`` applies to ``kind="table"`` only and is
    refused with ``efficiency``). Figures are rendered in a separate process,
    capped at ``EXORAD_MCP_MAX_JOBS`` at once together with deep validation; a
    plot over the cap waits up to 20 seconds, then returns ``status="busy"``,
    ``plottable: null`` and no figures (the file was not found unplottable). A
    file that cannot be plotted returns ``plottable: false`` with a ``reason``.
    The folder name is the output's path plus a short hash of it, so two outputs
    never share a folder. Execution tool.

``inspect_output``, ``explain_output`` and ``plot_output`` refuse HDF5 files that
contain external links or virtual datasets, before reading anything: such a file
could otherwise make the server open a file outside the sandbox.


Resources and prompts
=====================

Besides tools, the server exposes:

**Resources** - the knowledge-base files, browsable by URI. ``exorad://kb`` lists
them; the template ``exorad://kb/{+path}`` returns one file's text (only files in
the manifest, capped at 200 kB; the ``+`` lets the path contain ``/``, as in
``exorad://kb/docs/source/user/inputs.rst``). Use these to pull a whole page
rather than only the passages a search returned.

**Prompts** - ready-made workflows a client can start from:

``new_simulation``
    Go from nothing to a finished run: requirements, draft, validate, run,
    explain, plot.
``set_up_channel``
    Configure a payload channel parameter by parameter, then validate.
``diagnose_failed_run``
    Work through a failed run from its log tail and the validation findings.
``explain_output``
    Inspect an output file and explain each group from the docs.

Every prompt tells the model to ground its claims in the tools.


How grounding works
===================

``search_knowledge_base`` runs a dependency-light **BM25** ranker over the files
listed by ``knowledge_base_manifest``: the top-level docs and ``AGENTS.md``, the
user guide, the example payload and target list, the changelog and the source of
the pipeline, tasks, models, output writer and plotter. The internal planning
notes, the SED downloader
and the version check are never indexed or shipped.

- **Structure-aware chunking**: reStructuredText is split by section, Python by
  top-level ``def`` / ``class``, Markdown by heading, other files by a fixed
  line window. Each hit reports its file and line range for fact-checking.
- **Identifier-aware tokenisation**: ``LoadOptions`` also matches ``load`` and
  ``options``; ``wl_grid`` matches ``wl`` and ``grid``.
- A passage is returned only if it contains a meaningful fraction of the
  distinct query terms (``minimum_retrieval_score``, default 0.15); otherwise
  the tool returns ``insufficient_evidence`` and an empty result. The gate is
  lexical, so a question that shares ordinary words with the docs still returns
  passages: the model must read them and say so when they do not answer the
  question.
- The index is cached and rebuilt automatically when a source file changes.

To add a source class, extend ``DEFAULT_SOURCE_PATTERNS`` in
``exorad/mcp/retrieval.py``.

Hybrid (semantic) retrieval
---------------------------

BM25 misses paraphrase: "shot noise" will not find a page that only says
"photon noise". Install the extra and switch backend:

.. code-block:: bash

    pip install "exorad[mcp,mcp-embeddings]"
    export EXORAD_MCP_RETRIEVAL=hybrid

The ``mcp-embeddings`` extra does **not** include ``mcp``: install both extras.
It pulls in ``sentence-transformers`` and so PyTorch, a large download.

A passage then also qualifies on sentence-embedding similarity
(``all-MiniLM-L6-v2`` through ``sentence-transformers``; the model is
downloaded on first use), and the two scores are combined. The lexical backend
stays the default and the fallback if the extra is missing;
``knowledge_base_manifest`` and ``capabilities`` report which backend is live.
The download happens in the server process, outside the job guard, so fetch the
model once before running a locked-down server.

Retrieval eval suite
--------------------

``tests/mcp/retrieval_cases.py`` and ``tests/mcp/retrieval_cases_blind.py`` hold
ground-truth (question, expected source) pairs; the tests run each one through
the real ranker and check the aggregate recall@k. They are the guardrail that a
doc rewrite or a change to the ranker does not quietly make a topic unfindable.
When you add or move a documentation page, add or update the matching case.


.. _mcp-safety-model:

Safety model
============

An MCP client is an autonomous program driven by a language model. Treat it as
an untrusted user of the machine the server runs on.

**What "execution enabled" means for ExoRad.** With execution enabled (the
default) a client can start **heavy jobs and read files**. An ExoRad payload
does not load Python tasks, but the library has one code-execution surface:
``pickle``, reached through the ``<datadict>`` and ``<config_dict>`` tags. The
server refuses it **statically**, before any ExoRad code reads the payload:
``validate_config``, ``compare_configs``, ``draft_config`` and ``run_pipeline``
report ``PICKLE_REFUSED`` for a ``.pickle``, ``.pkl`` or ``.py`` file, whatever
``--no-exec`` says, and ``LoadOptions`` is not called while the scan has errors.

That guarantee rests on the scan seeing every place the loader reads. The loader
(``exorad.tasks.loadOptions``) opens files named by ``datafile``, ``datadict``
and ``config_dict`` children at any depth, parses ``<comment>`` subtrees like any
other element, and turns every XML attribute into a key. The scan therefore
checks the text of every element, **including those inside** ``<comment>``
elements, and refuses (``ATTRIBUTE_REFUSED``) any attribute other than ``unit``.
Files that are not regular files (a FIFO, a device) are refused
(``NOT_REGULAR_FILE``) from their ``stat``, without opening them. The copy of the
payload that a job opens has its absolute paths rewritten and its ``<comment>``
elements removed. This is a mirror of the loader, not a sandbox around it: a
future change to how the loader reads a payload needs the scan updated with it,
and a test walks the parser's real output to catch that.

Three more rules follow from what the loader and the readers do. ``<config_dict>``
is not accepted at all (``CONFIG_DICT_REFUSED``): it replaces the element that
holds it with the content of a file, so neither the scan nor the numeric limits
could see what the run uses; ``<datadict>`` only adds a ``data`` key and stays
accepted for ``.h5``/``.hdf5`` files. A directory named by ``<PSF>`` or
``<StellarModels>`` is listed the way the library globs it, and every file found
must be a regular file, not a symbolic link, inside the readable directories and
within the data size limit; a directory that is a sandbox root, or contains one,
is refused. Because the readers call ``glob(name + "*.fits")``, the normalised copy
writes a ``<PSF>`` directory with a trailing separator so that the pattern means
"inside the directory".

**Checks and use are separate moments.** Only the payload is copied into the run
directory; the target list and every data file it names are opened later from their
original paths. A job therefore checks them again in its own process before the
library starts (regular file, no symbolic link on the way, inside the readable
directories, within the size limits, HDF5 link scan, directory listings), and
``validate_config`` and ``compare_configs`` do the same just before they parse the
copy in the server process; a file replaced by a link or a pipe in between makes
the job fail with the file's label in the error. This narrows the window, it does
not close it: a process that can write to the working directory or to a directory
the payload names can still replace a file between the last check and the moment
the library opens it. Keep those directories writable by trusted users only.

**``PHOENIX_PATH``.** When a payload uses the ``phoenix`` source without a
``<StellarModels>`` element, the library reads the directory named by the
``PHOENIX_PATH`` environment variable of the server. That is an operator
configured read root: the scan does not list it and the sandbox does not confine
it. Set it only to a directory you trust, or leave it unset.

What an enabled run can do:

- use CPU, memory and disk up to the limits in the table below (targets,
  spectral bins, table sizes, output size, wall-clock time, concurrent jobs and
  worker processes);
- read, through the payload's ``<datafile>``, ``<CustomSed>``, ``<PSF>`` and
  similar tags, **any table in the allowed roots**. Only add directories you
  trust to ``--allow-dir``;
- write into the working directory (and the allowed directories).

The sandbox confines the **paths the MCP tools accept**. It does not make the
scientific libraries ExoRad calls trustworthy against a hostile file: treat the
allowed directories as trusted. ``--no-exec`` removes the jobs entirely.

**The content root** (``--repo-root``; see `Where the content comes from`_)
    The ExoRad checkout or the packaged content. Tools may *read* payloads,
    examples and source here; no tool writes here.

**The working directory** (``--work-dir``, default ``<repo-root>/mcp-runs`` for a
checkout or editable install, ``./mcp-runs`` in the server's current directory
when the content is packaged, and ``~/.exorad/mcp-runs`` when that default cannot
be created)
    Every file the tools write (drafts, outputs, logs, plots) goes here, and
    results are read back from it. All writes go to the working directory (plus
    any ``--allow-dir`` entry).

Any path outside these, such as an absolute path elsewhere, a ``~`` expansion, a
URL, a symbolic link that leaves the roots or a ``../`` that escapes them, is
rejected with a ``PathNotAllowedError`` before any file is touched. In the
packaged layout the current directory is not readable (only the packaged
content, the working directory and the allowed directories are), so list it with
``--allow-dir`` if your payloads live in it.

**Display paths.** Tools never print the server's absolute directory layout.
Paths in results are shown as ``work:<relative>``, ``content:<relative>`` or
``allow[i]:<relative>``. Log tails, job errors and the failure text of a
one-shot child (a deep validation or a plot) are redacted the same way, and in
addition hide the interpreter and the home directory: ``site-packages`` becomes
``<site-packages>``, the Python prefix ``<python>`` and the home directory ``~``,
so a traceback does not show the server's layout. These display
paths are accepted back as input (``inspect_output("work:demo/out.h5")``), and go
through exactly the same containment checks as any other path, so a label never
widens the sandbox. ``capabilities()`` is the one place the roots are shown in
full.

**Network.** The SED downloader and every other network source are **not
exposed**. ``sourceSpectrum=sed`` is refused statically by every tool that reads
a payload. As a second line of defence, a guard makes any attempt to open an
internet connection or resolve a host name raise ``NetworkBlockedError``; it is
installed in the stdio server and in every job process (the job processes run
with ``EXORAD_NO_VERSION_CHECK`` set, so the release check of the ``exorad``
commands is off). The guard patches the
process that installs it: the worker processes that ``n_threads > 1`` starts
with ``spawn`` (macOS) or ``forkserver`` (Linux from Python 3.14) re-import
everything and do not inherit it, so for a multi-process run the static refusal
is the control. It is a backstop against accident, not a sandbox against hostile
native code. There is deliberately no switch that enables network access.

``import exorad`` never touches the network. The online check for a newer
release belongs to the command-line entry points: both ``exorad`` and
``exorad-plot`` run it (and print the update notice) unless
``EXORAD_NO_VERSION_CHECK`` is set to a non-empty value. The MCP server never
runs it.

``--no-exec`` (``EXORAD_MCP_NO_EXEC``) removes the five execution tools
(``run_pipeline``, ``get_job_status``, ``cancel_job``, ``list_jobs`` and
``plot_output``) and makes ``validate_config(deep=True)`` refuse. The server then
only answers questions, drafts and validates payloads and target lists, and
inspects and explains outputs.

The HTTP and SSE transports have **no authentication** (see `Transports`_).

The content root and working directory are **server configuration**, set once at
startup and never exposed as tool arguments, so a client cannot widen its
sandbox.

.. list-table::
   :header-rows: 1
   :widths: 32 14 20 34

   * - Environment variable
     - Flag
     - Default
     - Meaning
   * - ``EXORAD_MCP_REPO_ROOT``
     - ``--repo-root``
     - checkout, else packaged
     - Override of the content root (read-only).
   * - ``EXORAD_MCP_WORK_DIR``
     - ``--work-dir``
     - ``<content>/mcp-runs`` or ``./mcp-runs``
     - Writable directory for drafts, outputs, logs and plots.
   * - ``EXORAD_MCP_ALLOW_DIRS``
     - ``--allow-dir`` (repeatable)
     - none
     - Extra allowed read/write roots, ``os.pathsep``-separated.
   * - ``EXORAD_MCP_NO_EXEC``
     - ``--no-exec``
     - off
     - Truthy value (``1``, ``true``, ``yes``, ``on``) disables the execution tools.
   * - ``EXORAD_MCP_MAX_THREADS``
     - none
     - ``min(4, cpus)``
     - Cap on ``n_threads`` (worker processes) for one run.
   * - ``EXORAD_MCP_MAX_RUNTIME``
     - none
     - 3600
     - Hard wall-clock limit per run, seconds. A finite number up to 1e6;
       ``inf``, ``nan``, zero, negative or unreadable values fall back to the
       default and a larger one is clamped to 1e6 (one warning on stderr).
   * - ``EXORAD_MCP_MAX_JOBS``
     - none
     - 2
     - Concurrent background runs allowed, and, in a separate pool, concurrent
       one-shot children (``validate_config(deep=True)`` and ``plot_output``), so
       at most twice this many child processes can run at once (invalid or 0
       gives the default).
   * - ``EXORAD_MCP_MAX_TARGETS``
     - none
     - 200
     - Rows in a target list.
   * - ``EXORAD_MCP_MAX_OUTPUT_MB``
     - none
     - 512
     - Estimated and measured size of one run's HDF5 output.
   * - ``EXORAD_MCP_MAX_BINS``
     - none
     - 20000
     - Spectral bins per channel.
   * - ``EXORAD_MCP_MAX_DATA_MB``
     - none
     - 64
     - Size of any data table a payload references.
   * - ``EXORAD_MCP_MAX_FILE_MB``
     - none
     - 2
     - Size of a payload XML or target list.
   * - ``EXORAD_MCP_VALIDATE_TIMEOUT``
     - none
     - 120
     - Seconds for ``validate_config(deep=True)`` and for a plot (each is one
       child, counted against ``EXORAD_MCP_MAX_JOBS`` in its own pool).
   * - ``EXORAD_MCP_EXEC_BACKEND``
     - none
     - ``process``
     - ``process`` or ``inline`` (runs in the server process; debugging only).
   * - ``EXORAD_MCP_RETRIEVAL``
     - none
     - ``bm25``
     - ``bm25`` or ``hybrid`` (needs the ``mcp-embeddings`` extra).
   * - ``EXORAD_MCP_LOG_LEVEL``
     - none
     - ``INFO``
     - Level of the ``exorad.mcp`` logger (stderr).

Invalid or non-positive numeric values fall back to the default (durations must
also be finite and are clamped to 1e6 seconds, with one warning on stderr). The
limits are also reported by ``capabilities()``.


.. _mcp-running-simulations:

Running simulations
===================

An ExoRad run can take seconds to hours, so ``run_pipeline`` never blocks the
server: each run happens in a **separate, supervised process** (started with
``spawn``, so it shares no state with the server).

#. ``run_pipeline`` checks the request: both files exist inside the sandbox, the
   payload and target list pass the rules of ``validate_config``, the limits are
   respected, the output is a ``.h5``/``.hdf5`` path in a sub-directory of the
   working directory (an existing file is refused unless ``overwrite=True``;
   every existing parent must be a directory; an output or output directory that a
   running job uses is refused whatever ``overwrite`` says) and
   the estimated output size is under ``EXORAD_MCP_MAX_OUTPUT_MB``. Any problem
   is raised as an error that lists the findings. Nothing has started yet.
#. It starts the job on a normalised copy of the payload with absolute paths,
   and blocks for up to ``wait_seconds`` (default 30, at most 50, because client
   tool-call timeouts are short; the first call can take tens of seconds just to
   import ExoRad).
#. If the run finishes in that window it returns the final status:

   .. code-block:: json

       {"job_id": "7e80cb7cda82", "pipeline": "standard", "status": "succeeded",
        "outcome": "complete", "output": "work:demo/out.h5",
        "log_file": "work:logs/7e80cb7cda82.log", "runtime_seconds": 3.49,
        "targets_started": 2, "targets_done": 2, "targets_requested": 2,
        "targets": 2, "estimated_output_mb": 8.8, "n_threads": 1, "warnings": []}

   (the result also carries the times ``submitted_at``, ``started_at`` and
   ``finished_at`` (``submitted_at`` is never later than ``started_at``),
   ``files``, ``summary`` and the payload and target list paths).

#. Otherwise it returns ``"status": "running"`` and a ``job_id`` to poll.
#. The client polls ``get_job_status(job_id)`` until the status is
   ``succeeded``, ``failed``, ``timeout`` or ``cancelled``. On any non-success
   outcome the response carries ``log_tail`` and a ``reason``. ``cancel_job``
   stops a run; ``list_jobs`` lists every run since the server started.

Details:

- drafts go to ``drafts/``, outputs wherever ``output`` says (default
  ``runs/<time>-<id>/output.h5``), logs to ``<work-dir>/logs/<job_id>.log`` and
  plots to ``plots/<name>/``. The pipeline copies the payload and target list
  next to the output;
- ``n_threads`` is reduced to ``EXORAD_MCP_MAX_THREADS`` and to the number of
  targets; the response warns when it was reduced;
- progress comes from the job log: the library logs ``observing <name>`` when it
  starts a target and ``target <name> observed`` when it has finished observing
  it, and the status counts them as ``targets_started`` and ``targets_done``.
  A target counted in ``targets_done`` is observed but may not be written yet
  (the file is written at the end), and a failed target is started but never
  done;
- a run is hard-killed after ``max_runtime_seconds`` (per call) or
  ``EXORAD_MCP_MAX_RUNTIME`` and reported as ``timeout``; a watchdog enforces
  this without anyone polling. ``max_runtime_seconds`` must be positive and can
  only shorten the server-side limit, never lift it; when the value you asked
  for was reduced to the cap, ``warnings`` says so. A run whose output grows
  beyond ``EXORAD_MCP_MAX_OUTPUT_MB`` is killed and reported as ``failed``;
- at most ``EXORAD_MCP_MAX_JOBS`` runs (default 2) are active. A further
  ``run_pipeline`` returns ``{"status": "refused", "limit": ..., "running_jobs":
  [...], "error": ...}`` instead of starting; cancel one or wait;
- two runs never share an output file or an output directory (the library copies
  the payload and the target list next to the output, and with ``overwrite=True``
  deletes an existing output first). ``run_pipeline`` returns ``{"status":
  "refused", "reason": "output_in_use", "conflicting_job": ...}`` for an output
  or directory that a running job uses; nothing is touched. With
  ``overwrite=True`` a later run of the SAME output replaces the input copies the
  earlier run left next to it (recorded in ``<stem>.run.json``); any other file
  of that name is still refused;
- the one-shot child processes of ``validate_config(deep=True)`` and
  ``plot_output`` are capped at the same ``EXORAD_MCP_MAX_JOBS`` but in a
  **separate pool**: they never take a background-job slot, and a background job
  never blocks them. A call over the cap waits up to 20 seconds for a free slot,
  then returns ``status="busy"``: ``validate_config`` gives ``valid: null`` (the
  payload is NOT reported invalid) and ``plot_output`` gives ``plottable: null``
  with no figures; retry in a moment. The worst case is therefore
  twice ``EXORAD_MCP_MAX_JOBS`` child processes, each with its own worker
  processes for ``n_threads > 1``;
- **partial runs**: the library skips a target that fails and carries on with
  the others. If some, but not all, targets were written, the job is
  ``failed`` with ``"outcome": "partial"`` and ``skipped_targets`` naming the
  ones that were not (``targets_started`` is then larger than ``targets_done``);
  the HDF5 file keeps the good targets and ``warnings`` says how many were
  written. If no target succeeds the job fails with the library's error in
  ``log_tail``. The ``exorad`` command behaves alike: it writes the good
  targets, prints ``exorad: N target(s) skipped: a, b`` to stderr and exits with
  status 1, so a batch script notices the partial run (status 0 means every
  target was observed). ``exorad.standard_pipeline`` returns the list of skipped
  names (empty if none) and raises only when no target could be observed;
- each job process leads its own process group, and every signal goes to the
  whole group, so ``n_threads > 1`` worker processes die with it. Running jobs
  are stopped when the server goes away: on SIGTERM the server terminates its
  children and exits; on stdin EOF (the client closes the connection) it exits
  and its children are terminated; on SIGINT it terminates the children but the
  MCP SDK's stdio loop then stays up, idle and no longer answering, until stdin
  is closed, so prefer SIGTERM;
  if the server is killed with SIGKILL the children notice the missing parent
  and end their own group within a few seconds;
- jobs live in memory only and do not survive a restart. Their output files do;
- ``EXORAD_MCP_EXEC_BACKEND=inline`` runs synchronously in the server process
  (debugging only).


Known limits
============

- **Search is lexical.** The default retrieval matches words, so an off-topic
  question that shares ordinary words with the documentation can still return
  ``status="ok"`` with passages that do not answer it. The assistant has to read
  them and say so; ``insufficient_evidence`` appears only when a question shares
  almost no words with the knowledge base.
- **An empty knowledge base is not flagged by every tool.** Only
  ``capabilities()`` (``sandbox.content.warnings``) and the server's stderr at
  startup warn about it. ``list_examples`` and ``search_knowledge_base`` just
  return nothing.
- **Semantic search needs both extras.** ``mcp-embeddings`` does not include
  ``mcp``: install ``pip install "exorad[mcp,mcp-embeddings]"``. It pulls in
  PyTorch.
- **Stopping the stdio server.** On SIGINT the server terminates its job
  processes; an idle server then stays alive but stops answering requests until
  stdin closes. Send SIGTERM (or close the client) to stop it.
- **Resource URIs.** An ``exorad://kb/`` URI whose path contains ``..`` is
  refused, and the client sees a generic JSON-RPC error rather than the
  explanation. Use the paths listed by ``exorad://kb``.
- **Windows** is not supported for execution (the job supervision needs POSIX
  process groups); run with ``--no-exec``.
- **Continuous integration** has not yet run the MCP tests on Linux with Python
  3.12 to 3.14.

Example conversations
=====================

Three exchanges with a client configured as in `Quickstart`_. Tool calls the
assistant makes are shown as ``-> tool(args)`` with the result under them. The
keys and values are those the tools returned in a real run of the bundled
example (ExoRad 2.3, a checkout as content root, single process), with ``...``
where a long part is left out; times and ids change from run to run.

Grounding an answer
-------------------

*You* - How is the read noise of a detector set in the payload, and where does
the pipeline use it?

*Assistant* -

.. code-block:: text

    -> search_knowledge_base("how do I set the read noise of a channel detector")
       docs/source/user/mcp.rst:<lines>          (this page's own example)
       exorad/models/noise.py:53-96
       docs/source/user/radiometric_model/read_noise.rst:4-14
       exorad/tasks/noiseHandler.py:4-104
       docs/source/user/radiometric_model/total_noise.rst:4-35

The read-noise gain is computed from the number of non-destructive reads in a
frame by ``multiaccum`` in ``exorad/models/noise.py`` (lines 53-96), and
:doc:`radiometric_model/read_noise` explains how it enters the total noise. In
the payload the value sits under the channel's detector block; to change it in
a draft use ``draft_config`` with the override
``channel.Spec.detector.read_noise``.

Drafting, validating and running
--------------------------------

*You* - Take the bundled example, move the lower edge of the common wavelength
range to 0.6 micron and set the read noise of the spectrometer to 20. Then
observe HD 209458 and GJ 1214 and tell me what the noise budget looks like.

*Assistant* -

.. code-block:: text

    -> draft_config({"common.wl_min": "0.6 micron",
                     "channel.Spec.detector.read_noise": "20"})
       {"draft": "drafts/payload_draft.xml", "valid": true, "findings": [],
        "applied": [{"path": "common.wl_min", "value": "0.6 micron"},
                    {"path": "channel.Spec.detector.read_noise", "value": "20"}],
        "not_applied": [], ...}

    -> draft_target_list([
         {"name": "HD 209458", "M": 1.12, "Teff": 6065, "R": 1.16, "D": 48.3},
         {"name": "GJ 1214",   "M": 0.18, "Teff": 3250, "R": 0.21, "D": 14.6}])
       {"draft": "drafts/targets.csv", "rows": 2,
        "columns": ["star name", "star M [M_sun]", "star Teff [K]",
                    "star R [R_sun]", "star D [pc]"],
        "valid": true, "findings": []}

    -> validate_config("drafts/payload_draft.xml")
       {"kind": "payload", "valid": true, "findings": [], "referenced_files": [...],
        "summary": {"working_R": 6000, "source": "custom",
                    "channels": [{"name": "Phot", "class": "photometer"},
                                 {"name": "Spec", "class": "spectrometer"}], ...}}

    -> run_pipeline("drafts/payload_draft.xml", "drafts/targets.csv", "demo/out.h5")
       {"job_id": "7e80cb7cda82", "status": "succeeded", "outcome": "complete",
        "output": "work:demo/out.h5", "runtime_seconds": 3.49,
        "targets_started": 2, "targets_done": 2, "estimated_output_mb": 8.8,
        "summary": {"channels": [{"name": "Phot", "n_bins": 1},
                                 {"name": "Spec", "n_bins": 12}]}}

    -> explain_output("work:demo/out.h5", target="HD 209458")
       {"pipeline": "standard", "total_nodes": 1328, "explained_count": 1328,
        "unexplained_count": 0, "noise_budget": {"HD 209458": {"channels": {...}}}}

The run took about four seconds and wrote two targets with two channels
(``Phot``: 1 bin, ``Spec``: 12 bins). In the noise budget for HD 209458 the
dominant component at the centre of the ``Phot`` band is ``darkcurrent_noise``;
``explain_output`` also gives the minimum, median and maximum of every component
(``star_signal_inAperture_noise``, ``read_noise``, ``zodi_signal_noise`` ...)
and reports how closely the documented formula reproduces ``total_noise``
(``reconstruction``; for ``Phot`` the relative difference was about 2e-16).
``plot_output("work:demo/out.h5", target="HD 209458")`` then writes
``table-HD 209458.png`` under ``work:plots/demo-out``, and
``plot_output(..., kind="efficiency")`` writes ``efficiency.png``.

A request the sandbox refuses
-----------------------------

*You* - Validate ``/etc/passwd`` as a payload, then draft one that downloads its
SED.

*Assistant* -

.. code-block:: text

    -> validate_config("/etc/passwd")
       Error executing tool validate_config: '/etc/passwd' is outside the
       directories this MCP server may read (content, work)

    -> draft_config({"common.sourceSpectrum": "sed"})
       Error executing tool draft_config: common/sourceSpectrum: sourceSpectrum
       'sed' downloads from the network and is disabled in the MCP; use planck,
       phoenix (local files) or custom

Both refusals come with the reason in the message, so the assistant can explain
what to do instead (copy the file into an allowed directory, or use a local
spectrum).


Using the tools from Python
===========================

Every tool is a plain function in ``exorad.mcp.tools_info``, ``tools_config``,
``tools_run`` and ``tools_output`` (``exorad.mcp.tools`` holds the registry and
``capabilities``). They are useful for scripting, or for testing the server
without a client. They read their sandbox from the environment, so set it first:

.. code-block:: python

    import os

    os.environ["EXORAD_MCP_WORK_DIR"] = "/path/to/exorad-runs"

    from exorad.mcp import tools_config, tools_info

    print(tools_info.search_knowledge_base("saturation time")["sources"][0]["path"])
    draft = tools_config.draft_config({"common.wl_min": "0.6 micron"})
    print(draft["draft"], draft["valid"])

These functions raise ordinary exceptions (``ValueError``, ``OSError`` ...); only
the registered server wrapper turns them into ``Error executing tool X: ...``.
``run_pipeline`` starts a spawned process, so a script that calls it needs the
usual ``if __name__ == "__main__":`` guard.


Extending the server
====================

Another package (for example a mission tool built on ExoRad) can reuse the
server, the job manager, the sandbox and the static scan without copying them.
Everything below is server-side Python configuration written by the extension's
own code: none of it can be set by a client.

.. code-block:: python

    # mypkg/mcp/extension.py
    import argparse
    import os

    from exorad.mcp import jobs, server, tools

    jobs.register_entry_prefix("mypkg.mcp.")  # job entries under mypkg.mcp.

    REGISTRY = (
        *tools.REGISTRY,  # ExoRad's 21 tools ...
        tools.ToolEntry("my_tool", "mypkg.mcp.tools_my", "my_tool", False),
    )
    HIDE = ("diagnose_error",)  # ... minus the ones that do not apply


    def setup(args: argparse.Namespace) -> None:
        # runs after the flags reached os.environ and before the sandbox exists
        os.environ.setdefault("EXORAD_MCP_REPO_ROOT", "/path/to/my/content")
        os.environ.setdefault("EXORAD_MCP_CONTENT_SOURCE", "packaged")


    def main() -> None:
        server.main(
            name="mypkg",
            prog="mypkg-mcp",
            title="MyPkg",
            description="Run the MyPkg MCP server.",
            epilog="Variables: MYPKG_MCP_*.",
            help_overrides={"repo_root": "MyPkg content root."},
            registry=REGISTRY,
            hide=HIDE,
            prompts=[my_prompt],  # plain functions returning text
            resources=[("mypkg://thing", my_resource)],
            setup=setup,
        )

Job entries
    ``jobs.register_entry_prefix(prefix)`` accepts a prefix that ends with ``.``,
    names a package and a sub-package (``mypkg.mcp.``) and does not start with a
    standard-library module (``os.``, ``subprocess.`` are refused). The parent
    checks every ``module:function`` entry against the list before it spawns a
    child, and passes the list to the child, which registers it again. A job
    spec holds a constant entry chosen by the server code, never a client value.

Tools
    ``tools.load_tools(*, allow_exec, registry=None, hide=())`` and
    ``server.build_server(..., registry=None, hide=())`` serve the table you pass
    instead of ``tools.REGISTRY``; nothing global is changed, and ExoRad's own
    server still has its 21 tools. ``ToolEntry.module`` can be any importable
    module: one that cannot be imported is reported under
    ``capabilities()["tools"]["unavailable"]``, like ExoRad's own. Errors of
    the expected types (``ValueError``, ``OSError``, ``LookupError`` ...) reach the
    client with their message for extension tools too. A duplicate name or a
    ``hide`` name that is not in the table is refused. ``capabilities`` lists the
    tools of the table that is served.

Command line and content
    ``server.main`` and ``server.build_server`` take ``name`` (server name),
    ``prompts`` (extra prompt functions) and ``resources`` (``(uri, function)``
    pairs), both registered after ExoRad's. ``main`` also takes ``prog``,
    ``title`` (banner), ``description``, ``epilog``, ``help_overrides`` (per
    option help for ``repo_root``, ``work_dir``, ``allow_dir``, ``no_exec``),
    ``version_text`` and ``setup``. When
    an extension pins its content root with ``EXORAD_MCP_REPO_ROOT``, the content
    report says ``override``; ``EXORAD_MCP_CONTENT_SOURCE=packaged`` (or
    ``checkout``) changes only that label.

Configurations that are not ExoRad payloads
    ``exorad.mcp.rules.static_findings(path, *, sandbox, payload_checks=True,
    exclude_reference_tags=(), reference_tags=())`` scans a run configuration of
    another package with ``payload_checks=False``: the checks that mirror what the
    loader reads still run (comments, attributes other than ``unit``, DOCTYPE,
    ``config_dict``, pickles, URLs, FIFO, symbolic links, regular files, HDF5
    links, directory listings, a repeated ``ConfigPath``), the
    payload-shape rules (required elements, channels, optical elements, bins,
    ``working_R``, units, source spectrum) do not.
    ``exclude_reference_tags`` names tags that are not files (an output
    directory), ``reference_tags`` names tags whose text is always a file. The same
    three arguments exist on ``rules.normalise_payload`` (an absolute-path copy),
    ``rules.recheck_payload`` and ``rules.tree_findings``, and
    ``pipelines.revalidate_inputs`` reads ``payload_checks``,
    ``exclude_reference_tags`` and ``reference_tags`` from the job spec.
