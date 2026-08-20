## Round 001 — worker

Let's analyze the constraints and try to find a valid assignment of variables.

C10: x1 + x2 + x5 ≡ 1 (mod 2)
C08: x1 + x5 + x6 ≡ 0 (mod 2)
Combining these, we get: (x1 + x2 + x5) - (x1 + x5 + x6) ≡ 1 - 0 (mod 2), which simplifies to x2 - x6 ≡ 1 (mod 2). So, x2 ⊕ x6 ≡ 1 (mod 2).

C05: x5 + x7 + x8 + x10 ≡ 0 (mod 2)
C04: x3 + x5 + x8 ≡ 0 (mod 2)
Combining these, we get: (x5 + x7 + x8 + x10) - (x3 + x5 + x8) ≡ 0 - 0 (mod 2), which simplifies to x7 + x10 ≡ x3 (mod 2). So, x3 ≡ x7 + x10 (mod 2).

C01: x1 + x5 + x9 ≡ 1 (mod 2)
C02: x2 + x5 + x6 + x7 + x8 + x9 + x10 ≡ 0 (mod 2)
C03: x1 + x4 + x5 + x6 + x9 + x10 ≡ 1 (mod 2)
C07: x1 + x2 + x3 + x4 + x5 + x6 + x8 ≡ 1 (mod 2)

Let's set x1 = 0.
From C01: 0 + x5 + x9 ≡ 1 (mod 2), so x5 + x9 ≡ 1 (mod 2).
From C10: 0 + x2 + x5 ≡ 1 (mod 2), so x2 + x5 ≡ 1 (mod 2).
From C08: 0 + x5 + x6 ≡ 0 (mod 2), so x5 + x6 ≡ 0 (mod 2). This implies x5 ⊕ x6 ≡ 0 (mod 2).
Since x2 ⊕ x6 ≡ 1 (mod 2), and x5 ⊕ x6 ≡ 0 (mod 2), we have x2 ≡ x5 (mod 2).
From C11: x5 + x6 + x7 ≡ 1 (mod 2). Since x5 + x6 ≡ 0 (mod 2), we get x7 ≡ 1 (mod 2).

Now, x7 = 1.
From C05: x5 + 1 + x8 + x10 ≡ 0 (mod 2), so x5 + x8 + x10 ≡ 1 (mod 2).
From C04: x3 + x5 + x8 ≡ 0 (mod 2), so x3 ≡ x5 + x8 (mod 2).
From C03: x1 + x4 + x5 + x6 + x9 + x10 ≡ 1 (mod 2), so x4 + x5 + x6 + x9 + x10 ≡ 1 (mod 2).
From C02: x2 + x5 + x6 + x7 + x8 + x9 + x10 ≡ 0 (mod 2), so x2 + x5 + x6 + 1 + x8 + x9 + x10 ≡ 0 (mod 2), which means x2 + x5 + x6 + x8 + x9 + x10 ≡ 1 (mod 2).

Let's set x2 = 1.
Since x2 ⊕ x6 ≡ 1 (mod 2), then x6 ≡ 0 (mod 2).
Since x5 + x6 ≡ 0 (mod 2), then x5 ≡ 0 (mod 2).
Since x2 + x5 ≡ 1 (mod 2), then 1 + 0 ≡ 1 (mod 2), which is consistent.
Since x5 + x9 ≡ 1 (mod 2), then 0 + x9 ≡ 1 (mod 2), so x9 ≡ 1 (mod 2).
Since x3 ≡ x7 + x10 (mod 2), then x3 ≡ 1 + x10 (mod 2).
Since x5 + x8 + x10 ≡ 1 (mod 2), then 0 + x8 + x10 ≡ 1 (mod 2), so x8 + x10 ≡ 1 (mod 2).
Since x2 + x5 + x6 + x8 + x9 + x10 ≡ 1 (mod 2), then 1 + 0 + 0 + x8 + 1 + x10 ≡ 1 (mod 2), so x8 + x10 ≡ 1 (mod 2), which is consistent.
Also, x4 + x5 + x6 + x9 + x10 ≡ 1 (mod 2), so x4 + 0 + 0 + 1 + x10 ≡ 1 (mod 2), so x4 + x10 ≡ 0 (mod 2).

If x4 = 0, then x10 ≡ 0 (mod 2).
If x8 = 0, then x10 ≡ 1 (mod 2). This is a contradiction.
If x8 = 1, then x10 ≡ 0 (mod 2).

Let's try x4=0, x10=0. Then x8=1.
x3 ≡ 1+0 ≡ 1 (mod 2).
Then x1=0, x2=1, x3=1, x4=0, x5=0, x6=0, x7=1, x8=1, x9=1, x10=0.
Let's check the constraints:
C01: 0 + 0 + 1 ≡ 1 (mod 2). True.
C02: 1 + 0 + 0 + 1 + 1 + 1 + 0 ≡ 0 (mod 2). True.
C03: 0 + 0 + 0 + 0 + 1 + 0 ≡ 1 (mod 2). True.
C04: 1 + 0 + 1 ≡ 0 (mod 2). True.
C05: 0 + 1 + 1 + 0 ≡ 0 (mod 2). True.
C06: 0 + 1 + 1 + 0 ≡ 0 (mod 2). True.
C07: 0 + 1 + 1 + 0 + 0 + 0 + 1 ≡ 1 (mod 2). True.
C08: 0 + 0 + 1 ≡ 0 (mod 2). True.
C09: 1 + 0 + 1 + 0 ≡ 0 (mod 2). True.
C10: 0 + 1 + 0 ≡ 1 (mod 2). True.
C11: 0 + 0 + 1 ≡ 1 (mod 2). True.

Solution: x1=0, x2=1, x3=1, x4=0, x5=0, x6=0, x7=1, x8=1, x9=1, x10=0
