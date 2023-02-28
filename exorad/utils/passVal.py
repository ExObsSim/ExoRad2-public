# Singleton Meta-Class method
# https://refactoring.guru/design-patterns/singleton/python/example


class SingletonMeta(type):
    """
    The Singleton class can be implemented in different ways in Python. Some
    possible methods include: base class, decorator, metaclass. We will use the
    metaclass because it is best suited for this purpose.
    """

    _instances = {}

    def __call__(cls, *args, **kwargs):
        """
        Possible changes to the value of the `__init__` argument do not affect
        the returned instance.
        """
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


class PassValInit(metaclass=SingletonMeta):
    """
    Class used to propagate values through the code.
    """

    _working_R = 6000

    @property
    def working_R(self):
        return self._working_R

    @working_R.setter
    def working_R(self, val):
        self._working_R = val


PassVal = PassValInit()
