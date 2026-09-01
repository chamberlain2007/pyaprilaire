# Exploration: rewriting the mock server as a state machine

Status: design exploration, no implementation. Every code snippet here was run
against `python-statemachine` 3.2.1 before being written down.

## Summary

A state machine library is the right tool for roughly 15% of
`pyaprilaire/mock_server.py` and the wrong tool for the other 85%. The file is
1137 lines, and the bulk of it is message dispatch and repetition, not state.
Reaching for `python-statemachine` first would add a dependency, touch the small
part, and leave the large part untouched.

The recommendation is to do this in layers, cheapest and highest-value first:

1. Fix the `hold_end` bug at `mock_server.py:795` (one line, independent of
   everything else — see [Hold](#2-schedule-hold-spec-34)).
2. Replace the read/write `if/elif` trees and the sync burst with dispatch
   tables (~400 lines removed, no new dependency).
3. Introduce a **session** state machine — the genuinely missing model, and the
   one that unlocks new tests.
4. Introduce **hold** and **equipment** state machines, which fix behaviour the
   mock currently fakes.

Steps 3 and 4 are ~12 transitions across three small machines. That is right at
the boundary where a library starts paying for itself, so the library choice is
a coin-flip that the packaging constraint (below) decides.

## What is actually in the file

Approximate line accounting for `_AprilaireServerProtocol`:

| Region | Lines | State-machine shaped? |
| --- | --- | --- |
| Logging setup, constants, COS attribute list | ~90 | No |
| `__init__` state fields | ~60 | Partly — this is extended state |
| `_setup_1_data` … `_identification_1_data` payload builders | ~140 | No |
| `_send_sync_burst` | ~167 | No — 13 near-identical `_queue_cos` blocks |
| `_queue_loop`, `connection_made/lost`, `data_received`, `_prescan_raw_frames` | ~130 | The connection part, yes |
| `_handle_read_request` | ~120 | No — a dispatch table written as `if/elif` |
| `_handle_write` and its handlers | ~290 | Mostly no; the hold writes, yes |

So about 570 lines — half the file — are dispatch and repetition. `mode`,
`cool_setpoint`, `dehumidification_setpoint`, `name`, `mac_address` and friends
are *extended state*: values that change but never gate behaviour. Modelling
them as states would produce a combinatorial explosion for no benefit. They stay
plain attributes under any design.

## The three machines that are real

### 1. Session / handshake

This does not exist in the code today at all. The mock tracks the connection as
`self.transport` truthiness, and `_queue_loop` spins on `while self.transport`.
There is no representation of *where in the handshake the client is*, even
though the client (`client.py:_update_status`) walks a specific spec Appendix J
sequence ending in `configure_cos()` then `sync()`.

```
disconnected → connected → subscribed → syncing → synced
```

What this buys:

- **Testability.** A test can assert `server.session.synced.is_active` instead
  of counting queued packets. Driving the mock into a state directly
  (`send("sync_requested")`) is much cheaper than replaying a byte stream.
- **Concurrent syncs become explicit.** Today `_write_sync` does a
  fire-and-forget `asyncio.ensure_future(self._send_sync_burst())`. Two SYNC
  writes in quick succession interleave two bursts and two sequence-number
  streams. A `syncing` state either rejects the second or queues it — either
  way it is a decision, in one place, instead of an accident.
- **A place to hang connection setup.** `connection_made` currently resets the
  receive buffer and launches the queue loop; entry/exit actions on `connected`
  and `disconnected` say that declaratively.

One caveat worth knowing before writing this: entry callbacks fire for the
*initial* state at construction time. In the prototype, `on_enter_disconnected`
logged "session reset" during `__init__`, before any client connected. Initial
state actions must be idempotent, or the machine must start in a dedicated
`new` state.

### 2. Schedule hold (spec 3.4)

Today `self.hold` (an int) and `self.hold_end` (a nullable datetime) are mutated
from three places: `_write_control_1`, `_write_hold`, and `_start_temporary_hold`.
The two fields must agree, and nothing enforces it — so they don't.

`mock_server.py:795` carries a stray unconditional reset, apparently duplicated
from `__init__` along with its comment:

```python
if Attribute.MODE in data:
    self.mode = data[Attribute.MODE]
    self.hold = HoldType.DISABLED
    self.hold_end = None

# When the current temporary hold ends; None whenever no hold is
# active. See _start_temporary_hold / _scheduling_4_data.
self.hold_end: datetime | None = None   # <-- unconditional

if Attribute.FAN_MODE in data:
    ...
```

A setpoint write survives it by luck, because `_start_temporary_hold()` runs
afterwards and re-sets the field. A **fan-mode-only** write does not. Observed
against the current code:

```
after setpoint write:  hold=TEMPORARY  hold_end=2026-09-01 04:03:35
  scheduling_4: {... hold_end_minute: 3, hold_end_hour: 4, hold_end_date: 1, ...}
after fan-only write:  hold=TEMPORARY  hold_end=None
  scheduling_4: {'hold': TEMPORARY, 'hold_fan_mode': 2, ...}   # no end fields
```

The mock reports a temporary hold with no end time — the exact "meaningless
zero" that `TEMPORARY_HOLD_HOURS` exists to avoid. This is a one-line fix and
should not wait for a rewrite, but it is also a clean illustration of the
argument: with `hold_end` owned by `on_enter_temporary` / `on_exit_temporary`,
the invariant cannot be broken by an unrelated code path, because no unrelated
code path can write the field.

```python
class HoldMachine(StateMachine):
    off = State(initial=True)
    temporary = State()
    permanent = State()
    away = State()
    vacation = State()

    setpoint_written = off.to(temporary) | temporary.to.itself()
    mode_written = (
        temporary.to(off) | permanent.to(off) | away.to(off) | vacation.to(off)
        | off.to.itself()
    )
    hold_written = (
        off.to(temporary, cond="wants_temporary")
        | off.to(permanent, cond="wants_permanent")
        | temporary.to(off, cond="wants_off")
        | ...
    )

    def on_enter_temporary(self):
        self.hold_end = datetime.now() + timedelta(hours=TEMPORARY_HOLD_HOURS)

    def on_exit_temporary(self):
        self.hold_end = None
```

Note the guard style: `hold_written` fans out over five `cond=` predicates
because the target depends on the written value. This is the least pleasant part
of the declarative syntax — a plain `dict[HoldType, State]` lookup reads better
for value-driven transitions. It is worth weighing.

### 3. Equipment status (spec 8.6)

`_status_6_data` currently hardcodes what the equipment is doing from `mode`
alone:

```python
Attribute.COOLING_EQUIPMENT_STATUS: {
    HvacMode.COOL: CoolingEquipmentStatus.STAGE_1,
    HvacMode.AUTO: CoolingEquipmentStatus.STAGE_1,   # always cooling in AUTO
}.get(self.mode, CoolingEquipmentStatus.NOT_ACTIVE),
Attribute.FAN_STATUS: FanStatus.ACTIVE
if self.fan_mode in (FanMode.ON, FanMode.AUTO)      # AUTO fan always running
else FanStatus.NOT_ACTIVE,
```

So the mock claims the compressor is running in AUTO at any indoor temperature,
and the fan is running in AUTO with no demand. Neither is what hardware does,
and a client that reacts to equipment transitions has nothing to react to.

An `idle / heating / cooling` machine evaluated against `(mode, setpoints,
indoor_temperature)` fixes that, and gives the mock something it lacks entirely:
the ability to *change* status over time, which is what exercises the client's
COS handling.

```python
evaluate = (
    idle.to(heating, cond="wants_heat")
    | idle.to(cooling, cond="wants_cool")
    | heating.to(idle, unless="wants_heat")
    | cooling.to(idle, unless="wants_cool")
    | idle.to.itself(internal=True)      # no-op when nothing changed
    | heating.to.itself(internal=True)
    | cooling.to.itself(internal=True)
)
```

Verified: with `mode=AUTO, cool_setpoint=25, indoor=27` a single
`send("evaluate")` lands in `cooling`; dropping indoor to 22 and re-evaluating
returns to `idle`. The `internal=True` self-transitions matter — without them,
an `evaluate` with no change raises `TransitionNotAllowed`.

The outdoor sensor (`OPEN → NO_ERROR` on first write) is technically a fourth
machine. Two states and one transition is not worth the ceremony; leave it.

## What the library actually gives you

Verified against `python-statemachine` 3.2.1:

- **Async is native.** `async def on_enter_syncing` works, and sending a
  follow-up event from inside an async callback (`await self.send("sync_finished")`)
  is queued correctly by the engine. This matters — `_send_sync_burst` is async.
- **Illegal transitions raise, with a readable message:**
  `TransitionNotAllowed: Can't Client connected when in Synced.`
- **Introspection.** `machine.allowed_events` returns what is legal right now,
  which is genuinely useful in tests and log output. `State.is_active` is the
  clean state predicate.
- **Diagrams.** `_repr_svg_` renders the machine, if graphviz is installed.
- **Cost is negligible.** ~0.44 ms to construct a machine; three per connection.

Two friction points:

- **API drift.** 3.x deprecates `current_state` in favour of `configuration` (a
  set, because 3.x added statecharts and parallel regions). Every
  `current_state` access in the prototype emitted a `DeprecationWarning`. A
  library pinning a version range inherits that churn.
- **Value-driven transitions are awkward**, as the `hold_written` fan-out above
  shows.

### Alternatives

| Option | Pros | Cons |
| --- | --- | --- |
| `python-statemachine` | Declarative, async-native, good errors, introspection, diagrams | New dependency; 2.x→3.x API drift; clumsy for value-driven transitions |
| `transitions` (pytransitions) | More mature and widely used; `AsyncMachine` exists | Injects attributes onto the model — less legible, weaker typing |
| Hand-rolled enum + dict table | Zero dependencies; ~40 lines; no packaging problem | No guards/introspection for free; you write the error messages |

### The packaging constraint, which probably decides it

`mock_server.py` ships *inside* the `pyaprilaire` package, and `pyproject.toml`
declares exactly one runtime dependency (`crc`). This library is consumed by the
Home Assistant Aprilaire integration, so a runtime dependency added for a test
mock lands on every install. The options are:

1. An optional extra (`pyaprilaire[mock]`) plus an import guard in
   `mock_server.py`.
2. A dev-only dependency, accepting that the README's documented
   `python -m pyaprilaire.mock_server` fails without the extra.
3. No dependency — hand-roll it.

Given that the three machines total roughly 12 transitions, option 3 is a
serious contender, and option 1 is the fallback if the machines grow. What is
*not* defensible is a plain runtime dependency.

## The other half: dispatch, which is not a state machine

This is where the line count actually is, and none of it needs a library.

`_handle_read_request` (120 lines) and `_handle_write` (~100 lines of branching)
are dispatch tables spelled as nested `if/elif`. A registry collapses both,
and makes the NACK-on-unknown-attribute path fall out of a lookup miss rather
than a chain of `else` clauses:

```python
READ_HANDLERS: dict[tuple[FunctionalDomain, int], Callable] = {}

def reads(domain, attribute):
    def decorate(fn):
        READ_HANDLERS[(domain, attribute)] = fn
        return fn
    return decorate

@reads(FunctionalDomain.CONTROL, 1)
def _control_1_data(self) -> dict: ...
```

`_send_sync_burst` (167 lines) is 13 copies of the same four-line shape, each
pairing a COS channel with a `(domain, attribute, payload)` triple. That is a
table:

```python
COS_MESSAGES = [
    (Attribute.COS_INSTALLER_THERMOSTAT_SETTINGS, FunctionalDomain.SETUP, 1, "_setup_1_data"),
    (Attribute.COS_THERMOSTAT_SETPOINT_AND_MODE_SETTINGS, FunctionalDomain.CONTROL, 1, "_control_1_data"),
    ...
    (None, FunctionalDomain.STATUS, 8, "_status_8_data"),   # always sent
    (None, FunctionalDomain.STATUS, 2, "_status_2_data"),   # sync complete
]
```

The burst becomes a loop over that table. Better, the *write* handlers stop
hand-writing their COS emissions too: `_write_dehumidification_setpoint`,
`_write_fresh_air` and `_write_air_cleaning` each end with two near-identical
`_queue_cos` blocks that a `self._emit_cos(FunctionalDomain.CONTROL, 3)` helper
replaces with one line. Roughly 400 lines go away, and adding a new attribute
becomes one table row instead of edits in four places.

This layer should land first regardless of what happens with state machines,
because it makes the state-machine change small enough to review.

## Suggested sequencing

| Step | Change | Lines | Dependency |
| --- | --- | --- | --- |
| 1 | Fix the `hold_end` reset at `mock_server.py:795` | −1 | none |
| 2 | Read/write dispatch registry | ~−200 | none |
| 3 | `COS_MESSAGES` table + `_emit_cos` helper | ~−200 | none |
| 4 | Session state machine | +60 | decide here |
| 5 | Hold state machine | +50 | same |
| 6 | Equipment state machine (fixes the AUTO/fan fakery) | +50 | same |

Steps 1–3 are pure refactors with no behaviour change and are worth doing on
their own merits. Steps 4–6 change behaviour, so each wants tests — and note
that `mock_server.py` is currently excluded from coverage in
`pyproject.toml:47` and has no tests at all. If the mock is going to grow real
behaviour, that exclusion should be revisited as part of step 4.

## Recommendation

Do steps 1–3 now; they are the bulk of the win and carry no risk. Do step 4
next, because the session model is the thing genuinely missing rather than
merely verbose. Hand-roll the machines unless a fourth or fifth appears — at
three small machines, `python-statemachine` is a pleasant but not yet a
load-bearing dependency, and the packaging constraint makes "pleasant" a hard
sell for a library that ships into Home Assistant.
