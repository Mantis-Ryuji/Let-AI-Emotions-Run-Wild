## Round 001 — worker

Let's analyze the constraints to find a possible solution.
C01: x3 + x5 + x6 + x9 + x10 ≡ 0 (mod 2)
C02: x1 + x3 + x4 + x7 + x9 + x10 ≡ 1 (mod 2)
C03: x1 + x2 + x4 + x5 + x7 + x9 + x10 ≡ 0 (mod 2)
C04: x2 + x6 + x9 ≡ 1 (mod 2)
C05: x1 + x4 + x6 ≡ 0 (mod 2)
C06: x1 + x2 + x3 + x4 + x7 + x8 + x9 ≡ 1 (mod 2)
C07: x3 + x5 + x6 + x7 + x9 + x10 ≡ 0 (mod 2)
C08: x2 + x7 + x9 + x10 ≡ 1 (mod 2)
C09: x1 + x3 + x5 + x7 + x9 + x10 ≡ 0 (mod 2)
C10: x1 + x4 + x6 + x7 + x8 + x9 + x10 ≡ 0 (mod 2)
C11: x2 + x3 + x8 + x10 ≡ 1 (mod 2)

Let's start by assigning some initial values and checking the constraints. Let's try x1 = 0.
If x1 = 0, then from C02: x3 + x4 + x7 + x9 + x10 ≡ 1 (mod 2).
From C05: x4 + x6 ≡ 0 (mod 2), so x4 ≡ x6 (mod 2).
From C03: 0 + x2 + x4 + x5 + x7 + x9 + x10 ≡ 0 (mod 2), so x2 + x4 + x5 + x7 + x9 + x10 ≡ 0 (mod 2).
From C04: x2 + x6 + x9 ≡ 1 (mod 2). Since x4 ≡ x6 (mod 2), x2 + x4 + x9 ≡ 1 (mod 2).

Let's set x1 = 0, x2 = 1.
Then from C03, 1 + x4 + x5 + x7 + x9 + x10 ≡ 0 (mod 2), so x4 + x5 + x7 + x9 + x10 ≡ 1 (mod 2).
From C04, 1 + x6 + x9 ≡ 1 (mod 2), so x6 + x9 ≡ 0 (mod 2), which means x6 ≡ x9 (mod 2).
From C05, 0 + x4 + x6 ≡ 0 (mod 2), so x4 + x6 ≡ 0 (mod 2), which implies x4 ≡ x6 (mod 2).
From C06, 0 + 1 + x3 + x4 + x7 + x8 + x9 ≡ 1 (mod 2), so x3 + x4 + x7 + x8 + x9 ≡ 0 (mod 2).
From C07, x3 + x5 + x6 + x7 + x9 + x10 ≡ 0 (mod 2).
From C08, 1 + x7 + x9 + x10 ≡ 1 (mod 2), so x7 + x9 + x10 ≡ 0 (mod 2).
From C09, 0 + x3 + x5 + x7 + x9 + x10 ≡ 0 (mod 2), so x3 + x5 + x7 + x9 + x10 ≡ 0 (mod 2).
From C10, 0 + x4 + x6 + x7 + x8 + x9 + x10 ≡ 0 (mod 2), so x4 + x6 + x7 + x8 + x9 + x10 ≡ 0 (mod 2).
From C11, 1 + x3 + x8 + x10 ≡ 1 (mod 2), so x3 + x8 + x10 ≡ 0 (mod 2).

If x6 = x9 = 0, then x4 ≡ 0 (mod 2), so x4 = 0.
From C04, x2 + x6 + x9 ≡ 1 (mod 2), so 1 + 0 + 0 ≡ 1 (mod 2), which is true.
From C03, 0 + x2 + 0 + x5 + x7 + x9 + x10 ≡ 0 (mod 2), so x2 + x5 + x7 + x10 ≡ 0 (mod 2), so 1 + x5 + x7 + x10 ≡ 0 (mod 2), which means x5 + x7 + x10 ≡ 1 (mod 2).
From C07, x3 + x5 + 0 + x7 + 0 + x10 ≡ 0 (mod 2), so x3 + x5 + x7 + x10 ≡ 0 (mod 2).
Since x5 + x7 + x10 ≡ 1 (mod 2), then x3 ≡ 1 (mod 2), so x3 = 1.
From C06, 0 + 1 + 1 + 0 + x7 + x8 + 0 ≡ 1 (mod 2), so x7 + x8 ≡ 0 (mod 2), so x7 ≡ x8 (mod 2).
From C08, 1 + x7 + x9 + x10 ≡ 1 (mod 2), so x7 + x9 + x10 ≡ 0 (mod 2).
From C09, 0 + 1 + x5 + x7 + x9 + x10 ≡ 0 (mod 2), so x5 + x7 + x9 + x10 ≡ 1 (mod 2).
From C10, 0 + 0 + 0 + x7 + x8 + x9 + x10 ≡ 0 (mod 2), so x7 + x8 + x9 + x10 ≡ 0 (mod 2).
From C11, 1 + 1 + x8 + x10 ≡ 1 (mod 2), so x8 + x10 ≡ 1 (mod 2).

Let x7 = 0, then x8 = 0.
Then x7 + x9 + x10 ≡ 0 (mod 2) means 0 + x9 + x10 ≡ 0 (mod 2), so x9 + x10 ≡ 0 (mod 2).
Also x8 + x10 ≡ 1 (mod 2) means 0 + x10 ≡ 1 (mod 2), so x10 ≡ 1 (mod 2).
Since x9 + x10 ≡ 0 (mod 2), x9 ≡ 1 (mod 2).
Now, x5 + x7 + x10 ≡ 1 (mod 2) means x5 + 0 + 1 ≡ 1 (mod 2), so x5 ≡ 0 (mod 2).
x3 + x5 + x7 + x10 ≡ 0 (mod 2) means x3 + 0 + 0 + 1 ≡ 0 (mod 2), so x3 ≡ 1 (mod 2), which is consistent.
x4 ≡ 0 (mod 2), so x4 = 0.
x6 ≡ x9 (mod 2) means x6 ≡ 1 (mod 2), so x6 = 1.

So x1 = 0, x2 = 1, x3 = 1, x4 = 0, x5 = 0, x6 = 1, x7 = 0, x8 = 0, x9 = 1, x10 = 1.

Solution: x1=0, x2=1, x3=1, x4=0, x5=0, x6=1, x7=0, x8=0, x9=1, x10=1
