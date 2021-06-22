from abc import ABCMeta, abstractmethod

from exorad.log.logger import Logger


class Task(Logger):
    """
    Base class for tasks.
    """

    __metaclass__ = ABCMeta

    _output = None
    _task_input = None
    _task_params = None

    @abstractmethod
    def __init__(self):
        '''
        Class initialisation, needed to prepare the task inputs reader
        '''
        pass

    @abstractmethod
    def execute(self):
        '''
        Class execution. It runs on call and executes all the task actions returning the outputs.
        It requires the input with correct keywords
        '''
        pass

    def __call__(self, **kwargs):
        self.set_log_name()
        self._task_input = kwargs
        self._validate_input_params()
        self._populate_empty_param()
        self.execute()
        return self.get_output()

    def _validate_input_params(self):
        for key in self._task_input.keys():
            if key not in self._task_params.keys():
                self.error("Unexpected Task input parameter: {}".format(key))
                raise ValueError

    def _populate_empty_param(self):
        for key in self._task_params.keys():
            if key not in self._task_input.keys():
                self._task_input[key] = self._task_params[key]['default']

    def get_output(self):
        return self._output

    def set_output(self, product):
        self._output = product

    def get_task_param(self, paramName):
        return self._task_input[paramName]

    def addTaskParam(self, param_name, param_description, default=None):
        if self._task_params is None:
            self._task_params = {}
        self._task_params[param_name] = {"description": param_description,
                                         "default": default}
