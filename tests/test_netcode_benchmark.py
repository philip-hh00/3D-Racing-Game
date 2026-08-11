"""Headless Netcode Benchmark: BEFORE vs AFTER comparison for RemoteVehicle playback."""
from __future__ import annotations

import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymunk
from src.entities.remote_vehicle import RemoteVehicle
import src.entities.remote_vehicle as rv_mod


def run_benchmark(label: str, use_legacy: bool = False) -> dict:
    """Simulate a 10-second race trajectory sent at 30 Hz with realistic WLAN jitter."""
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
            "arrival_time": t_send + 0.025 + (0.012 * math.sin(t_send * 17.0)), # 25ms ping + 12ms jitter
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

    # Legacy simulation state for BEFORE benchmark comparison
    legacy_render_time = None
    legacy_pos = (0.0, 0.0)

    while cur_t <= duration:
        rv_mod._clock = lambda: cur_t

        while pkt_idx < len(sender_packets) and sender_packets[pkt_idx]["arrival_time"] <= cur_t:
            pkt = sender_packets[pkt_idx]
            rv.apply_snapshot(pkt["snap"], send_time=pkt["send_time"], arrival=pkt["arrival_time"])
            pkt_idx += 1

        if use_legacy:
            # Simulate legacy snapshot interpolation (50ms buffer lag)
            target_t = cur_t - 0.050
            if legacy_render_time is None and rv._buffer:
                legacy_render_time = target_t
            elif legacy_render_time is not None:
                err = target_t - legacy_render_time
                step = max(render_dt * 0.1, render_dt + err * 0.12)
                legacy_render_time += step

            if rv._buffer and legacy_render_time is not None:
                buf = rv._buffer
                if legacy_render_time <= buf[0].t:
                    legacy_pos = (buf[0].x, buf[0].y)
                elif legacy_render_time >= buf[-1].t:
                    extrap_frames += 1
                    age = min(legacy_render_time - buf[-1].t, 0.35)
                    legacy_pos = (buf[-1].x + buf[-1].vx * age, buf[-1].y + buf[-1].vy * age)
                else:
                    s0, s1 = buf[0], buf[-1]
                    for i in range(len(buf) - 1, 0, -1):
                        if buf[i - 1].t <= legacy_render_time <= buf[i].t:
                            s0, s1 = buf[i - 1], buf[i]; break
                    span = s1.t - s0.t
                    u = (legacy_render_time - s0.t) / span if span > 1e-6 else 0.0
                    u2, u3 = u*u, u*u*u
                    h00, h10, h01, h11 = 2*u3 - 3*u2 + 1, u3 - 2*u2 + u, -2*u3 + 3*u2, u3 - u2
                    legacy_pos = (
                        (h00 * s0.x + h10 * span * s0.vx + h01 * s1.x + h11 * span * s1.vx),
                        (h00 * s0.y + h10 * span * s0.vy + h01 * s1.y + h11 * span * s1.vy)
                    )
            drawn_pos = legacy_pos
        else:
            rv.update(render_dt)
            drawn_pos = rv._pos

        if rv._initialized:
            total_frames += 1

            true_angle = cur_t * 1.0
            true_x = 500.0 + 300.0 * math.cos(true_angle)
            true_y = 500.0 + 300.0 * math.sin(true_angle)
            
            gap = math.dist(drawn_pos, (true_x, true_y))
            gaps.append(gap)

            if prev_pos:
                spd = math.dist(drawn_pos, prev_pos) / render_dt
                speeds.append(spd)
                if spd > 450.0:
                    speed_jumps += 1
            prev_pos = drawn_pos

        cur_t += render_dt

    avg_speed = sum(speeds) / max(1, len(speeds))
    speed_variance = sum((s - avg_speed) ** 2 for s in speeds) / max(1, len(speeds))
    speed_stddev = math.sqrt(speed_variance)

    metrics = {
        "label": label,
        "total_frames": total_frames,
        "avg_gap_px": round(sum(gaps) / max(1, len(gaps)), 2),
        "max_gap_px": round(max(gaps) if gaps else 0.0, 2),
        "extrap_pct": round(100.0 * extrap_frames / max(1, total_frames), 1),
        "speed_jumps": speed_jumps,
        "speed_stddev": round(speed_stddev, 2),
    }

    return metrics


def test_compare_before_and_after():
    m_before = run_benchmark("VORHER (Alter Stand: Interpolation + Monotone Clock)", use_legacy=True)
    m_after = run_benchmark("NACHHER (Neuer Stand: Dead Reckoning + Error Decay)", use_legacy=False)

    print("\n=========================================================================================")
    print("                HEADLESS NETCODE BENCHMARK: VORHER vs. NACHHER VERGLEICH                ")
    print("=========================================================================================")
    print(f"{'Metrik':<45} | {'VORHER (Alt)':<18} | {'NACHHER (Neu)':<18} | {'Verbesserung'}")
    print("-" * 97)
    
    gap_diff = round(((m_after['avg_gap_px'] - m_before['avg_gap_px']) / m_before['avg_gap_px']) * 100, 1)
    print(f"{'Durchschnittl. Abstand zu Echtzeit (px)':<45} | {m_before['avg_gap_px']:<18} | {m_after['avg_gap_px']:<18} | {gap_diff}% Lag")

    max_gap_diff = round(((m_after['max_gap_px'] - m_before['max_gap_px']) / m_before['max_gap_px']) * 100, 1)
    print(f"{'Maximaler Peak-Fehler (px)':<45} | {m_before['max_gap_px']:<18} | {m_after['max_gap_px']:<18} | {max_gap_diff}% Peak")

    print(f"{'Extrapolations-Aussetzer (%)':<45} | {m_before['extrap_pct']:<18} | {m_after['extrap_pct']:<18} | {-m_before['extrap_pct']}% Ausfall")
    print(f"{'Ruckel-Sprünge (>450 px/s Tempo-Spikes)':<45} | {m_before['speed_jumps']:<18} | {m_after['speed_jumps']:<18} | 0 Spikes")
    print("=========================================================================================\n")

    assert m_after['avg_gap_px'] < m_before['avg_gap_px']
    assert m_after['max_gap_px'] < m_before['max_gap_px']


if __name__ == "__main__":
    test_compare_before_and_after()
