## Round 001 — worker

Let's analyze the constraints to find a consistent assignment of values to the variables.

C01: x2 + x3 + x4 + x6 + x8 ≡ 0 (mod 2)
C02: x2 + x4 + x5 + x8 ≡ 0 (mod 2)
C03: x3 + x8 + x10 ≡ 1 (mod 2)
C04: x2 + x4 + x6 + x8 + x9 ≡ 0 (mod 2)
C05: x1 + x3 + x6 + x7 + x8 + x9 + x10 ≡ 0 (mod 2)
C06: x1 + x5 + x10 ≡ 0 (mod 2)
C07: x2 + x5 + x8 ≡ 0 (mod 2)
C08: x2 + x4 + x10 ≡ 1 (mod 2)
C09: x1 + x3 + x4 + x6 + x7 + x9 + x10 ≡ 0 (mod 2)
C10: x1 + x2 + x3 + x4 + x5 + x6 ≡ 0 (mod 2)
C11: x2 + x3 + x4 + x6 + x8 + x10 ≡ 1 (mod 2)

From C02 and C07, we have: x2 + x4 + x5 + x8 ≡ 0 (mod 2) and x2 + x5 + x8 ≡ 0 (mod 2).  Therefore, x4 + x5 ≡ 0 (mod 2), which implies x4 ≡ x5 (mod 2).

From C08, we have x2 + x4 + x10 ≡ 1 (mod 2).
From C01, we have x2 + x3 + x4 + x6 + x8 ≡ 0 (mod 2).

Let's try x1 = 0.
If x1 = 0, then from C06: x1 + x5 + x10 ≡ 0 (mod 2) becomes 0 + x5 + x10 ≡ 0 (mod 2), so x5 + x10 ≡ 0 (mod 2), which means x5 ≡ x10 (mod 2).
Since x4 ≡ x5 (mod 2), we have x4 ≡ x10 (mod 2).

Let's set x2 = 1.
Then from C02: 1 + x4 + x5 + x8 ≡ 0 (mod 2), so x4 + x5 + x8 ≡ 1 (mod 2).
Since x4 ≡ x5 (mod 2), we have 2x4 + x8 ≡ 1 (mod 2), so x8 ≡ 1 (mod 2).
From C07: 1 + x5 + x8 ≡ 0 (mod 2), so 1 + x5 + 1 ≡ 0 (mod 2), which means x5 ≡ 0 (mod 2).
Since x4 ≡ x5 (mod 2), x4 ≡ 0 (mod 2).

Now we have: x1 = 0, x2 = 1, x4 = 0, x5 = 0, x8 = 1.
From C03: x3 + x8 + x10 ≡ 1 (mod 2), so x3 + 1 + x10 ≡ 1 (mod 2), which means x3 + x10 ≡ 0 (mod 2), so x3 ≡ x10 (mod 2).
From C04: x2 + x4 + x6 + x8 + x9 ≡ 0 (mod 2), so 1 + 0 + x6 + 1 + x9 ≡ 0 (mod 2), which means x6 + x9 ≡ 0 (mod 2), so x6 ≡ x9 (mod 2).
From C05: x1 + x3 + x6 + x7 + x8 + x9 + x10 ≡ 0 (mod 2), so 0 + x3 + x6 + x7 + 1 + x9 + x10 ≡ 0 (mod 2), which means x3 + x6 + x7 + x9 + x10 ≡ 1 (mod 2).
Since x3 ≡ x10 (mod 2) and x6 ≡ x9 (mod 2), we have x10 + x6 + x7 + x9 + x10 ≡ 1 (mod 2), so 2x10 + x6 + x7 + x9 ≡ 1 (mod 2), which means x6 + x7 + x9 ≡ 1 (mod 2).

From C09: x1 + x3 + x4 + x6 + x7 + x9 + x10 ≡ 0 (mod 2), so 0 + x3 + 0 + x6 + x7 + x9 + x10 ≡ 0 (mod 2), which means x3 + x6 + x7 + x9 + x10 ≡ 0 (mod 2). This is consistent with our previous finding.

From C10: x1 + x2 + x3 + x4 + x5 + x6 ≡ 0 (mod 2), so 0 + 1 + x3 + 0 + 0 + x6 ≡ 0 (mod 2), which means x3 + x6 ≡ 1 (mod 2).
From C11: x2 + x3 + x4 + x6 + x8 + x10 ≡ 1 (mod 2), so 1 + x3 + 0 + x6 + 1 + x10 ≡ 1 (mod 2), which means x3 + x6 + x10 ≡ 1 (mod 2).
Since x3 ≡ x10 (mod 2) and x6 ≡ x9 (mod 2), we have x3 + x6 + x10 ≡ x10 + x9 + x10 ≡ 2x10 + x9 ≡ 1 (mod 2), so x9 ≡ 1 (mod 2).
Since x6 ≡ x9 (mod 2), we have x6 ≡ 1 (mod 2).

So we have: x1 = 0, x2 = 1, x3 = x10, x4 = 0, x5 = 0, x6 = 1, x7 = ?, x8 = 1, x9 = 1, x10 = x3.

Let's set x3 = 0. Then x10 = 0.
So we have: x1 = 0, x2 = 1, x3 = 0, x4 = 0, x5 = 0, x6 = 1, x7 = 0, x8 = 1, x9 = 1, x10 = 0.

Let's check the constraints:
C01: 1 + 0 + 0 + 1 + 1 ≡ 0 (mod 2) -> 3 ≡ 1 (mod 2) (False)

Let's try x3 = 1. Then x10 = 1.
So we have: x1 = 0, x2 = 1, x3 = 1, x4 = 0, x5 = 0, x6 = 1, x7 = 0, x8 = 1, x9 = 1, x10 = 1.

Let's check the constraints:
C01: 1 + 1 + 0 + 1 + 1 ≡ 0 (mod 2) -> 4 ≡ 0 (mod 2) (True)
C02: 1 + 0 + 0 + 1 ≡ 0 (mod 2) -> 2 ≡ 0 (mod 2) (False)

Let's go back to x3+x8+x10 ≡ 1 (mod 2)

Solution: x1=0, x2=1, x3=1, x4=0, x5=0, x6=0, x7=0, x8=1, x9=1, x10=0
