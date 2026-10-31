# Online Code Judge

A small LeetCode style backend. Users submit Python or C++ code, and the system runs it against hidden tests inside a sandbox and returns a verdict.

## Architecture

```
  client
    |
    v
 +-------+        +------------+        +----------------------+
 |  API  | -----> | PostgreSQL | <----- | worker (many)        |
 +-------+        |            |        |   claims submissions |
 FastAPI + JWT    | submissions|        |   sends heartbeats   |
                  | is the     |        +----------+-----------+
                  | job queue  |                   |
                  +------------+                   | one per test
                                                   v
                                        +----------------------+
                                        | sandbox              |
                                        |   launcher.py        |
                                        |    -> init (pid 1)   |
                                        |        -> program    |
                                        +----------------------+
```

The API only writes to the database and returns 202. Workers pick up the work from there. The API and the workers never talk to each other directly.

## Folder layout

- `judge/api` has the HTTP routes.
- `judge/models.py` has the database tables.
- `judge/queue.py` has claiming, heartbeats, re-queueing and rejudging.
- `judge/worker.py` is the worker process.
- `judge/sandbox` has the sandbox. `launcher.py` runs inside it and `runner.py` starts it.
- `judge/compiler.py` compiles C++.
- `judge/judging.py` runs the tests and picks the verdict.
- `judge/checker.py` has the exact, token, float and custom checkers.
- `judge/scoring.py` has the group scoring.
- `judge/contests.py` has the leaderboard.
- `samples` has three problems with reference solutions in Python and C++.
- `hostile` has the malicious submissions.
- `tests` has the pytest suite.

## How the sandbox works

I chose Linux namespaces, rlimits and seccomp instead of starting a Docker container for each run. A worker that starts containers needs the Docker socket, and that socket is the same as root on the host. Starting a container for every test is also slow. This way the worker needs no Docker socket and no root, and each test starts much faster. The one exception is explained under Worker container.

For every run, the worker starts `launcher.py`, which does the following:

1. Creates new user, PID, network, mount, IPC and UTS namespaces. The worker's user is mapped to uid 65534 inside.
2. Builds a new root on a small tmpfs. It only has `/usr`, `/bin`, `/lib` and similar folders mounted read-only, plus `/dev/null`, `/dev/zero` and `/dev/urandom`.
3. Calls `pivot_root` and detaches the old root, so the real filesystem can't be reached at all. There is no `/etc`, `/proc`, `/sys`, `/tmp` or `/app`.
4. Makes the working directory `/box`, a small tmpfs that disappears after the run. The program itself is in `/code`, which is read-only.
5. Sets the rlimits, sets no_new_privs and installs a seccomp filter, then starts the program with a clean environment.

The network namespace has no interfaces, so there is no network. The seccomp filter also kills any process that calls `socket`, so there are two layers.

Stdin, stdout and stderr are files outside the sandbox, passed in as open file descriptors. Only the input of the current test is ever given to the program. Expected outputs never enter the sandbox.

The program runs as pid 2 and a small init process is pid 1. Init can't be killed from inside, and it holds the wall clock watchdog and collects the time and memory numbers with `wait4`. When init exits the kernel kills everything left in the namespace, even a process that used `setsid` to leave the process group. The worker also kills the whole process group as a backup.

C++ compilation runs in the same sandbox, so tricks like `#include "/etc/passwd"` fail too.

### Worker container

The worker runs as a non-root user with a read-only root filesystem, all capabilities dropped, no-new-privileges and no internet access, because it is only on an internal Docker network.

The worker container uses `seccomp=unconfined` and `apparmor=unconfined`, because Docker's default profiles block the calls needed to create namespaces. This is a real trade-off. Submissions still get our own stricter seccomp filter, but the worker process itself has a wider set of syscalls than a default container.

## Threat model

It protects against:

- Reading the judge's files, test data, environment variables or database password.
- Writing anywhere outside `/box`.
- Any network access.
- Fork bombs, memory bombs, infinite loops and huge output.
- Killing or looking at other processes, including other submissions.
- Filling the disk, because `/box` has a size limit.
- Symlink and `..` path tricks, because the files they point to don't exist in the new root.
- Leftover processes after a timeout.
- Creating new namespaces, ptrace, mounting, kernel modules, bpf, io_uring and 32-bit syscalls, which seccomp blocks.

It does not protect against:

- A bug in the Linux kernel. All sandboxes share the host kernel, so a kernel exploit in an allowed syscall could escape. A deny-list also allows any syscall not listed. A VM per run or gVisor would be stronger.
- Attacks on the CPU itself, like Spectre.
- A noisy neighbour. Submissions running at the same time share CPU, caches and memory bandwidth, so timings can change a little. Measuring CPU time instead of wall time reduces this.
- Total memory across processes. RLIMIT_AS is per process, so up to 32 processes could each use the limit. The container's 2 GB limit is the final cap. If the kernel OOM killer steps in, the run gets Memory Limit Exceeded. In a bad case it could hit the worker, and then the submission is re-queued.
- Information leaking through verdicts. A program can learn about hidden tests from its own verdicts, and this can't be fully prevented in any judge.

