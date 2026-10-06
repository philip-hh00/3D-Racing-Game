"""Headless Netcode-Benchmark fuer die Wiedergabe ferner Fahrzeuge.

Ein Kreis mit 300 px/s, gesendet mit 30 Hz, 25 ms Laufzeit und 12 ms
Schwankung. Bis 06.10.2026 verglich dieser Test die Snapshot-Interpolation mit
Dead Reckoning und verlangte, dass Dead Reckoning *naeher an der Echtzeit*
liegt — das tut es immer, nur ruckelt es dafuer und springt zurueck (siehe
``tests/test_remote_vehicle_netzstrom.py``). Gemessen wird jetzt, worauf es
ankommt: keine Tempospruenge, kaum Hochrechnung, ein kleiner, ruhiger Abstand.
"""
from __future__ import annotations

import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymunk
from src.entities.remote_vehicle import RemoteVehicle, INTERP_DELAY_MAX
import src.entities.remote_vehicle as rv_mod

LATENZ = 0.025
SCHWANKUNG = 0.012
TEMPO = 300.0


def run_benchmark() -> dict:
    """10 s Kreisfahrt, 30 Hz gesendet, 60 fps gezeichnet."""
    space = pymunk.Space()
    rv = RemoteVehicle(vehicle_id=1, sender_slot=1, space=space)

    duration = 10.0
    send_dt = 1.0 / 30.0
    render_dt = 1.0 / 60.0

    sender_packets = []
    t_send = 0.0
    while t_send <= duration:
        angle = t_send * 1.0
        x = 500.0 + 300.0 * math.cos(angle)
        y = 500.0 + 300.0 * math.sin(angle)
        vx = -300.0 * math.sin(angle)
        vy = 300.0 * math.cos(angle)
        sender_packets.append({
            "send_time": t_send,
            "arrival_time": t_send + LATENZ + (SCHWANKUNG * math.sin(t_send * 17.0)),
            "snap": {
                "id": 1, "x": x, "y": y, "vx": vx, "vy": vy,
                "angle": angle, "omega": 1.0, "lap": 1, "wp": int(t_send * 5)
            }
        })
        t_send += send_dt

    cur_t = 0.0
    pkt_idx = 0
    gaps = []
    speeds = []
    extrap_frames = 0
    total_frames = 0
    speed_jumps = 0
    prev_pos = None
    alt_clock = rv_mod._clock
    try:
        while cur_t <= duration:
            rv_mod._clock = lambda: cur_t
            while pkt_idx < len(sender_packets) and sender_packets[pkt_idx]["arrival_time"] <= cur_t:
                pkt = sender_packets[pkt_idx]
                rv.apply_snapshot(pkt["snap"], send_time=pkt["send_time"], arrival=pkt["arrival_time"])
                pkt_idx += 1
            rv.update(render_dt)
            drawn_pos = rv._pos

            # Anlauf des Puffers nicht mitzaehlen.
            if rv._initialized and cur_t > 0.5:
                total_frames += 1
                if rv._render_time is not None and rv._render_time > rv._buffer[-1].t:
                    extrap_frames += 1
                true_x = 500.0 + 300.0 * math.cos(cur_t)
                true_y = 500.0 + 300.0 * math.sin(cur_t)
                gaps.append(math.dist(drawn_pos, (true_x, true_y)))
                if prev_pos:
                    spd = math.dist(drawn_pos, prev_pos) / render_dt
                    speeds.append(spd)
                    if spd > 1.3 * TEMPO or spd < 0.7 * TEMPO:
                        speed_jumps += 1
            prev_pos = drawn_pos
            cur_t += render_dt
    finally:
        rv_mod._clock = alt_clock

    avg_speed = sum(speeds) / max(1, len(speeds))
    speed_variance = sum((s - avg_speed) ** 2 for s in speeds) / max(1, len(speeds))
    return {
        "total_frames": total_frames,
        "avg_gap_px": round(sum(gaps) / max(1, len(gaps)), 2),
        "max_gap_px": round(max(gaps) if gaps else 0.0, 2),
        "extrap_pct": round(100.0 * extrap_frames / max(1, total_frames), 1),
        "speed_jumps": speed_jumps,
        "speed_stddev": round(math.sqrt(speed_variance), 2),
    }


def test_wiedergabe_ist_ruhig_und_nah():
    m = run_benchmark()
    print("\n" + "  ".join(f"{k}={v}" for k, v in m.items()))
    assert m["speed_jumps"] == 0
    assert m["speed_stddev"] < 0.05 * TEMPO
    # Interpoliert, nicht geraten: hochgerechnet wird so gut wie nie.
    assert m["extrap_pct"] < 2.0
    # Abstand zum echten Wagen: Laufzeit plus Puffer, nicht mehr.
    assert m["max_gap_px"] < TEMPO * (LATENZ + SCHWANKUNG + INTERP_DELAY_MAX)


if __name__ == "__main__":
    test_wiedergabe_ist_ruhig_und_nah()
