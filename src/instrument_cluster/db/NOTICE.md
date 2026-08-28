# Data licensing notice

## `tracks.json` — GPL-3.0

`tracks.json` is a derived work: the start/finish gates, crossing
directions, and bounding boxes were converted from `gt7trackdetect.csv` in
[Bornhall/gt7telemetry](https://github.com/Bornhall/gt7telemetry), which is
licensed under the **GNU General Public License v3.0**. Accordingly,
`tracks.json` is distributed under **GPL-3.0** as well. The full license
text is in [`LICENSES/GPL-3.0.txt`](../../../LICENSES/GPL-3.0.txt) at the
repository root, or at <https://www.gnu.org/licenses/gpl-3.0.txt>.

The display names in `tracks.json` were joined from `course.csv` in
[ddm999/gt7info](https://github.com/ddm999/gt7info), licensed under
**MIT-0** (no obligations).

`tracks.json` is a standalone data file read by the application at
runtime. The application code is itself licensed GPL-3.0-or-later, so the
whole repository now shares one license family. If you redistribute
`tracks.json` (alone or modified), keep this notice and the GPL-3.0
license with it.

## `car_classes.json` — MIT

`car_classes.json` carries each GT7 car's aspiration, car type, category and
engine layout, extracted from the per-vehicle inventory in
[zetetos/gt-telemetry](https://github.com/zetetos/gt-telemetry), which is
licensed under the **MIT license**. The shift-point curve reads it to pick
how fast an engine loses power past its peak — see
`../core/vehicle/ecu.py`.

Regenerate it with `tools/fetch_car_classes.py` (`--check` reports drift
without writing). If you redistribute the file, keep upstream's MIT notice
with it.

## `cars.json` — provenance unrecorded

`cars.json` (the five per-car engine scalars) predates this notice and
arrived with the initial import; its upstream source was never recorded and
there is no script that regenerates it. Treat its numbers as unverified —
the code comments that read from it say so too.

Thanks to Bornhall, ddm999, and the GTPlanet telemetry community for
collecting and maintaining this data.
