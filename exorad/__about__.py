import os.path

__all__ = [
    "__title__",
    "__summary__",
    "__url__",
    "__commit__",
    "__author__",
    "__email__",
    "__license__",
    "__copyright__",
]

try:
    base_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    base_dir = None

__title__ = "ExoRad2"
__summary__ = "The exoplanet observation simulator"
__url__ = "https://github.com/ExoRad/ExoRad2"

if base_dir is not None and os.path.exists(os.path.join(base_dir, ".commit")):
    with open(os.path.join(base_dir, ".commit")) as fp:
        __commit__ = fp.read().strip()
else:
    __commit__ = None

__author__ = "Lorenzo V. Mugnai"
__email__ = "lorenzo.mugnai@uniroma1.it"

__license__ = "BSD-2-Claus"
__copyright__ = "2020 %s" % __author__
