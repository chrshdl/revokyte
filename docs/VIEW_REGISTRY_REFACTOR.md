# ViewRegistry Refactor

**Status:** Implemented (community tree; §6 deferred) · **Scope:** `states/` + `ui/views/` · **Drafted:** 2026-08-25 · **Board measured:** Raspberry Pi 4, 1024x600, `arm_freq=1000`

> **What shipped.** §§1–5 and 7–9 are implemented in `revokyte`. §6
> (extension-declared views, the variant budget assertion, the `/run` failure
> marker and the `ota-health-check.sh` check) is deferred — it spans
> `instrument-cluster-pro` and `instrument-cluster-os` and is worth doing once
> the pattern here has run on a device. Five findings from the implementation
> correct the design as drafted; they are recorded in §11.

Separating view lifetime from state lifetime, so screen transitions allocate
nothing and the frame loop never pays for a garbage collection.

---

## 1. The problem

Every `State` builds its own `View` in `__init__`, and allocates a full-screen
background surface in `enter()`. Both are discarded when the state is popped.
Navigating the menus therefore churns megabytes of surface memory per
transition.

Nothing leaks. Teardown is correct. But the memory involved is **allocated in C
by SDL**, while Python's garbage collector is driven by **object counts** — so
the runtime cannot see the cost of what it is holding. The result is a long,
invisible accumulation ended by one abrupt collection.

Measured on device:

| metric | value |
|---|---|
| per `SetupView` construction | **3.49 MB** |
| Python objects per view | 234 |
| freed in one gen-2 collection | **−47 MB** |
| frame rate during that collection | **3.0 fps** |
| RSS sawtooth range | 120–150 MB |

The 1-second stall at 3 fps is the only user-visible defect, and it lands at an
arbitrary moment — potentially mid-corner.

## 2. What the evidence rules out

| hypothesis | test | result |
|---|---|---|
| Memory leak | RSS over 28 switches | Returned to 89.9 MB — below start. Not a leak. |
| Reference cycles in the view graph | `weakref` + `gc.disable()` | `freed by refcount alone: True` — acyclic. |
| Leaked reader threads / sockets | `/proc/<pid>` counters | threads 9, fds 44, sockets 4 — stable. |
| Plugin sprites accumulating | journal `Loaded plugin` count | 2 per plugin = 2 app starts. No reloads. |
| Dashboard page churn | journal `Swipe to page` count | 0. Pages were never switched. |

**The teardown logic is already correct.** This refactor is not a bug fix — it
removes an allocation pattern whose cost the runtime cannot account for.

## 3. Rejected alternatives

### `gc.collect()` at a safe point

Placing a collection in `SetupState.exit()` would move the stall to a moment
where nothing is animating. A few lines, no structural change.

**Rejected:** treats the symptom and reintroduces non-determinism by design —
the pause still happens, we merely guess when. Frame timing should not depend
on collector heuristics.

### Caching the `SetupView` instance

Holding one long-lived `SetupView` removes 3.49 MB of churn per visit.

**Rejected:** does not generalise. Applied to one screen it is a special case;
the ninth screen re-creates the problem. If the pattern is right, it should be
uniform.

### Sharing one background surface (as a standalone change)

Hoisting the screen-sized background into `StateManager` saves ~1.8 MB per
state.

**Rejected standalone — adopted inside this design.** States coexist on the
stack: `DashboardState` stays alive under `SetupState`, and
`draw_static_background()` is only ever called from `enter()`. Sharing one
surface today would let Setup paint over the Dashboard's dirty-rect restore
source, causing persistent visual corruption. It becomes safe only once every
state has a defined repaint point — which the bind step in §5 provides.

## 4. Principle

Production automotive HMI stacks share
one rule: allocate at startup, never during runtime. The screen set is
bounded and known at design time, so every view exists before the first frame.
Transitions flip visibility and rebind data; they never construct.

That answers the objection to manual collection directly: if nothing is
allocated per transition, nothing needs collecting. The collector stops being
part of the frame budget because it has no work.

