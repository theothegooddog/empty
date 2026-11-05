"""One sample program per technique.

Each sample must (a) trigger its technique and (b) print the same output
optimized and unoptimized. ``test_every_technique_has_a_sample`` makes sure
nothing in the registry is left untested.
"""

STR_METHODS = {
    "capitalize": ("hello", ()), "casefold": ("HeLLo", ()), "center": ("ab", (6, "*")),
    "count": ("banana", ("a",)), "encode": ("héllo", ()), "endswith": ("file.py", (".py",)),
    "expandtabs": ("a\tb", (4,)), "find": ("hello", ("l",)), "format": ("{}-{}", (1, 2)),
    "index": ("hello", ("e",)), "isalnum": ("abc1", ()), "isalpha": ("abc", ()),
    "isascii": ("abc", ()), "isdecimal": ("123", ()), "isdigit": ("123", ()),
    "isidentifier": ("x_1", ()), "islower": ("abc", ()), "isnumeric": ("12", ()),
    "isprintable": ("ab", ()), "isspace": ("  ", ()), "istitle": ("Ab Cd", ()),
    "isupper": ("AB", ()), "join": (",", (("a", "b", "c"),)), "ljust": ("ab", (5, ".")),
    "lower": ("ABC", ()), "lstrip": ("  ab", ()), "partition": ("a=b", ("=",)),
    "removeprefix": ("prefix_x", ("prefix_",)), "removesuffix": ("x.txt", (".txt",)),
    "replace": ("a-b-c", ("-", "+")), "rfind": ("hello", ("l",)), "rindex": ("hello", ("l",)),
    "rjust": ("ab", (5,)), "rpartition": ("a.b.c", (".",)), "rsplit": ("a b c", (None, 1)),
    "rstrip": ("ab  ", ()), "split": ("a,b,c", (",",)), "splitlines": ("a\nb", ()),
    "startswith": ("hello", ("he",)), "strip": ("  ab  ", ()), "swapcase": ("aBc", ()),
    "title": ("hello world", ()), "upper": ("abc", ()), "zfill": ("42", (5,)),
}
BYTES_METHODS = {
    "decode": (b"abc", ()), "hex": (b"\x01\xff", ()), "upper": (b"abc", ()),
    "lower": (b"ABC", ()), "strip": (b"  ab ", ()), "split": (b"a b", ()),
    "startswith": (b"abc", (b"a",)), "endswith": (b"abc", (b"c",)), "count": (b"aab", (b"a",)),
    "find": (b"abc", (b"c",)), "replace": (b"abc", (b"b", b"x")), "join": (b"-", ((b"a", b"b"),)),
    "isdigit": (b"12", ()), "isalpha": (b"ab", ()),
}
NUM_METHODS = {"int.bit_length": "(255).bit_length()", "int.bit_count": "(255).bit_count()",
               "float.is_integer": "(2.0).is_integer()", "float.hex": "(1.5).hex()"}
