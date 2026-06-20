#!/usr/bin/env python3
"""
MNA solver latency benchmark.

Tests DC and transient solve times for circuits of increasing complexity,
verifies results against analytical / known values, and reports NR iterations.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from physics.mna import (MNASolver, Resistor, Capacitor, Inductor,
                          VSource, Diode, BJT, MOSFET)

# ── helpers ───────────────────────────────────────────────────────────────────

def _solve_dc(devices):
    s = MNASolver()
    s.load(devices)
    return s, s.solve_dc()

def _solve_tran(devices, dt_ms, n_steps):
    s = MNASolver()
    s.load(devices)
    s.solve_dc()          # DC operating point (warm start)
    t0 = time.perf_counter()
    for _ in range(n_steps):
        v = s.step_tran(dt_ms)
    elapsed = time.perf_counter() - t0
    return s, v, elapsed

def _bench(label, fn, repeat=200):
    """Run fn() repeat times, return (median_us, result)."""
    times = []
    result = None
    for _ in range(repeat + 5):    # 5 warm-up
        t0 = time.perf_counter()
        result = fn()
        times.append((time.perf_counter() - t0) * 1e6)
    times.sort()
    median = times[len(times)//2]
    p95    = times[int(len(times)*0.95)]
    return median, p95, result

def _header(title):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")

def _row(label, median_us, p95_us, note=""):
    print(f"  {label:<38}  {median_us:>7.1f}µs  p95={p95_us:>7.1f}µs  {note}")

# ── 1. Resistor divider (3 nodes, pure linear) ───────────────────────────────

def bench_rdiv():
    _header("Resistor divider: VCC → R1(10k) → MID → R2(10k) → GND")
    # analytical: MID = VCC * R2/(R1+R2) = 3.3 * 0.5 = 1.65 V
    devs = [
        VSource("VCC", 3.3, "VCC", "GND"),
        Resistor("R1", 10e3, "VCC", "MID"),
        Resistor("R2", 10e3, "MID", "GND"),
    ]
    median, p95, v = _bench("DC solve", lambda: _solve_dc(devs)[1])
    mid = v.get("MID", float("nan"))
    err = abs(mid - 1.65)
    _row("3-node, 2R, 1 VSource", median, p95, f"Vmid={mid:.4f}V (err={err:.2e}V)")

# ── 2. LED + series R (5 nets, 1 nonlinear) ──────────────────────────────────

def bench_led():
    _header("LED + series R: GPIO(3.3V) → R(220Ω) → LED → GND")
    # LED: red, Vf≈2.0V, N=2.0, If≈(3.3-2.0)/220 ≈ 5.9mA
    Vt = 0.02585
    vf = 2.0; if_ma = 20e-3; N = 2.0
    IS = if_ma / (np.exp(vf / (N * Vt)) - 1.0)

    devs = [
        VSource("GPIO", 3.3, "LED_A", "GND"),
        Resistor("R1", 220.0, "LED_A", "LED_K"),
        Diode("D1", "LED_K", "GND", IS=IS, N=N),
    ]
    median, p95, v = _bench("DC solve", lambda: _solve_dc(devs)[1])
    v_led_k = v.get("LED_K", float("nan"))
    v_led_a = v.get("LED_A", float("nan"))
    i_led   = (v_led_a - v_led_k) / 220.0 * 1e3
    _row("5-net, 1R+1Diode, 1 VSource", median, p95,
         f"V_anode={v_led_a:.3f}V  V_cathode={v_led_k:.3f}V  I={i_led:.2f}mA")

# ── 3. RC transient (charging) ───────────────────────────────────────────────

def bench_rc():
    _header("RC transient: GPIO(3.3V) → R(1kΩ) → C(1µF) → GND")
    # τ = RC = 1ms.  At t=1ms: Vc = 3.3*(1 - e^-1) ≈ 2.086V
    devs = [
        VSource("GPIO", 3.3, "RC_IN", "GND"),
        Resistor("R1", 1e3, "RC_IN", "RC_OUT"),
        Capacitor("C1", 1e-6, "RC_OUT", "GND"),
    ]
    dt_ms   = 0.1
    n_steps = 10          # 1ms = 1τ
    _, v1ms, elapsed = _solve_tran(devs, dt_ms, n_steps)
    vc_1ms = v1ms.get("RC_OUT", float("nan"))
    analytical = 3.3 * (1.0 - np.exp(-1.0))

    # bench single step
    s = MNASolver(); s.load(devs); s.solve_dc()
    median, p95, _ = _bench("Transient step (dt=0.1ms)", lambda: s.step_tran(dt_ms))
    err = abs(vc_1ms - analytical)
    _row("3-net, 1R+1C, 1 VSource", median, p95,
         f"Vc@1ms={vc_1ms:.3f}V  analytical={analytical:.3f}V  err={err:.2e}V")

# ── 4. Full button+LED circuit ────────────────────────────────────────────────

def bench_button_led():
    _header("button+LED circuit  (IO2→R→LED→GND, IO4 with pullup→GND via button)")
    Vt = 0.02585; vf = 2.0; N = 2.0; if_ma = 20e-3
    IS = if_ma / (np.exp(vf / (N * Vt)) - 1.0)

    devs_off = [
        VSource("3V3", 3.3, "3V3", "GND"),
        VSource("IO2", 0.0, "LED_A", "GND"),   # LED off
        VSource("IO4_PU", 3.3, "BTN_SIG", "GND"),   # pullup (btn released)
        Resistor("R1",  220.0, "LED_A", "LED_K"),
        Diode("D1", "LED_K", "GND", IS=IS, N=N),
    ]
    devs_on = [
        VSource("3V3", 3.3, "3V3", "GND"),
        VSource("IO2", 3.3, "LED_A", "GND"),   # LED on
        VSource("BTN", 0.0, "BTN_SIG", "GND"), # button pressed
        Resistor("R1", 220.0, "LED_A", "LED_K"),
        Diode("D1", "LED_K", "GND", IS=IS, N=N),
    ]

    median_off, p95_off, v_off = _bench("LED OFF  (IO2=0V)", lambda: _solve_dc(devs_off)[1])
    median_on,  p95_on,  v_on  = _bench("LED ON   (IO2=3.3V)", lambda: _solve_dc(devs_on)[1])

    vk_off = v_off.get("LED_K", float("nan"))
    vk_on  = v_on.get("LED_K", float("nan"))
    va_on  = v_on.get("LED_A", float("nan"))
    i_on   = (va_on - vk_on) / 220.0 * 1e3

    _row("LED OFF", median_off, p95_off, f"V_LED_K={vk_off:.4f}V")
    _row("LED ON",  median_on,  p95_on,  f"V_LED_K={vk_on:.3f}V  I={i_on:.2f}mA")

# ── 5. BJT common-emitter switch ──────────────────────────────────────────────

def bench_bjt():
    _header("BJT common-emitter switch: 2N2222 (NPN)")
    # Base driven via 10k from 3.3V → Ib ≈ 0.26mA
    # Collector: 3.3V → 1kΩ → Collector → Emitter → GND
    # Expected: transistor saturates, Vce ≈ 0.2V, Ic ≈ 3.1mA
    devs = [
        VSource("VCC", 3.3, "VCC",  "GND"),
        VSource("VB",  3.3, "VB_IN","GND"),
        Resistor("RB", 10e3,  "VB_IN", "BASE"),
        Resistor("RC",  1e3,  "VCC",   "COL"),
        BJT("Q1", "COL", "BASE", "GND",
            polarity="NPN",
            IS=1e-14, BF=100, NF=1.0, VAF=74.0,
            ISE=6.73e-15, NE=1.66, BR=6, NR=1.0,
            RB=10.0, RC=1.0, RE=1.0),
    ]
    median, p95, v = _bench("DC solve (BJT saturated)", lambda: _solve_dc(devs)[1])
    vce = v.get("COL", float("nan"))
    vbe = v.get("BASE", float("nan"))
    ic  = (3.3 - vce) / 1e3 * 1e3   # mA through RC
    _row("5-net, 1BJT+2R, 2 VSource", median, p95,
         f"Vce={vce:.3f}V  Vbe={vbe:.3f}V  Ic≈{ic:.2f}mA")

# ── 6. MOSFET switch ──────────────────────────────────────────────────────────

def bench_mosfet():
    _header("NMOS switch: BSS138 (Vth≈1.5V, KP=270mA/V²)")
    # Gate = 3.3V, Drain via 1kΩ from 3.3V, Source = GND
    # Should be deep saturation: Id ≈ 3.3mA (limited by RD)
    devs = [
        VSource("VDD", 3.3, "VDD", "GND"),
        VSource("VG",  3.3, "GATE","GND"),
        Resistor("RD", 1e3, "VDD", "DRAIN"),
        MOSFET("M1", "DRAIN", "GATE", "GND",
               polarity="NMOS",
               VTO=1.5, KP=270e-3, LAMBDA=0.02,
               W=1e-4, L=1e-4),
    ]
    median, p95, v = _bench("DC solve (NMOS on)", lambda: _solve_dc(devs)[1])
    vd = v.get("DRAIN", float("nan"))
    id_ma = (3.3 - vd) / 1e3 * 1e3
    _row("4-net, 1NMOS+1R, 2 VSource", median, p95,
         f"Vdrain={vd:.4f}V  Id≈{id_ma:.2f}mA")

# ── 7. Large circuit: 30-node RC ladder ──────────────────────────────────────

def bench_large():
    _header("RC ladder: 30-stage (60 nodes), pure linear")
    N = 30
    devs = [VSource("VS", 3.3, "N0", "GND")]
    for i in range(N):
        devs.append(Resistor(f"R{i}", 1e3,  f"N{i}", f"N{i+1}"))
        devs.append(Capacitor(f"C{i}", 10e-9, f"N{i+1}", "GND"))

    s = MNASolver(); s.load(devs)
    median_dc, p95_dc, v_dc = _bench(f"DC solve ({N*2} devices, {N+1} nodes)",
                                      s.solve_dc, repeat=100)
    _row(f"{N}-stage RC ladder  DC", median_dc, p95_dc,
         f"V_last={v_dc.get(f'N{N}', float('nan')):.4f}V")

    s2 = MNASolver(); s2.load(devs); s2.solve_dc()
    median_tr, p95_tr, _ = _bench(f"Transient step  dt=0.01ms",
                                   lambda: s2.step_tran(0.01), repeat=100)
    _row(f"{N}-stage RC ladder  tran", median_tr, p95_tr)

# ── 8. Mixed circuit: BJT amp + RC ────────────────────────────────────────────

def bench_mixed():
    _header("Mixed: BJT amp + 3-stage RC filter  (~20 nodes, nonlinear)")
    devs = [
        VSource("VCC", 5.0, "VCC", "GND"),
        VSource("VIN", 3.0, "VIN", "GND"),

        # BJT common-emitter amp
        Resistor("R1",  47e3,  "VCC", "BASE"),
        Resistor("R2",  10e3,  "BASE","GND"),
        Resistor("RC1",  4.7e3,"VCC", "COL"),
        Resistor("RE1",  1e3,  "EMI", "GND"),
        Capacitor("CB",  10e-6, "VIN", "BASE"),
        Capacitor("CE",  47e-6, "EMI", "GND"),
        BJT("Q1", "COL","BASE","EMI", polarity="NPN",
            IS=1e-14, BF=150, VAF=100.0),

        # 3-stage RC low-pass after collector
        Resistor("RF1", 1e3,  "COL",  "F1"),
        Capacitor("CF1", 10e-9, "F1",  "GND"),
        Resistor("RF2", 1e3,  "F1",   "F2"),
        Capacitor("CF2", 10e-9, "F2",  "GND"),
        Resistor("RF3", 1e3,  "F2",   "F3"),
        Capacitor("CF3", 10e-9, "F3",  "GND"),
    ]
    s = MNASolver(); s.load(devs)
    median_dc, p95_dc, v_dc = _bench("DC solve", s.solve_dc, repeat=100)
    _row("BJT + 3×RC", median_dc, p95_dc,
         f"Vcol={v_dc.get('COL',float('nan')):.3f}V")

    s2 = MNASolver(); s2.load(devs); s2.solve_dc()
    median_tr, p95_tr, _ = _bench("Transient step  dt=0.01ms",
                                   lambda: s2.step_tran(0.01), repeat=100)
    _row("BJT + 3×RC  tran", median_tr, p95_tr)

# ── summary ───────────────────────────────────────────────────────────────────

def bench_summary():
    """Quick solve-time table for the most common circuit sizes."""
    _header("Summary: solve time vs. circuit size")
    print(f"  {'Circuit':<38}  {'DC median':>10}  {'DC p95':>10}")
    print(f"  {'':-<38}  {'':-<10}  {'':-<10}")

    cases = [
        ("1 VSource + 1R (2-node)",
         [VSource("V1",3.3,"A","GND"), Resistor("R1",1e3,"A","GND")]),
        ("1 VSource + 2R divider (3-node)",
         [VSource("V1",3.3,"A","GND"), Resistor("R1",10e3,"A","B"), Resistor("R2",10e3,"B","GND")]),
        ("LED circuit with diode (5-node)",
         [VSource("V1",3.3,"A","GND"), Resistor("R1",220,"A","B"),
          Diode("D1","B","GND",IS=1e-12,N=2.0)]),
        ("BJT switch (5-node)",
         [VSource("VCC",3.3,"VCC","GND"), VSource("VB",3.3,"VBI","GND"),
          Resistor("RB",10e3,"VBI","B"), Resistor("RC",1e3,"VCC","C"),
          BJT("Q1","C","B","GND",polarity="NPN",IS=1e-14,BF=100)]),
        ("NMOS switch (4-node)",
         [VSource("VDD",3.3,"VDD","GND"), VSource("VG",3.3,"G","GND"),
          Resistor("RD",1e3,"VDD","D"),
          MOSFET("M1","D","G","GND",polarity="NMOS",VTO=1.5,KP=270e-3)]),
        ("10-stage RC ladder (11-node, linear)",
         [VSource("VS",3.3,"N0","GND")]
         + [d for i in range(10)
            for d in (Resistor(f"R{i}",1e3,f"N{i}",f"N{i+1}"),
                      Capacitor(f"C{i}",10e-9,f"N{i+1}","GND"))]),
        ("20-stage RC ladder (21-node, linear)",
         [VSource("VS",3.3,"N0","GND")]
         + [d for i in range(20)
            for d in (Resistor(f"R{i}",1e3,f"N{i}",f"N{i+1}"),
                      Capacitor(f"C{i}",10e-9,f"N{i+1}","GND"))]),
    ]

    for label, devs in cases:
        s = MNASolver(); s.load(devs)
        med, p95, _ = _bench(label, s.solve_dc, repeat=300)
        print(f"  {label:<38}  {med:>9.1f}µs  {p95:>9.1f}µs")


# ── main ──────────────────────────────────────────────────────────────────────

def bench_adaptive():
    """Show how solve_interval skips work vs naive fixed-dt stepping."""
    _header("Adaptive stepping — solve_interval() vs fixed-dt")

    Vt = 0.02585; N = 2.0; if_ma = 20e-3; vf = 2.0
    IS = if_ma / (np.exp(vf / (N * Vt)) - 1.0)

    # ── pure-resistive LED circuit ────────────────────────────────────────────
    devs_res = [
        VSource("GPIO", 3.3, "LED_A", "GND"),
        Resistor("R1", 220.0, "LED_A", "LED_K"),
        Diode("D1", "LED_K", "GND", IS=IS, N=N),
    ]

    # simulate delay(500) with fixed dt=1ms  → 500 solves
    s_fixed = MNASolver(); s_fixed.load(devs_res); s_fixed.solve_dc()
    t0 = time.perf_counter()
    for _ in range(500):
        s_fixed.step_tran(1.0)
    t_fixed = (time.perf_counter() - t0) * 1e3

    # same delay with solve_interval — should do 1 DC solve then skip
    s_adaptive = MNASolver(); s_adaptive.load(devs_res)
    t0 = time.perf_counter()
    for _ in range(10):          # 10 × delay(50ms) calls
        s_adaptive.solve_interval(50.0, gpio_changed=False)
    t_adaptive = (time.perf_counter() - t0) * 1e3

    print(f"\n  LED circuit (no caps): delay(500ms) equivalent")
    print(f"  Fixed dt=1ms (500 steps):      {t_fixed:>7.2f}ms CPU")
    print(f"  solve_interval (skip-stable):  {t_adaptive:>7.2f}ms CPU")
    print(f"  Speedup:  {t_fixed / max(t_adaptive, 0.001):.0f}×")

    # ── RC circuit: compare fixed vs adaptive across delay(100ms) ────────────
    devs_rc = [
        VSource("GPIO", 3.3, "RC_IN", "GND"),
        Resistor("R1", 1e3, "RC_IN", "RC_OUT"),
        Capacitor("C1", 10e-6, "RC_OUT", "GND"),    # τ = 10ms
    ]

    s_fixed2 = MNASolver(); s_fixed2.load(devs_rc); s_fixed2.solve_dc()
    t0 = time.perf_counter()
    for _ in range(100):         # fixed dt=1ms, 100 steps for 100ms
        s_fixed2.step_tran(1.0)
    t_fixed2 = (time.perf_counter() - t0) * 1e3

    s_adap2 = MNASolver(); s_adap2.load(devs_rc)
    t0 = time.perf_counter()
    s_adap2.solve_interval(100.0, gpio_changed=True,
                           dt_max_ms=1.0, dt_min_ms=0.1)
    t_adap2 = (time.perf_counter() - t0) * 1e3

    print(f"\n  RC circuit (τ=10ms): delay(100ms) = 10τ")
    print(f"  Fixed dt=1ms (100 steps):      {t_fixed2:>7.2f}ms CPU")
    print(f"  solve_interval (stops at 3τ):  {t_adap2:>7.2f}ms CPU")
    print(f"  Speedup:  {t_fixed2 / max(t_adap2, 0.001):.1f}×")


def bench_numba():
    """Compare first-call (cold) vs warm Numba kernel times."""
    from physics.mna.devices.kernels import diode_eval, bjt_gummel_poon, mosfet_ids
    _header("Numba kernel warm-up")

    # warm up (already compiled from bench_led etc, but force here)
    diode_eval(0.7, 1e-12, 2.0, 0.02585, 1e30, 1e-3)
    bjt_gummel_poon(0.7, -3.0, 1e-14, 100, 1.0, 74.0, 1e30,
                    6.73e-15, 1.66, 6, 1.0, 1e30, 1e30, 0, 2.0, 0.02585)
    mosfet_ids(2.0, 1.0, 0.0, 1.5, 0.27, 0.0, 0.6, 0.02)

    # bench warmed kernels
    N = 100_000
    t0 = time.perf_counter()
    for _ in range(N):
        diode_eval(0.7, 1e-12, 2.0, 0.02585, 1e30, 1e-3)
    t_diode = (time.perf_counter() - t0) * 1e9 / N

    t0 = time.perf_counter()
    for _ in range(N):
        bjt_gummel_poon(0.7, -3.0, 1e-14, 100, 1.0, 74.0, 1e30,
                        6.73e-15, 1.66, 6, 1.0, 1e30, 1e30, 0, 2.0, 0.02585)
    t_bjt = (time.perf_counter() - t0) * 1e9 / N

    t0 = time.perf_counter()
    for _ in range(N):
        mosfet_ids(2.0, 1.0, 0.0, 1.5, 0.27, 0.0, 0.6, 0.02)
    t_mos = (time.perf_counter() - t0) * 1e9 / N

    print(f"  diode_eval (Shockley):          {t_diode:>6.1f}ns / call")
    print(f"  bjt_gummel_poon (Ebers-Moll):   {t_bjt:>6.1f}ns / call")
    print(f"  mosfet_ids (Shichman-Hodges):   {t_mos:>6.1f}ns / call")


if __name__ == "__main__":
    print("MNA Solver — Latency Benchmark  (Numba + Sparse + Adaptive)")
    print("numpy:", np.__version__)

    import importlib.util
    has_numba = importlib.util.find_spec("numba") is not None
    has_scipy = importlib.util.find_spec("scipy") is not None
    print(f"numba: {'✓' if has_numba else '✗ (fallback to numpy)'}  "
          f"scipy: {'✓' if has_scipy else '✗'}")
    print()

    # Warm up Numba JIT (first call compiles; don't count it in benchmarks)
    if has_numba:
        print("Warming up Numba JIT... ", end="", flush=True)
        from physics.mna.devices.kernels import diode_eval, bjt_gummel_poon, mosfet_ids
        diode_eval(0.7, 1e-12, 2.0, 0.02585, 1e30, 1e-3)
        bjt_gummel_poon(0.7, -3.0, 1e-14, 100, 1.0, 74.0, 1e30,
                        6.73e-15, 1.66, 6, 1.0, 1e30, 1e30, 0, 2.0, 0.02585)
        mosfet_ids(2.0, 1.0, 0.0, 1.5, 0.27, 0.0, 0.6, 0.02)
        print("done")

    bench_rdiv()
    bench_led()
    bench_rc()
    bench_button_led()
    bench_bjt()
    bench_mosfet()
    bench_large()
    bench_mixed()
    bench_summary()
    bench_adaptive()
    bench_numba()
    print(f"\n{'─'*60}")
    print("  Done.")