Budget for this codebase:

| | |
|---|---|
| real views (11 files − 3 helpers) | **8** |
| states | 14 |
| all views held permanently | **≈ 28 MB** |
| free RAM on the device | 0.5 GB |

Adding a ninth view costs a known 3.5 MB, visible in review — rather than
adding unbounded runtime churn. The budget scales *predictably*.

### Boot cost measurements

Preallocation moves view construction to startup, which matters because boot
time is a tracked product metric (currently ~14 s). Measured on the Pi 4:

| view | cold | warm | | view | cold | warm |
|---|---|---|---|---|---|---|
| `DashboardView` | 19.1 ms | 2.3 ms | | `EnterIPView` | 30.4 ms | 12.6 ms |
| `SetupView` | 38.5 ms | 19.9 ms | | `AgentSetupView` | 12.1 ms | 4.1 ms |
| `SoftwareView` | 21.4 ms | 8.9 ms | | `ListenerSetupView` | 4.3 ms | 3.6 ms |
| `WifiSetupView` | 3.0 ms | 1.1 ms | | `InstallView` | 5.6 ms | 4.2 ms |

**Total: 134.4 ms cold, 56.7 ms warm.** The *added* cost is smaller still —
`DashboardView` is already built at boot today, so preallocation adds the other
seven at roughly **115 ms, under 1% of a 14 s boot**. For scale,
`pygame.display.set_mode()` alone costs 158 ms on the same board.

Cold is first construction of a class (paying font and asset cache misses);
warm is a second construction with those caches populated. The 2.4x gap means
the marginal view is cheaper than the first, so the budget does not grow
linearly in wall time as screens are added.

This is the number P2 exists to produce, obtained early. It also weakens the
case for lazy building: 115 ms does not justify the extra state machine.

**The production board has 1 GB, not the 8 GB development board.** That changes
the shape of this trade and is the reason to judge it explicitly rather than
wave it through. The estimate above was ~3.5 MB per view and ≈28 MB held; the
measurement below replaces it.

### Measured budget — Pi 4, 1024x600, v0.2.40

`ViewRegistry.preload()`, one view at a time, RSS sampled after a forced
collection between each:

| view | build ms | RSS MB | | view | build ms | RSS MB |
|---|---|---|---|---|---|---|
| `SetupView` | 35.2 | **2.83** | | `InstallView` | 8.9 | 0.56 |
| `EnterIPView` | 29.5 | 1.77 | | `DashboardView` | 17.7 | 0.45 |
| `SoftwareView` | 20.3 | 0.71 | | `AgentSetupView` | 5.5 | 0.45 |
| `ListenerSetupView` | 3.4 | 0.35 | | `WifiSetupView` | 3.0 | 0.19 |

**Total: 123.7 ms, 10.73 MB for all eight.** The 3.49 MB/view figure came from
macOS `ru_maxrss` — a peak, not a current reading — and was 2.6x pessimistic;
only `SetupView` approaches it. Build time matched the prediction well (123.7
vs 134.4 ms).

| | share of 1 GB |
|---|---|
| app RSS on the dashboard (104 MB observed) | ~10% |
| the per-transition churn this removes (34.8 MB over 20 switches) | ~3.4%, transient |
| all views held permanently (**10.73 MB**) | **~1%** |

So preallocation swaps a transient 34.8 MB of churn for a permanent 10.7 MB
reservation, and peak RSS fell 103.4 -> 64.9 MB in the harness (§9). The
lazy-build hedge is not needed: `acquire()` still builds on demand, so
dropping the `preload()` call in `main.py` is a one-line fallback if a future
view is heavy, but nothing today argues for it.

## 5. Design

### Ownership moves

