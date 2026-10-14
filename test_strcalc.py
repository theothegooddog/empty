"""Randomized checks of strcalc against Python's own arithmetic."""
import random
from fractions import Fraction
from strcalc import Calculator

calc = Calculator(precision=30)

def big(n):
    return random.choice([1, -1]) * random.randrange(10 ** random.randrange(1, n))

def test_integers():
    for _ in range(3000):
        a, b = big(60), big(60)
        assert calc.evaluate(f"{a}+({b})") == str(a + b)
        assert calc.evaluate(f"{a}-({b})") == str(a - b)
        assert calc.evaluate(f"{a}*({b})") == str(a * b)
        if b:
            assert calc.evaluate(f"{a}//({b})") == str(a // b)
            assert calc.evaluate(f"{a}%({b})") == str(a % b)

def test_division_and_decimals():
    for _ in range(2000):
        a, b = Fraction(big(30), 10 ** random.randrange(5)), Fraction(big(30), 10 ** random.randrange(5))
        if not b:
            continue
        q = a / b
        trunc = Fraction(int(q * 10 ** 30), 10 ** 30)  # truncated to 30 places
        assert Fraction(calc.evaluate(f"({float_str(a)})/({float_str(b)})")) == trunc
        assert Fraction(calc.evaluate(f"({float_str(a)})*({float_str(b)})")) == a * b
        assert Fraction(calc.evaluate(f"({float_str(a)})+({float_str(b)})")) == a + b

def float_str(f):
    s = f"{abs(f.numerator) * 10**5 // f.denominator:06d}"
    s = s[:-5] + "." + s[-5:]
    return ("-" if f < 0 else "") + s

def test_power_and_precedence():
    for _ in range(300):
        a, e = big(8), random.randrange(40)
        assert calc.evaluate(f"({a})^{e}") == str(a ** e)
    assert calc.evaluate("-2^2") == "-4"
    assert calc.evaluate("2^3^2") == "512"
    assert calc.evaluate("2 + 3 * (4 - 1) // 2") == "6"
    assert calc.evaluate("9859738*6478326") == str(9859738 * 6478326)

if __name__ == "__main__":
    test_integers(); test_division_and_decimals(); test_power_and_precedence()
    print("all tests passed")
