"""StrInt: a ``str`` that does integer arithmetic.

A StrInt is a real ``str`` (``isinstance(x, str)`` is True) holding the
canonical decimal text of an integer, e.g. ``"5"``, ``"-42"``, ``"0"``.
Arithmetic is done digit by digit on that text with schoolbook
algorithms, so there is no size limit.
"""

from __future__ import annotations

import operator

__all__ = ["StrInt", "S"]

_DIGITS = "0123456789"


# --------------------------------------------------------------------------
# Magnitude helpers. Each operates on non-negative digit strings that have
# no leading zeros ("0" is the only string allowed to start with 0).
# --------------------------------------------------------------------------

def _strip(digits: str) -> str:
    return digits.lstrip("0") or "0"


def _cmp_mag(a: str, b: str) -> int:
    if len(a) != len(b):
        return -1 if len(a) < len(b) else 1
    return (a > b) - (a < b)  # same length: lexicographic == numeric


def _add_mag(a: str, b: str) -> str:
    out = []
    carry = 0
    i, j = len(a) - 1, len(b) - 1
    while i >= 0 or j >= 0 or carry:
        d = carry
        if i >= 0:
            d += _DIGITS.index(a[i])
            i -= 1
        if j >= 0:
            d += _DIGITS.index(b[j])
            j -= 1
        out.append(_DIGITS[d % 10])
        carry = d // 10
    return "".join(reversed(out))


def _sub_mag(a: str, b: str) -> str:
    """a - b, requires a >= b."""
    out = []
    borrow = 0
    i, j = len(a) - 1, len(b) - 1
    while i >= 0:
        d = _DIGITS.index(a[i]) - borrow - (_DIGITS.index(b[j]) if j >= 0 else 0)
        borrow = 1 if d < 0 else 0
        out.append(_DIGITS[d + 10 * borrow])
        i -= 1
        j -= 1
    return _strip("".join(reversed(out)))


def _mul_mag(a: str, b: str) -> str:
    if a == "0" or b == "0":
        return "0"
    acc = [0] * (len(a) + len(b))
    for i in range(len(a) - 1, -1, -1):
        da = _DIGITS.index(a[i])
        for j in range(len(b) - 1, -1, -1):
            pos = i + j + 1
            total = acc[pos] + da * _DIGITS.index(b[j])
            acc[pos] = total % 10
            acc[pos - 1] += total // 10
    return _strip("".join(_DIGITS[d] for d in acc))


def _divmod_mag(a: str, b: str) -> tuple[str, str]:
    """Long division of magnitudes: (a // b, a % b). b must not be "0"."""
    if b == "0":
        raise ZeroDivisionError("integer division or modulo by zero")
    if _cmp_mag(a, b) < 0:
        return "0", a
    quotient = []
    rem = "0"
    for ch in a:
        rem = _strip(rem + ch)
        q = 0
        while _cmp_mag(rem, b) >= 0:
            rem = _sub_mag(rem, b)
            q += 1
        quotient.append(_DIGITS[q])
    return _strip("".join(quotient)), rem


# --------------------------------------------------------------------------
# Signed helpers on (negative, magnitude) pairs.
# --------------------------------------------------------------------------

def _normalize(text: str) -> str:
    s = text.strip().replace("_", "")
    neg = False
    if s[:1] in ("+", "-"):
        neg = s[0] == "-"
        s = s[1:]
    if not s or any(c not in _DIGITS for c in s):
        raise ValueError(f"invalid literal for StrInt: {text!r}")
    s = _strip(s)
    return "-" + s if neg and s != "0" else s


def _parts(x: str) -> tuple[bool, str]:
    s = str.__str__(x)  # plain str, so the helpers never re-enter StrInt methods
    return (True, s[1:]) if s.startswith("-") else (False, s)


def _make(neg: bool, mag: str) -> "StrInt":
    return StrInt("-" + mag if neg and mag != "0" else mag)


def _add(a: str, b: str) -> "StrInt":
    an, am = _parts(a)
    bn, bm = _parts(b)
    if an == bn:
        return _make(an, _add_mag(am, bm))
    c = _cmp_mag(am, bm)
    if c == 0:
        return StrInt("0")
    if c > 0:
        return _make(an, _sub_mag(am, bm))
    return _make(bn, _sub_mag(bm, am))


def _neg(a: str) -> "StrInt":
    n, m = _parts(a)
    return _make(not n, m)


def _sub(a: str, b: str) -> "StrInt":
    return _add(a, _neg(b))