```python
# today — states/setup_state.py
class SetupState(State):
    def __init__(self, state_manager):
        self.view = SetupView()          # 3.49 MB, per entry

    def enter(self, screen):
        self.background = pygame.Surface(screen.get_size()).convert()
        self.draw_static_background(self.background)

# proposed
class SetupState(State):
    view_class = SetupView                     # declarative

    def enter(self, screen):
        self.view = registry.acquire(SetupView)
        self.view.reset(self.view_context())
        self.background = registry.background(self.background_color())
        self.draw_static_background(self.background)   # now also on resume
```

### View lifecycle contract

`View` (in `ui/views/base.py`) gains two methods alongside the existing
`draw()` / `full_paint()` contract:

| method | called | responsibility |
|---|---|---|
| `build()` | Once, at registry init | Create every widget and surface. Everything expensive happens here. |
| `reset(ctx)` | Every `enter()` / `on_resume()` | Rebind data, restore scroll to top, close dropdowns, apply context. Allocates nothing. |

`SetupView.close_dropdowns()` is already the beginning of `reset()` — the
pattern exists, it is just not yet named or uniform.

### The hard part: parameterised views

Five of eight views take constructor arguments, and one class is instantiated
twice with *different* arguments:

| view | constructor args | migration |
|---|---|---|
| `WifiSetupView` | `show_back` | **Two live instances** (`WifiSetupState`, `WifiConnectingState`) with different values. Structural — changes the widget set. |
| `EnterIPView` | `recent_connected`, `title` | Data only → `reset(ctx)`. |
| `AgentSetupView` | `feed_label`, `unlocks` | Data only → `reset(ctx)`. |
| `ListenerSetupView` | `feed_label` | Data only → `reset(ctx)`. |
| `InstallView` | `feed_label`, `updating` | Data only → `reset(ctx)`. |
| `DashboardView`, `SetupView`, `SoftwareView` | none | Direct. |

**Key decision.** `show_back` is not data — it decides whether a back button
*exists*. Two options: build both widget sets once and toggle visibility in
`reset()`, or key the registry on `(class, variant)` and hold two instances.

**Recommendation:** visibility toggle. Keying on variants reopens the unbounded-
instances problem the registry exists to close.

### Registry

```python
class ViewRegistry:
    """Owns every view for the life of the process.

    Built once after display init, when surface creation is legal and
    no frame budget applies. acquire() never allocates.
    """
    def __init__(self, screen, view_classes):
        self._views = {}
        self._background = pygame.Surface(screen.get_size()).convert()
        for cls in view_classes:          # core + extension-declared
            try:
                v = cls(); v.build()
                self._views[cls] = v
            except Exception:             # fail-open, see §6
                log.exception("view %s failed to build", cls.__name__)

    def acquire(self, cls):
        return self._views[cls]

    def background(self, color):
        self._background.fill(color)   # reused, never reallocated
        return self._background
```

One background surface serves every state because `reset()` gives each state a
defined repaint point on both `enter()` and `on_resume()` — closing the
stacked-state hazard described in §3.

## 6. Variants and feature flags

`instrument-cluster-pro` adds views and states for OTA and licensing. A registry
that preallocates everything must know the full view set before the first frame, so the question is when the set
becomes known.

### The compile-time flag already exists

`BR2_PACKAGE_PYTHON_INSTRUMENT_CLUSTER_PRO=y` decides whether
`instrument_cluster_pro` is installed at all. In a community build its views are
not on target in any form. That is already a compile-time feature flag,
expressed as package presence.

The gap is elsewhere. Discovery is runtime and entry-point based:
`extensions.py` calls `importlib.metadata.entry_points(group="instrument_cluster.extensions")`
and invokes each `wire()`. The app learns its view set by executing extension
code — which a registry that must allocate before the first frame cannot wait
for.

### Extensions declare their views

`wire()` already runs at the right moment: after the core objects exist, before
plugins load. It gains one method, and the registry builds after all wiring
completes.

```python
# in instrument_cluster_pro
def wire(runtime: ExtensionRuntime) -> None:
    runtime.register_views([ProOtaView, LicenseView, InstallView])
    runtime.add_setup_entry(SetupEntry(...))
```

