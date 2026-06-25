# type: ignore
"""
Fixed iRacing-style spotter for LMU.

Run directly:  python spotter_fixed.py

Approach (matches TinyPedal's tested convention):
  - yaw = atan2(mOri[2].x, mOri[2].z)   (row 2 = car forward/Z basis vector)
  - Rotate the world X-Z displacement by (yaw - pi) into the car's local frame.
    The (yaw - pi) flip is required because in rF2/LMU the car "forward"
    direction runs along world -Z.
  - 2D ground plane only (Y ignored).
  - Tick-counter debounce so a single-frame glitch never announces.
"""

import time
from math import atan2, cos, sin, pi
from pyLMUSharedMemory import lmu_data
from pyLMUSharedMemory.lmu_data import LMUConstants
from pyLMUSharedMemory.lmu_mmap import MMapControl


# ── Tunable constants ────────────────────────────────────────────────
OVERLAP_ZONE  = 5.0   # metres — longitudinal half-window (≈ one car length)
LATERAL_MIN   = 1.5   # metres — ignore the same lane / your own car
LATERAL_MAX   = 4.0   # metres — max side gap to count as alongside
CONFIRM_TICKS = 2     # consecutive ticks (~100 ms) before announcing


def is_game_running(data) -> bool:
    return data.generic.gameVersion > 0 and data.telemetry.activeVehicles > 0


def get_local_offset(my_car, other_car):
    """Return (side, forward) offset of other_car in my_car's local frame.

    side    > 0 → RIGHT,  side    < 0 → LEFT
    forward > 0 → AHEAD,  forward < 0 → BEHIND

    mOri[2] is the car's local Z (forward) basis vector expressed in world
    space, so atan2(.x, .z) is the world heading.  Rotating the displacement
    by (yaw - pi) puts +forward out the nose and +side out the right door.
    """
    fwd = my_car.mOri[2]
    yaw = atan2(fwd.x, fwd.z)

    dx = other_car.mPos.x - my_car.mPos.x
    dz = other_car.mPos.z - my_car.mPos.z

    theta = yaw - pi
    c, s = cos(theta), sin(theta)
    side    = c * dx - s * dz
    forward = c * dz + s * dx
    return side, forward


def is_alongside(side, forward) -> bool:
    """True when the other car overlaps us longitudinally and sits in an
    adjacent lane (not directly ahead/behind, not our own car)."""
    return abs(forward) < OVERLAP_ZONE and LATERAL_MIN < abs(side) < LATERAL_MAX


class SideState:
    """Independent debounce + announce state for one side."""

    def __init__(self, label):
        self.label = label
        self.count = 0
        self.announced = False

    def update(self, present: bool):
        if present:
            self.count += 1
            if self.count >= CONFIRM_TICKS and not self.announced:
                self.announced = True
                print(f"[SPOTTER] {self.label}")
        else:
            # Require a clean gap before re-arming so a 1-tick flicker
            # cannot spam repeated announcements.
            self.count = 0
            self.announced = False


def left_right_engineer():
    """Spotter loop — only outputs LEFT / RIGHT when a car is alongside."""

    lmu = MMapControl(LMUConstants.LMU_SHARED_MEMORY_FILE, lmu_data.LMUObjectOut)
    lmu.create(0)

    left  = SideState("LEFT")
    right = SideState("RIGHT")

    try:
        while True:
            lmu.update()
            data = lmu.data

            if not is_game_running(data):
                print("Waiting for game...")
                time.sleep(1.0)
                continue

            num_cars    = data.scoring.scoringInfo.mNumVehicles
            active_cars = min(data.telemetry.activeVehicles, num_cars)

            # Find the player by flag, not by telemetry index: playerVehicleIdx
            # indexes the telemetry array, which need not match the scoring
            # array ordering used below.
            player_index = next(
                (i for i in range(num_cars)
                 if data.scoring.vehScoringInfo[i].mIsPlayer),
                -1,
            )
            if player_index < 0:
                time.sleep(0.05)
                continue

            my_car = data.scoring.vehScoringInfo[player_index]

            found_left  = False
            found_right = False

            for i in range(active_cars):
                if i == player_index:
                    continue

                other = data.scoring.vehScoringInfo[i]
                if other.mInPits or other.mFinishStatus == 2:
                    continue

                side, forward = get_local_offset(my_car, other)
                if is_alongside(side, forward):
                    if side < 0:
                        found_left = True
                    else:
                        found_right = True

            left.update(found_left)
            right.update(found_right)

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("Stopped")
    finally:
        lmu.close()


if __name__ == "__main__":
    left_right_engineer()