It only runs on x86_64 Linux, because seccomp filters use syscall numbers. On anything else it fails with Internal Error instead of running unprotected. The per-sandbox process limit needs kernel 5.14 or newer. It refuses to run as root.

## Limits

Per run:

- CPU time: the problem's time limit. The verdict uses measured CPU time, and RLIMIT_CPU kills the program about a second later.
- Wall clock: twice the time limit plus 1 second, enforced by a watchdog in init.
- Memory: the problem's memory limit. Peak RSS over the limit gives Memory Limit Exceeded. RLIMIT_AS is set to the limit plus 64 MB, because interpreters and libraries map memory they never use.
- Output: 16 MB, using RLIMIT_FSIZE. This also applies to files in `/box`.
- Processes and threads: 32, using RLIMIT_NPROC.
- Open files: 64, using RLIMIT_NOFILE.
- Stack: 64 MB.
- Working directory: 16 MB.
- Core dumps: off.

C++ compilation:

- 15 seconds of CPU time and 30 seconds of wall clock.
- 1 GB of memory and 64 MB per output file.
- Compiler messages are cut to 16 KB.

Custom checkers: 10 seconds of CPU time, 20 seconds of wall clock and 512 MB of memory.

API and workers:

- Source code: 64 KB.
- Submissions: 10 per minute per user.
- Sandboxes per worker: 2 by default, set with `MAX_SANDBOXES`.
- Heartbeat every 5 seconds. A submission is re-queued after 30 seconds without one.
- A submission that crashes workers 3 times ends as Internal Error.

## Verdicts and measurement

Verdicts are Accepted, Wrong Answer, Time Limit Exceeded, Memory Limit Exceeded, Runtime Error, Output Limit Exceeded, Compilation Error and Internal Error. Runtime Error results include the exit code or signal.

Time is the user plus system CPU time from `wait4`. Memory is `ru_maxrss` from `wait4`.

Things to know:

- If a run breaks more than one limit, the order is output, then memory, then time.
- On a busy machine or VM, measured CPU time can go up, so a program close to its time limit could get a different verdict on a rerun.
- `ru_maxrss` keeps the peak from before `exec`, so the size of the launcher, about 9.5 MB, is the lowest value you will see. Small programs all show about that. Values above it are exact.
- An allocation that fails under RLIMIT_AS shows up as a crash. We report Memory Limit Exceeded if stderr has `MemoryError` or `std::bad_alloc`. A C++ program that ignores a failed `malloc` and then crashes gets Runtime Error.
- A Python syntax error is a Runtime Error, because Python has no compile step here.

## Queue

Submissions are the queue. A worker claims one with `SELECT ... FOR UPDATE SKIP LOCKED` and then an update that checks the status is still queued, so two workers can't get the same one.

Fair scheduling: the claim picks from the user who was served longest ago. This gives round robin between users, so a user with 1000 queued submissions just gets one turn like everyone else.

Crash recovery: every claim gets a new lease token and the worker sends heartbeats. Any worker can re-queue a submission whose heartbeat has stopped. Saving a result needs the current lease, so a slow worker that was presumed dead can't overwrite a newer run.

Each worker runs `MAX_SANDBOXES` threads and each thread runs one sandbox, which is the concurrency cap.

## Scoring and contests

A test group pays its full score only if all its tests pass. `stop_on_first_fail` on a problem chooses between stopping at the first failure and running all tests.

Contests have a start time, an end time and a style. Pass `contest_id` in `POST /submissions` to enter one.

- `icpc`: a solved problem is worth 1. Rank is by problems solved, then by penalty.
- `score`: a problem is worth the user's best score. Rank is by total score, then by penalty.

The penalty for a problem is the minutes taken to reach that result, plus `penalty_minutes` for each wrong attempt before it. Compilation Error and Internal Error cost nothing. The leaderboard is worked out on each request, so it is always live and it follows rejudges.

## API

- `POST /auth/register`
- `POST /auth/login`
- `POST /problems` (admin)
- `GET /problems`
- `GET /problems/{id}`
- `PUT /problems/{id}/tests` (admin)
- `POST /problems/{id}/rejudge` (admin)
- `POST /submissions`
- `GET /submissions/{id}`
- `POST /submissions/{id}/rejudge` (admin)
- `POST /contests` (admin)
- `GET /contests/{id}`
- `GET /contests/{id}/leaderboard`

Swagger docs are at `/docs` when the API is running.

## Running it

You need Docker with Compose.

```bash
cp .env.example .env
```

Edit `.env` and set real passwords and a long `JWT_SECRET`. If port 8000 is in use, change `API_PORT`.

```bash
docker compose up -d --build
```

Create the admin user and load the sample problems:

```bash
docker compose exec api python seed.py
```

The API is now at http://localhost:8000.

## Running the tests

```bash
docker compose --profile test run --rm tests
```

```bash
docker compose --profile test down -v
```

The tests use their own temporary database. They run in the same locked down setup as the workers, because the sandbox needs Linux. On other systems the sandbox tests are skipped.
