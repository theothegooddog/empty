#!/usr/bin/env python3
"""String calculator: arbitrary-size arithmetic done digit by digit on strings.

Numbers are never converted with int() or float(). Every operation works on
strings of digit characters the way you would on paper: column addition with
carries, subtraction with borrows, long multiplication, and long division.
The only "number facts" used are single-digit ones (e.g. 7 + 8 = 15).

Supports: + - * / // % ^ (or **), parentheses, negatives and decimals.

Usage:
    python strcalc.py "9859738*6478326"
    python strcalc.py --steps "9859738*6478326"
    python strcalc.py --precision 50 "22/7"
    python strcalc.py            # interactive mode
"""

import argparse
import re

DIGITS = "0123456789"


def dv(c):
    """Value of a single digit character (a one-digit 'times table' lookup)."""
    return ord(c) - 48


class LiveLog(list):
    """A step log that prints each line the moment it is added."""

    def append(self, line):
        super().append(line)
        print(line, flush=True)

    def extend(self, lines):
        for line in lines:
            self.append(line)

    def __iadd__(self, lines):
        self.extend(lines)
        return self


def strip(a):
    """Remove leading zeros from a digit string."""
    return a.lstrip("0") or "0"


# ---------------------------------------------------------------------------
# Unsigned operations on digit strings
# ---------------------------------------------------------------------------

def cmp_abs(a, b):
    """Compare two digit strings: -1, 0 or 1."""
    a, b = strip(a), strip(b)
    if len(a) != len(b):
        return 1 if len(a) > len(b) else -1
    return (a > b) - (a < b)


def add_abs(a, b, log=None):
    """Column addition with carries."""
    n = max(len(a), len(b))
    A, B = a.zfill(n), b.zfill(n)
    out, carry = [], 0
    carries = [" "] * (n + 1)
    for i in range(n - 1, -1, -1):
        s = dv(A[i]) + dv(B[i]) + carry
        out.append(DIGITS[s % 10])
        carry = 1 if s >= 10 else 0
        if carry:
            carries[i] = "1"
    if carry:
        out.append("1")
    result = strip("".join(reversed(out)))
    if log is not None:
        w = n + 3
        if carry or "1" in carries:
            log.append("".join(carries).rjust(w) + "   <- carries")
        log += [a.rjust(w), "+ " + b.rjust(w - 2), "-" * w, result.rjust(w)]
    return result


def sub_abs(a, b, log=None):
    """Column subtraction with borrows. Requires a >= b."""
    n = len(a)
    B = b.zfill(n)
    out, borrow = [], 0
    borrows = [" "] * n
    for i in range(n - 1, -1, -1):
        d = dv(a[i]) - borrow - dv(B[i])
        if d < 0:
            d += 10
            borrow = 1
            borrows[i] = "1"
        else:
            borrow = 0
        out.append(DIGITS[d])
    result = strip("".join(reversed(out)))
    if log is not None:
        w = n + 3
        if "1" in borrows:
            log.append("".join(borrows).rjust(w) + "   <- borrowed 10")
        log += [a.rjust(w), "- " + b.rjust(w - 2), "-" * w, result.rjust(w)]
    return result


def mul_digit(a, d):
    """Multiply a digit string by a single digit (0-9)."""
    out, carry = [], 0
    for c in reversed(a):
        s = dv(c) * d + carry
        out.append(DIGITS[s % 10])
        carry = s // 10
    if carry:
        out.append(DIGITS[carry])
    return strip("".join(reversed(out)))


def mul_abs(a, b, log=None):
    """Long multiplication: one partial product per digit of b, then add."""
    a, b = strip(a), strip(b)
    w = len(a) + len(b) + 2  # the product has at most len(a) + len(b) digits
    if log is not None:
        log += [a.rjust(w), ("x " + b).rjust(w), "-" * w]
    total = "0"
    for i, c in enumerate(reversed(b)):
        p = mul_digit(a, dv(c))
        total = add_abs(total, p + "0" * i)
        if log is not None:
            log.append(p.rjust(w - i) + " " * i + f"   {a} x {c}   (row {i + 1} of {len(b)})")
    if log is not None and len(b) > 1:
        log += ["-" * w, total.rjust(w) + "   (sum of the rows above)"]
    return total


