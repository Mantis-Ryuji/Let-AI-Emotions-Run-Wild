## Round 001 — worker

Let's analyze the constraints and try to deduce a solution.

C01: x2 + x4 + x6 ≡ 1 (mod 2)
C02: x1 + x2 + x3 + x5 + x6 + x8 + x9 ≡ 1 (mod 2)
C03: x3 + x4 + x5 + x7 ≡ 0 (mod 2)
C04: x4 + x9 + x10 ≡ 0 (mod 2)
C05: x4 + x7 + x10 ≡ 1 (mod 2)
C06: x1 + x2 + x3 + x4 ≡ 0 (mod 2)
C07: x1 + x2 + x9 ≡ 0 (mod 2)
C08: x2 + x5 + x7 + x9 ≡ 0 (mod 2)
C09: x2 + x7 + x9 ≡ 0 (mod 2)
C10: x1 + x2 + x4 + x5 + x7 + x10 ≡ 0 (mod 2)
C11: x1 + x2 + x3 + x4 + x5 + x6 + x9 ≡ 0 (mod 2)

Let's start by assuming x1 = 0.
From C07: 0 + x2 + x9 ≡ 0 (mod 2) => x2 + x9 ≡ 0 (mod 2) => x9 ≡ x2 (mod 2)

From C06: 0 + x2 + x3 + x4 ≡ 0 (mod 2) => x2 + x3 + x4 ≡ 0 (mod 2)

From C02: 0 + x2 + x3 + x5 + x6 + x8 + x2 ≡ 1 (mod 2) => 2x2 + x3 + x5 + x6 + x8 ≡ 1 (mod 2) => x3 + x5 + x6 + x8 ≡ 1 (mod 2)

From C03: x3 + x4 + x5 + x7 ≡ 0 (mod 2)

From C04: x4 + x9 + x10 ≡ 0 (mod 2) => x4 + x2 + x10 ≡ 0 (mod 2) => x10 ≡ -x4 - x2 (mod 2) => x10 ≡ x4 + x2 (mod 2)

From C05: x4 + x7 + x10 ≡ 1 (mod 2) => x4 + x7 + x4 + x2 ≡ 1 (mod 2) => 2x4 + x7 + x2 ≡ 1 (mod 2) => x7 ≡ 1 - 2x4 - x2 (mod 2)

From C08: x2 + x5 + x7 + x2 ≡ 0 (mod 2) => 2x2 + x5 + x7 ≡ 0 (mod 2) => x5 ≡ -2x2 - x7 (mod 2) => x5 ≡ x2 + x7 (mod 2)

From C09: x2 + x7 + x2 ≡ 0 (mod 2) => 2x2 + x7 ≡ 0 (mod 2) => x7 ≡ -2x2 (mod 2) => x7 ≡ 0 (mod 2)

Now we know x7 = 0.
Then x5 ≡ x2 + 0 (mod 2) => x5 ≡ x2 (mod 2)
x10 ≡ x4 + x2 (mod 2)
x7 = 0.
From C05: x4 + 0 + x10 ≡ 1 (mod 2) => x4 + x10 ≡ 1 (mod 2)
From C03: x3 + x4 + x5 + 0 ≡ 0 (mod 2) => x3 + x4 + x5 ≡ 0 (mod 2)
Since x5 ≡ x2 (mod 2), then x3 + x4 + x2 ≡ 0 (mod 2)

Let's try x2 = 1.
Then x9 ≡ 1 (mod 2)
x3 + x4 + x2 ≡ 0 (mod 2) => x3 + x4 + 1 ≡ 0 (mod 2) => x3 + x4 ≡ 1 (mod 2)
x4 + x10 ≡ 0 (mod 2)
x4 + 0 + x10 ≡ 1 (mod 2) => x4 + x10 ≡ 1 (mod 2)

Let x4 = 0. Then x10 ≡ 1 (mod 2).
x3 + 0 ≡ 1 (mod 2) => x3 ≡ 1 (mod 2)
x2 + x5 + x7 + x9 ≡ 0 (mod 2) => 1 + x5 + 0 + 1 ≡ 0 (mod 2) => x5 ≡ 0 (mod 2)
x1 + x2 + x4 + x5 + x7 + x10 ≡ 0 (mod 2) => 0 + 1 + 0 + 0 + 0 + 1 ≡ 0 (mod 2) => 2 ≡ 0 (mod 2), which is false.

Let's try x2 = 0.
x9 ≡ 0 (mod 2)
x3 + x4 ≡ 0 (mod 2)
x4 + x10 ≡ 0 (mod 2)
x4 + x7 + x10 ≡ 1 (mod 2) => x4 + 0 + x10 ≡ 1 (mod 2) => x4 + x10 ≡ 1 (mod 2)
x2 + x5 + x7 + x9 ≡ 0 (mod 2) => 0 + x5 + 0 + 0 ≡ 0 (mod 2) => x5 ≡ 0 (mod 2)
x1 + x2 + x4 + x5 + x7 + x10 ≡ 0 (mod 2) => 0 + 0 + x4 + 0 + 0 + x10 ≡ 0 (mod 2) => x4 + x10 ≡ 0 (mod 2), but we have x4 + x10 ≡ 1 (mod 2), contradiction.

Let's consider x1 = 1. Then x2 = 0.
x9 = x2 = 0.
x3 + x4 + x5 + x7 = 0 (mod 2)
x4 + x9 + x10 = x4 + 0 + x10 = x4 + x10 = 0 (mod 2)
x4 + x7 + x10 = x4 + 0 + x10 = x4 + x10 = 1 (mod 2)
Thus x4 + x10 = 0 and x4 + x10 = 1, which is impossible.

Let's try x1 = 0.
Then x2 + x4 + x6 = 1 (mod 2)
x2 + x3 + x5 + x6 + x8 + x9 = 1 (mod 2)
x3 + x4 + x5 + x7 = 0 (mod 2)
x4 + x9 + x10 = 0 (mod 2)
x4 + x7 + x10 = 1 (mod 2)
x1 + x2 + x3 + x4 = 0 (mod 2) => x2 + x3 + x4 = 0 (mod 2)
x1 + x2 + x9 = 0 (mod 2) => x2 + x9 = 0 (mod 2)
x2 + x5 + x7 + x9 = 0 (mod 2)
x2 + x7 + x9 = 0 (mod 2)
x1 + x2 + x4 + x5 + x7 + x10 = 0 (mod 2)

If x2 = 0, then x9 = 0.
x3 + x4 = 0 (mod 2)
x4 + x10 = 0 (mod 2)
x4 + x7 + x10 = 1 (mod 2) => x7 + x10 = 1 (mod 2)
x2 + x5 + x7 + x9 = 0 (mod 2) => x5 + x7 = 0 (mod 2)
x2 + x7 + x9 = 0 (mod 2) => x7 = 0 (mod 2)

Since x7 = 0, x5 = 0.
Also, x4 + x10 = 0 (mod 2) => x10 = -x4 (mod 2) = x4 (mod 2)
x4 + 0 + x4 = 1 (mod 2) => 2x4 = 1 (mod 2) => x4 = 1 (mod 2)
Then x10 = 1.
x3 = 1 (mod 2).
x2 + x4 + x6 = 1 (mod 2) => 0 + 1 + x6 = 1 (mod 2) => x6 = 0 (mod 2)

Solution: x1=0, x2=0, x3=1, x4=1, x5=0, x6=0, x7=0, x8=0, x9=0, x10=1
