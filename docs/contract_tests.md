# Contract test enumeration

Contract tests define what a backend must do to satisfy an oak Protocol.

This doc enumerates named tests for the v0.1 Protocols:

- `oak.workspace` - `Workspace` Protocol
- `oak.session` - `SessionStateStore`, `TraceSource`, and `LeaseManager` (internal) Protocols

Each test runs against any backend implementing the Protocol. A custom backend must pass the relevant suite to claim oak compatibility.

---

## `oak.workspace.tests.contract`

Run with: `pytest -m contract --backend my_module:MyWorkspaceClass`

The `--backend` arg points to a `module:class` that the suite instantiates via `cls.create(working_dir="/tmp/contract-test")` (or equivalent factory) for each test.

### Required tests (14)

```python
async def test_execute_simple_command(workspace):
    """Given a brand-new workspace, when execute('echo hi') is called,
    then exit_code == 0, stdout == 'hi\\n', stderr == '', timeout_occurred is False."""

async def test_execute_nonzero_exit(workspace):
    """Given a workspace, when execute('exit 7') is called,
    then exit_code == 7. No exception raised. Exit codes are not errors."""

async def test_execute_respects_timeout(workspace):
    """Given a workspace, when execute('sleep 10', timeout=0.5) is called,
    then WorkspaceTimeout is raised within 1.0s, carrying command='sleep 10' and timeout=0.5."""

async def test_execute_captures_stderr_independently(workspace):
    """Given a workspace, when execute('echo out; echo err >&2') is called,
    then stdout == 'out\\n' and stderr == 'err\\n'."""

async def test_upload_then_download_roundtrip(workspace):
    """Given a workspace, when upload(local_file, '/tmp/x') then download('/tmp/x', local_file2),
    then sha256(local_file) == sha256(local_file2)."""

async def test_upload_returns_file_size(workspace):
    """Given a workspace, when upload(file_with_123_bytes, '/tmp/x'),
    then result.success is True and result.file_size == 123."""

async def test_handle_is_serializable(workspace):
    """workspace.handle is a dict with str/int/bool values only (JSON-serializable).
    Contains NO secrets (no api_keys, no tokens)."""

async def test_reconnect_roundtrip(workspace):
    """Given supports_reconnect=True, when:
       1. ws1 = create(...); handle = ws1.handle
       2. ws1.execute('echo hi > /tmp/marker')
       3. ws1.pause()
       4. ws2 = reconnect(provider, handle)
       5. result = ws2.execute('cat /tmp/marker')
    then result.stdout == 'hi\\n' (filesystem state preserved).
    (Skipped if supports_reconnect=False.)"""

async def test_reconnect_after_termination_raises(workspace):
    """Given a terminated workspace's handle, when reconnect(handle) is called,
    then WorkspaceUnreachable is raised carrying handle + reason.
    (Skipped if supports_reconnect=False.)"""

async def test_pause_unsupported_raises(workspace):
    """Given supports_reconnect=False, when pause() is called,
    then CapabilityUnsupported is raised with capability='supports_reconnect'."""

async def test_snapshot_restore_roundtrip(workspace):
    """Given supports_snapshot=True, when execute('echo x > /tmp/y'), sid = snapshot(),
    execute('rm /tmp/y'), restore(sid), execute('cat /tmp/y'),
    then stdout == 'x\\n'. (Skipped if capability is False.)"""

async def test_terminate_is_idempotent(workspace):
    """Given a workspace, when terminate() is called twice,
    then the second call does NOT raise. Best-effort semantics."""

async def test_use_after_terminate_raises(workspace):
    """Given a terminated workspace, when execute('echo x') is called,
    then WorkspaceTerminated is raised."""

async def test_boot_emits_otel_span(workspace, span_collector):
    """When create() is called, then an OTel span named 'workspace.boot' is emitted
    with attributes: workspace.provider, workspace.handle (JSON-encoded), workspace.region (if applicable),
    workspace.image (if applicable). workspace.handle attribute MUST NOT contain secrets."""
```

