"""GTA VI trophy earn-rate forecaster (gta6-trophy-rarity-forecast-01).

Model, per trophy: take the case history's distinct page states (Exophase only
changes on its own refreshes, so repeated identical reads are one observation),
map each earn rate to the logit scale, and fit a weighted least-squares line of
logit(rate) against ln(1 + hours since release). Adoption curves decelerate, so
log-time extrapolation bends the trend instead of running it off a cliff; the
fitted slope is shrunk mildly toward persistence. The predictive spread on the
logit scale grows with the horizon and with the trophy's own fit residuals, so
volatile trophies get honestly wider bands. Everything is deterministic.
"""
import json
import math
import os
from datetime import datetime, timezone

LEVELS_Z = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817, 1.6448536269514722]


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def logit(p):
    p = min(max(p, 0.01), 99.99) / 100.0
    return math.log(p / (1.0 - p))


def inv_logit(x):
    return 100.0 / (1.0 + math.exp(-x))


def forecast_case(case):
    trophies = case["trophies"]
    history = case["history"]
    target = parse_ts(case["target"])
    horizon_days = case["horizon_minutes"] / 1440.0
    # Release origin: the game's release date at 00:00 UTC when parseable.
    try:
        rel = parse_ts(case["game"]["release_date"])
        origin = rel.replace(hour=0, minute=0, second=0, microsecond=0)
    except Exception:
        origin = parse_ts(history[0]["at"]).replace(hour=0, minute=0, second=0, microsecond=0)

    def x_of(ts):
        return math.log1p(max(0.0, (ts - origin).total_seconds() / 3600.0))

    x_target = x_of(target)

    # Distinct page states: a new state when players tracked or any rate moves.
    states = []
    prev_key = None
    for read in history:
        key = (read["players_tracked"], tuple(read["rates"]))
        if key != prev_key:
            states.append(read)
            prev_key = key
    if not states:
        states = history[-1:]

    rows = []
    for idx, tr in enumerate(trophies):
        pts = []
        for st in states:
            r = st["rates"][idx] if idx < len(st["rates"]) else None
            if r is not None:
                pts.append((x_of(parse_ts(st["at"])), logit(r)))
        last_logit = pts[-1][1] if pts else 0.0
        median = last_logit
        resid_sd = 0.0
        if len(pts) >= 3:
            # Weighted least squares, recent states weighted more.
            n = len(pts)
            ws = [1.0 + 2.0 * (i / (n - 1)) for i in range(n)]
            sw = sum(ws)
            mx = sum(w * x for w, (x, _) in zip(ws, pts)) / sw
            my = sum(w * y for w, (_, y) in zip(ws, pts)) / sw
            sxx = sum(w * (x - mx) ** 2 for w, (x, _) in zip(ws, pts))
            sxy = sum(w * (x - mx) * (y - my) for w, (_, y) in zip(ws, pts))
            if sxx > 1e-9:
                slope = sxy / sxx
                intercept = my - slope * mx
                pred = intercept + slope * x_target
                # Shrink the move away from the last value: extrapolation is
                # where forecasts go to die.
                median = last_logit + 0.85 * (pred - last_logit)
                resid = [y - (intercept + slope * x) for x, y in pts]
                resid_sd = math.sqrt(sum(r * r for r in resid) / len(resid))
        move = abs(median - last_logit)
        sigma = 0.30 + 0.50 * math.sqrt(horizon_days) + min(resid_sd, 1.0) + 0.25 * min(move, 1.5)
        sigma = min(max(sigma, 0.35), 2.4)
        q = [round(inv_logit(median + z * sigma), 4) for z in LEVELS_Z]
        q = [min(max(v, 0.0), 100.0) for v in q]
        q.sort()
        rows.append({"id": tr["id"], "q": q})
    return {"trophies": rows}


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    for name in sorted(os.listdir(in_dir)):
        if name.endswith(".in"):
            with open(os.path.join(in_dir, name), encoding="utf-8") as f:
                case = json.load(f)
            result = forecast_case(case)
            with open(os.path.join(out_dir, name[:-3] + ".out"), "w", encoding="utf-8") as f:
                json.dump(result, f)


if __name__ == "__main__":
    main()
