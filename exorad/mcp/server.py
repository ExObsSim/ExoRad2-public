"""MCP server entry point for ExoRad (console script ``exorad-mcp``).

Nothing is written to stdout here: on the stdio transport stdout is the JSON-RPC
channel, so the banner and every log line go to stderr.
"""

from __future__ import annotations

import argparse
import functools
import logging
import os
import sys
from importlib.metadata import (
    PackageNotFoundError,
    version as _pkg_version,
)
from typing import TYPE_CHECKING, Any

from exorad.mcp import jobs, prompts, resources, tools
from exorad.mcp.assets import ContentMissingError
from exorad.mcp.embeddings import EmbeddingsUnavailableError
from exorad.mcp.sandbox import (
    ENV_ALLOW_DIRS,
    ENV_NO_EXEC,
    ENV_REPO_ROOT,
    ENV_WORK_DIR,
    Sandbox,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

# ``build_server`` / ``main`` take parameters called ``prompts`` and ``resources``:
# keep the ExoRad modules reachable under other names inside them.
_EXORAD_PROMPTS = prompts
_EXORAD_RESOURCES = resources

ENV_LOG_LEVEL = "EXORAD_MCP_LOG_LEVEL"

_TRANSPORTS = {"stdio": "stdio", "sse": "sse", "http": "streamable-http"}

_LOGGER = logging.getLogger("exorad.mcp")
_HANDLER_TAG = "_exorad_mcp_stderr"

# Failures a tool raises on purpose (sandbox refusals, missing files, bad
# arguments, an unavailable optional extra). The SDK would reduce any other
# exception to "Error executing tool X". ``RuntimeError`` is deliberately NOT
# listed as a whole: it is also what a genuine bug often raises, and those must
# keep the SDK's generic error (the traceback goes to the server's stderr). The
# RuntimeError subclasses this package defines for user-facing conditions
# (``ContentMissingError``, ``EmbeddingsUnavailableError``) are listed one by
# one; ``JobLimitError``, ``OutputInUseError`` and ``SyncLimitError`` are not
# errors at all: the tools turn them into ``refused`` / ``busy`` results.
# ``PathNotAllowedError`` and the configuration rule errors are ValueErrors.
_EXPECTED_ERRORS = (
    OSError,
    ValueError,
    ImportError,
    KeyError,
    LookupError,
    ContentMissingError,
    EmbeddingsUnavailableError,
)


def _tool_error_class() -> type[Exception]:
    """Return the SDK's anticipated-tool-failure exception."""
    from mcp.server.mcpserver.exceptions import ToolError

    return ToolError


def _expose_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a tool so its expected errors reach the client with their message.

    The function itself is unchanged (unit tests call it directly and expect the
    original exceptions); only the registered wrapper converts them to the SDK's
    ``ToolError``, which the client receives as an error result carrying the text.
    """
    tool_error = _tool_error_class()

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except _EXPECTED_ERRORS as exc:
            # KeyError.__str__ adds quotes around the message.
            message = (
                str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
            )
            raise tool_error(message or type(exc).__name__) from exc

    return wrapper


def _mcp_in_range(installed: str) -> bool:
    """Whether the installed ``mcp`` version satisfies ``>=2,<3``."""
    head = installed.split(".", 1)[0]
    return head.isdigit() and int(head) == 2


def _load_server_class() -> type:
    """Return the ``mcp`` SDK server class (``MCPServer``, ``mcp>=2,<3`` only).

    Raises
    ------
    ImportError
        If the SDK is missing or is a 1.x release (there is no fallback).
    """
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:
        try:
            installed: str | None = _pkg_version("mcp")
        except PackageNotFoundError:
            installed = None
        if installed is None:
            detail = "the 'mcp' SDK (mcp>=2,<3) is not installed"
        elif not _mcp_in_range(installed):
            detail = f"mcp {installed} is installed but mcp>=2,<3 is required"
        else:
            # the version is right: the import failed for another reason (for
            # example a dependency of the SDK is missing); do not blame the version
            detail = f"mcp {installed} is installed but could not be imported"
        raise ImportError(
            "The ExoRad MCP server needs the optional dependency group: "
            f'pip install "exorad[mcp]" (needs mcp>=2,<3; {detail}; '
            f"{type(exc).__name__}: {exc})."
        ) from exc
    return MCPServer


def _route_logging_to_stderr() -> None:
    """Make sure every ExoRad log line goes to stderr, never to stdout.

    ExoRad's console handler binds ``sys.stderr`` when it is imported; this
    rebinds it to the current ``sys.stderr`` anyway. The shared handler sits at
    INFO and is reset to INFO by the library (``enableLogging``), so the level
    requested by ``EXORAD_MCP_LOG_LEVEL`` is served by the ``exorad.mcp`` logger's
    own stderr handler (``propagate=False``: no duplicate line).
    """
    from exorad.log import logger as exorad_logger

    try:
        exorad_logger.ch.setStream(sys.stderr)
    except ValueError:  # the previous stream was already closed (flush failed)
        exorad_logger.ch.stream = sys.stderr

    name = os.environ.get(ENV_LOG_LEVEL, "INFO").strip().upper() or "INFO"
    level = logging.getLevelName(name)
    if not isinstance(level, int):
        level = logging.INFO
    for handler in list(_LOGGER.handlers):
        if getattr(handler, _HANDLER_TAG, False):
            _LOGGER.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(name)s - %(levelname)s - %(message)s"))
    setattr(handler, _HANDLER_TAG, True)
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(level)
    _LOGGER.propagate = False


def _set_child_environment() -> None:
    """Put the job-child environment into the SERVER's ``os.environ``.

    A spawned child imports numpy/matplotlib/exorad before any of its own code
    runs, so these variables must already be in the environment it inherits
    (``MPLBACKEND=Agg``, ``EXORAD_NO_VERSION_CHECK=1``, BLAS/OpenMP threads = 1).
    """
    jobs.apply_child_env()


def build_server(
    *,
    allow_exec: bool | None = None,
    host: str | None = None,
    port: int | None = None,
    name: str = "exorad",
    registry: Sequence[tools.ToolEntry] | None = None,
    hide: Iterable[str] = (),
    prompts: Iterable[Callable[..., Any]] = (),
    resources: Iterable[tuple[str, Callable[..., Any]]] = (),
):
    """Build the ExoRad MCP server.

    Tools come from the registry in :mod:`exorad.mcp.tools`; a tool group that is
    not available is skipped, logged, and reported by ``capabilities``.

    Parameters
    ----------
    allow_exec : bool, optional
        Whether to register the execution tools. Defaults to the value derived
        from the environment (``EXORAD_MCP_NO_EXEC``).
    host, port : optional
        Bind address for the network transports (``sse`` / ``http``).
    name : str, optional
        Server name the client sees (default ``"exorad"``).
    registry : sequence of ToolEntry, optional
        Tool table to serve instead of :data:`exorad.mcp.tools.REGISTRY`; an
        extension passes ExoRad's entries plus its own. Nothing global changes.
    hide : iterable of str, optional
        Names of tools of ``registry`` that are not registered at all.
    prompts : iterable of callables, optional
        Extra prompt functions, registered after ExoRad's.
    resources : iterable of ``(uri_or_template, function)``, optional
        Extra resources, registered after ExoRad's.

    Returns
    -------
    MCPServer
        Configured MCP server instance. ``server._exorad_bind`` carries the
        ``(host, port)`` for the network transports, which ``main`` passes as
        ``run()`` keywords; ``server._exorad_unavailable`` lists the skipped tools.

    Raises
    ------
    ImportError
        If the optional MCP dependency (``mcp>=2,<3``) is not installed.
    """
    server_class = _load_server_class()
    hide, prompts, resources = tuple(hide), tuple(prompts), tuple(resources)

    sandbox = Sandbox.from_env(allow_exec=allow_exec)

    server = server_class(name)
    server._exorad_bind = (host, port)

    custom = registry is not None or bool(hide)
    loaded = tools.load_tools(
        allow_exec=sandbox.allow_exec, registry=registry, hide=hide
    )
    for tool_name, func in loaded.registered:
        if custom and func is tools.capabilities:
            # report the tools of the registry that is actually served
            func = tools.capabilities_for(registry, hide)
        server.tool(name=tool_name)(_expose_errors(func))
    server._exorad_unavailable = loaded.unavailable
    if loaded.unavailable:
        _LOGGER.warning(
            "tools not available in this build: %s",
            ", ".join(f"{u['tool']} ({u['reason']})" for u in loaded.unavailable),
        )

    # Resources: the knowledge-base files, browsable by URI. The template needs
    # the RFC 6570 "+" so that nested paths (docs/source/user/inputs.rst) match.
    server.resource(_EXORAD_RESOURCES.KB_INDEX_URI)(
        _EXORAD_RESOURCES.knowledge_base_index
    )
    server.resource(_EXORAD_RESOURCES.KB_URI_TEMPLATE)(
        _EXORAD_RESOURCES.read_knowledge_file
    )
    for uri, resource in resources:
        server.resource(uri)(resource)

    # Prompts: ready-made workflows
    for prompt in (*_EXORAD_PROMPTS.ALL_PROMPTS, *prompts):
        server.prompt()(prompt)

    return server


def _parse_args(
    argv: list[str] | None = None,
    *,
    prog: str = "exorad-mcp",
    description: str | None = None,
    epilog: str | None = None,
    help_overrides: Mapping[str, str] | None = None,
    version_text: str | None = None,
) -> argparse.Namespace:
    """Parse the command line (the extension parameters are described at :func:`main`)."""
    overrides = help_overrides or {}
    parser = argparse.ArgumentParser(
        prog=prog,
        description=description or "Run the ExoRad Model Context Protocol server.",
        epilog=epilog,
    )
    parser.add_argument(
        "--transport",
        choices=sorted(_TRANSPORTS),
        default="stdio",
        help="Transport: stdio (default, one local client), sse or http "
        "(networked). sse and http have NO authentication: they bind to "
        "127.0.0.1 unless --host says otherwise, so do not expose them.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address for sse / http (default: 127.0.0.1, loopback only).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for sse / http (default: 8000).",
    )
    parser.add_argument(
        "--repo-root",
        metavar="PATH",
        help=overrides.get(
            "repo_root",
            "Content root to serve (knowledge base, examples). Precedence: this "
            f"option or {ENV_REPO_ROOT}, then the current directory if it is an "
            "ExoRad checkout, then the checkout the installed package lives in, "
            "then the content packaged in the wheel.",
        ),
    )
    parser.add_argument(
        "--work-dir",
        metavar="PATH",
        help=overrides.get(
            "work_dir",
            "Writable directory for drafts, runs, logs and plots (default: "
            f"{ENV_WORK_DIR}, else <content root>/mcp-runs for a checkout or "
            "./mcp-runs for packaged content).",
        ),
    )
    parser.add_argument(
        "--allow-dir",
        metavar="PATH",
        action="append",
        default=[],
        help=overrides.get(
            "allow_dir",
            "Extra directory the server may read AND write (repeatable; "
            f"appended to {ENV_ALLOW_DIRS}). Payloads can read any file in the "
            "allowed roots, so add only directories you trust.",
        ),
    )
    parser.add_argument(
        "--no-exec",
        action="store_true",
        help=overrides.get(
            "no_exec",
            "Disable the execution tools (run_pipeline, get_job_status, "
            "cancel_job, list_jobs, plot_output, validate_config deep=True); serve "
            "read-only Q&A, drafting and validation only.",
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=version_text or f"exorad-mcp (exorad {_exorad_version()})",
    )
    return parser.parse_args(argv)


def _exorad_version() -> str:
    try:
        return _pkg_version("exorad")
    except PackageNotFoundError:
        return "unknown"


def _prepare_work_dir(sandbox: Sandbox, *, explicit: bool, prog: str) -> None:
    """Create the work directory at start-up, or exit with one clear line.

    Without execution nothing needs the directory until a tool writes (a draft),
    so it is created lazily and only a path that exists and is not a directory is
    reported. A default directory that cannot be created was already replaced by
    the per-user fallback (``Sandbox.from_env``); an explicit one is never
    replaced: ``--work-dir`` / ``EXORAD_MCP_WORK_DIR`` that cannot be used is an error.
    """
    where = "--work-dir / EXORAD_MCP_WORK_DIR" if explicit else "the work directory"
    try:
        if sandbox.allow_exec:
            sandbox.ensure_work_dir()
        elif sandbox.work_dir.exists() and not sandbox.work_dir.is_dir():
            raise NotADirectoryError("not a directory")
    except OSError as exc:
        reason = exc.strerror or str(exc)
        sys.stderr.write(
            f"{prog}: error: cannot use {where} '{sandbox.work_dir}': {reason}\n"
        )
        raise SystemExit(2) from None


def main(
    argv: list[str] | None = None,
    *,
    name: str = "exorad",
    prog: str = "exorad-mcp",
    title: str = "ExoRad",
    description: str | None = None,
    epilog: str | None = None,
    help_overrides: Mapping[str, str] | None = None,
    version_text: str | None = None,
    registry: Sequence[tools.ToolEntry] | None = None,
    hide: Iterable[str] = (),
    prompts: Iterable[Callable[..., Any]] = (),
    resources: Iterable[tuple[str, Callable[..., Any]]] = (),
    setup: Callable[[argparse.Namespace], None] | None = None,
) -> None:
    """Run the MCP server (ExoRad's by default; other packages can reuse it).

    Parameters
    ----------
    argv : list of str, optional
        Command line (default ``sys.argv[1:]``).
    name : str
        Server name the client sees (default ``"exorad"``).
    prog : str
        Program name shown by ``--help`` and the usage line (default
        ``"exorad-mcp"``).
    title : str
        Product name in the start-up banner (default ``"ExoRad"``).
    description, epilog : str, optional
        Text of ``--help`` (default: ExoRad's description, no epilog). Write
        ``%%`` for a literal percent sign (argparse formatting).
    help_overrides : mapping, optional
        Replacement ``--help`` text per option: keys ``repo_root``, ``work_dir``,
        ``allow_dir``, ``no_exec`` (the defaults name ``EXORAD_MCP_*``).
    version_text : str, optional
        Text printed by ``--version`` (default names ``exorad``).
    registry, hide, prompts, resources
        Passed to :func:`build_server`.
    setup : callable, optional
        Called with the parsed namespace after the command-line flags were
        applied to ``os.environ`` and BEFORE logging is routed, the sandbox is
        built and the server is created. It may adjust ``os.environ`` (an
        extension maps its own variable prefix and defaults there and resolves
        its content root once ``--repo-root`` is known).
    """
    hide, prompts, resources = tuple(hide), tuple(prompts), tuple(resources)
    args = _parse_args(
        argv,
        prog=prog,
        description=description,
        epilog=epilog,
        help_overrides=help_overrides,
        version_text=version_text,
    )
    _set_child_environment()
    if args.repo_root:
        os.environ[ENV_REPO_ROOT] = args.repo_root
    if args.work_dir:
        os.environ[ENV_WORK_DIR] = args.work_dir
    if args.allow_dir:
        existing = [
            d for d in os.environ.get(ENV_ALLOW_DIRS, "").split(os.pathsep) if d
        ]
        os.environ[ENV_ALLOW_DIRS] = os.pathsep.join([*existing, *args.allow_dir])
    if args.no_exec:
        os.environ[ENV_NO_EXEC] = "1"
    if setup is not None:
        setup(args)

    try:
        _load_server_class()  # fail early, with one clean line
    except ImportError as exc:
        sys.stderr.write(f"{prog}: error: {exc}\n")
        raise SystemExit(1) from None

    _route_logging_to_stderr()
    sandbox = Sandbox.from_env()
    _prepare_work_dir(
        sandbox,
        explicit=bool(os.environ.get(ENV_WORK_DIR)),
        prog=prog,
    )
    where = (
        "stdio"
        if args.transport == "stdio"
        else f"{args.transport} on {args.host}:{args.port}"
    )
    # stdout is the JSON-RPC channel for the stdio transport: log to stderr.
    _LOGGER.info(
        "%s MCP server\n"
        "  transport:  %s\n"
        "  content:    %s (%s)\n"
        "  work dir:   %s\n"
        "  execution:  %s",
        title,
        where,
        sandbox.repo_root,
        sandbox.content_source,
        sandbox.work_dir,
        "enabled" if sandbox.allow_exec else "disabled (--no-exec)",
    )
    if args.transport != "stdio":
        _LOGGER.warning(
            "the %s transport has NO authentication; anyone who can reach %s:%s "
            "can use this server%s",
            args.transport,
            args.host,
            args.port,
            " (with execution enabled, that includes running pipelines)"
            if sandbox.allow_exec
            else "",
        )
    server = build_server(
        host=args.host,
        port=args.port,
        name=name,
        registry=registry,
        hide=hide,
        prompts=prompts,
        resources=resources,
    )
    transport = _TRANSPORTS[args.transport]
    run_kwargs: dict[str, object] = {}
    if transport != "stdio":
        # The bind address is a run() keyword, not a constructor argument.
        run_kwargs = {"host": args.host, "port": args.port}
    else:
        # The stdio server never needs the network. (Not for sse/http: binding
        # resolves 127.0.0.1 through getaddrinfo, which the guard refuses.)
        from exorad.mcp import netguard

        netguard.block_network()
    # Signal handlers can only be installed from the main thread; tools run in
    # worker threads, so register them here, before serving.
    jobs.JOBS.install_hooks()
    server.run(transport=transport, **run_kwargs)


if __name__ == "__main__":
    main()
