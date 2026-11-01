"""strnum: integers that are strings.

    >>> from strnum import S
    >>> S(5) + 3
    '8'
    >>> type(S(5) + 3).__mro__[1]
    <class 'str'>

Run a whole script with every int literal turned into a StrInt:

    python -m strnum script.py
"""

from .core import S, StrInt
from .transform import compile_strnum, exec_strnum, install, transform, uninstall

__all__ = ["S", "StrInt", "transform", "compile_strnum", "exec_strnum", "install", "uninstall"]
__version__ = "0.1.0"
