"""meat_python_plus — abridge a unified diff into a reading diff."""

from meat_python_plus.abridge import Result, abridge
from meat_python_plus.model import Block, Message, Model, Response, Role, Tool

__all__ = [
    "Block",
    "Message",
    "Model",
    "Response",
    "Result",
    "Role",
    "Tool",
    "abridge",
]

__version__ = "0.1.0"