For flags finer than package presence, `FEAT_OTA` separately from
`FEAT_LICENSE`, generate a `features.py` at build time from the Buildroot
config. `board/*/post-build.sh` already generates `/etc/os-release` and
substitutes `@BOARD_COMPATIBLE@` into the RAUC config; same pattern, and it
keeps flags greppable rather than implicit in packaging.

### The variant matrix

**Decided:** a declared variant matrix, not free-form flags. Independent
booleans produce 2^n configurations and only a handful can ever be tested.

The build matrix and the *feature* matrix are not the same size. Builds vary on
three axes - board, dev/release, tree - but the view set varies on exactly
one. A Pi 4 and a Pi 5 run the same views; so do a dev and a release image.
Only Pro changes the set.

| variant | tree | boards built in CI | views | budget |
|---|---|---|---|---|
| `community` | instrument-cluster-os | pi4, pi5 | 8 | ≈ 28 MB |
| `pro` | instrument-cluster-pro-os | pi4, pi5 | 8 + N | ≈ 28 + N×3.5 MB |

Two rows, not eight. The rule that keeps it testable: adding a variant means
adding a row and a CI job. Undeclared flag combinations are refused by the
build rather than silently produced.

> Pro ships on both boards (Pi 4 support added 2026-08-24). `ci.yml` in the Pro
> tree was still building `raspberrypi5` only; `raspberrypi4-64` was added to
> that matrix in `instrument-cluster-pro-os@03816da`.

### The budget becomes assertable

`scripts/assert-release-image.sh` already asserts properties of the *built
artifact* rather than trusting configuration — that is its stated reason for
existing. Asserting the declared view count and budget against a ceiling fits
that philosophy, and makes a new screen show up as a reviewable budget change on
the PR instead of a surprise on target.

### When a view fails to build

Preallocation moves this failure from "the user taps that row" to "during boot",
which changes both its timing and its blast radius.

| strategy | dev / manufacturing | in the field |
|---|---|---|
| **Fail-closed** (let it propagate) | Brutal. App will not start → watchdog → `StartLimitAction=reboot` → black screen. No SSH on a release image, so diagnosis means pulling the card. | **Self-healing.** Health check never runs → slot never marked good → U-Boot rotates to the previous slot within three reboots. A bad OTA undoes itself. |
| **Fail-open** (log and skip) | Graceful. Dashboard comes up, one feature missing — matching the promise `extensions.py` already makes. | **Silently permanent.** Display, GPU, wlan and input all pass, so the slot is marked good and the broken build never rolls back. |

**Decided: fail-open at the registry, with the health check made aware of it.**
Three parts, taking the field safety of one and the user experience of the
other:

1. The registry catches per view, logs, and skips — the dashboard always comes
   up.
2. Rollback is dependency-aware: a missing view also removes the setup entries
   that need it, so there are no dead buttons. The existing rollback in
   `extensions.py` does **not** cover this — it operates at `wire()` granularity,
   and a `build()` failure happens later, after wiring succeeded.
3. The registry records failures to `/run/instrument-cluster/unhealthy`, and
   `ota-health-check.sh` fails while that file is non-empty. The slot is never
   marked good, so a bad update still rolls back — while the driver keeps a
   working dashboard throughout.

**Why `/run` and not `/data`:** `/run` is tmpfs, cleared every boot, so the
marker describes *this* boot only. On `/data` it would persist and one transient
failure would poison every subsequent boot into permanent rollback. Ordering
already works: the registry builds before the first frame; the health check runs
15 s after the app signals ready. If the app dies before writing the marker it
never signals ready either, so the slot is not marked good regardless.

**Two limits of the rollback.** It is *not immediate* — the health check
deliberately never forces a reboot (a genuine hardware fault would otherwise
ping-pong both slots forever), so attempts burn on real reboots: roughly three
power cycles on an appliance users switch off by pulling the plug. And it does
*nothing on a factory image*, where both slots are identical — no harm, but the
device runs with the feature missing until someone reflashes. This mechanism
protects OTA updates, which is where it matters.

