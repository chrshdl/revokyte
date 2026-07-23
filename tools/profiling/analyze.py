"""Classify a cluster profile into wait / GL / app / library buckets and
rank app-code entries by tottime."""

import pstats
import sys


def classify(key):
    fn, line, name = key
    if name in ("{built-in method pygame.display.flip}",):
        return "wait:vsync-flip"
    if "'pygame.time.Clock'" in name:
        return "wait:clock-tick"
    if "/OpenGL/" in fn or name.startswith("{built-in method OpenGL"):
        return "gl:pyopengl"
    if "/instrument_cluster/" in fn:
        return "app"
    if "/pydantic" in fn:
        return "pydantic"
    if "/pygame/" in fn or "pygame" in name:
        return "pygame"
    return "other"


def load(path):
    st = pstats.Stats(path)
    return st


def summary(path):
    st = load(path)
    total = st.total_tt
    buckets = {}
    for key, (cc, nc, tt, ct, callers) in st.stats.items():
        b = classify(key)
        buckets[b] = buckets.get(b, 0.0) + tt
    ticks = 0
    for key, (cc, nc, tt, ct, callers) in st.stats.items():
        if "'pygame.time.Clock'" in key[2]:
            ticks = nc
    print(f"== {path}")
    print(f"   total profiled time: {total:.1f}s, frames(tick calls): {ticks}, fps ~ {ticks / total:.1f}")
    for b in sorted(buckets, key=buckets.get, reverse=True):
        print(f"   {b:18s} {buckets[b]:8.2f}s  {buckets[b] / total * 100:5.1f}%")
    print()
    return st, total


def top_app(path, n=30):
    st = load(path)
    total = st.total_tt
    rows = []
    for key, (cc, nc, tt, ct, callers) in st.stats.items():
        if classify(key) in ("app", "pydantic", "pygame", "other", "gl:pyopengl"):
            rows.append((tt, ct, nc, key))
    rows.sort(reverse=True)
    print(f"== {path}: top non-wait entries by tottime (total {total:.1f}s)")
    for tt, ct, nc, (fn, line, name) in rows[:n]:
        short = fn.split("site-packages/")[-1]
        print(f"  {tt:7.3f}s tot {ct:7.3f}s cum {nc:7d}x  {short}:{line} {name}")
    print()


def callers_of(path, pattern):
    st = load(path)
    print(f"== {path}: callers of '{pattern}'")
    st.print_callers(pattern)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "summary":
        for p in sys.argv[2:]:
            summary(p)
    elif cmd == "top":
        for p in sys.argv[2:]:
            top_app(p)
    elif cmd == "callers":
        callers_of(sys.argv[2], sys.argv[3])
