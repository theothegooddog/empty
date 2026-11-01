import operator
import os
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from strnum import S, StrInt, exec_strnum, install, uninstall  # noqa: E402


def samples():
    rng = random.Random(1234)
    vals = [0, 1, -1, 2, -2, 7, -7, 9, 10, -10, 99, 100, 12345, -98765]
    vals += [rng.randint(-10**40, 10**40) for _ in range(25)]
    return vals


class TestStrInt(unittest.TestCase):
    def test_is_str(self):
        x = S(5)
        self.assertIsInstance(x, str)
        self.assertEqual(str.__str__(x), "5")
        self.assertEqual(repr(x), "'5'")
        self.assertEqual(x.upper(), "5")

    def test_normalizes(self):
        self.assertEqual(str.__str__(S("007")), "7")
        self.assertEqual(str.__str__(S("-0")), "0")
        self.assertEqual(str.__str__(S(" +42 ")), "42")
        self.assertEqual(str.__str__(S("1_000")), "1000")
        with self.assertRaises(ValueError):
            S("abc")
        with self.assertRaises(ValueError):
            S(2.5)

    def test_arithmetic_matches_int(self):
        ops = [operator.add, operator.sub, operator.mul]
        div_ops = [operator.floordiv, operator.mod, divmod]
        vals = samples()
        for a in vals:
            for b in vals:
                for op in ops:
                    got = op(S(a), S(b))
                    self.assertIsInstance(got, StrInt)
                    self.assertEqual(int(got), op(a, b), (op, a, b))
                if b != 0:
                    for op in div_ops:
                        got = op(S(a), S(b))
                        self.assertEqual(
                            tuple(map(int, got)) if op is divmod else int(got),
                            op(a, b),
                            (op, a, b),
                        )
                self.assertEqual(S(a) < S(b), a < b)
                self.assertEqual(S(a) == S(b), a == b)
                self.assertEqual(S(a) >= S(b), a >= b)

    def test_pow_and_shifts(self):
        for a in [0, 1, -3, 7, 123456789]:
            for e in [0, 1, 2, 5, 13]:
                self.assertEqual(int(S(a) ** S(e)), a ** e)
                self.assertEqual(int(pow(S(a), S(e), S(97))), pow(a, e, 97))
                self.assertEqual(int(S(a) << S(e)), a << e)
                self.assertEqual(int(S(a) >> S(e)), a >> e)
        self.assertEqual(S(2) ** -1, 0.5)
        self.assertEqual(int(S(2) ** 1000), 2 ** 1000)

    def test_bitwise_and_unary(self):
        for a in [-13, -1, 0, 6, 255]:
            for b in [-7, 0, 3, 12]:
                self.assertEqual(int(S(a) & S(b)), a & b)
                self.assertEqual(int(S(a) | S(b)), a | b)
                self.assertEqual(int(S(a) ^ S(b)), a ^ b)
            self.assertEqual(int(~S(a)), ~a)
            self.assertEqual(int(-S(a)), -a)
            self.assertEqual(int(abs(S(a))), abs(a))

    def test_mixed_with_int_and_str(self):
        self.assertEqual(S(5) + 3, "8")
        self.assertEqual(3 + S(5), "8")
        self.assertEqual("3" + S(5), "8")
        self.assertEqual(S(5) + "3", "8")
        self.assertEqual(S(10) - "4", "6")
        self.assertEqual(S(5) == 5, True)
        self.assertEqual(5 == S(5), True)
        self.assertEqual(S(10) > 9, True)
        self.assertEqual(S(10) > "9", True)  # numeric, not lexicographic

    def test_non_numeric_text_still_concatenates(self):
        self.assertEqual("total: " + S(5), "total: 5")
        self.assertEqual(S(5) + " apples", "5 apples")
        self.assertEqual("ab" * S(3), "ababab")
        self.assertEqual([0] * S(2), [0, 0])

    def test_floats(self):
        self.assertEqual(S(5) + 0.5, 5.5)
        self.assertEqual(S(7) / S(2), 3.5)
        self.assertEqual(S(1) < 1.5, True)

    def test_conversions(self):
        self.assertFalse(S(0))
        self.assertTrue(S(-1))
        self.assertEqual(int(S("-12")), -12)
        self.assertEqual(float(S(3)), 3.0)
        self.assertEqual(list(range(S(3))), [0, 1, 2])
        self.assertEqual("abcdef"[S(1):S(3)], "bc")
        self.assertEqual(f"{S(42):05d}", "00042")
        self.assertEqual(f"{S(1234567):,}", "1,234,567")
        self.assertEqual(f"{S(5)}", "5")
        self.assertEqual({S(5): "x"}["5"], "x")