### Widening `ota-health-check.sh`

The script looks hardware-only, and its header says it exists to "verify the
hardware a driver/kernel regression would silently break, not just 'the app
started'". But its real contract is narrower and more useful than "hardware",
and `check_wifi` states it outright:

> brcmfmac probed and created the interface. Association is **NOT** required —
> a device at the track may have no known network, but the driver coming up
> must never regress silently.

The rule it is actually applying is **report faults the image causes, never
faults the environment causes.** Association is excluded because no rollback
fixes an unknown Wi-Fi network. A view that cannot build is the opposite: it is
baked into the image, and rolling back is exactly the cure.

So this is not scope creep, provided two rules hold:

**1. One generic check, not app knowledge.** The script never learns what a
view is. It gains a single check against a marker the app owns:

```sh
check_app() {
    # The app publishes IMAGE-ATTRIBUTABLE faults here: conditions a rollback
    # would actually fix (a view that cannot build, a missing bundled asset).
    # Never environmental ones (no network, no telemetry, no game running) —
    # same principle as check_wifi above, which deliberately does not require
    # association. /run is tmpfs, so the marker describes this boot only.
    [ ! -s /run/instrument-cluster/unhealthy ]
}
```

Future faults are added by the app writing a line, never by editing this script
again. That is what stops the contract accreting.

**2. The marker means "this image is defective", not "something is wrong
now".** Writing it for a transient or environmental condition would withhold
`mark-good` for something a rollback cannot fix. The blast radius is bounded —
the check never forces a reboot, so a wrong marker costs attempts on reboots
that would have happened anyway — but the discipline is the whole point.

**And it cannot be left to a review checklist.** As drafted, this rule was
unenforceable: views read `/data` during construction, so "a view failed to
build" did *not* imply "the image is defective". `SetupView` read
`config.json` and the installed feed version, `DashboardView` read
`status_lights`, `EnterIPView` read `recent_connected` and `get_ip_prefill()`
(the live network interface), and a `SetupEntry`'s callable `button_text` can
reach anything the extension likes — Pro's licence row reads its tier. Any of
those raising would have withheld `mark-good` and rolled the device back to a
slot with the same unreadable `/data`: the update lost, the fault kept, which
is strictly worse than having no check.

The fix is the lifecycle contract this document already declares but the code
did not honour — `build()` creates widgets, `reset(ctx)` binds data.
Construction now touches only image-resident things (fonts, skins, icons,
`is_raspberry_pi()`, which feeds exist, which extensions are installed), so the
implication holds *structurally* rather than by anyone remembering the rule.
`test_build_is_image_only.py` pins it: every view builds while
`ConfigManager.get_config()` and `get_ip_prefill()` raise. Against the commit
before the split, that test fails on three views and writes three faults.

The existing retry loop needs no change. The marker is written during registry
build, well before the health check runs 15 s after the app signals ready, so
it is already present on the first iteration; a persistent marker simply fails
all 15 tries and exits non-zero after the 30 s grace window.

## 7. Migration

Ordered so that each phase is independently shippable and revertible. The
sequence matters: the contract must exist before anything depends on it, and the
background can only be shared once every state repaints on resume.

| phase | work | notes |
|---|---|---|
| **P1** | Define the contract | Add `build()` and `reset(ctx)` to `View` with no-op defaults. Nothing calls them yet. Ships green. |
| **P2** | Registry alongside the old path | Introduce `ViewRegistry`, built at startup. States still construct their own views. Measures the real preallocation cost on device before anything depends on it. |
| **P3** | Migrate the parameterless views | `SetupView`, `SoftwareView`, `DashboardView`. Highest value — `SetupView` is the screen in the reported stall — and lowest risk. |
| **P4** | Migrate the data-parameterised views | Constructor args become `reset(ctx)` fields for `EnterIPView`, `AgentSetupView`, `ListenerSetupView`, `InstallView`. |
| **P5** | Resolve `WifiSetupView` | Convert `show_back` to a visibility toggle. Isolated deliberately — the only genuinely structural case. |
| **P6** | Extension-declared views | Add `runtime.register_views()` to `ExtensionRuntime`, call it from `instrument_cluster_pro`'s `wire()`. Build the registry after wiring. Add the variant budget assertion to CI, the `/run` failure marker, and the matching check in `ota-health-check.sh`. |
| **P7** | Share the background | Requires P3–P5. Move background ownership to the registry and repaint static elements on `on_resume()` as well as `enter()`. |
| **P8** | Consider `gc.freeze()` after init | Optional. With steady-state allocation near zero, moving the startup heap out of collector scope makes remaining collections cheaper. Measure before adopting. |

