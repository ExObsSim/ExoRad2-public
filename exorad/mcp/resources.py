"""MCP resources: the curated knowledge-base files, browsable by URI.

Tools *do* things; resources are content a client can list and read. The MCP
server exposes every file in the knowledge-base manifest under
``exorad://kb/<content-relative-path>`` so a client can pull a whole page rather
than only the passages a search returned.
"""

from __future__ import annotations

from typing import Any

from exorad.mcp.retrieval import knowledge_base_manifest
from exorad.mcp.schemas import resolve_repo_path

KB_URI_PREFIX = "exorad://kb/"
KB_INDEX_URI = "exorad://kb"
# RFC 6570 reserved expansion (``+``): a plain ``{path}`` matches ONE path segment
# only, so ``docs/source/user/inputs.rst`` would be unreachable (verified with
# mcp 2.x); ``{+path}`` also matches the ``/`` in nested paths. The SDK rejects
# ``..`` and absolute values before the function is called.
KB_URI_TEMPLATE = "exorad://kb/{+path}"
_MAX_RESOURCE_BYTES = 200_000


def knowledge_base_index() -> dict[str, Any]:
    """List the readable knowledge-base resources."""
    manifest = knowledge_base_manifest()
    return {
        "resources": [
            {"uri": f"{KB_URI_PREFIX}{path}", "path": path}
            for path in manifest["matched_files"]
        ],
        "count": manifest["matched_file_count"],
    }


def read_knowledge_file(path: str) -> str:
    """Return the text of one knowledge-base file.

    Only files listed by :func:`knowledge_base_index` can be read: the path is
    compared with the manifest as a plain string, so ``..`` segments, absolute
    paths and files outside the approved patterns (``pyproject.toml``, the
    internal planning notes) are all refused before the filesystem is touched.

    Parameters
    ----------
    path : str
        Content-relative path, as listed by :func:`knowledge_base_index`.

    Raises
    ------
    FileNotFoundError
        If the path is not part of the approved knowledge base.
    """
    allowed = set(knowledge_base_manifest()["matched_files"])
    if path not in allowed:
        raise FileNotFoundError(
            f"{path} is not part of the ExoRad knowledge base; "
            "see knowledge_base_manifest for the approved files"
        )
    resolved = resolve_repo_path(path)
    text = resolved.read_text(encoding="utf-8", errors="replace")
    raw = text.encode("utf-8")
    if len(raw) > _MAX_RESOURCE_BYTES:
        text = raw[:_MAX_RESOURCE_BYTES].decode("utf-8", errors="ignore")
        text += "\n\n... [truncated]\n"
    return text
