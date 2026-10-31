import sys

WRONG = 1

with open(sys.argv[1]) as f:
    n, target = map(int, f.readline().split())
    values = list(map(int, f.readline().split()))

with open(sys.argv[2]) as f:
    tokens = f.read().split()

try:
    i, j = map(int, tokens)
except ValueError:
    sys.exit(WRONG)

if not (1 <= i <= n and 1 <= j <= n) or i == j:
    sys.exit(WRONG)
if values[i - 1] + values[j - 1] != target:
    sys.exit(WRONG)
