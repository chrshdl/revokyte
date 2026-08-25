"""The app's side of the OTA health-check contract.

`ota-health-check.sh` gates `rauc status mark-good`. This marker is how a
fault the *image* causes withholds that, so U-Boot rotates back to the
previous slot — while the dashboard keeps running in the meantime.
"""

from instrument_cluster.core.system import unhealthy


def test_a_clean_run_reports_nothing(tmp_path):
    marker = str(tmp_path / "unhealthy")
    assert unhealthy.reasons(marker) == []


def test_each_fault_is_one_line(tmp_path):
    marker = str(tmp_path / "unhealthy")

    unhealthy.report("view ProOtaView failed to build", marker)
    unhealthy.report("view LicenseView failed to build", marker)

    assert unhealthy.reasons(marker) == [
        "view ProOtaView failed to build",
        "view LicenseView failed to build",
    ]


def test_the_marker_is_created_with_its_directory(tmp_path):
    # /run/instrument-cluster does not exist until something makes it.
    marker = str(tmp_path / "nested" / "dir" / "unhealthy")

    unhealthy.report("something broke", marker)

    assert unhealthy.reasons(marker) == ["something broke"]


def test_clear_drops_an_earlier_runs_verdict(tmp_path):
    marker = str(tmp_path / "unhealthy")
    unhealthy.report("stale fault from the previous start", marker)

    unhealthy.clear(marker)

    assert unhealthy.reasons(marker) == []


def test_clearing_nothing_is_not_an_error(tmp_path):
    unhealthy.clear(str(tmp_path / "never-existed"))


def test_reporting_never_raises_on_an_unwritable_path():
    # This runs on the startup path: failing to *report* a degraded image
    # must not be the thing that takes the dashboard down.
    unhealthy.report("fault", "/proc/cannot/write/here/unhealthy")
