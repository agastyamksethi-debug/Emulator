# Emulator — Design: Adaptive Multi-Fidelity Pre-Production Simulation

## Goal
Move the simulator from "does my firmware behave" to **"is my board wired correctly
before I fab it."** Catch miswiring (floating pins, missing pull-ups, power errors,
bus-speed limits, contention) and surface it visually — without making a complex
board slow to simulate.

## The core idea
Treat the board as a **digital sea with analog islands**. A static analysis pass
("compile" step) identifies the electrically-significant phenomena, assigns each the
cheapest sufficient solver, characterizes it once, caches the result, and re-uses it
across runs. Tolerances are applied as corners so we catch "passes nominal, fails at a
corner" bugs.

This is adaptive multi-fidelity simulation with a static planner, memoized
characterization, and corner/tolerance analysis.

## Layers

### Layer 0 — Pin contracts + tolerances (metadata)  ← implemented in core/contracts.py
Descriptors declare, per pin, an electrical `role` (power_in/power_out/gnd/
digital_in/digital_out/open_drain/analog_in/analog_out/i2c/nc), whether it is
`required`, a `v_min`/`v_max` window (for power), and `needs_pullup`. Components
declare a `tolerance` (fractional); passives fall back to class defaults
(R 1%, C 10%, L/FB 10%, else 5%). Everything downstream reasons over this metadata.

### Layer 1 — Identifier / planner (static, the "compile" pass)
Scans netlist + contracts and emits a **SimPlan**: a list of *phenomena*, each tagged
with `(region, solver tier, params, cache key, tolerance spec)`. Template-driven (not
general graph partitioning), recognizing:
- **power_sequence** — rails/regulators/bulk+decoupling caps → bring-up order + RC ramp.
- **bus_rc** — I2C/SPI nets: pull-up R × bus capacitance → rise time → max safe clock.
- **pullup_opendrain** — open-drain nets, pull presence, resulting logic levels.
- **divider / reference** — analog reference accuracy under load.
- **switching** — fast-toggling nodes that may need finer local dt.
- **fault / unknown** — floating required pins, missing pull-ups, driver contention.

The same scan doubles as the **ERC** pass (emits diagnostics).

### Layer 2 — Tiered solvers + characterization cache
- **Standard** — today's behavioural GPIO propagation (cheap; most of the board).
- **Intermediate** — a library of closed-form analytic templates keyed by recognized
  topology (RC rise/fall, power ramp, debounce). Not a general solver.
- **Advanced** — the existing-but-unwired MNA solver (`physics/mna/`) run on the
  *subcircuit only*. Boundary stitching via Thévenin/Norton equivalents at region ports.

Each phenomenon is characterized once; results (τ, rise time, max clock, power-up
timeline, DC operating point) are memoized by a **content-hash cache key** over the
region's topology + values + params + tier. Region-level invalidation: change one
component → only that region re-simulates. Scopes: in-session + on-disk per board.

### Layer 3 — Device contracts (per-part self-checks)
Each model validates preconditions each tick and emits anomalies instead of faking
data (MPU with VCC=0 → no ACK; AD0 floating → address indeterminate → NAK). Makes a
miswire *behave* wrong, not just report wrong.

### Layer 4 — Diagnostics + overlays
One structured stream `Diagnostic(severity, parts, nets, pins, message, code)` written
by all layers. GUI draws pin halos / dashed-red nets / part badges + a Problems panel.

## Worked example — disconnected AD0
- L1 ERC: "U1.AD0 floating — I2C address indeterminate" (warning, instant).
- L2: AD0 net high-Z, no defined logic level.
- L3: MPU can't resolve 0x68 vs 0x69 → no ACK → reads fail.
- L4: AD0 pin glows red, net highlighted, Problems entry, serial read fails.

## How it maps to the codebase
- `core/fidelity.py` `auto_select` grows into the per-region **planner**.
- `physics/mna/` = the **Advanced** solver (currently unused).
- `physics/passive.py` already half-does the **Intermediate** RC math — formalize + cache.
- `core/protocols/gpio.py` `_drivers` enables a cheap conflict/floating detector before full MNA.
- Descriptors + `core/contracts.py` = **Layer 0**.
- `gui/rw_canvas.py` + a new Problems panel = **Layer 4**.

## Phased plan
- **Phase 0 (done locally):** DESIGN.md, metadata schema + loader (`core/contracts.py`),
  proof-set contracts (ESP32, MPU6050; passive tolerance defaults), autonomy settings,
  pushed to GitHub for phone/cloud sessions.
- **Phase 1 (thin vertical slice):** `core/analyzer.py` identifying **power_sequence**
  and **bus_rc** on the MPU board; Intermediate characterizers; content-hash cache
  (prove cache-hit on re-run); tolerance corners → rise-time band + spec-violation flag;
  missing-pull-up / floating-AD0 fault diagnostics. Headless tests; existing sketches
  still pass. No GUI overlays yet.
- **Phase 2+:** widen the template library, wire MNA for advanced islands, GUI overlays
  + Problems panel, on-disk cache, runtime ±δ jitter on passives/rails.

## Prerequisites / risks
- Metadata coverage is the gate — the planner is only as good as the contracts.
- Cache-key correctness/invalidation is the top correctness risk (key must capture
  everything the result depends on).
- Coupling cheap↔expensive solvers at region boundaries (co-simulation) is the hard 20%.
- Keep the Basic tier fast; gate heavy solving behind the Advanced fidelity tier.

## Repo orientation (for a fresh/cloud session)
- Two domains: electrical (`core/bus.py` + `core/protocols/`) and real-world
  (`core/rw_bus.py`). Two firmware paths: compiled C++ shim (`firmware/sim_arduino.h`
  + `core/cpp_runtime.py`, the real one) and the legacy Python `ArduinoShim`.
- `core/runner.py` ticks at 1 ms; `core/registry.py` resolves parts (ref-prefix decides
  passive vs active — add new prefixes to `PREFIX_CATEGORY`).
- Fidelity tiers in `core/fidelity.py`; GUI in `gui/`; parts in `parts/<name>/`.
- PWM is DC-averaged; sim is real-time-paced; `*_sim` binaries + `crash.log` are ignored.
