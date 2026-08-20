## Round 001 — worker

Let's analyze the constraints to deduce the values of the variables.

C03: x1 + x8 + x9 ≡ 0 (mod 2)
C07: x1 + x2 + x3 + x9 ≡ 1 (mod 2)
C11: x1 + x2 + x6 + x7 + x10 ≡ 1 (mod 2)

From C03, we have x1 ≡ 0, x8 ≡ 0, x9 ≡ 0 (mod 2) or x1 ≡ 1, x8 ≡ 1, x9 ≡ 1 (mod 2).

Let's assume x1 = 0, x8 = 0, x9 = 0.
C01: 0 + x4 + x7 + 0 + 0 + x10 ≡ 0 (mod 2)  => x4 + x7 + x10 ≡ 0 (mod 2)
C02: 0 + x2 + x5 + x6 + 0 + 0 ≡ 1 (mod 2) => x2 + x5 + x6 ≡ 1 (mod 2)
C04: x2 + x3 + x4 + x5 + 0 ≡ 0 (mod 2) => x2 + x3 + x4 + x5 ≡ 0 (mod 2)
C05: x2 + x3 + x5 + x6 + 0 + 0 + x10 ≡ 0 (mod 2) => x2 + x3 + x5 + x6 + x10 ≡ 0 (mod 2)
C06: x3 + x5 + x9 + x10 ≡ 1 (mod 2) => x3 + x5 + 0 + x10 ≡ 1 (mod 2) => x3 + x5 + x10 ≡ 1 (mod 2)
C08: 0 + x3 + x5 + x6 + x7 + 0 ≡ 0 (mod 2) => x3 + x5 + x6 + x7 ≡ 0 (mod 2)
C09: 0 + x2 + x6 + x7 + 0 + 0 ≡ 1 (mod 2) => x2 + x6 + x7 ≡ 1 (mod 2)

Let's try x1=0, x2=1, x3=0, x4=0, x5=1, x6=0, x7=0, x8=0, x9=0, x10=0.
C01: 0 + 0 + 0 + 0 + 0 + 0 ≡ 0 (mod 2) - True
C02: 0 + 1 + 1 + 0 + 0 ≡ 1 (mod 2) - True
C03: 0 + 0 + 0 ≡ 0 (mod 2) - True
C04: 1 + 0 + 0 + 1 + 0 ≡ 0 (mod 2) - True
C05: 1 + 0 + 1 + 0 + 0 + 0 ≡ 0 (mod 2) - True
C06: 0 + 1 + 0 + 0 ≡ 1 (mod 2) - True
C07: 0 + 1 + 0 + 0 ≡ 1 (mod 2) - True
C08: 0 + 0 + 1 + 0 + 0 ≡ 0 (mod 2) - True
C09: 0 + 1 + 0 + 0 ≡ 1 (mod 2) - True
C10: 1 + 0 + 0 + 0 ≡ 1 (mod 2) - True
C11: 0 + 1 + 0 + 0 + 0 ≡ 1 (mod 2) - True

Solution: x1=0, x2=1, x3=0, x4=0, x5=1, x6=0, x7=0, x8=0, x9=0, x10=0
