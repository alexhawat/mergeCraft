import numpy as np
from os.path import join as path_join


def build(path: str) -> object:
    return np.array([path_join(path, "file")])
