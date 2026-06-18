import socket
import json
import time
import copy
import matplotlib.pyplot as plt
import numpy as np
import pyvisa
import skrf as rf
import io
import base64
from RsInstrument import RsInstrument, BinFloatFormat # Rohde&Schwarz
from windfreak import SynthHD
import hid # pip install hidapi
import serial.tools.list_ports
from urllib.request import urlopen

warm_switches_ip_address = '169.254.10.10'
programmable_attenuator_ip_address = '169.254.11.11'

rm = pyvisa.ResourceManager()
instruments = rm.list_resources()
for instrument in instruments:
    if 'Rohde' in instrument:
        vna = RsInstrument(instrument, id_query=True, reset=False)
    if '33220A' in instrument:
        dc_source = rm.open_resource(instrument)
    if 'E7405' in instrument:
        spa = rm.open_resource(instrument)
        
ports = serial.tools.list_ports.comports()
for port in ports:
    #print(f"Port Name:   {port.device}")
    #print(f"Description: {port.description}")
    #print(f"Hardware ID: {port.hwid}")  # Shows USB Vendor ID, Product ID, and Location string
    if 'A3E5' in port.hwid:
        print(f"Windfreak is on COM port {port.device}")
        synth = SynthHD(port.device)
        channel_a = synth[0]
#synth.close() # close connection to make GUI work
#channel_a.enable = True
#channel_a.frequency = 13.0e9   # frequency in Hz
#channel_a.power = 3.0        #  power in dBm


mm4250_vid = 0x04D8
mm4250_pid = 0xEDFB
mm4250 = hid.device()
mm4250.open(mm4250_vid,mm4250_pid)

