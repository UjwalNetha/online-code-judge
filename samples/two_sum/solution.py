n, target = map(int, input().split())
values = list(map(int, input().split()))

seen = {}
for position, value in enumerate(values, start=1):
    if target - value in seen:
        print(seen[target - value], position)
        break
    seen[value] = position
