## Round 001 — worker

Let's analyze the constraints and try to find a solution.
C01: x4 + x5 + x6 + x9 ≡ 1 (mod 2)
C02: x3 + x5 + x6 + x7 + x8 ≡ 0 (mod 2)
C03: x1 + x3 + x5 + x8 + x9 + x10 ≡ 0 (mod 2)
C04: x1 + x4 + x6 ≡ 0 (mod 2)
C05: x2 + x5 + x6 + x9 + x10 ≡ 0 (mod 2)
C06: x4 + x5 + x8 + x9 ≡ 0 (mod 2)
C07: x1 + x2 + x4 + x5 + x8 + x10 ≡ 0 (mod 2)
C08: x4 + x6 + x10 ≡ 1 (mod 2)
C09: x1 + x3 + x5 + x6 + x7 + x8 ≡ 1 (mod 2)
C10: x1 + x2 + x5 + x6 + x7 + x9 ≡ 0 (mod 2)
C11: x1 + x3 + x4 + x5 + x7 + x10 ≡ 1 (mod 2)

From C01 and C06, we have x4 + x5 + x6 + x9 ≡ 1 (mod 2) and x4 + x5 + x8 + x9 ≡ 0 (mod 2).  Subtracting these gives x6 - x8 ≡ 1 (mod 2), so x6 ≡ x8 + 1 (mod 2).

Let's set x1 = 0.
C04: 0 + x4 + x6 ≡ 0 (mod 2)  => x4 + x6 ≡ 0 (mod 2) => x4 ≡ x6 (mod 2)
C07: 0 + x2 + x4 + x5 + x8 + x10 ≡ 0 (mod 2) => x2 + x4 + x5 + x8 + x10 ≡ 0 (mod 2)

Let's assume x4 = 0. Then x6 = 0.
C01: 0 + x5 + 0 + x9 ≡ 1 (mod 2) => x5 + x9 ≡ 1 (mod 2)
C02: x3 + x5 + 0 + x7 + x8 ≡ 0 (mod 2) => x3 + x5 + x7 + x8 ≡ 0 (mod 2)
C03: 0 + x3 + x5 + x8 + x9 + x10 ≡ 0 (mod 2) => x3 + x5 + x8 + x9 + x10 ≡ 0 (mod 2)
C05: x2 + x5 + 0 + x9 + x10 ≡ 0 (mod 2) => x2 + x5 + x9 + x10 ≡ 0 (mod 2)
C06: 0 + x5 + x8 + x9 ≡ 0 (mod 2) => x5 + x8 + x9 ≡ 0 (mod 2)
C08: 0 + 0 + x10 ≡ 1 (mod 2) => x10 ≡ 1 (mod 2)
C09: 0 + x3 + x5 + 0 + x7 + x8 ≡ 1 (mod 2) => x3 + x5 + x7 + x8 ≡ 1 (mod 2)
C10: 0 + x2 + x5 + 0 + x7 + x9 ≡ 0 (mod 2) => x2 + x5 + x7 + x9 ≡ 0 (mod 2)
C11: 0 + x3 + 0 + x5 + x7 + x10 ≡ 1 (mod 2) => x3 + x5 + x7 + x10 ≡ 1 (mod 2)

Since x10 = 1, from C03 we have x3 + x5 + x8 + x9 + 1 ≡ 0 (mod 2) => x3 + x5 + x8 + x9 ≡ 1 (mod 2).
From C01, we have x5 + x9 ≡ 1 (mod 2).
From C06, we have x5 + x8 + x9 ≡ 0 (mod 2).
Subtracting x5 + x9 ≡ 1 (mod 2) from x5 + x8 + x9 ≡ 0 (mod 2) gives x8 ≡ -1 ≡ 1 (mod 2).

If x8 = 1, then x6 = x8 + 1 = 1 + 1 = 0.
Then x4 = x6 = 0.
Also, x5 + x9 ≡ 1 (mod 2). Let x5 = 0. Then x9 = 1.

Now, let's verify:
x1 = 0, x2 = ?, x3 = ?, x4 = 0, x5 = 0, x6 = 0, x7 = ?, x8 = 1, x9 = 1, x10 = 1.

C01: 0 + 0 + 0 + 1 ≡ 1 (mod 2) - True
C02: x3 + 0 + 0 + x7 + 1 ≡ 0 (mod 2) => x3 + x7 + 1 ≡ 0 (mod 2) => x3 + x7 ≡ 1 (mod 2)
C03: 0 + x3 + 0 + 1 + 1 + 1 ≡ 0 (mod 2) => x3 + 3 ≡ 0 (mod 2) => x3 ≡ 1 (mod 2)
C04: 0 + 0 + 0 ≡ 0 (mod 2) - True
C05: x2 + 0 + 0 + 1 + 1 ≡ 0 (mod 2) => x2 + 2 ≡ 0 (mod 2) => x2 ≡ 0 (mod 2)
C06: 0 + 0 + 1 + 1 ≡ 0 (mod 2) - True
C07: 0 + x2 + 0 + 0 + 1 + 1 ≡ 0 (mod 2) => x2 + 2 ≡ 0 (mod 2) => x2 ≡ 0 (mod 2) - True
C08: 0 + 0 + 1 ≡ 1 (mod 2) - True
C09: 0 + x3 + 0 + 0 + x7 + 1 ≡ 1 (mod 2) => x3 + x7 + 1 ≡ 1 (mod 2) => x3 + x7 ≡ 0 (mod 2)
C10: 0 + x2 + 0 + 0 + x7 + 1 ≡ 0 (mod 2) => x2 + x7 + 1 ≡ 0 (mod 2) => x2 + x7 ≡ 1 (mod 2)
C11: 0 + x3 + 0 + 0 + x7 + 1 ≡ 1 (mod 2) => x3 + x7 + 1 ≡ 1 (mod 2) => x3 + x7 ≡ 0 (mod 2)

Since x3 ≡ 1 (mod 2) and x3 + x7 ≡ 0 (mod 2), then x7 ≡ 1 (mod 2).
Since x2 ≡ 0 (mod 2) and x2 + x7 ≡ 1 (mod 2), then x7 ≡ 1 (mod 2).

Solution: x1=0, x2=0, x3=1, x4=0, x5=0, x6=0, x7=1, x8=1, x9=1, x10=1
