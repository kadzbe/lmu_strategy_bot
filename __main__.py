# type: ignore
import time
import json
import io
from gtts import gTTS
import pygame
from pyLMUSharedMemory import lmu_data
from pyLMUSharedMemory.lmu_data import LMUConstants
from pyLMUSharedMemory.lmu_mmap import MMapControl
from collections import deque
import requests
import os
from pydub import AudioSegment
from pydub.effects import high_pass_filter, low_pass_filter
import math



def load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def apply_radio_filter(audio):
    """Apply motorsport radio engineer filters to audio."""
    audio = high_pass_filter(audio, 300)
    audio = low_pass_filter(audio, 4000)
    return audio


def speak_engineer_feedback(text: str) -> None:
    """Convert text to speech with motorsport engineer radio effect."""
    try:
        tts = gTTS(text=text, lang='en', slow=False)
        audio_buffer = io.BytesIO()
        tts.write_to_fp(audio_buffer)
        audio_buffer.seek(0)
        
        audio = AudioSegment.from_file(audio_buffer, format="mp3")
        audio = apply_radio_filter(audio)
        
        wav_buffer = io.BytesIO()
        audio.export(wav_buffer, format="wav")
        wav_buffer.seek(0)
        
        pygame.mixer.music.load(wav_buffer)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
    except Exception as e:
        print(f"Voice synthesis error: {e}")


def is_game_running(data) -> bool:
    return data.generic.gameVersion > 0 and data.telemetry.activeVehicles > 0


def run_delta():
    pygame.mixer.init()
    load_env_file("keys.env")
    
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not found in environment or keys.env")
    
    lmu = MMapControl(LMUConstants.LMU_SHARED_MEMORY_FILE, lmu_data.LMUObjectOut)
    lmu.create(0)
    Last_five_laps_delta = deque(maxlen=5)
    Last_five_laps_info = deque(maxlen=5)
    counter = 0
    

    try:
        while True:
            lmu.update()
            data = lmu.data

            if not is_game_running(data):
                print("Game not running yet. Waiting...")
                time.sleep(1.0)
                continue

            player_index = data.telemetry.playerVehicleIdx
            if player_index < 0 or player_index >= data.scoring.scoringInfo.mNumVehicles:
                player_index = 0

            scoring = data.scoring.vehScoringInfo[player_index]
            telemetry = data.telemetry.telemInfo[player_index]

            last_s1 = scoring.mLastSector1
            last_s2 = scoring.mLastSector2
            last_lap = scoring.mLastLapTime
            best_s1 = scoring.mBestSector1
            best_s2 = scoring.mBestSector2
            best_lap = scoring.mBestLapTime
            lapDistance = scoring.mLapDist

            last_s3 = last_lap - last_s2 if last_lap > 0 else 0.0
            best_s3 = best_lap - best_s2 if best_lap > 0 else 0.0
            lap_delta = last_lap - best_lap if last_lap > 0 and best_lap > 0 else 0.0
            if(lapDistance < 100):
                time.sleep(5)

                Last_five_laps_delta.append(lap_delta)
                Last_lap_data = {
                    "last_lap" : last_lap,
                    "last_sector_1" : last_s1,
                    "last_sector_2" : last_s2,
                    "last_sector_3" : last_s3,
                    "lap_delta": last_lap - best_lap if last_lap > 0 and best_lap > 0 else 0.0,  
                    "best_sector_1" : best_s1,     
                    "best_sector_2" : best_s2,
                    "best_sector_3" : best_s3
                    
                }
                Last_five_laps_info.append(Last_lap_data)
                print(list(Last_five_laps_delta))
                json_data = json.dumps(list(Last_five_laps_info), indent = 4)
                print(json_data)
                counter += 1
                if counter == 5:
                    url = "https://openrouter.ai/api/v1/chat/completions"
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "model": "openrouter/owl-alpha",
                        "messages": [
                            {
                                "role": "system",
                                "content": "you are a racing engineer that analyses laps and by looking at sector times it is your job to determine where the driver is losing time over the last five laps and to communicate it to them. If the time delta is 0.0 it means the driver either matched their pace or went faster. If you get weird data remember that a driver might've gotten an off track and had to lift or for example it was an outlap just keep that in mind as these are possibilities which could've made them lift and lose time. Remember this is racing so differences of 0.2s in a sector matter. Do not make the response overly aggressive. Analyze each lap individually and describe overall pace, the least consistent sectors, where time is lost, and which lap lost the most time. Output only the sentence the driver will hear."
                            },
                            {
                                "role": "user",
                                "content": list(Last_five_laps_info)
                            }
                        ]
                    }

                    try:
                        response = requests.post(url, headers=headers, json=payload)
                        response.raise_for_status()
                        response_json = response.json()
                        feedback_text = response_json['choices'][0]['message']['content']
                        print(f"Engineer feedback: {feedback_text}")
                        speak_engineer_feedback(feedback_text)
                    except requests.exceptions.RequestException as e:
                        print(f"API request failed: {e}")
                    except (KeyError, IndexError) as e:
                        print(f"Unexpected API response format: {e}")
                    finally:
                        counter = 0

            time.sleep(0.2)
    except KeyboardInterrupt:
        print("Stopped by user")
    finally:
        lmu.close()
        