def _mul(a: str, b: str) -> "StrInt":
    an, am = _parts(a)
    bn, bm = _parts(b)
    return _make(an != bn, _mul_mag(am, bm))


def _divmod(a: str, b: str) -> tuple["StrInt", "StrInt"]:
    """Floor division and modulo with Python's sign rules."""
    an, am = _parts(a)
    bn, bm = _parts(b)
    q, r = _divmod_mag(am, bm)
    if an != bn and r != "0":
        # Round the quotient toward -infinity; remainder takes b's sign.
        q = _add_mag(q, "1")
        r = _sub_mag(bm, r)
    return _make(an != bn, q), _make(bn, r)


def _cmp(a: str, b: str) -> int:
    an, am = _parts(a)
    bn, bm = _parts(b)
    if an != bn:
        return -1 if an else 1
    c = _cmp_mag(am, bm)
    return -c if an else c


def _pow(base: "StrInt", exp: "StrInt", mod: "StrInt | None" = None) -> "StrInt":
    result = StrInt("1")
    two = StrInt("2")
    while exp != "0":
        exp, bit = _divmod(exp, two)
        if bit == "1":
            result = _mul(result, base)
            if mod is not None:
                result = _divmod(result, mod)[1]
        base = _mul(base, base)
        if mod is not None:
            base = _divmod(base, mod)[1]
    if mod is not None:
        result = _divmod(result, mod)[1]
    return result


# --------------------------------------------------------------------------
# The public type.
# --------------------------------------------------------------------------

def _coerce(value) -> "StrInt | None":
    """Turn value into a StrInt if it is an integer or integer-looking text."""
    if isinstance(value, StrInt):
        return value
    if isinstance(value, int):  # includes bool
        return StrInt(value)
    if isinstance(value, str):
        try:
            return StrInt(value)
        except ValueError:
            return None
    return None


def _binary(op, float_op):
    """Build forward and reflected dunder methods for a numeric operator."""

    def forward(self, other):
        o = _coerce(other)
        if o is not None:
            return op(self, o)
        if isinstance(other, float):
            return float_op(float(self), other)
        return NotImplemented

    def reflected(self, other):
        o = _coerce(other)
        if o is not None:
            return op(o, self)
        if isinstance(other, float):
            return float_op(other, float(self))
        return NotImplemented

    return forward, reflected