## 8. Risks

| risk | why it matters | mitigation |
|---|---|---|
| Stale view state between visits | A reused view keeps scroll position, dropdown state, error text. Leaks information across screens. | `reset()` is mandatory, not optional. Assert in `enter()` that it ran. |
| Dirty-rect corruption from the shared background | Failure is subtle, state-dependent visual artefacts — passes tests, shows on hardware. | Gated behind P7. Verify each screen on device, including back-navigation from every child state. |
| Startup time regression | All eight views build before the first frame; boot time is a tracked product metric (~14 s). | **Measured: 134 ms for all eight, ~115 ms added** (see §4). Under 1% of boot. Lazy building remains the fallback if a future view is heavy, but is not needed today. |
| A Pro view fails to build at startup | Preallocation runs before the first frame; an exception there could blank the dashboard rather than degrade — or, handled naively, mark a broken update as good. | Fail-open per view, dependency-aware entry rollback, and a `/run` marker that makes `ota-health-check.sh` withhold `mark-good` (§6). |
| Two states sharing one view instance | A state pushed over another using the same view class would corrupt the one underneath. | Registry asserts single-borrower per view; caught at development time, not in the field. |

## 9. Verification

Acceptance is measured, not asserted. The perf stream carrying `fps`, `rss_mb`
and `load_pct` lives in the **Pro** tree (see the note at the end of §11), so
these runs are taken on a Pro dev image:

| metric | before | target | **measured after** |
|---|---|---|---|
| RSS across 20 view switches | 125 → 150 MB, sawtooth | flat ±2 MB | **flat ±0.1 MB** |
| `SetupView` constructions per 20 visits | 20 | 1 | **1** |
| peak RSS during the run | 103.4 MB | lower | **64.9 MB** |
| frames under 60 fps (steady state) | — | 0 | **0 / 45 samples** |
| worst frame (steady state) | 3.0 fps at collection | > 55 fps | **61.8 fps** |
| steady-state CPU | 7–8% (of 4 cores) | unchanged | **6.3% median** |
| app init (display → systemd ready) | 0.66–0.82 s | no regression | **0.81 s** |

### Measured 2026-08-25, Pi 4, Waveshare 7″ (1024×600), `0.2.40.dev2+g431ca81`

Taken by driving `StateManager` push/pop directly on the board rather than
tapping the panel, so the run is unattended and identical on both sides of the
change. Before and after are the same device in the same session — the refactor
was deployed as bytecode between the two runs.

| | before | after |
|---|---|---|
| `SetupView` constructions | 20 | **1** |
| RSS start → end | 62.6 → 97.4 MB | 62.2 → **64.9 MB** |
| total growth over 20 switches | +34.8 MB | **+2.7 MB** (all of it the one build) |
| mean RSS, first half → second half | 79.5 → 95.8 MB | 64.9 → **64.9 MB** |
| peak RSS | 103.4 MB | **64.9 MB** |

The before series is the staircase the design predicted —
`69.8, 74.6, 72.2, …, 98.6, 103.4, 95.2, …` — climbing about 1.7 MB per visit
with a partial collection visible at cycle 18. The after series is
`64.8, 64.8, 64.9, 64.9, …` for all twenty. Sawtooth means churn remains; flat
means the refactor did its job.

### Confirmed by hand on the panel

