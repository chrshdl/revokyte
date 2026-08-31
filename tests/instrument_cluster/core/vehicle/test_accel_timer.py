"""The acceleration timer: the number it publishes is the whole feature.

The point of the screen is comparing two runs against each other, so the
tests that matter are the ones that keep the number comparable — that it
agrees with the analytic answer for a known pull (and does not quantise to
the frame rate), and that everything which would make one run measured
differently from another voids it instead of publishing it.
"""

import math

import pytest

from instrument_cluster.core.vehicle.accel_timer import AccelTimer, TimerState
from instrument_cluster.telemetry.models import Flags, TelemetryFrame

HZ = 60.0


def _frame(speed: float, t: float, car_id: int = 1461, **flags) -> TelemetryFrame:
    kw = {"car_on_track": True}
    kw.update(flags)
    return TelemetryFrame(
        car_id=car_id,
        received_time=t,
        car_speed=speed,
        flags=Flags(**kw),
    )


def _stand(timer: AccelTimer, t0: float = 0.0, seconds: float = 0.2) -> float:
    """Sit at the line long enough to arm. Returns the next timestamp."""
    t = t0
    for _ in range(int(seconds * HZ)):
        timer.feed(_frame(0.0, t), t)
        t += 1 / HZ
    return t


def _pull(timer: AccelTimer, accel: float, t0: float, seconds: float = 30.0) -> None:
    """Constant-acceleration launch from a standstill, sampled at 60 Hz."""
    for i in range(int(seconds * HZ)):
        t = t0 + i / HZ
        timer.feed(_frame(accel * (i / HZ), t), t)
        if timer.state == TimerState.DONE:
            return


# --------------------------------------------------------------------------
# the measurement
# --------------------------------------------------------------------------
@pytest.mark.parametrize("target", [100, 200, 300, 400])
def test_a_known_pull_is_timed_to_the_analytic_answer(target):
    """Constant acceleration has a closed-form answer, so the timer can be
    checked against arithmetic rather than against itself.

    The clock starts as the car crosses LAUNCH_SPEED, so the run is the
    distance covered from that crossing — which is what the analytic times
    below account for.
    """
    accel = 5.0
    timer = AccelTimer(target)
    t0 = _stand(timer)
    _pull(timer, accel, t0)

    assert timer.state == TimerState.DONE

    # x(t) = ½at², measured from the LAUNCH_SPEED crossing at t_launch.
    t_launch = timer.LAUNCH_SPEED / accel
    x_launch = 0.5 * accel * t_launch**2
    t_finish = math.sqrt(2 * (x_launch + target) / accel)

    assert timer.elapsed_s == pytest.approx(t_finish - t_launch, abs=0.005)
    assert timer.end_speed_ms == pytest.approx(accel * t_finish, abs=0.05)
    assert timer.distance_m == target


def test_the_finish_is_solved_inside_the_frame_that_crosses_the_line():
    """A stop that quantised to the frame rate would put up to 16 ms of
    noise on a comparison whose whole content is tenths."""
    timer = AccelTimer(100)
    t0 = _stand(timer)
    _pull(timer, 5.0, t0)

    frame_period = 1 / HZ
    # A quantised answer would land on a whole number of frames from the
    # launch. This one must not.
    frames = timer.elapsed_s / frame_period
    assert abs(frames - round(frames)) > 0.01


def test_a_held_frame_advances_nothing():
    """Readers hold their last frame forever; re-integrating it would run
    the clock on a car that is no longer sending anything."""
    timer = AccelTimer(400)
    t0 = _stand(timer)
    for i in range(30):
        t = t0 + i / HZ
        timer.feed(_frame(20.0, t), t)
    running_distance = timer.distance_m
    running_elapsed = timer.elapsed_s

    for i in range(30, 60):  # same received_time, later arrival
        timer.feed(_frame(20.0, t), t0 + i / HZ)

    assert timer.distance_m == running_distance
    assert timer.elapsed_s == running_elapsed


# --------------------------------------------------------------------------
# arming
# --------------------------------------------------------------------------
def test_a_rolling_car_cannot_launch_a_run():
    """Every run has to start from the same place — a standstill — or the
    two times being compared measured different things."""
    timer = AccelTimer(100)
    t = 0.0
    for _ in range(60):  # already rolling when the screen opened
        timer.feed(_frame(15.0, t), t)
        t += 1 / HZ

    assert timer.state == TimerState.ROLLING
    assert timer.elapsed_s == 0.0


def test_stopping_arms_the_timer_again():
    timer = AccelTimer(100)
    t = 0.0
    for _ in range(30):
        timer.feed(_frame(15.0, t), t)
        t += 1 / HZ
    assert timer.state == TimerState.ROLLING

    _stand(timer, t)
    assert timer.state == TimerState.READY


