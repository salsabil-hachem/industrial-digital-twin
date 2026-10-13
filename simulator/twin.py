"""
twin.py - Digital twin: a NOMINAL (healthy) model running in parallel with the plant.

It only sees what a real twin would see: sensor measurements + the known load schedule.
It never sees the injected faults or the true parameters.

Residuals (measured - predicted):
  r_current : current not explained by the healthy torque balance -> friction or extra load
  r_temp    : heating not explained by the healthy thermal model  -> cooling problem
  r_vib     : vibration above the healthy baseline                  -> bearing degradation
"""
from plant import NOMINAL


class DigitalTwin:
    def __init__(self, dt=0.05):
        self.p = dict(NOMINAL)
        self.dt = dt
        self.temp_pred = NOMINAL["T_amb"]
        self.w_filt = None
        self.dw_filt = 0.0
        self.vib_baseline = 0.8  # mm/s, commissioning value of the healthy machine
        # residual low-pass filters (reject sensor noise)
        self.r_i = self.r_T = self.r_v = 0.0

    def update(self, m):
        p, dt = self.p, self.dt

        # filtered speed derivative (sensor speed is noisy)
        if self.w_filt is None:
            self.w_filt = m["speed"]
        w_prev = self.w_filt
        self.w_filt += 0.3 * (m["speed"] - self.w_filt)
        self.dw_filt += 0.3 * ((self.w_filt - w_prev) / dt - self.dw_filt)

        # 1) mechanical twin: current needed by a HEALTHY machine
        i_pred = (p["J"] * self.dw_filt + p["b"] * self.w_filt + m["load_known"]) / p["K"]

        # 2) thermal twin driven by the measured current, with nominal cooling
        R = p["R0"] * (1 + p["alpha"] * (self.temp_pred - 25.0))
        self.temp_pred += dt * (m["current"] ** 2 * R - (self.temp_pred - p["T_amb"]) / p["R_th"]) / p["C_th"]

        # 3) residuals (exponential smoothing)
        a = 0.1
        self.r_i += a * ((m["current"] - i_pred) - self.r_i)
        self.r_T += a * ((m["temperature"] - self.temp_pred) - self.r_T)
        self.r_v += a * ((m["vibration"] - self.vib_baseline) - self.r_v)

        diagnosis, health = self.diagnose()
        return dict(
            current_pred=i_pred,
            temperature_pred=self.temp_pred,
            r_current=self.r_i,
            r_temp=self.r_T,
            r_vib=self.r_v,
            health=health,
            diagnosis=diagnosis,
        )

    def diagnose(self):
        """Rule-based fault isolation from the residual signature."""
        TH_I, TH_T, TH_V = 1.0, 5.0, 0.8  # A, C, mm/s
        hi_i, hi_T, hi_v = self.r_i > TH_I, self.r_T > TH_T, self.r_v > TH_V
        faults = []
        if hi_v:
            faults.append("bearing_wear")
        elif hi_i:
            faults.append("overload")  # extra current without vibration -> unexpected load
        if hi_T:
            faults.append("cooling_failure")

        # health index 0..100 from normalized residuals
        score = max(self.r_i / 6.0, self.r_T / 40.0, self.r_v / 5.0, 0.0)
        health = max(0.0, 100.0 * (1 - min(score, 1.0)))
        return ("+".join(faults) if faults else "normal"), health
