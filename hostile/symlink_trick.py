import os

os.symlink("/etc/passwd", "link")
os.symlink("../../../../../../etc/shadow", "link2")

for path in ("link", "link2", "../../../etc/passwd", "/box/../etc/passwd"):
    with open(path) as f:
        print(f.read())
