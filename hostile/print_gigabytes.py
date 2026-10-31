import sys

line = "x" * 1024 * 1024
while True:
    sys.stdout.write(line)