MATH_CALLS = {
    "acos": "0.5", "acosh": "2.0", "asin": "0.5", "asinh": "1.0", "atan": "1.0",
    "atan2": "1.0, 2.0", "atanh": "0.5", "cbrt": "27.0", "ceil": "2.3", "comb": "10, 3",
    "copysign": "1.0, -2.0", "cos": "1.0", "cosh": "1.0", "degrees": "1.0",
    "dist": "(0, 0), (3, 4)", "erf": "0.5", "erfc": "0.5", "exp": "1.0", "exp2": "3.0",
    "expm1": "0.001", "fabs": "-2.0", "factorial": "10", "floor": "2.7", "fmod": "7.0, 3.0",
    "frexp": "8.0", "fsum": "(0.1, 0.2, 0.3)", "gamma": "5.0", "gcd": "12, 18",
    "hypot": "3.0, 4.0", "isclose": "1.0, 1.0", "isfinite": "1.0", "isinf": "1.0",
    "isnan": "1.0", "isqrt": "17", "lcm": "4, 6", "ldexp": "1.5, 3", "lgamma": "5.0",
    "log": "8.0, 2", "log10": "1000.0", "log1p": "0.5", "log2": "8.0", "modf": "2.5",
    "nextafter": "1.0, 2.0", "perm": "5, 2", "pow": "2.0, 3.0", "prod": "(1, 2, 3, 4)",
    "radians": "180.0", "remainder": "10.0, 3.0", "sin": "1.0", "sinh": "1.0", "sqrt": "2.0",
    "tan": "1.0", "tanh": "1.0", "trunc": "2.7", "ulp": "1.0",
}
BUILTIN_CALLS = {
    "abs": "-3", "all": "(1, 2)", "any": "(0, 1)", "ascii": "'é'", "bin": "10", "bool": "0",
    "bytes": "3", "callable": "1", "chr": "65", "complex": "1, 2", "divmod": "7, 2",
    "float": "'1.5'", "hex": "255", "int": "'42'", "isinstance": "3, int", "len": "'abc'",
    "list": "'ab'", "max": "1, 5, 3", "min": "4, 2", "oct": "8", "ord": "'a'", "pow": "2, 10",
    "repr": "'x'", "round": "2.567, 2", "set": "(1, 2)", "sorted": "(3, 1, 2)", "str": "42",
    "sum": "(1, 2, 3)", "tuple": "'ab'", "format": "3.14159, '.2f'",
}
OPERATORS = {
    "fold.add": "1 + 2", "fold.sub": "5 - 3", "fold.mul": "4 * 3", "fold.truediv": "7 / 2",
    "fold.floordiv": "7 // 2", "fold.mod": "7 % 3", "fold.pow": "2 ** 10",
    "fold.lshift": "1 << 4", "fold.rshift": "16 >> 2", "fold.bitor": "5 | 2",
    "fold.bitxor": "5 ^ 1", "fold.bitand": "6 & 3", "fold.pos": "+3", "fold.neg": "-3",
    "fold.not": "not 0", "fold.invert": "~5", "fold.cmp-eq": "1 == 1", "fold.cmp-ne": "1 != 2",
    "fold.cmp-lt": "1 < 2", "fold.cmp-le": "2 <= 2", "fold.cmp-gt": "3 > 2",
    "fold.cmp-ge": "3 >= 4", "fold.cmp-in": "1 in (1, 2)", "fold.cmp-not-in": "3 not in (1, 2)",
    "fold.cmp-is": "None is None", "fold.cmp-is-not": "None is not True",
    "fold.and": "1 and 2", "fold.or": "0 or 3", "fold.ifexp": "1 if True else 2",
    "fold.index": "'abc'[1]", "fold.slice": "'abcdef'[1:4]", "fold.fstring": "f'{1}-{2.5:.1f}'",
}

INT_RULES = {  # inside: for n in range(5)
    "add-zero": "n + 0", "sub-zero": "n - 0", "zero-sub": "0 - n", "mul-one": "n * 1",
    "floordiv-one": "n // 1", "pow-one": "n ** 1", "pow-two": "n ** 2", "pow-three": "n ** 3",
    "or-zero": "n | 0", "xor-zero": "n ^ 0", "and-minus-one": "n & -1",
    "lshift-zero": "n << 0", "rshift-zero": "n >> 0", "double-negation": "-(-n)",
    "double-invert": "~~n", "unary-plus": "+n", "int-call-identity": "int(n)",
    "abs-abs": "abs(abs(n - 2))", "zero-test": "n == 0", "nonzero-test": "1 if n != 0 else 0",
    "membership-set": "n in (1, 3, 4)",
}
FLOAT_RULES = {  # x = n / 2
    "mul-one": "x * 1.0", "div-one": "x / 1", "sub-zero": "x - 0.0", "pow-one": "x ** 1",
    "float-call-identity": "float(x)", "unary-plus": "+x",
}
STR_RULES = {  # s = 'ab' * n
    "add-empty": "s + ''", "mul-one": "s * 1", "fstring-identity": "f'{s}'",
    "str-call-identity": "str(s)", "membership-set": "s in ('a', 'ab', 'abab')",
}
BOOL_RULES = {  # b = n > 1
    "eq-true": "b == True", "eq-false": "b == False", "ne-true": "b != True",
    "ne-false": "b != False", "is-true": "b is True", "is-false": "b is False",
    "bool-call-identity": "bool(b)", "not-not": "not not b",
}
CONTAINER_RULES = {  # c = [0] * n ; t = (n,)
    "len-test": "1 if len(c) else 0", "len-eq-zero": "len(c) == 0",
    "len-nonzero-test": "1 if len(c) > 0 else 0", "empty-eq": "c == []",
    "empty-ne-test": "1 if c != [] else 0", "tuple-call-identity": "tuple(t)",
}

LOOP_TEMPLATE = """
def f():
    out = []
    for n in range(5):
        x = n / 2
        s = 'ab' * n
        b = n > 1
        c = [0] * n
        t = (n,)
        out.append({expr})
    return out
print(f())
"""

