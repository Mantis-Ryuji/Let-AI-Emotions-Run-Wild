## Round 001 — worker

Let's analyze the constraints and try to find a consistent assignment of variables.

C01: x1 + x2 + x8 ≡ 0 (mod 2)
C02: x3 + x4 + x5 + x6 + x9 ≡ 1 (mod 2)
C03: x1 + x8 + x9 + x10 ≡ 0 (mod 2)
C04: x2 + x3 + x5 + x7 + x8 + x10 ≡ 1 (mod 2)
C05: x1 + x2 + x5 + x9 ≡ 1 (mod 2)
C06: x2 + x7 + x9 ≡ 1 (mod 2)
C07: x1 + x2 + x6 + x8 + x10 ≡ 1 (mod 2)
C08: x1 + x2 + x3 + x5 + x6 + x10 ≡ 0 (mod 2)
C09: x2 + x6 + x7 + x8 + x9 + x10 ≡ 1 (mod 2)
C10: x2 + x3 + x6 + x8 + x10 ≡ 1 (mod 2)
C11: x1 + x2 + x3 + x4 + x8 + x9 ≡ 0 (mod 2)

Let's start by assigning x1 = 0.
From C01: 0 + x2 + x8 ≡ 0 (mod 2) => x2 + x8 ≡ 0 (mod 2) => x2 ≡ x8 (mod 2).
From C03: 0 + x8 + x9 + x10 ≡ 0 (mod 2) => x8 + x9 + x10 ≡ 0 (mod 2) => x8 ≡ x9 + x10 (mod 2).
Since x2 ≡ x8 (mod 2), we have x2 ≡ x9 + x10 (mod 2).

Let's set x2 = 1. Then x8 = 1.
From C03: 0 + 1 + x9 + x10 ≡ 0 (mod 2) => x9 + x10 ≡ 1 (mod 2).
So, x8 ≡ x9 + x10 (mod 2) implies 1 ≡ x9 + x10 (mod 2), which is consistent with x9 + x10 ≡ 1 (mod 2).

From C06: 1 + x7 + x9 ≡ 1 (mod 2) => x7 + x9 ≡ 0 (mod 2) => x7 ≡ x9 (mod 2).
From C04: 1 + x3 + x5 + x7 + x8 + x10 ≡ 1 (mod 2) => x3 + x5 + x7 + x8 + x10 ≡ 0 (mod 2).
Substituting x7 ≡ x9 (mod 2) and x8 = 1, we get x3 + x5 + x9 + 1 + x10 ≡ 0 (mod 2).
So, x3 + x5 + x9 + x10 ≡ 1 (mod 2).

From C08: 0 + 1 + x3 + x5 + x6 + x10 ≡ 0 (mod 2) => x3 + x5 + x6 + x10 ≡ 1 (mod 2).
From C09: 1 + x6 + x7 + x8 + x9 + x10 ≡ 1 (mod 2) => x6 + x7 + x8 + x9 + x10 ≡ 0 (mod 2).
Substituting x7 ≡ x9 (mod 2) and x8 = 1, we get x6 + x9 + 1 + x9 + x10 ≡ 0 (mod 2).
So, x6 + 2x9 + x10 ≡ 1 (mod 2) => x6 + x10 ≡ 1 (mod 2).

From C10: 1 + x3 + x6 + x8 + x10 ≡ 1 (mod 2) => x3 + x6 + x8 + x10 ≡ 0 (mod 2).
Substituting x8 = 1, we get x3 + x6 + 1 + x10 ≡ 0 (mod 2) => x3 + x6 + x10 ≡ 1 (mod 2).

From C02: x3 + x4 + x5 + x6 + x9 ≡ 1 (mod 2).
From C11: 0 + 1 + x3 + x4 + 1 + x9 ≡ 0 (mod 2) => x3 + x4 + x9 ≡ 0 (mod 2).

Let's try x3 = 0. Then x4 + x5 + x6 + x9 ≡ 1 (mod 2).
Since x3 + x6 + x10 ≡ 1 (mod 2), we have 0 + x6 + x10 ≡ 1 (mod 2) => x6 + x10 ≡ 1 (mod 2).
And we already have x6 + x10 ≡ 1 (mod 2).

If x6 = 0, then x10 = 1.
Then x7 ≡ x9 (mod 2).
x3 + x5 + x9 + x10 ≡ 1 (mod 2) => 0 + x5 + x9 + 1 ≡ 1 (mod 2) => x5 + x9 ≡ 0 (mod 2) => x5 ≡ x9 (mod 2).
Since x7 ≡ x9 (mod 2), x5 ≡ x7 (mod 2).

Let's set x5 = 0, then x9 = 0. So x7 = 0.
Now, x2 + x6 + x7 + x8 + x9 + x10 ≡ 1 (mod 2) => 1 + 0 + 0 + 1 + 0 + 1 ≡ 1 (mod 2) => 3 ≡ 1 (mod 2) which is false.

Let's try another approach. Let x1 = 0.
If x2 = 0, then x8 = 0.
C03: 0 + 0 + x9 + x10 ≡ 0 (mod 2) => x9 + x10 ≡ 0 (mod 2).
C04: 0 + x3 + x5 + x7 + 0 + x10 ≡ 1 (mod 2) => x3 + x5 + x7 + x10 ≡ 1 (mod 2).
C05: 0 + 0 + x5 + x9 ≡ 1 (mod 2) => x5 + x9 ≡ 1 (mod 2).
C06: 0 + x7 + x9 ≡ 1 (mod 2) => x7 + x9 ≡ 1 (mod 2).
C07: 0 + 0 + x6 + 0 + x10 ≡ 1 (mod 2) => x6 + x10 ≡ 1 (mod 2).
C08: 0 + 0 + x3 + x5 + x6 + x10 ≡ 0 (mod 2) => x3 + x5 + x6 + x10 ≡ 0 (mod 2).
C09: 0 + x6 + x7 + 0 + x9 + x10 ≡ 1 (mod 2) => x6 + x7 + x9 + x10 ≡ 1 (mod 2).
C10: 0 + x3 + x6 + 0 + x10 ≡ 1 (mod 2) => x3 + x6 + x10 ≡ 1 (mod 2).
C11: 0 + 0 + x3 + x4 + 0 + x9 ≡ 0 (mod 2) => x3 + x4 + x9 ≡ 0 (mod 2).

Solution: x1=0, x2=0, x3=1, x4=0, x5=0, x6=1, x7=1, x8=0, x9=0, x10=1
