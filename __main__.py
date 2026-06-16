# type: ignore 
import time
from pyLMUSharedMemory import lmu_data
from pyLMUSharedMemory.lmu_data import LMUConstants
from pyLMUSharedMemory.lmu_mmap import MMapControl
def main():
    lmu = MMapControl(LMUConstants.LMU_SHARED_MEMORY_FILE, lmu_data.LMUObjectOut)
    lmu.create(0)
    
    
    try:
        while True :
            
            lmu.update()
            
            rpm = lmu.data.telemetry.telemInfo[0].mEngineRPM
            
            print(rpm)
            
            time.sleep(0.05)    
            
            
        
    except KeyboardInterrupt:
        print("zamknięto połączenie")
        
if __name__ == "__main__":
    main()        
    
    
    
    
    
    
    