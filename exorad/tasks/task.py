from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import Any

from exorad.log.logger import Logger


class Task(Logger):
    """
    Base class for tasks.
    """

    __metaclass__ = ABCMeta

    _output: Any = None
    _task_input: dict[str, Any]
    _task_params: dict[str, dict[str, Any]] | None = None

    @abstractmethod
    def __init__(self) -> None:
        """
        Class initialisation, needed to prepare the task inputs reader
        """

    @abstractmethod
    def execute(self) -> None:
        """
        Class execution. It runs on call and executes all the task actions returning the outputs.
        It requires the input with correct keywords
        """

    def __call__(self, **kwargs: Any) -> Any:
        self.set_log_name()
        self._task_input = kwargs
        self._validate_input_params()
        self._populate_empty_param()
        self.execute()
        return self.get_output()

    def _validate_input_params(self) -> None:
        assert self._task_params is not None
        for key in self._task_input.keys():
            if key not in self._task_params.keys():
                self.error(f"Unexpected Task input parameter: {key}")
                raise ValueError

    def _populate_empty_param(self) -> None:
        assert self._task_params is not None
        for key in self._task_params.keys():
            if key not in self._task_input.keys():
                self._task_input[key] = self._task_params[key]["default"]

    def get_output(self) -> Any:
        return self._output

    def set_output(self, product: Any) -> None:
        self._output = product

    def get_task_param(self, paramName: str) -> Any:
        return self._task_input[paramName]

    def addTaskParam(
        self, param_name: str, param_description: str, default: Any = None
    ) -> None:
        if self._task_params is None:
            self._task_params = {}
        self._task_params[param_name] = {
            "description": param_description,
            "default": default,
        }