class StrInt(str):
    """An integer that is also a ``str``.

    >>> StrInt(5) + "3"
    '8'
    >>> isinstance(StrInt(5), str)
    True
    """

    __slots__ = ()

    def __new__(cls, value="0"):
        if type(value) is cls:
            return value
        if isinstance(value, int):
            text = str(int(value))
        elif isinstance(value, float):
            if not value.is_integer():
                raise ValueError(f"StrInt needs a whole number, got {value!r}")
            text = str(int(value))
        elif isinstance(value, str):
            text = str.__str__(value)
        else:
            raise TypeError(f"cannot make StrInt from {type(value).__name__}")
        return super().__new__(cls, _normalize(text))

    # -- arithmetic -------------------------------------------------------

    __sub__, __rsub__ = _binary(_sub, operator.sub)
    __floordiv__, __rfloordiv__ = _binary(lambda a, b: _divmod(a, b)[0], operator.floordiv)
    __mod__, __rmod__ = _binary(lambda a, b: _divmod(a, b)[1], operator.mod)
    __divmod__, __rdivmod__ = _binary(_divmod, divmod)
    __truediv__, __rtruediv__ = _binary(lambda a, b: int(a) / int(b), operator.truediv)

    def __add__(self, other):
        o = _coerce(other)
        if o is not None:
            return _add(self, o)
        if isinstance(other, float):
            return float(self) + other
        if isinstance(other, str):  # non-numeric text: plain concatenation
            return str.__str__(self) + other
        return NotImplemented

    def __radd__(self, other):
        o = _coerce(other)
        if o is not None:
            return _add(o, self)
        if isinstance(other, float):
            return other + float(self)
        if isinstance(other, str):
            return other + str.__str__(self)
        return NotImplemented

    def __mul__(self, other):
        o = _coerce(other)
        if o is not None:
            return _mul(self, o)
        if isinstance(other, float):
            return float(self) * other
        if isinstance(other, (str, list, tuple, bytes)):  # repetition
            return other * int(self)
        return NotImplemented

    __rmul__ = __mul__

    def __pow__(self, other, mod=None):
        o = _coerce(other)
        if o is None:
            if isinstance(other, float):
                return float(self) ** other
            return NotImplemented
        if mod is not None:
            m = _coerce(mod)
            if m is None:
                return NotImplemented
            if o.startswith("-"):
                return StrInt(pow(int(self), int(o), int(m)))
            return _pow(self, o, m)
        if o.startswith("-"):
            return float(self) ** int(o)  # same as int: negative power -> float
        return _pow(self, o)

    def __rpow__(self, other, mod=None):
        o = _coerce(other)
        if o is None:
            if isinstance(other, float):
                return other ** float(self)
            return NotImplemented
        return o.__pow__(self, mod)

    def __neg__(self):
        return _neg(self)

    def __pos__(self):
        return self

    def __abs__(self):
        return _make(False, _parts(self)[1])

    # Shifts are multiplication / floor division by powers of two.
    def __lshift__(self, other):
        n = _coerce(other)
        if n is None:
            return NotImplemented
        if n.startswith("-"):
            raise ValueError("negative shift count")
        return _mul(self, _pow(StrInt("2"), n))

    def __rshift__(self, other):
        n = _coerce(other)
        if n is None:
            return NotImplemented
        if n.startswith("-"):
            raise ValueError("negative shift count")
        return _divmod(self, _pow(StrInt("2"), n))[0]

    def __rlshift__(self, other):
        o = _coerce(other)
        return NotImplemented if o is None else o.__lshift__(self)

    def __rrshift__(self, other):
        o = _coerce(other)
        return NotImplemented if o is None else o.__rshift__(self)

    # Bitwise and/or/xor go through int: there is no sensible decimal-text
    # algorithm for two's-complement bit logic.
    __and__, __rand__ = _binary(lambda a, b: StrInt(int(a) & int(b)), operator.and_)
    __or__, __ror__ = _binary(lambda a, b: StrInt(int(a) | int(b)), operator.or_)
    __xor__, __rxor__ = _binary(lambda a, b: StrInt(int(a) ^ int(b)), operator.xor)

    def __invert__(self):
        return _sub(_neg(self), "1")

    # -- comparison -------------------------------------------------------
    # Numeric, so "10" > "9" (plain str would say the opposite).

    def _compare(self, other):
        o = _coerce(other)
        if o is not None:
            return _cmp(self, o)
        if isinstance(other, float):
            f = float(self)
            return (f > other) - (f < other)
        return None

    def __eq__(self, other):
        c = self._compare(other)
        if c is None:
            return str.__eq__(self, other)
        return c == 0

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __lt__(self, other):
        c = self._compare(other)
        return NotImplemented if c is None else c < 0

    def __le__(self, other):
        c = self._compare(other)
        return NotImplemented if c is None else c <= 0

    def __gt__(self, other):
        c = self._compare(other)
        return NotImplemented if c is None else c > 0

    def __ge__(self, other):
        c = self._compare(other)
        return NotImplemented if c is None else c >= 0

    # Hash as the text, so StrInt("5") and "5" are the same dict key.
    __hash__ = str.__hash__

    # -- conversions ------------------------------------------------------

    def __bool__(self):
        return self != "0"  # plain str would make "0" truthy

    def __int__(self):
        return int(str.__str__(self))

    __index__ = __int__  # lets it work in range(), list[i], slices

    def __float__(self):
        return float(int(self))

    def __trunc__(self):
        return self

    __floor__ = __ceil__ = __trunc__

    def __round__(self, ndigits=None):
        if ndigits is None or ndigits >= 0:
            return self
        return StrInt(round(int(self), ndigits))

    def __format__(self, spec):
        if not spec:
            return str.__str__(self)
        try:
            return format(int(self), spec)  # f"{x:05d}", f"{x:,}", f"{x:x}"
        except ValueError:
            return str.__format__(self, spec)

    def __getnewargs__(self):
        return (str.__str__(self),)


S = StrInt


# --------------------------------------------------------------------------
# StrInt versions of the builtins that hand out ints. Rewritten code uses
# these in place of range/len/enumerate.
# --------------------------------------------------------------------------

def srange(*args):
    """range() that yields StrInt."""
    return map(StrInt, range(*(int(a) for a in args)))


def slen(obj):
    """len() that returns StrInt."""
    return StrInt(len(obj))


def senumerate(iterable, start=0):
    """enumerate() whose counter is StrInt."""
    i = StrInt(start)
    for item in iterable:
        yield i, item
        i = _add(i, "1")