def divmod_abs(a, b, log=None):
    """Long division. Returns (quotient, remainder) as digit strings."""
    a, b = strip(a), strip(b)
    if b == "0":
        raise ZeroDivisionError("division by zero")
    if log is not None:
        log.append(f"long division: {a} / {b}")
    q, rem = [], "0"
    for k, c in enumerate(a, 1):
        cur = strip(rem + c)
        d, rem = 0, cur
        while cmp_abs(rem, b) >= 0:  # how many times does b fit?
            rem = sub_abs(rem, b)
            d += 1
        started = any(x != "0" for x in q)
        q.append(DIGITS[d])
        if log is not None and (d or started):
            if d:
                log.append(f"  bring down {c} -> {cur}: {b} fits {d}x, "
                           f"{cur} - {mul_digit(b, d)} = {rem}  -> write {d}   (digit {k} of {len(a)})")
            else:
                log.append(f"  bring down {c} -> {cur}: smaller than {b}  -> write 0   (digit {k} of {len(a)})")
    quotient = strip("".join(q))
    if log is not None:
        log.append(f"  quotient {quotient}, remainder {rem}")
    return quotient, rem


# ---------------------------------------------------------------------------
# Signed decimal numbers: (negative, digits, scale) means digits / 10**scale
# ---------------------------------------------------------------------------

def norm(n):
    neg, d, s = n
    d = strip(d)
    while s > 0 and d != "0" and d.endswith("0"):
        d, s = d[:-1], s - 1
    if d == "0":
        neg, s = False, 0
    return (neg, d, s)


def parse(text):
    text = text.strip()
    neg = False
    if text[:1] in ("+", "-"):
        neg, text = text[0] == "-", text[1:]
    if not text or text == "." or text.count(".") > 1 or any(c not in DIGITS + "." for c in text):
        raise ValueError(f"not a number: {text!r}")
    whole, _, frac = text.partition(".")
    return norm((neg, (whole + frac) or "0", len(frac)))


def fmt(n):
    neg, d, s = n
    if s:
        d = d.zfill(s + 1)
        d = d[:-s] + "." + d[-s:]
    return ("-" if neg else "") + d


ONE = (False, "1", 0)


def _scale_note(log, s):
    if log is not None and s:
        log.append(f"(decimals: working with whole numbers scaled by 10^{s}, "
                   f"then putting the point back)")


def add(x, y, log=None):
    s = max(x[2], y[2])
    a, b = x[1] + "0" * (s - x[2]), y[1] + "0" * (s - y[2])
    _scale_note(log, s)
    if x[0] == y[0]:
        return norm((x[0], add_abs(a, b, log), s))
    if cmp_abs(a, b) >= 0:
        return norm((x[0], sub_abs(a, b, log), s))
    if log is not None:
        log.append("(second number is bigger, so subtract the other way and keep its sign)")
    return norm((y[0], sub_abs(b, a, log), s))


def neg(x):
    return norm((not x[0], x[1], x[2]))


def sub(x, y, log=None):
    return add(x, neg(y), log)


def mul(x, y, log=None):
    _scale_note(log, x[2] + y[2])
    return norm((x[0] != y[0], mul_abs(x[1], y[1], log), x[2] + y[2]))


def div(x, y, precision=20, log=None):
    """Decimal division, truncated to `precision` decimal places."""
    if y[1] == "0":
        raise ZeroDivisionError("division by zero")
    shift = y[2] + precision - x[2]
    a, b = x[1], y[1]
    if shift >= 0:
        a += "0" * shift
    else:
        b += "0" * -shift
    if log is not None and precision:
        log.append(f"(adding zeros to get {precision} decimal places)")
    q, r = divmod_abs(a, b, log)
    if log is not None and r != "0":
        log.append(f"(remainder not zero: result cut off at {precision} decimal places)")
    return norm((x[0] != y[0], q, precision))


def divmod_int(x, y, log=None):
    """Whole-number floor division and modulo (same rules as Python's // and %)."""
    if x[2] or y[2]:
        raise ValueError("// and % need whole numbers")
    q, r = divmod_abs(x[1], y[1], log)
    qn, rn = (x[0] != y[0], q, 0), (x[0], r, 0)
    if x[0] != y[0] and r != "0":
        if log is not None:
            log.append("(signs differ: round the quotient down, adjust the remainder)")
        qn = (True, add_abs(q, "1"), 0)
        rn = add(norm(rn), y)
    return norm(qn), norm(rn)


def power(x, y, precision=20, log=None):
    """x ^ y for a whole-number y, using exponentiation by squaring."""
    if y[2]:
        raise ValueError("exponent must be a whole number")
    e, result, base, step = y[1], ONE, x, 0
    if log is not None:
        log.append(f"exponentiation by squaring (exponent {e} halved each step)")
    while e != "0":
        e, bit = divmod_abs(e, "2")
        step += 1
        if bit == "1":
            result = mul(result, base)
        if e != "0":
            base = mul(base, base)
        if log is not None:
            log.append(f"  step {step}, bit {bit}: " + ("result = result x base; " if bit == "1" else "")
                       + ("base = base x base" if e != "0" else "done"))
    if y[0]:
        result = div(ONE, result, precision, log)
    return result


# ---------------------------------------------------------------------------
# Expression parser
# ---------------------------------------------------------------------------

