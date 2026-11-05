import opticomp  # must be the first statement: everything below runs optimized

import time

DEBUG = False
SECONDS_PER_DAY = 24 * 60 * 60
SCALE = 2 ** 10


def collect_squares(n):
    out = []
    for i in range(n):
        out.append(i ** 2 % SCALE)
        if DEBUG:
            print("i =", i)
    return out


def describe(x):
    if x < 0:
        return "negative"
        print("never printed")
    return "non-negative"


start = time.perf_counter()
total = 0
for _ in range(20):
    total += sum(collect_squares(200_000))
elapsed = time.perf_counter() - start

print("seconds/day:", SECONDS_PER_DAY)
print(describe(-1), describe(3))
print("total:", total)
print(f"elapsed: {elapsed:.3f}s")
