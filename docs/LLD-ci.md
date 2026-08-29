# LLD — CI infrastructure

> **Status: design for infrastructure still to be built.** The ownership
> boundary and the existing shared doubles are current. The workflow,
> development dependency group, and isolated real-Redis job described below
> are the intended implementation.

## 1. Purpose and ownership

CI is the cross-cutting harness in which lane-owned checks run. The `testbed`
lane owns:

- `.github/workflows/` and the commands, service containers, caches, and
  artifacts declared there;
- the test/development dependency declaration in `pyproject.toml`;
- shared fixtures and service doubles in `tests/conftest.py`; and
- harnesses that start or connect to real services for integration tests.

It does **not** own every test merely because CI executes it. A lane owns the
tests of its module (`bus` owns `tests/test_bus.py`, `api` owns
`tests/test_api.py`, and so on), including the assertions and cases that define
that module's behaviour. Testbed owns changes to the common machinery those
files import. A change that needs both is coordinated across the two owners
rather than silently moving the module test into the infrastructure lane.

Container acceptance remains a separate, explicit gate. `container/accept.sh`
has host capacity, browser, credential, and teardown requirements documented in
`BUILD-CONVENTION.md`; an ordinary GitHub-hosted unit-test job must not imply
that those checks ran.

## 2. Workflow contract

The workflow runs on pull requests targeting `main`, pushes to `main`, and
manual dispatch. Pull requests are the pre-merge gate; the `main` run detects
merge-only/environment drift; manual dispatch permits diagnosis without
inventing a commit. There is deliberately no path filter: source, tests,
packaging, shell/container code, and documentation can all contain executable
contracts or alter the test collector, so a path allow-list can manufacture a
green result by skipping the workflow.

The workflow has two required jobs:

1. **Unit** uses the repository's minimum supported Python, currently 3.12,
   installs the package with its `dev` extra, and runs the normal pytest suite
   with real-service tests excluded by marker. One minimum-version job is the
   initial contract; a Python matrix is added only when the project supports
   more than one Python minor and each entry answers a compatibility question.
2. **Redis integration** runs only tests marked `redis_integration`, backed by
   a pinned Redis service-container major version. It waits for `PING`, passes
   an explicit test-only URL, and never falls back to `FakeRedis` or silently
   skips when Redis is absent. Keys use a unique per-test namespace and cleanup
   is scoped to that namespace/database.

Jobs get least-privilege read access to repository contents, use concurrency
cancellation for superseded runs on the same pull request or branch, and have
timeouts so a wedged service cannot occupy a runner indefinitely. Dependency
caching may key from `pyproject.toml`, but cache hits are an optimization only:
a cold runner must install and pass from declarations committed in this repo.

The real-service job is separate because its failure domain and diagnostics
differ from pure in-process tests. Both jobs remain required: combining them
would let a Redis startup failure obscure unit results, while running only the
fake-backed suite would not execute Redis semantics.

## 3. Development dependencies

