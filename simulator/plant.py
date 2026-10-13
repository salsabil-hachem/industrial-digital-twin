"""
plant.py - Simulated industrial asset: conveyor drive (DC motor + PI speed control).
This replaces the real machine: it generates the "sensor data".

Physics:
  Electrical (quasi-static, L/R << mechanical tau):  i = (V - K*w) / R(T)
  Mechanical:  J dw/dt = K*i - b*w - T_load
  Thermal:     C_th dT/dt = i^2 * R(T) - (T - T_amb) / R_th
  Copper resistance: R(T) = R0 * (1 + alpha * (T - 25))

Injectable faults:
  bearing_wear     -> viscous friction b grows over time + vibration rises
  overload         -> unexpected extra load torque (jam on the conveyor)
  cooling_failure  -> thermal resistance R_th increases (blocked fan)
"""
import numpy as np

NOMINAL = dict(
    R0=0.6,       # ohm, winding resistance at 25 C
    alpha=0.0039, # 1/C, copper temperature coefficient
    K=0.08,       # Nm/A = V/(rad/s), torque/back-EMF constant
    J=2e-3,       # kg.m^2, rotor + reflected load inertia
    b=1e-3,       # Nm/(rad/s), viscous friction
    C_th=30.0,    # J/C, thermal capacitance
    R_th=0.6,     # C/W, thermal resistance to ambient
    T_amb=25.0,   # C
    V_max=48.0,   # V, drive saturation
)


def load_profile(t):
    """Known process load (from the production schedule): conveyor cycles every 20 s."""
    return 0.25 + 0.15 * (np.sin(2 * np.pi * t / 20.0) > 0)  # Nm


def speed_setpoint(t):
    return 300.0  # rad/s (~2865 rpm)


class Plant:
    def __init__(self, dt=0.05, seed=0):
        self.p = dict(NOMINAL)
        self.dt = dt
        self.rng = np.random.default_rng(seed)
        self.t = 0.0
        self.w = 0.0
        self.temp = NOMINAL["T_amb"]
        self.i = 0.0
        self.V = 0.0
        self.integ = 0.0
        # fault states
        self.faults = {"bearing_wear": False, "overload": False, "cooling_failure": False}
        self.wear = 0.0  # 0 = new bearing, 1 = end of life
        self.tripped = False  # thermal protection (class F insulation limit)
        self.T_TRIP = 150.0

    def set_fault(self, name, active):
        self.faults[name] = active

    def _controller(self, w_ref):
        """PI speed controller with anti-windup."""
        kp, ki = 0.5, 4.0
        e = w_ref - self.w
        V = kp * e + ki * self.integ + self.p["K"] * w_ref
        if abs(V) < self.p["V_max"]:
            self.integ += e * self.dt
        return float(np.clip(V, 0.0, self.p["V_max"]))

    def step(self):
        p, dt = self.p, self.dt

        # --- fault effects on physical parameters ---
        if self.faults["bearing_wear"]:
            self.wear = min(1.0, self.wear + dt / 120.0)  # reaches end of life in ~120 s (accelerated)
        b = p["b"] * (1 + 4.0 * self.wear ** 2)
        R_th = p["R_th"] * (2.5 if self.faults["cooling_failure"] else 1.0)
        T_load = load_profile(self.t) + (0.35 if self.faults["overload"] else 0.0)

        # --- dynamics (explicit Euler, 5 substeps) ---
        n = 5
        h = dt / n
        for _ in range(n):
            if self.temp > self.T_TRIP:
                self.tripped = True
            self.V = 0.0 if self.tripped else self._controller(speed_setpoint(self.t))
            R = p["R0"] * (1 + p["alpha"] * (self.temp - 25.0))
            self.i = 0.0 if self.tripped else (self.V - p["K"] * self.w) / R  # trip = contactor open
            dw = (p["K"] * self.i - b * self.w - T_load) / p["J"]
            dT = (self.i ** 2 * R - (self.temp - p["T_amb"]) / R_th) / p["C_th"]
            self.w += h * dw
            self.temp += h * dT
        self.t += dt

        # --- sensors (with noise) ---
        vib = 0.8 + 6.0 * self.wear ** 1.5 + 0.4 * (T_load > 0.5)  # mm/s RMS (ISO 10816 scale)
        return dict(
            t=round(self.t, 3),
            voltage=self.V + self.rng.normal(0, 0.05),
            current=self.i + self.rng.normal(0, 0.03),
            speed=self.w + self.rng.normal(0, 0.5),
            temperature=self.temp + self.rng.normal(0, 0.1),
            vibration=max(0.0, vib + self.rng.normal(0, 0.08)),
            load_known=load_profile(self.t),
            # ground truth (for ML labels only, NOT visible to the twin)
            label=self.active_label(),
            wear=self.wear,
            tripped=self.tripped,
        )

    def active_label(self):
        active = [k for k, v in self.faults.items() if v]
        return "+".join(active) if active else "normal"