TOKEN = re.compile(r"\s*(?:([0-9]+\.?[0-9]*|\.[0-9]+)|(\*\*|//|[-+*/%^()]))")


def tokenize(text):
    text = text.rstrip()
    pos, toks = 0, []
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise SyntaxError(f"don't understand {text[pos:].strip()!r}")
        toks.append(("num", m.group(1)) if m.group(1) else ("op", m.group(2)))
        pos = m.end()
    return toks


class Calculator:
    def __init__(self, precision=20, show_steps=False, live=False):
        self.precision = precision
        self.show_steps = show_steps
        self.live = live  # print each step as soon as it's done
        self.steps = []

    def evaluate(self, text):
        """Evaluate an expression string. Returns the result as a string."""
        self.toks, self.i, self.steps = tokenize(text), 0, []
        if not self.toks:
            raise SyntaxError("empty expression")
        result = self._expr()
        if self.i < len(self.toks):
            raise SyntaxError(f"unexpected {self.toks[self.i][1]!r}")
        return fmt(result)

    # grammar:  expr   := term (('+'|'-') term)*
    #           term   := unary (('*'|'/'|'//'|'%') unary)*
    #           unary  := ('+'|'-') unary | power
    #           power  := atom (('^'|'**') unary)?
    #           atom   := NUMBER | '(' expr ')'

    def _peek(self):
        return self.toks[self.i][1] if self.i < len(self.toks) else None

    def _next(self):
        if self.i >= len(self.toks):
            raise SyntaxError("expression ended too early")
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def _expr(self):
        x = self._term()
        while self._peek() in ("+", "-"):
            op = self._next()[1]
            x = self._apply(op, x, self._term())
        return x

    def _term(self):
        x = self._unary()
        while self._peek() in ("*", "/", "//", "%"):
            op = self._next()[1]
            x = self._apply(op, x, self._unary())
        return x

    def _unary(self):
        if self._peek() in ("+", "-"):
            op = self._next()[1]
            x = self._unary()
            return neg(x) if op == "-" else x
        return self._power()

    def _power(self):
        x = self._atom()
        if self._peek() in ("^", "**"):
            self._next()
            x = self._apply("^", x, self._unary())
        return x

    def _atom(self):
        kind, val = self._next()
        if kind == "num":
            return parse(val)
        if val == "(":
            x = self._expr()
            if self._next()[1] != ")":
                raise SyntaxError("missing )")
            return x
        raise SyntaxError(f"unexpected {val!r}")

    def _apply(self, op, x, y):
        log = None
        if self.show_steps:
            log = LiveLog() if self.live else []
            log.append(f"=== {fmt(x)} {op} {fmt(y)} ===")
        if op == "+":
            r = add(x, y, log)
        elif op == "-":
            r = sub(x, y, log)
        elif op == "*":
            r = mul(x, y, log)
        elif op == "/":
            r = div(x, y, self.precision, log)
        elif op == "//":
            r = divmod_int(x, y, log)[0]
        elif op == "%":
            r = divmod_int(x, y, log)[1]
        else:
            r = power(x, y, self.precision, log)
        if log is not None:
            log += [f"=> {fmt(r)}", ""]
            self.steps += log
        return r


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def run_one(calc, text):
    try:
        result = calc.evaluate(text)
    except (SyntaxError, ValueError, ZeroDivisionError) as e:
        print(f"error: {e}")
        return
    if calc.show_steps and not calc.live and calc.steps:
        print("\n".join(calc.steps))
    print(result)


def repl(calc):
    print("String calculator. Operators: + - * / // % ^ ( )")
    print("Commands: 'steps' toggles step display, 'precision N' sets decimal places, 'quit' exits.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("quit", "exit", "q"):
            break
        if line == "steps":
            calc.show_steps = not calc.show_steps
            print(f"steps {'on' if calc.show_steps else 'off'}")
        elif line.startswith("precision"):
            arg = line[len("precision"):].strip()
            if arg and all(c in DIGITS for c in arg):
                calc.precision = int(arg)  # a setting, not part of any calculation
                print(f"precision {calc.precision}")
            else:
                print(f"precision is {calc.precision} (use: precision N)")
        else:
            run_one(calc, line)


def main():
    ap = argparse.ArgumentParser(description="Arbitrary-size calculator that works on digit strings.")
    ap.add_argument("expression", nargs="*", help="expression to evaluate (omit for interactive mode)")
    ap.add_argument("-s", "--steps", action="store_true", help="show the working")
    ap.add_argument("-p", "--precision", type=int, default=20, help="decimal places for / (default 20)")
    args, extra = ap.parse_known_args()  # lets "-5*3" through as an expression
    args.expression += extra
    calc = Calculator(precision=args.precision, show_steps=args.steps, live=True)
    if args.expression:
        run_one(calc, " ".join(args.expression))
    else:
        repl(calc)


if __name__ == "__main__":
    main()
