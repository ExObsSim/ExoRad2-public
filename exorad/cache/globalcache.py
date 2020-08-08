from .singleton import Singleton
from exorad.log import Logger


class GlobalCache(Singleton, Logger):
    """

    Allows for the storage of global variables

    """

    def init(self):
        super().__init__()
        self.variable_dict = {}

    def __getitem__(self, key):
        try:
            return self.variable_dict[key]
        except KeyError:
            return None

    def __setitem__(self, key, value):
        self.variable_dict[key] = value