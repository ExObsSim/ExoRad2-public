import os
import pathlib

# Automatic relative directories and files
path = pathlib.Path(__file__).parent.absolute()
main_path = os.path.join(path.parent, 'exorad')
example_dir = os.path.join(path.parent.absolute(), 'examples')
test_dir = os.path.join(path, 'test_data')
regression_dir = os.path.join(path, 'regression_data')
