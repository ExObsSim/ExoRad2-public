import importlib.metadata as metadata
import os.path
from datetime import date

# load package info
__pkg_name__ = metadata.metadata("exorad")["Name"]
__url__ = metadata.metadata("exorad")["Project-URL"]
__author__ = metadata.metadata("exorad")["Author"]
__email__ = metadata.metadata("exorad")["Author_email"]
__license__ = metadata.metadata("exorad")["license"]
__summary__ = metadata.metadata("exorad")["Summary"]

# load package commit number
try:
    __base_dir__ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    __base_dir__ = None

__commit__ = None
__branch__ = None
if __base_dir__ is not None and os.path.exists(
    os.path.join(__base_dir__, ".git")
):
    git_folder = os.path.join(__base_dir__, ".git")
    with open(os.path.join(git_folder, "HEAD")) as fp:
        ref = fp.read().strip()
    ref_dir = ref[5:]
    __branch__ = ref[16:]
    try:
        with open(os.path.join(git_folder, ref_dir)) as fp:
            __commit__ = fp.read().strip()
    except FileNotFoundError:
        __commit__ = None

__title__ = "ExoRad2"

__copyright__ = "2020-{:d}, {}".format(date.today().year, __author__)
__citation__ = "Mugnai et al., 2020, 'ArielRad: the ARIEL radiometric model', Exp. Astron, 50, 303-328"

from .exorad import standard_pipeline


from exorad.utils.version_control import VersionControl

VersionControl()
