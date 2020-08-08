import logging
import unittest

from exorad.log import setLogLevel
from exorad.tasks.task import Task

setLogLevel(logging.DEBUG)


class TaskTestTask1(Task):
    class_name = 'testTask'

    def __init__(self):
        self.addTaskParam('input1', 'test input first parameter')
        self.addTaskParam('input2', 'test input second parameter')

    def execute(self):
        self.set_output(None)
        self.info('started')


class TaskTestTask2(Task):

    def __init__(self):
        pass

    def execute(self):
        pass


class TaskTest(unittest.TestCase):
    task1 = TaskTestTask1()
    task2 = TaskTestTask2()

    def test_input(self):
        with self.assertRaises(ValueError):
            self.task1(input1=1, input3=3)
        with self.assertRaises(TypeError):
            self.task1(1, 2)
        with self.assertRaises(ValueError):
            self.task1(input1=1, input2=2, input3=3)

        try:
            self.task1(input1=1, input2=2)
        except ValueError:
            self.fail("TaskTest() raised ValueErros unexpectedly!")