EXPLICIT = {
    # dead code
    "dce.if-constant": "if False:\n    print(1)\nelse:\n    print(2)",
    "dce.while-false": "while 0:\n    print(1)\nelse:\n    print(2)",
    "dce.after-return": "def f():\n    return 1\n    print('no')\nprint(f())",
    "dce.after-raise": "def f():\n    raise ValueError('v')\n    print('no')\ntry:\n    f()\nexcept ValueError as e:\n    print('caught', e)",
    "dce.after-break": "for i in range(3):\n    print(i)\n    break\n    print('no')",
    "dce.after-continue": "for i in range(3):\n    print(i)\n    continue\n    print('no')",
    "dce.after-infinite-loop": "def f():\n    while True:\n        return 7\n    print('no')\nprint(f())",
    "dce.for-empty": "for x in ():\n    print(x)\nelse:\n    print('empty')",
    "dce.assert-true": "assert True\nprint('ok')",
    "dce.try-pass": "try:\n    pass\nexcept ValueError:\n    print('x')\nelse:\n    print('ok')",
    "dce.redundant-pass": "def f():\n    pass\n    return 1\nprint(f())",
    "dce.empty-else": "for i in range(2):\n    print(i)\nelse:\n    pass",
    "dce.constant-expression": "def f():\n    'doc'\n    42\n    return 1\nprint(f(), f.__doc__)",
    "prop.module-constant": "LIMIT = 3\nprint(LIMIT * 2)",
    "prop.local-constant": "def f():\n    k = 4\n    return k + 1\nprint(f())",
    # module constants
    "inline.sys.version_info": "import sys\nprint(sys.version_info >= (3, 8), sys.version_info[0], sys.version_info[:2])",
    # idioms
    "idiom.not-is": "x = None\nprint(not (x is None))",
    "idiom.not-is-not": "x = None\nprint(not (x is not None))",
    "idiom.not-in": "x = 1\nprint(not (x in [1, 2]))",
    "idiom.not-not-in": "x = 1\nprint(not (x not in [1, 2]))",
    "idiom.not-not-test": "x = 3\nif not not x:\n    print('t')",
    "idiom.bool-call-test": "x = 3\nif bool(x):\n    print('t')",
    "idiom.isinstance-single-tuple": "x = 3\nprint(isinstance(x, (int,)))",
    "idiom.isinstance-merge": "x = 's'\nprint(isinstance(x, int) or isinstance(x, str))",
    "idiom.compare-chain": "a, b, c = 1, 2, 3\nprint(a < b and b < c, c < b and b < a)",
    "idiom.if-return-bool": "def f(x):\n    if x > 2:\n        return True\n    return False\nprint(f(3), f(1))",
    "idiom.if-return-not": "def f(x):\n    if x > 2:\n        return False\n    else:\n        return True\nprint(f(3), f(1))",
    "idiom.dict-kwargs-literal": "x = 2\nprint(dict(a=1, b=x))",
    "idiom.list-literal-call": "x = 1\nprint(list((x, 2)), list([y for y in 'ab']))",
    "idiom.tuple-literal-call": "x = 1\nprint(tuple([x, 2]))",
    "idiom.set-literal-call": "x = 1\nprint(sorted(set([x, 2])))",
    "idiom.dict-literal-call": "x = 1\nprint(dict({'a': x}))",
    "idiom.list-genexpr": "xs = [1, 2]\nprint(list(x * 2 for x in xs))",
    "idiom.set-genexpr": "xs = [1, 2]\nprint(sorted(set(x * 2 for x in xs)))",
    "idiom.dict-genexpr": "xs = [1, 2]\nprint(dict((x, x * 2) for x in xs))",
    "idiom.list-identity-comprehension": "xs = (1, 2)\nprint([x for x in xs])",
    "idiom.set-identity-comprehension": "xs = (1, 2)\nprint(sorted({x for x in xs}))",
    "idiom.range-zero-start": "n = 3\nprint(list(range(0, n)))",
    "idiom.range-unit-step": "n = 3\nprint(list(range(1, n, 1)))",
    "idiom.enumerate-zero-start": "w = 'ab'\nprint(list(enumerate(w, 0)), list(enumerate(w, start=0)))",
    "idiom.sorted-reverse-false": "xs = [2, 1]\nprint(sorted(xs, reverse=False))",
    "idiom.getattr-constant": "x = 3\nprint(getattr(x, 'real'))",
    "idiom.join-genexpr": "xs = [1, 2]\nprint(','.join(str(x) for x in xs))",
    "idiom.tuple-genexpr": "xs = [1, 2]\nprint(tuple(x + 1 for x in xs))",
    "idiom.sorted-genexpr": "xs = [2, 1]\nprint(sorted(x + 1 for x in xs))",
    "idiom.format-to-fstring": "a, b = 1, 'x'\nprint('{} and {!r} {:>4}'.format(a, b, a))",
    "idiom.fstring-str-call": "x = 5\nprint(f'{str(x)}')",
    "idiom.fstring-repr-call": "x = 'q'\nprint(f'{repr(x)}')",
    "idiom.fstring-ascii-call": "x = 'é'\nprint(f'{ascii(x)}')",
    # aggressive (level 2)
    "aggr.module-attr-hoisting": "import math\ndef f():\n    t = 0.0\n    for i in range(5):\n        t += math.sqrt(i)\n    return t\nprint(f())",
    "aggr.pow-two": "def f(x):\n    return x ** 2\nprint(f(3), f(1.5))",
    "aggr.pow-three": "def f(x):\n    return x ** 3\nprint(f(3))",
    "aggr.dict-keys-iteration": "d = {'a': 1, 'b': 2}\nfor k in d.keys():\n    print(k)\nprint([k for k in d.keys()])",
    "aggr.dict-keys-membership": "d = {'a': 1}\nprint('a' in d.keys(), 'z' not in d.keys())",
    "aggr.len-test": "def f(x):\n    return 1 if len(x) else 0\nprint(f([1]), f(''))",
    "aggr.len-eq-zero": "def f(x):\n    return len(x) == 0\nprint(f([]), f('a'))",
    "aggr.type-is": "def f(x):\n    return type(x) == int, type(x) != str\nprint(f(1), f('a'))",
    "aggr.eq-none": "def f(x):\n    return x == None\nprint(f(None), f(1))",
    "aggr.ne-none": "def f(x):\n    return x != None\nprint(f(None), f(1))",
}