def test_a_finished_run_stands_until_the_next_launch():
    """Back-to-back runs need no screen taps: the time stays up while the
    car returns to the line, and only the next launch clears it."""
    timer = AccelTimer(100)
    _pull(timer, 5.0, _stand(timer))
    finished = timer.elapsed_s
    assert timer.state == TimerState.DONE

    t = _stand(timer, 20.0)  # roll back to the line and stop
    assert timer.state == TimerState.READY
    assert timer.elapsed_s == finished

    timer.feed(_frame(3.0, t), t)  # launch again
    assert timer.state == TimerState.RUNNING
    assert timer.elapsed_s < finished


# --------------------------------------------------------------------------
# what voids a run
# --------------------------------------------------------------------------
def test_a_car_that_stops_mid_run_voids_it():
    timer = AccelTimer(400)
    t = _stand(timer)
    for i in range(60):  # away, then a spin
        timer.feed(_frame(20.0, t), t)
        t += 1 / HZ
    assert timer.state == TimerState.RUNNING

    for _ in range(10):
        timer.feed(_frame(0.0, t), t)
        t += 1 / HZ

    assert timer.state != TimerState.RUNNING
    assert timer.elapsed_s == 0.0
    assert timer.note == "run stopped"


def test_a_gap_in_the_stream_voids_a_run_rather_than_guessing_across_it():
    """The last known speed standing in for a stretch of road nobody
    measured would invent distance, and quietly produce a fast time."""
    timer = AccelTimer(400)
    t = _stand(timer)
    for i in range(60):
        timer.feed(_frame(30.0, t), t)
        t += 1 / HZ
    assert timer.state == TimerState.RUNNING

    t += AccelTimer.MAX_GAP_S + 0.1
    timer.feed(_frame(45.0, t), t)

    assert timer.state != TimerState.RUNNING
    assert timer.note == "signal lost"


def test_losing_telemetry_voids_a_run():
    timer = AccelTimer(400)
    t = _stand(timer)
    for i in range(60):
        timer.feed(_frame(30.0, t), t)
        t += 1 / HZ

    timer.feed(None, t)

    assert timer.state == TimerState.NO_SIGNAL
    assert timer.elapsed_s == 0.0
    assert timer.note == "waiting for telemetry"


def test_a_paused_game_voids_a_run():
    timer = AccelTimer(400)
    t = _stand(timer)
    for i in range(60):
        timer.feed(_frame(30.0, t), t)
        t += 1 / HZ

    timer.feed(_frame(30.0, t, paused=True), t)

    assert timer.state == TimerState.NO_SIGNAL
    assert timer.elapsed_s == 0.0


def test_leaving_the_track_voids_a_run():
    timer = AccelTimer(400)
    t = _stand(timer)
    for i in range(60):
        timer.feed(_frame(30.0, t), t)
        t += 1 / HZ

    timer.feed(_frame(30.0, t, car_on_track=False), t)

    assert timer.state == TimerState.NO_SIGNAL
    assert timer.elapsed_s == 0.0


def test_changing_car_voids_a_run():
    timer = AccelTimer(400)
    t = _stand(timer)
    for i in range(60):
        timer.feed(_frame(30.0, t), t)
        t += 1 / HZ

    timer.feed(_frame(30.0, t, car_id=999), t)

    assert timer.state != TimerState.RUNNING
    assert timer.elapsed_s == 0.0


# --------------------------------------------------------------------------
# controls
# --------------------------------------------------------------------------
def test_changing_the_distance_discards_the_run_in_progress():
    """It was measuring a different distance; re-scoring it against the new
    one would put up a number that was never driven to that line."""
    timer = AccelTimer(400)
    t = _stand(timer)
    for i in range(60):
        timer.feed(_frame(30.0, t), t)
        t += 1 / HZ
    assert timer.state == TimerState.RUNNING

    timer.set_target(200)

    assert timer.target_m == 200
    assert timer.state != TimerState.RUNNING
    assert timer.elapsed_s == 0.0


def test_reset_zeroes_a_finished_run():
    timer = AccelTimer(100)
    _pull(timer, 5.0, _stand(timer))
    assert timer.elapsed_s > 0

    timer.reset()

    assert timer.elapsed_s == 0.0
    assert timer.distance_m == 0.0
    assert timer.end_speed_ms == 0.0
    assert timer.note is None


def test_reset_re_arms_within_a_frame_of_a_standing_car():
    timer = AccelTimer(100)
    t = _stand(timer)
    timer.reset()

    timer.feed(_frame(0.0, t), t)

    assert timer.state == TimerState.READY
