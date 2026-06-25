# type: ignore
"""
Fixed iRacing-style spotter for LMU.

Run directly:  python spotter_fixed.py

Approach (from TinyPedal):
  - atan2 on orientation matrix → yaw angle
  - Rotate X-Z displacement by negative yaw → local lateral/longitudinal
  - 2D ground plane only (Y ignored)
  - Simple tick-counter debounce to avoid phantom single-frame calls
"""

import time
from math import atan2, cos, sin
from pyLMUSharedMemory import lmu_data
from pyLMUSharedMemory.lmu_data import LMUConstants
from pyLMUSharedMemory.lmu_mmap import MMapControl


# ── Tunable constants ────────────────────────────────────────────────
OVERLAP_ZONE = 5.0   # metres — longitudinal window (≈ one car length)
LATERAL_MAX  = 4.0   # metres — max side gap to count as alongside
CONFIRM_TICKS = 2    # consecutive ticks (~100 ms) before announcing


def is_game_running(data) -> bool:
    return data.generic.gameVersion > 0 and data.telemetry.activeVehicles > 0


def get_local_offset(my_car, other_car):
    """Return (side, forward) offset of other_car in my_car's local frame.

    side    > 0 → RIGHT,  side    < 0 → LEFT
    forward > 0 → AHEAD,  forward < 0 → BEHIND
    """
    ori = my_car.mOri
    yaw = atan2(ori[0].z, ori[0].x)

    dx = other_car.mPos.x - my_car.mPos.x
    dz = other_car.mPos.z - my_car.mPos.z

    c, s = cos(yaw), sin(yaw)
    side    =  c * dx + s * dz
    forward = -s * dx + c * dz
    return side, forward


def left_right_engineer():
    """Spotter loop — only outputs LEFT / RIGHT when a car is alongside."""

    lmu = MMapControl(LMUConstants.LMU_SHARED_MEMORY_FILE, lmu_data.LMUObjectOut)
    lmu.create(0)

    # Simple debounce counters (no class needed)
    left_count  = 0   # consecutive ticks a car is alongside on the left
    right_count = 0   # … on the right
    left_announced  = False
    right_announced = False

    try:
        while True:
            lmu.update()
            data = lmu.data

            if not is_game_running(data):
                print("Waiting for game...")
                time.sleep(1.0)
                continue

            player_index = data.telemetry.playerVehicleIdx
            if player_index < 0 or player_index >= data.scoring.scoringInfo.mNumVehicles:
                player_index = 0

            my_car      = data.scoring.vehScoringInfo[player_index]
            num_cars    = data.scoring.scoringInfo.mNumVehicles
            active_cars = min(data.telemetry.activeVehicles, num_cars)

            # ── Scan all other cars ──────────────────────────────────
            found_left  = False
            found_right = False

            for i in range(active_cars):
                if i == player_index:
                    continue

                other = data.scoring.vehScoringInfo[i]
                if other.mInPits or other.mFinishStatus == 2:
                    continue

                side, forward = get_local_offset(my_car, other)
                print(abs(forward))
                print(OVERLAP_ZONE)
                # Is this car alongside?  (within the overlap zone AND close laterally)
                if abs(forward) < OVERLAP_ZONE and abs(side) < LATERAL_MAX:
                    if side < 0:
                        found_left = True
                    else:
                        found_right = True

            # ── Debounce LEFT ────────────────────────────────────────
            if found_left:
                left_count += 1
                if left_count >= CONFIRM_TICKS and not left_announced:
                    left_announced = True
                    print("[SPOTTER] LEFT")
            else:
                left_count = 0
                left_announced = False

            # ── Debounce RIGHT ───────────────────────────────────────
            if found_right:
                right_count += 1
                if right_count >= CONFIRM_TICKS and not right_announced:
                    right_announced = True
                    print("[SPOTTER] RIGHT")
            else:
                right_count = 0
                right_announced = False

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("Stopped")
    finally:
        lmu.close()


if __name__ == "__main__":
    left_right_engineer()