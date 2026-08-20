## Round 001 — worker

Let's analyze the constraints and try to find a consistent assignment of variables.

C01: x4 + x5 + x8 + x10 ≡ 1 (mod 2)
C02: x1 + x5 + x8 + x9 + x10 ≡ 1 (mod 2)
C03: x1 + x2 + x5 + x6 + x7 + x8 + x10 ≡ 1 (mod 2)
C04: x4 + x5 + x8 + x9 + x10 ≡ 1 (mod 2)
C05: x2 + x3 + x4 + x5 + x6 + x9 + x10 ≡ 1 (mod 2)
C06: x2 + x4 + x5 + x10 ≡ 0 (mod 2)
C07: x2 + x4 + x6 + x7 + x8 + x9 + x10 ≡ 0 (mod 2)
C08: x2 + x3 + x7 + x9 ≡ 0 (mod 2)
C09: x1 + x3 + x6 + x7 + x8 + x9 + x10 ≡ 1 (mod 2)
C10: x1 + x4 + x5 + x6 + x9 ≡ 1 (mod 2)
C11: x1 + x2 + x3 + x6 + x7 ≡ 1 (mod 2)

From C01 and C04, we have: x4 + x5 + x8 + x10 ≡ 1 (mod 2) and x4 + x5 + x8 + x9 + x10 ≡ 1 (mod 2).  Subtracting the first equation from the second gives: x9 ≡ 0 (mod 2), so x9 = 0.

Now let's consider C02 with x9 = 0: x1 + x5 + x8 + 0 + x10 ≡ 1 (mod 2)  => x1 + x5 + x8 + x10 ≡ 1 (mod 2).

C06: x2 + x4 + x5 + x10 ≡ 0 (mod 2)

C07: x2 + x4 + x6 + x7 + x8 + x9 + x10 ≡ 0 (mod 2) => x2 + x4 + x6 + x7 + x8 + 0 + x10 ≡ 0 (mod 2) => x2 + x4 + x6 + x7 + x8 + x10 ≡ 0 (mod 2)

Let's set x1 = 0. Then C02 becomes: 0 + x5 + x8 + x10 ≡ 1 (mod 2), so x5 + x8 + x10 ≡ 1 (mod 2).
C01 becomes: x4 + x5 + x8 + x10 ≡ 1 (mod 2).

If we set x2 = 1, then C05 becomes: 1 + x3 + x4 + x5 + x6 + x9 + x10 ≡ 1 (mod 2) => x3 + x4 + x5 + x6 + x10 ≡ 0 (mod 2).
C08 becomes: 1 + x3 + x7 + x9 ≡ 0 (mod 2) => 1 + x3 + x7 + 0 ≡ 0 (mod 2) => x3 + x7 ≡ 1 (mod 2).

Since x9 = 0, C03 becomes: x1 + x2 + x5 + x6 + x7 + x8 + x10 ≡ 1 (mod 2) => 0 + 1 + x5 + x6 + x7 + x8 + x10 ≡ 1 (mod 2) => x5 + x6 + x7 + x8 + x10 ≡ 0 (mod 2).

Let's assume x5 = 0. Then x8 + x10 ≡ 1 (mod 2) and x6 + x7 + x8 + x10 ≡ 0 (mod 2).
Also, x2 + x4 + x5 + x10 ≡ 0 (mod 2) => 1 + x4 + 0 + x10 ≡ 0 (mod 2) => x4 + x10 ≡ 1 (mod 2).

If x4 = 1, then x10 ≡ 0 (mod 2). From x8 + x10 ≡ 1 (mod 2), we have x8 ≡ 1 (mod 2).
From x6 + x7 + x8 + x10 ≡ 0 (mod 2), we have x6 + x7 + 1 + 0 ≡ 0 (mod 2) => x6 + x7 ≡ 1 (mod 2).
Finally, x3 + x7 ≡ 1 (mod 2).

Let's try x3 = 0. Then x7 ≡ 1 (mod 2).
Now, let's check if this satisfies all constraints.
x1=0, x2=1, x3=0, x4=1, x5=0, x6=1, x7=1, x8=1, x9=0, x10=0

C01: 1 + 0 + 1 + 0 ≡ 1 (mod 2) - True
C02: 0 + 0 + 1 + 0 + 0 ≡ 1 (mod 2) - True
C03: 0 + 1 + 0 + 1 + 1 + 1 + 0 ≡ 1 (mod 2) - True
C04: 1 + 0 + 1 + 0 + 0 ≡ 1 (mod 2) - True
C05: 1 + 0 + 1 + 0 + 1 + 0 + 0 ≡ 1 (mod 2) - True
C06: 1 + 1 + 0 + 0 ≡ 0 (mod 2) - True
C07: 1 + 1 + 1 + 1 + 1 + 0 + 0 ≡ 0 (mod 2) - True
C08: 1 + 0 + 1 + 0 ≡ 0 (mod 2) - True
C09: 0 + 0 + 1 + 1 + 1 + 0 + 0 ≡ 1 (mod 2) - True
C10: 0 + 1 + 0 + 1 + 0 ≡ 1 (mod 2) - True
C11: 0 + 1 + 0 + 1 + 1 ≡ 1 (mod 2) - True

Solution: x1=0, x2=1, x3=0, x4=1, x5=0, x6=1, x7=1, x8=1, x9=0, x10=0