class TestTransform(unittest.TestCase):
    def test_literals_become_strint(self):
        g = exec_strnum(
            "a = (5)\n"
            "b = a * 3 - 1\n"
            "c = [i * i for i in range(4)]\n"
            "d = -2 ** 10\n"
            "e = True\n"
            "f = 1.5\n"
            "def g(x=2):\n"
            "    match x:\n"
            "        case 2: return 'two'\n"
            "        case _: return 'other'\n"
            "h = g()\n"
            "i = len('abc') + 1\n"
        )
        self.assertIsInstance(g["a"], StrInt)
        self.assertEqual(g["a"], "5")
        self.assertEqual(g["b"], "14")
        self.assertEqual(c := g["c"], ["0", "1", "4", "9"])
        self.assertTrue(all(isinstance(x, StrInt) for x in c))
        self.assertEqual(g["d"], "-1024")
        self.assertIs(g["e"], True)
        self.assertEqual(g["f"], 1.5)
        self.assertEqual(g["h"], "two")  # match on StrInt("2") hits case 2
        self.assertEqual(g["i"], "4")

    def test_import_hook(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "strnum_demo_mod.py"), "w") as f:
                f.write("# strnum\nX = 40 + 2\n")
            with open(os.path.join(d, "plain_demo_mod.py"), "w") as f:
                f.write("X = 40 + 2\n")
            sys.path.insert(0, d)
            install()
            try:
                import plain_demo_mod
                import strnum_demo_mod
            finally:
                uninstall()
                sys.path.remove(d)
            self.assertIsInstance(strnum_demo_mod.X, StrInt)
            self.assertEqual(strnum_demo_mod.X, "42")
            self.assertIs(type(plain_demo_mod.X), int)

    def test_cli(self):
        env = dict(os.environ, PYTHONPATH=ROOT)
        out = subprocess.run(
            [sys.executable, "-m", "strnum", "-c", "x = (5)\nprint(repr(x), type(x).__name__, x + 1)"],
            capture_output=True, text=True, env=env, check=True,
        ).stdout
        self.assertEqual(out.strip(), "'5' StrInt 6")

    def test_repl(self):
        env = dict(os.environ, PYTHONPATH=ROOT)
        out = subprocess.run(
            [sys.executable, "-m", "strnum"],
            input="(5)\n(5) + (3)\nfor i in range(2):\n    print(repr(i))\n\nlen('abc')\n",
            capture_output=True, text=True, env=env, check=True,
        ).stdout
        self.assertIn("'5'", out)
        self.assertIn("'8'", out)
        self.assertIn("'0'\n'1'", out)
        self.assertIn("'3'", out)

    def test_user_can_shadow_range(self):
        g = exec_strnum("def range(n):\n    return 'mine'\nr = range(3)\n")
        self.assertEqual(g["r"], "mine")

    def test_docstring_and_future_import_kept_first(self):
        g = exec_strnum('"""doc"""\nfrom __future__ import annotations\nx = len([1, 2])\n')
        self.assertEqual(g["__doc__"], "doc")
        self.assertIsInstance(g["x"], StrInt)
        self.assertEqual(g["x"], "2")


if __name__ == "__main__":
    unittest.main()