_EMPTY_CALLS = ["dict"]
_REDUNDANT = {  # (outer, inner): sample input
    ("list", "list"): "xs", ("list", "tuple"): "xs", ("tuple", "list"): "xs",
    ("set", "list"): "xs", ("set", "tuple"): "xs", ("set", "set"): "xs",
    ("frozenset", "list"): "xs", ("frozenset", "tuple"): "xs", ("sorted", "list"): "xs",
    ("sorted", "tuple"): "xs", ("sorted", "sorted"): "xs", ("list", "sorted"): "xs",
    ("sum", "list"): "xs", ("sum", "tuple"): "xs", ("min", "list"): "xs", ("max", "list"): "xs",
}
_MODULE_CONSTANTS = [
    "math.pi", "math.e", "math.tau", "math.inf", "string.ascii_letters", "string.ascii_lowercase",
    "string.ascii_uppercase", "string.digits", "string.hexdigits", "string.octdigits",
    "string.punctuation", "string.whitespace", "string.printable", "sys.platform",
    "sys.maxsize", "sys.byteorder", "sys.hexversion", "sys.implementation.name",
    "sys.version_info.major", "sys.version_info.minor", "os.name", "os.sep", "os.linesep",
    "os.pathsep", "os.curdir", "os.pardir", "os.extsep", "os.altsep", "typing.TYPE_CHECKING",
]


def build():
    """-> {technique_name: (level, source)}"""
    out = {}
    for m, (recv, args) in STR_METHODS.items():
        out[f"fold.str.{m}"] = (1, f"print(repr({recv!r}.{m}({', '.join(map(repr, args))})))")
    for m, (recv, args) in BYTES_METHODS.items():
        out[f"fold.bytes.{m}"] = (1, f"print(repr({recv!r}.{m}({', '.join(map(repr, args))})))")
    for t, expr in NUM_METHODS.items():
        out[f"fold.{t}"] = (1, f"print(repr({expr}))")
    for f, args in MATH_CALLS.items():
        out[f"fold.math.{f}"] = (1, f"import math\nprint(repr(math.{f}({args})))")
    for b, args in BUILTIN_CALLS.items():
        out[f"fold.builtin.{b}"] = (1, f"print(repr({b}({args})))")
    for t, expr in OPERATORS.items():
        out[t] = (1, f"print(repr({expr}))")
    out["fold.literal-truthiness"] = (1, "if [1, 2]:\n    print('yes')\nif []:\n    print('no')")
    for q in _MODULE_CONSTANTS:
        mod = q.split(".")[0]
        out[f"inline.{q}"] = (1, f"import {mod}\nprint(repr({q}))")
    for group, rules in (("int", INT_RULES), ("float", FLOAT_RULES), ("str", STR_RULES),
                         ("bool", BOOL_RULES), ("container", CONTAINER_RULES)):
        for rule, expr in rules.items():
            out[f"typed.{group}.{rule}"] = (1, LOOP_TEMPLATE.format(expr=expr))
    for n in _EMPTY_CALLS:
        out[f"idiom.empty-{n}-call"] = (1, f"print(repr({n}()))")
    for (o, i), arg in _REDUNDANT.items():
        out[f"idiom.{o}-of-{i}"] = (1, f"xs = [3, 1, 2]\nprint(repr(sorted({o}({i}({arg}))) if '{o}' in ('set', 'frozenset') else {o}({i}({arg}))))")
    for t, src in EXPLICIT.items():
        out[t] = (2 if t.startswith("aggr.") else 1, src)
    return out
