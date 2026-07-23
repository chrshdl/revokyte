"""Per-packet cost of the UDP feed deserialization path on this hardware.

The UDP reader thread does: sock.recvfrom -> data.decode -> json.loads ->
TelemetryFrame.model_validate. cProfile on the main thread never sees it,
so measure it directly. Also measures the alternatives worth knowing about
(model_validate_json, and construction the ReplayReader-style way).
"""

import json
import time

from instrument_cluster.telemetry.demo import DemoReader
from instrument_cluster.telemetry.models import TelemetryFrame

N = 20000


def bench(label, fn, payloads):
    # warmup
    for p in payloads[:200]:
        fn(p)
    t0 = time.perf_counter()
    for _ in range(N // len(payloads)):
        for p in payloads:
            fn(p)
    dt = time.perf_counter() - t0
    per = dt / N * 1e6
    print(f"{label:45s} {per:8.1f} us/packet   ({per / 16667 * 100:.2f}% of a 60fps frame)")


def main() -> None:
    reader = DemoReader()
    raw = []
    for _ in range(100):
        raw.append(reader.latest().model_dump_json().encode("utf-8"))
        time.sleep(0.002)

    # Real feeds omit fields they don't have; explicit nulls fail validation
    # for fields typed `List[float] = None` etc. (see report), so strip them.
    objs = [{k: v for k, v in json.loads(p).items() if v is not None} for p in raw]
    payloads = [json.dumps(o).encode("utf-8") for o in objs]

    bench("json.loads(bytes)", lambda p: json.loads(p.decode("utf-8")), payloads)
    bench("TelemetryFrame.model_validate(obj)", TelemetryFrame.model_validate, objs)
    bench(
        "current path: loads + model_validate",
        lambda p: TelemetryFrame.model_validate(json.loads(p.decode("utf-8"))),
        payloads,
    )
    bench("TelemetryFrame.model_validate_json(bytes)", TelemetryFrame.model_validate_json, payloads)
    bench("TelemetryFrame(**obj)  (ReplayReader style)", lambda o: TelemetryFrame(**o), objs)

    # demo-mode comparison: full synthetic frame construction per frame
    t0 = time.perf_counter()
    for _ in range(N):
        reader.latest()
    dt = time.perf_counter() - t0
    per = dt / N * 1e6
    print(f"{'DemoReader.latest() (demo mode, main loop)':45s} {per:8.1f} us/call     ({per / 16667 * 100:.2f}% of a 60fps frame)")


if __name__ == "__main__":
    main()