mm4250_bitmasks = {
        "short":  [0x00, 0x08, 0x00, 0x00, 0x08, 0x00],
        "open":   [0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
        "load":   [0x00, 0x00, 0x01, 0x00, 0x00, 0x01],
        "port_1": [0x14, 0x20, 0x04, 0x14, 0x20, 0x04],
        "port_2": [0x04, 0x10, 0x44, 0x04, 0x10, 0x44],
        "port_3": [0x01, 0x01, 0x82, 0x01, 0x01, 0x82],
        "port_4": [0x00, 0x82, 0x82, 0x00, 0x82, 0x82],
        "port_5": [0x02, 0x04, 0x82, 0x02, 0x04, 0x82],
        "port_6": [0x0C, 0x40, 0x04, 0x0C, 0x40, 0x04],
    }

def set_cold_switch_state(state_string):
    if state_string not in mm4250_bitmasks:
        print(f"Invalid state string: '{state_string}'")
        return
    mask = mm4250_bitmasks[state_string]
    # Manually prepend the two leading 0s to the mask array
    full_payload = [0, 0] + mask
    mm4250.write(full_payload)
    # Send the latch command explicitly as a clean 2-byte list
    mm4250.write([0, 2])
    print(state_string)

def send_url_command(ip_address, CmdToSend):
    CmdToSend = 'http://' + ip_address + '/:' + CmdToSend
    # Try up to 3 times to absorb intermittent link-local drops
    for attempt in range(3):
        try:
            HTTP_Result = urlopen(CmdToSend, timeout=3)
            PTE_Return = HTTP_Result.read()
            HTTP_Result.close() # Keep socket memory clear

            if len(PTE_Return) > 100:
                print(f"Error, command not found: {CmdToSend}")
                return "Invalid Command!"
                
            return PTE_Return.decode('utf-8').strip()

        except Exception as network_err:
            # If it's the last attempt and still fails, log the warning
            if attempt == 2:
                print(f"Hardware Network Warning: No response from {ip_address}. Error: {network_err}")
                return "No Response!"
            # Otherwise, wait 50ms and try again instantly
            time.sleep(0.05)
    
def set_warm_switch_state(measurement_state_string):
    output_port = 0
    input_port = 0
    spa_state = 0
    noise_diode = 0    
    if measurement_state_string == "s11":
        output_port = 0
        input_port = 0
        spa_state = 0
        noise_diode = 0
    if measurement_state_string == "s21":
        output_port = 1
        input_port = 0
        spa_state = 0
        noise_diode = 0
    if measurement_state_string == "s12":
        output_port = 0
        input_port = 1
        spa = 0
        noise_diode = 0
    if measurement_state_string == "s22":
        output_port = 1
        input_port = 1
        spa_state = 0
        noise_diode = 0
    if measurement_state_string == "noise":
        output_port = 0
        input_port = 0
        spa_state = 1
        noise_diode = 0
    if measurement_state_string == "diode":
        output_port = 0
        input_port = 0
        spa_state = 1
        noise_diode = 0
    state_byte = 128 + input_port + (2 * spa_state) + (4 * noise_diode) + (8 * output_port)
    response_status = send_url_command(warm_switches_ip_address, f"SETP={state_byte}")
    return response_status

def get_warm_switch_state():
    """Queries the switch box and decodes the current state back into ports."""
    # Send the question mark query to read the state
    raw_reply = send_url_command(warm_switches_ip_address, "SWPORT?")
    
    # If using alternative firmware versions, try "SETP?" if "SWPORT?" returns an error
    if "Error" in raw_reply or "No Response" in raw_reply:
        return {"status": "Disconnected or Error"}
        
    try:
        # Convert the string answer (e.g., "129") into an integer
        state_byte = int(raw_reply.strip())
        
        # Reverse the math used to create the state byte:
        # state_byte = 128 + input_port + (2 * spa) + (4 * noise_diode) + (8 * output_port)
        
        # Strip away the base offset (128)
        working_value = state_byte - 128
        
        # Extract individual bits using modulus and floor division
        input_port   = working_value % 2
        spa          = (working_value // 2) % 2
        noise_diode  = (working_value // 4) % 2
        output_port  = (working_value // 8) % 16  # Remaining bits represent output port
        
        return {
            "status": "Online",
            "raw_byte": state_byte,
            "input_port": input_port,
            "output_port": output_port,
            "noise_diode": noise_diode,
            "spa": spa
        }
    except ValueError:
        return {"status": f"Malformed hardware response: {raw_reply}"}

def set_programmable_attenuator_value(attenuation):
    """Calculates switch state byte and sends the HTTP command."""
    send_url_command(programmable_attenuator_ip_address,f"SETATT={attenuation}")

def get_programmable_attenuator_value():
    # The direct URL that successfully delivers the information
    url = f"http://{programmable_attenuator_ip_address}/ATT?"
    
    try:
        with urlopen(url, timeout=2.0) as response:
            # Read bytes, decode to string, and remove whitespace/newlines
            attenuation_value = response.read().decode('utf-8').strip()
            return float(attenuation_value)
            
    except URLError as e:
        print(f"Connection failed: {e.reason}")
        return None
    except ValueError:
        print(f"Parsing Error: Could not convert response to number: {attenuation_value}")
        return None
    
def fetch_vna_trace():
    vna.write("INITiate:IMMediate")  # single trigger
    # trigger and Pull raw values
    opc_done = vna.query("*OPC?").strip()
    if opc_done != "1":
        print(f"Error: OPC returned unexpected value '{opc_done}'; ending execution.")
        exit()
    raw_floats = vna.query_bin_or_ascii_float_list(":CALC1:DATA? SDAT")
    # Separate real and imaginary pairs
    real_parts = np.array(raw_floats[0::2])
    imag_parts = np.array(raw_floats[1::2])
    complex_trace = real_parts + 1j * imag_parts
    s_matrix = np.zeros((len(frequencies), 1, 1), dtype=complex)
    s_matrix[:, 0, 0] = complex_trace
    return rf.Network(frequency=frequencies, s=s_matrix, name='data trace')


#  vna.write('OUTPut:STATe OFF')
#  vna.write('OUTPut:STATe ON')
#  bool(vna.query('OUTPut:STATe?'))

def fetch_noise_trace(timeout_sec=5.0):
    
    spa.write('INITiate:CONTinuous OFF')    
    spa.write('INITiate:IMMediate')
    
    start_time = time.time()
    while True:
        try:
            if int(spa.query('*OPC?').strip()) == 1:
                break
        except Exception:
            pass
        
        # Enforce a safety timeout so your script never hangs indefinitely
        if (time.time() - start_time) > timeout_sec:
            raise TimeoutError("Spectrum analyzer sweep timed out before completing.")
            
        time.sleep(0.05) 
        
    noise_dbm = spa.query_binary_values("TRACe:DATA? TRACE1", datatype='f', container=np.array)
    noise_watts = 10 ** ((noise_dbm - 30) / 10)
    

    spa.write('INITiate:CONTinuous ON')
    return noise_dbm, noise_watts
    
    
with open("live-web-instrument.json", "r", encoding="utf-8") as file:
    file_contents = file.read()
live_web_instrument = json.loads(file_contents)

set_cold_switch_state(live_web_instrument['cold_switch_state'])

set_warm_switch_state(live_web_instrument['warm_switch_state'])

# set vna parameters
vna.write(':SENS1:BAND ' + str(live_web_instrument['vna_ifbw']))          # set IF bandwidth
vna.write(':SENS1:FREQ:START ' + str(live_web_instrument['fstart']*1e9))      # set start frequency in Hz
vna.write(':SENS1:FREQ:STOP ' + str(live_web_instrument['fstop']*1e9))        # set stop frequency in Hz
vna.write(':SENS1:SWEep:POINts ' + str(live_web_instrument['numpoints'])) # set number of points in frequency sweep
vna.write(':SENS1:BAND ' + str(live_web_instrument['vna_ifbw'])) # set IF bandwidth in Hz
vna.write(':SOURce1:POWer1:LEVel:IMMediate:AMPLitude ' + str(live_web_instrument['vna_power'])) # set VNA power in dBm

# Tell the VNA to package binary blocks as 32-bit single-precision floats
vna.write("FORMAT REAL,32") 
# Tell the Python VISA driver to interpret the blocks as 4-byte singles
vna.bin_float_numbers_format = BinFloatFormat.Single_4bytes
vna.write("INITiate:CONTinuous OFF")

#set spectrum analyzer parameters
spa.write(":UNIT:POWer DBM")
spa.write(":SENSe:AMPLitude:SCALe:TYPE LOGarithmic")
spa.write(":DISPlay:WINDow1:TRACe:Y:SCALe:SPACing LOGarithmic")
spa.write("FORMat:DATA REAL,32")
spa.write("FORMat:BORDer SWAPped")
spa.write(':SENSe:FREQuency:STARt ' + str(live_web_instrument['fstart']*1e9)) # set start frequency in GHz
spa.write(':SENSe:FREQuency:STOP? ' + str(live_web_instrument['fstop']*1e9)) # set stop frequency in GHz
spa.write(':SENS:SWEep:POINts ' + str(live_web_instrument['numpoints'])) # set number of points in sweep
spa.write(':SENSe:BANDwidth:RESolution ' + str(live_web_instrument['spa_rbw'])) # set resolution bandwidth in Hz
spa.write(':SENSe:BANDwidth:VIDeo ' + str(live_web_instrument['spa_rbw']))      # set video bandwidth in Hz

dc_source.write("FUNC DC") #dc output
dc_source.write('VOLT:OFFset ' + str(live_web_instrument['dc_bias']))
if live_web_instrument['dc_source_on']:
    dc_source.write('OUTP ON') # on
else:
    dc_source.write('OUTP OFF') # off

channel_a.enable = live_web_instrument['pump_on']
channel_a.frequency = live_web_instrument['pump_frequency']*1e9
channel_a.power = live_web_instrument['pump_power']
fghz = np.linspace(live_web_instrument['fstart'],live_web_instrument['fstop'],live_web_instrument['numpoints'])
frequencies = fghz*1e9


vna.visa_timeout = 5000  # Give the VNA up to 5 seconds to respond to a sweep

previous_state = copy.deepcopy(live_web_instrument)

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', 8000))
    server.listen(5)
    server.settimeout(0.5) 
    
    print("=== LIVE SERVER ACTIVE ===")
    
    try:
        while True:
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue 
            
            with conn:
                raw_web_input = conn.makefile('r', encoding='utf-8').readline()
                if not raw_web_input:
                    continue
                try:
                    live_web_instrument = json.loads(raw_web_input.strip())
                    if live_web_instrument['cold_switch_state'] != previous_state['cold_switch_state']:
                        set_cold_switch_state(live_web_instrument['cold_switch_state'])
                        #print('set cold switch state to ' + live_web_instrument['cold_switch_state'])
                    if live_web_instrument['warm_switch_state'] != previous_state['warm_switch_state']:
                        set_warm_switch_state(live_web_instrument['warm_switch_state'])
                        print('set warm switch state to ' + live_web_instrument['warm_switch_state'])

                except (json.JSONDecodeError, ValueError):
                    pass                    
                try:
                    vna_trace = fetch_vna_trace()
                    trace_db = vna_trace.s_db[:, 0, 0]
                except Exception as hardware_err:
                    print(f"Skipping frame due to hardware error: {hardware_err}")
                    continue # Skip this frame instead of killing the notebook cell

                previous_state = copy.deepcopy(live_web_instrument)

                xdata = fghz
                ydata = trace_db
                dataset = {}
                dataset['xdata'] = xdata.tolist()
                dataset['ydata'] = ydata.tolist()
                dataset['xlabel'] = 'Frequency [GHz]'
                dataset['ylabel'] = 's11 [dB]'
                dataset['ymin'] = -80
                dataset['ymax'] = -20
                dataset['metadata'] = live_web_instrument
                
                plt.cla()
                plt.figure(figsize=(8, 5))
                plt.plot(xdata, ydata)
                plt.xlim(xdata[0], xdata[-1])
                plt.ylim(dataset['ymin'],dataset['ymax'])
                plt.grid(True)
                plt.xlabel(dataset['xlabel'])
                plt.ylabel(dataset['ylabel'])
                plt.tight_layout()
                img_buf = io.BytesIO()
                plt.savefig(img_buf, format='png')
                plt.close() 
                img_buf.seek(0)
                b64_string = base64.b64encode(img_buf.read()).decode('utf-8')
                imagedata = f"data:image/png;base64,{b64_string}"
                dataset['image'] = imagedata
                
                payload = json.dumps(dataset) + "\n"
                conn.sendall(payload.encode('utf-8'))
                conn.shutdown(socket.SHUT_WR)

    except KeyboardInterrupt:
        print("\n=== SERVER TERMINATED CLEANLY BY USER ===")
        
        