### Optional asserts (warnings, not failures)

```python
async def test_concurrent_execute_isolated(workspace):
    """20 parallel execute() calls return without cross-contamination."""

async def test_cold_start_under_5s(workspace):
    """create() + first execute completes in <5s. Warn if slower."""

async def test_capabilities_match_methods(workspace):
    """For each method whose docstring says 'raises CapabilityUnsupported if X is False',
    verify the actual method raises that error when the capability is False."""
```

---

## `oak.session.tests.contract.state_store`

Run with: `pytest -m contract --backend my_module:MyStateStoreClass`

### Required tests (8)

```python
async def test_put_then_get_roundtrip(store):
    """Given store, when put('sess-1', 'workspace', {'provider': 'e2b', 'handle': 'sb-x'}),
    then get('sess-1', 'workspace') returns the same dict."""

async def test_get_missing_returns_none(store):
    """Given a fresh store, when get('sess-1', 'workspace') is called,
    then None is returned (no exception)."""

async def test_put_overwrites_existing(store):
    """Given put('sess-1', 'workspace', {'v': 1}), when put('sess-1', 'workspace', {'v': 2}),
    then get returns {'v': 2}."""

async def test_multiple_keys_per_session(store):
    """Given put('sess-1', 'workspace', {...}) and put('sess-1', 'pending_action', {...}),
    then both keys are independently gettable. delete_session removes both."""

async def test_session_isolation(store):
    """Given put('sess-1', 'workspace', ...) and put('sess-2', 'workspace', ...),
    each session's key reads back independently. delete_session('sess-1') leaves sess-2 intact."""

async def test_delete_session_clears_all_keys(store):
    """Given put('sess-1', 'workspace', ...) + put('sess-1', 'pending_action', ...),
    when delete_session('sess-1'), then get('sess-1', 'workspace') and ('sess-1', 'pending_action')
    both return None."""

async def test_delete_missing_session_is_noop(store):
    """delete_session('never-existed') does not raise."""

async def test_values_serializable(store):
    """Given a complex JSON-serializable dict (nested, lists, ints, strings),
    put + get roundtrips it losslessly."""
```

### Cross-process tests (durable backends only - Redis, Postgres, DynamoDB, etc.)

```python
async def test_cross_process_visibility(store, second_store_instance):
    """Process A puts; Process B (separate Python interpreter / second store instance)
    sees the same value via get()."""

async def test_survives_store_restart(store, restart_store):
    """Put a key, simulate store restart (reconnect), key is still readable."""
```

---

## `oak.session.tests.contract.trace_source`

Run with: `pytest -m contract --backend my_module:MyTraceSourceClass`

The `--backend` is instantiated with vendor-specific config via env vars or fixture.

### Required tests (6)

```python
async def test_fetch_empty_session_returns_empty(source):
    """For a session_id with no spans, fetch_session_spans returns []."""

async def test_fetch_returns_ordered_spans(source, populated_session):
    """For a populated session, returned spans are in start_time order."""

async def test_fetch_includes_gen_ai_attributes(source, populated_session):
    """Returned GenAISpan objects have gen_ai.* attributes per OTel semconv where applicable
    (gen_ai.system, gen_ai.request.model, gen_ai.input.messages, gen_ai.output.messages)."""

async def test_fetch_includes_workspace_boot_span(source, populated_session_with_workspace):
    """If the session had a workspace.boot span, it appears in the returned list
    with workspace.provider and workspace.handle attributes."""

async def test_fetch_handles_pagination(source, large_session):
    """For a session with 1000+ spans, fetch_session_spans returns all of them
    (auto-paginates internally)."""

async def test_fetch_raises_on_backend_error(source, broken_backend):
    """If the backend is unreachable / unauthorized, fetch_session_spans raises
    TraceSourceError (or a documented subclass) - does NOT silently return []."""
```