def get_relative_position(myCar, other_car):
    """Get side, forward distance and total distance to another car.
    Returns: (side_value, forward_value, distance)
    - side_value > 0: car on RIGHT, < 0: on LEFT
    - forward_value > 0: car ahead, < 0: car behind
    """
    dx = other_car.mPos.x - myCar.mPos.x
    dy = other_car.mPos.y - myCar.mPos.y
    dz = other_car.mPos.z - myCar.mPos.z
    
    ori = myCar.mOri
    # Right vector (lateral)
    right_x = ori[1].x
    right_y = ori[1].y
    right_z = ori[1].z
    # Forward vector (longitudinal)
    forward_x = ori[0].x
    forward_y = ori[0].y
    forward_z = ori[0].z
    
    # Project onto right and forward vectors
    side_value = (dx * right_x) + (dy * right_y) + (dz * right_z)
    forward_value = (dx * forward_x) + (dy * forward_y) + (dz * forward_z)
    
    # Calculate total distance
    distance = math.sqrt(dx*dx + dy*dy + dz*dz)
    
    return side_value, forward_value, distance


def left_right_engineer():
    """Main radar function to detect nearby cars and their position."""
    lmu = MMapControl(LMUConstants.LMU_SHARED_MEMORY_FILE, lmu_data.LMUObjectOut)
    lmu.create(0)
    alongside_state = {}
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
            
            my_car = data.scoring.vehScoringInfo[player_index]
            my_telemetry = data.telemetry.telemInfo[player_index]

            # Only scan when the nearest car ahead or behind is within 1 second
            if abs(my_telemetry.mTimeGapCarAhead) >= 1.0 and abs(my_telemetry.mTimeGapCarBehind) >= 1.0:
                alongside_state.clear()
                time.sleep(0.05)
                continue

            num_cars = data.scoring.scoringInfo.mNumVehicles
            alongside_zone = 10.0
            side_threshold = 1.0
            active_cars = min(data.telemetry.activeVehicles, num_cars)
            
            for i in range(active_cars):
                if i == player_index:
                    continue
                
                other_car = data.scoring.vehScoringInfo[i]
                if other_car.mInPits or other_car.mFinishStatus == 2:
                    continue
                
                side, forward, dist = get_relative_position(my_car, other_car)

                if abs(side) > side_threshold and abs(forward) < alongside_zone:
                    current_state = "RIGHT" if side > 0 else "LEFT"
                else:
                    current_state = None

                previous_state = alongside_state.get(i)
                if current_state != previous_state:
                    if current_state is not None:
                        print(f"Car {i}: alongside {current_state} (fwd={forward:.1f}m, side={side:.1f}m)")
                        alongside_state[i] = current_state
                    else:
                        alongside_state.pop(i, None)
            
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        lmu.close()


if __name__ == "__main__":
    left_right_engineer()
    
    
    
    
    
    
    