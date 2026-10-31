import os
import signal

for pid in range(1, 5000):
    if pid != os.getpid():
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

print("still alive")