`pyproject.toml` will declare a `dev` optional-dependency group containing the
test runner and plugins imported by the suite:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8,<9",
    "pytest-asyncio>=0.24,<1",
    "pyyaml>=6,<7",
]
```

CI and fresh contributors install with `python -m pip install -e '.[dev]'`.
Runtime libraries remain in `project.dependencies`; a library imported only by
tests or test tooling belongs in `dev`. The group is the single declaration for
local and CI test prerequisites—workflow-only ad-hoc `pip install pytest ...`
commands are prohibited because they recreate the current “works on an already
provisioned agent” failure on every clean environment.

Version floors record the API level the tests rely on and upper bounds prevent
an unrelated future major from silently changing the gate. Updating a bound is
an explicit dependency change, tested on a cold install.

## 4. Shared Redis doubles

`tests/conftest.py` models the production split described in
`LLD-bus-and-switch.md`:

- `FakeRespRedis` models the exact 24-command surface of the hand-rolled
  `flock.bus.resp.Redis` client used by short-lived CLI and port processes.
  Keeping this surface strict catches tests that accidentally give a transient
  process a redis-py-only capability.
- `FakeRedis` extends `FakeRespRedis` with the operations used by long-lived
  redis-py daemons, including pipelines, list inspection/trimming, sets,
  scans, and service-oriented helpers.

The split is a performance boundary, not naming ceremony. Importing redis-py
costs roughly 700 ms in the short-lived path, comparable to the measured
659–911 ms port-kick budget. The dependency-free RESP2 client avoids paying
that process-start cost; its fake must therefore remain independently usable
without importing or growing toward the full daemon interface.

Shared fake state is in-memory and deterministic. Fixtures return a new
instance per test; fault-injection hooks record calls and raise at named or
numbered operations. Add a fake operation only when the corresponding
production client exposes it, and test the fake's state transition directly.
Aliases such as `WatchRedis` and `UsageRedis` may describe a consumer, but they
remain aliases of one common implementation and must not suggest stronger
service fidelity than exists.

### 4.1 The `eval()` boundary

The current fake does not execute Lua. Its `eval()` recognizes known scripts
through source substrings and argument shapes, then performs a Python
approximation of their effects. This is useful for fast caller tests and for
injecting failures, but it cannot prove Lua syntax, Redis command arity/type
rules, return encoding, script atomicity, or concurrent claim behaviour.
Substring matching is therefore a declared double implementation detail, never
evidence that a Lua script works on Redis.

New production Lua must have both kinds of coverage: fake-backed lane tests for
caller branches and one infrastructure-owned real-service contract for Redis
semantics. The fake handler should carry the script's stable identifying
comment where one exists; a generic catch-all must not turn unknown Lua into a
successful result.

## 5. Atomic usage-emission integration contract

`flock.watchdog.activity._EMIT_USAGE_LUA` atomically checks a request claim,
appends a usage record to a stream, claims the request ID, and records an
attributed delivery marker. `tests/conftest.py` currently approximates this by
searching for `SISMEMBER`, `XADD`, and `SADD`. The authoritative integration
test executes the production script through redis-py against the Redis service
used by the dedicated job.

The test proves at least:

- the first invocation returns `1`, appends exactly one decodable usage record,
  claims the request ID, and claims the attribution ID;
- replay of the same request returns `0` and leaves stream/set cardinalities
  unchanged, including after constructing a new `ActivityTailer` to remove its
  in-memory cache from the proof;
- empty optional request/attribution IDs still emit without creating claims;
- concurrent invocations with one request ID produce exactly one stream entry
  and one successful return, which is the atomicity claim the Python fake
  cannot establish; and
- Redis errors fail the integration job rather than selecting the fake or a
  non-atomic fallback.

The existing real-Redis test starts its own `redis-server` on a discovered local
port and proves first-emission/replay behaviour. It should move behind the
`redis_integration` marker and shared real-service fixture, then gain the empty-ID
and concurrency controls above. In CI the service container is the lifecycle
owner; locally the fixture may spawn `redis-server` in a temporary directory,
but missing Redis is a hard failure when the integration marker is selected.
The fixture must wait on `PING`, yield only after readiness, terminate what it
started, and surface captured server output on startup or teardown failure.

Per `BUILD-CONVENTION.md` §1, this gate is accepted only after a negative
control: temporarily make the Lua invalid or remove its `XADD`, demonstrate the
real-service job fails for the intended assertion, then restore the production
script. Making only the fake reject the mutation is not evidence for this gate.

## 6. Change rules

- A workflow or dependency change updates this document in the same branch
  when it changes the contract above.
- Every newly required job or integration assertion gets the demonstrated-red
  control required by `BUILD-CONVENTION.md` §1.
- Tests that need network credentials or paid/external APIs are not added to
  the default workflow by implication; their trust boundary and trigger require
  an explicit design decision.
- CI must report skipped or uncollected required integration tests as failure.
  A green job means its named gate ran, not merely that pytest exited zero.

