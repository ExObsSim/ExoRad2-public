import importlib.metadata as metadata
import os.path
from datetime import date

# load package info
__pkg_name__ = metadata.metadata("exorad")["Name"]
__url__ = metadata.metadata("exorad")["Project-URL"]
__author__ = metadata.metadata("exorad")["Author"]
__license__ = metadata.metadata("exorad")["license"]
__summary__ = metadata.metadata("exorad")["Summary"]

# load package commit number


def _git_info():
    """Return ``(branch, commit)`` for the source checkout, or ``(None, None)``.

    Only a plain ``.git`` directory is inspected (no subprocess); worktrees,
    packed refs and detached HEAD degrade gracefully to ``None``.
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        return None, None

    git_folder = os.path.join(base_dir, ".git")
    if not os.path.isdir(git_folder):
        return None, None

    try:
        with open(os.path.join(git_folder, "HEAD")) as fp:
            ref = fp.read().strip()
    except OSError:
        return None, None

    if ref.startswith("ref: "):
        ref_path = ref[5:]
        branch = ref_path.split("/")[-1]
        try:
            with open(os.path.join(git_folder, ref_path)) as fp:
                return branch, fp.read().strip()
        except OSError:
            return branch, None
    # detached HEAD: ref is the commit hash itself
    return "HEAD", ref


__branch__, __commit__ = _git_info()

__title__ = "ExoRad2"

__copyright__ = f"2020-{date.today().year:d}, {__author__}"
__citation__ = "Mugnai et al., 2023, 'ExoRad 2.0: The generic point source radiometric model'. Journal of Open Source Software, 8(89), 5348,"

from .exorad import standard_pipeline

# The online version check (network access) is NOT run at import time: it is
# run by the ``exorad`` command-line entry point only, see
# ``exorad.exorad.check_version``.