---

## `oak.session.tests.contract.lease`

Run with: `pytest -m contract --backend my_module:MyLeaseClass`

### Required tests (10)

```python
async def test_acquire_succeeds_when_unowned(lease):
    """Given no existing lease, when acquire('sess-1') is called,
    then a Lease is returned with owner set, generation == 1."""

async def test_acquire_raises_when_owned_by_other(lease, second_lease_instance):
    """Given lease A acquired 'sess-1', when lease B calls acquire('sess-1'),
    then LeaseHeld is raised. State unchanged for lease A."""

async def test_release_makes_session_acquirable_again(lease, second_lease_instance):
    """Given A acquires + releases 'sess-1', when B acquires 'sess-1',
    then acquire succeeds. Generation increments across the cycle."""

async def test_renew_extends_ttl(lease):
    """Given A acquires 'sess-1' with ttl=10s, when A renews after 5s,
    then expiration is bumped to now+10s."""

async def test_renew_on_non_owner_raises(lease, second_lease_instance):
    """Given A holds 'sess-1', when B calls renew('sess-1'),
    then LeaseHeld is raised."""

async def test_lease_expires_and_can_be_reclaimed(lease, second_lease_instance):
    """Given A acquires 'sess-1' with ttl=1s and doesn't renew, after 2s sleep,
    when B calls acquire('sess-1'), then it succeeds with generation > A's generation."""

async def test_release_is_idempotent(lease):
    """Given A holds 'sess-1', when release('sess-1') is called twice,
    then the second call does NOT raise."""

async def test_wait_for_lease_blocks_until_release(lease, second_lease_instance):
    """Given A holds 'sess-1', when B calls acquire('sess-1', wait_for_lease=5.0)
    AND A releases at t=1s, then B acquires successfully before the 5s timeout."""

async def test_wait_for_lease_timeout_raises(lease, second_lease_instance):
    """Given A holds 'sess-1' indefinitely, when B calls acquire(wait_for_lease=0.5),
    then LeaseHeld is raised after ~0.5s."""

async def test_force_reclaim_overrides_live_owner(lease, second_lease_instance):
    """Given A holds 'sess-1' (live), when B calls acquire(force_reclaim=True),
    then B acquires successfully with generation > A's generation.
    Subsequent A.renew() raises (A is no longer the owner)."""
```

### Cross-process tests (durable backends only)

```python
async def test_cross_process_lease_visibility(redis_backend):
    """Process A acquires; Process B (separate Python interpreter) sees the lease."""

async def test_lease_survives_process_a_crash(redis_backend):
    """Process A acquires with ttl=2s; kill Process A; Process B can reclaim after ttl expires."""
```

---

## How users invoke the contract suite against their own backend

Documented in `extending-oak.md`. Quick form:

```bash
# Workspace backend
python -m pytest oak_workspace.tests.contract --backend my_pkg:MyWorkspace

# State store backend
python -m pytest oak_session.tests.contract.state_store --backend my_pkg:MyStore

# Trace source adapter
python -m pytest oak_session.tests.contract.trace_source --backend my_pkg:MySource

# Lease backend (rarely user-implemented; usually Redis is enough)
python -m pytest oak_session.tests.contract.lease --backend my_pkg:MyLease
```

If all required tests pass, the backend is oak-compliant. Optional tests emit warnings, not failures.

---

## How the suite ships

- Lives at `oak_<module>/tests/contract.py` (or `tests/contract/<protocol>.py` for multi-Protocol modules)
- Marker: `@pytest.mark.contract` so users opting in run only contract tests
- Each test is a top-level `async def` taking a fixture
- Fixtures are parametrized via the `--backend` pytest option (`conftest.py` plumbing)
- Docstrings ARE the spec, not just comments

## Rule

Do not weaken assertion docstrings casually. They are the behavior spec backend authors implement against.