The programmatic harness cannot tap, so the run above was repeated with a
person navigating Dashboard → Setup → back ten times on the touchscreen, with
`PerfMonitor` streaming at 1 Hz. 176 samples over ~199 s:

| | |
|---|---|
| fps | min **61.4**, median 62.1, max 62.5 |
| samples under 60 fps | **0** |
| RSS | 104.0 → 104.3 MB, max 104.3, growth **+0.3 MB** |
| mean RSS, first half → second half | 104.04 → **104.30 MB** |
| CPU | 6.8% median, 23.4% peak while Setup draws |

This is the real touch path — hit-testing, dropdowns, the scrollable viewport's
immediate-mode redraw — not just `push_state`/`pop_state`, and it stays flat.
No stall was observed because there was nothing to collect.

One excursion in the trace is *not* this refactor and is worth recording so it
is not misread later: RSS ramped 104 → 131 MB over four seconds and was freed
in one step, with an fps dip to 50.2 on the free. The journal identifies it —
`serving acc-agent-win-0.1.4.zip on :8321`, then `pairing window closed`. That
is `AgentSetupState` reading the ~27 MB agent bundle into memory to serve it
over HTTP, on a different screen, doing exactly what it is supposed to do.

**What is still unmeasured.** `boot to first frame` is app init from
`Active display` to systemd ready, not a cold reboot.

## 10. Open questions — resolved

- **Lazy or eager build?** *Both, and they share one path.* `acquire()` builds
  on first use; `preload()` builds a known set eagerly. Eager is what ships, so
  no transition allocates; lazy is what makes the fallback a one-line change
  and what keeps tests and preview tools working without a registry.
- **Where does the registry live?** *A module-level singleton* (`views`),
  mirroring `extensions.runtime`, rather than on `StateManager` — that would
  have meant threading it through 19 state constructors. The *background*
  surface did go to `StateManager`, which already owned the screen. Splitting
  the two is what kept either from growing awkward: views need no screen,
  backgrounds need only its size.
- **What is the budget ceiling?** *There isn't one, and there should not be.*
  The measured cost is **10.73 MB for eight views** (§4), ~1% of a 1 GB board —
  not the ≈28 MB estimated. But a byte ceiling cannot be a gate: surfaces scale
  with the panel, so it would need re-measuring for every skin (1280x720,
  1024x600, 800x480, and whatever comes next) and every variant, and would rot
  into a number nobody trusts. What a screen costs is a *measurement* — true of
  one panel at one moment — while a gate has to assert an *invariant*.

  So `test_view_budget.py` gates the **set**: the eight views are declared, and
  a ninth fails until someone adds it deliberately. That is resolution- and
  variant-independent, and it is what §6 actually wanted — a new screen showing
  up as a reviewable change. Pro's three are gated the same way in its own
  repo, since `core_views()` cannot see them. The numbers stay here, next to
  the panel they were taken on.

  Worth being precise: the set gate is a notification, not enforcement. It
  cannot stop a view being added, only make it a visible act. The genuinely
  load-bearing assertion in that file is that every view constructs with no
  arguments and survives `reset(None)` — that is what makes a view poolable at
  all, and it is what caught Pro's `ProFeaturesView(status_text)` and
  `LicenseActivationView(device_id)`.
- **Is `DashboardView` in scope?** *Yes.* The premise that it was already
  long-lived was wrong — see §11.3.

---

## Measurement notes

Measurements were taken on a Raspberry Pi 4 dev image, 2026-08-24/25, with
`tools/perf_viewer.py` and `/proc` sampling.

The 3.49 MB per-view figure was measured on macOS via `ru_maxrss` (a peak, not a
current reading) with pygame 2.6.1 / SDL 2.28. The device runs SDL 2.30 at
1024x600, so treat the magnitude as indicative. The structural finding — a
full-screen surface allocated per state in `State.enter()` — is read directly
from the source and is not measurement-dependent.

A related but separate line of work reduced per-frame blit cost by removing
redundant alpha compositing (`revokyte@f42ce92`); it does not affect the
allocation churn this document addresses.


---

## 11. Corrections from the implementation

Five things the design got wrong about the code it was describing. Recorded
here because §6 will be planned against the same assumptions.

**1. The `WifiSetupView` variant problem does not exist.** §5 calls
`show_back` the one "genuinely structural" case, needing its own phase (P5) and
a decision between a visibility toggle and keying the registry on
`(class, variant)`. Neither was needed: `_back_button` is always constructed
(`wifi_setup_view.py`), and `_header_widgets()` / `_rescan_button()` read the
flag every time they run. `show_back` moving into `reset(ctx)` is a single
assignment. The second instantiator, `WifiConnectingState`, was dead code —
constructed nowhere in `src/` since `WifiStatusWindow` replaced the boot gate —
and has been deleted.

**2. The "no constructor args → Direct" views were the hardest.** §5 lists
`SetupView` and `SoftwareView` as trivial. Both bake live state into their
widget tree at construction: config, `is_raspberry_pi()`, the
`feed_needs_reinstall()` label flip, and each extension entry's `button_text`,
which is documented as re-evaluated per entry and which Pro uses to show
licence tier. A pooled view freezes all of it at boot. Their `reset()`
implementations are the largest in the change. `InstallView` is the only view
whose widget *set* genuinely varies with its context (Cancel alone while
updating, versus Install + Cancel), and it resolves the way §5 suggested for
`show_back`: build both, re-enrol on reset.

**3. `DashboardView` was not long-lived.** §4 and §10 assume it is.
`gate.entry_state()` built a fresh `DashboardState` — and view — on every call:
boot, Wi-Fi setup success, Wi-Fi connect success. Pooling it also required
making plugin linking authoritative (`plugin_layer.empty()` before re-adding):
adding is idempotent but never removes, so a plugin set that changed between
dashboard visits left the old gauges drawn underneath.

**4. Acquire must happen in `enter()`, and the reason is ordering, not
taste.** §5 puts it there without saying why. `change_state()` pops and
`exit()`s the outgoing state, but the incoming state object is constructed by
the *caller* first. Acquiring in `__init__` would let an incoming state reset a
view the outgoing one is still drawing. This also forced view-touching work out
of three constructors (`DashboardState`'s plugin linking, `WifiSetupState`'s
scan kickoff, and the deleted `WifiConnectingState`'s status message).

**5. Two hazards the design does not list.**

- *A typed Wi-Fi password survives.* `WifiSetupView` holds `password_field`
  and `phase`, and `WifiSetupState` reads `view.phase` as authoritative. Pooled
  without a hard reset, the screen re-opens in `PHASE_PASSWORD` with the
  previous visit's password still in the field. `reset()` forces `PHASE_SCAN`
  and clears both fields; `test_view_reset.py` names the test after it.
- *Worker threads write into a shared view.* Surveying the three suspects
  found only one real case. `WifiSetupState`'s scan and connect workers and
  `InstallState`'s installer all publish to state fields that `update()` drains
  on the main thread — already safe. `AgentSetupState._prepare` was the
  exception: it called `view.set_error(...)` directly off the UI thread, so a
  worker finishing after the user left would paint onto whatever screen was
  showing, or onto this screen's next visit after `reset()` had cleared it.
  Fixed with an epoch taken in `enter()` and dropped in `exit()`, checked by a
  `_publish()` helper before every worker→view write — the same generation
  guard `WifiSetupState._connect_gen` already used.

### Also worth knowing for §6

`tools/perf_viewer.py` and the `fps`/`rss_mb`/`load_pct` stream referenced by
§9 live in the **Pro** tree (`instrument_cluster_pro/perf/monitor.py`, armed
off `PERF_DEST` or `/data/perf-dest`), not here. This repo's
`core/system/performance_sender.py` is dead code — never instantiated — and
reports system-wide `MemTotal - MemAvailable` rather than process RSS. On-device
acceptance therefore runs on a Pro dev image.
