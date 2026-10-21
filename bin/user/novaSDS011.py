# coding: utf-8
# Modified 2026-10-22 by weewx-packages.
##############################################################################################
#   Nova SDS011 WeeWX 5.1 Service
#   Query-mode support: adds PM2.5 and PM10 to loop packets
#   and writes realtime JSON (particles.json).
#   Implements 60s reading period followed by 60s sleep with fan off.
#
#   Copyright (C) 2025 Ian Millard
#   License: GPLv3
##############################################################################################
import time
import json
import threading
import logging
import serial
import os
import tempfile
import math
import urllib.request
import weewx
from weewx.engine import StdService
from weeutil.weeutil import to_bool

log = logging.getLogger(__name__)

# --- Version ---
DRIVER_NAME = "NovaSDS011"
DRIVER_VERSION = "1.1.0"   # bump this when you make changes

# SDS011 commands
CMD_MODE = 2
CMD_QUERY_DATA = 4
CMD_SLEEP = 6
MODE_QUERY = 1

def construct_command(cmd, data=None):
    """Build SDS011 command packet."""
    if data is None:
        data = []
    assert len(data) <= 12
    data += [0] * (12 - len(data))
    checksum = (sum(data) + cmd - 2) % 256
    ret = b'\xaa\xb4' + bytes([cmd])
    ret += bytes(data)
    ret += b'\xff\xff' + bytes([checksum]) + b'\xab'
    return ret

class NovaSDS011Service(StdService):
    """WeeWX service to poll SDS011 in query mode with 60s read/60s sleep cycle."""
    
    def __init__(self, engine, config_dict):
        super(NovaSDS011Service, self).__init__(engine, config_dict)
        log.info("%s service version %s starting up", DRIVER_NAME, DRIVER_VERSION)
        
        sds_dict = config_dict.get('NovaSDS011', {})
        self.port = sds_dict.get('port', '/dev/ttyUSB0')
        self.timeout = float(sds_dict.get('timeout', 3.0))
        self.url = sds_dict.get('url')
        self.http_poll_interval = float(sds_dict.get('http_poll_interval', 60))
        if self.timeout <= 0 or self.http_poll_interval <= 0:
            raise ValueError('timeout and http_poll_interval must be positive')
        self.stop_event = threading.Event()
        self.thread = None
        self.ser = None
        self.json_output = sds_dict.get('json_output', '/var/www/html/divumwx/jsondata/particles.txt')
        self.log_raw = to_bool(sds_dict.get('log_raw', False))
        
        # Cycle timing (configurable)
        self.read_period = int(sds_dict.get('read_period', 60))    # seconds to read
        self.sleep_period = int(sds_dict.get('sleep_period', 60))  # seconds to sleep
        self.sample_interval = int(sds_dict.get('sample_interval', 2))  # seconds between samples
        
        # Latest readings cache
        self.latest_pm25 = None
        self.latest_pm10 = None
        self.last_update = None
        self.lock = threading.Lock()
        
        if not self.url:
            # Serial connection
            try:
                self.ser = serial.Serial(
                    port=self.port,
                    baudrate=9600,
                    timeout=self.timeout
                )
                self.ser.flushInput()
                log.info("%s connected on %s", DRIVER_NAME, self.port)
            except Exception as e:
                log.error("Could not open %s on %s: %s", DRIVER_NAME, self.port, e)
                self.ser = None
                return
            
            # Initialize sensor to query mode with retry logic
            self.initialize_sensor()
            
        # Start background thread for read/sleep cycle
        self.running = True
        self.thread = threading.Thread(target=self.http_loop if self.url else self.sensor_loop, daemon=True)
        self.thread.start()
        log.info("Started sensor loop: %ds read, %ds sleep", self.read_period, self.sleep_period)
        
        # Bind to loop packet events
        self.bind(weewx.NEW_LOOP_PACKET, self.new_loop_packet)
    
    def query_http(self):
        """Read particulate concentrations from a local Sensor.Community endpoint.

        Returns:
            tuple[float, float]: PM2.5 and PM10 in micrograms per cubic metre.
        """
        with urllib.request.urlopen(self.url, timeout=self.timeout) as response:
            data = json.load(response)
        values = {item['value_type']: float(item['value'])
                  for item in data['sensordatavalues']
                  if item.get('value_type') in ('SDS_P1', 'SDS_P2')}
        if float(data.get('age', 0)) > 2 * self.http_poll_interval:
            raise ValueError('Sensor.Community response is stale')
        result = values['SDS_P2'], values['SDS_P1']
        if any(not math.isfinite(value) or value < 0 for value in result):
            raise ValueError('Invalid particulate concentration')
        return result

    def http_loop(self):
        """Poll the configured HTTP endpoint until shutdown."""
        while not self.stop_event.is_set():
            try:
                pm25, pm10 = self.query_http()
                with self.lock:
                    self.latest_pm25 = pm25
                    self.latest_pm10 = pm10
                    self.last_update = int(time.time())
                self.write_json(self.last_update, pm25, pm10)
            except (OSError, ValueError, KeyError, TypeError) as error:
                log.warning('HTTP particulate read failed: %s', error)
            self.stop_event.wait(self.http_poll_interval)

    def initialize_sensor(self):
        """Initialize sensor with retry logic."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                log.info("Initializing sensor (attempt %d/%d)...", attempt + 1, max_retries)
                
                # Wake the sensor first
                self.cmd_set_sleep(0)
                time.sleep(2)  # Give sensor time to stabilize
                
                # Flush any stale data
                self.ser.flushInput()
                
                # Set to query mode
                self.cmd_set_mode(MODE_QUERY)
                
                log.info("Sensor initialized successfully")
                return
                
            except Exception as e:
                log.warning("Sensor initialization attempt %d failed: %s", attempt + 1, e)
                if attempt < max_retries - 1:
                    time.sleep(3)
                else:
                    log.error("Failed to initialize sensor after %d attempts", max_retries)
                    log.error("Sensor will be initialized in background thread")
    
    def cmd_set_mode(self, mode):
        """Set sensor to active or query mode."""
        cmd = construct_command(CMD_MODE, [0x1, mode])
        self.ser.write(cmd)
        self.read_response()
    
    def cmd_set_sleep(self, sleep):
        """Put sensor to sleep (1) or wake it (0)."""
        mode = 0 if sleep else 1
        cmd = construct_command(CMD_SLEEP, [0x1, mode])
        self.ser.write(cmd)
        self.read_response()
    
    def cmd_query_data(self):
        """Query sensor for PM data."""
        cmd = construct_command(CMD_QUERY_DATA)
        self.ser.write(cmd)
        d = self.read_response()
        
        if len(d) == 10 and d[0] == 0xaa and d[1] == 0xc0 and d[9] == 0xab:
            pm25 = (d[2] + d[3] * 256) / 10.0
            pm10 = (d[4] + d[5] * 256) / 10.0
            return pm25, pm10
        return None, None
    
    def read_response(self):
        """Read one response packet from sensor."""
        byte = b''
        retries = 0
        max_retries = 10  # Try reading header byte multiple times
        
        while byte != b'\xaa' and retries < max_retries:
            byte = self.ser.read(size=1)
            if not byte:
                retries += 1
                time.sleep(0.1)
        
        if byte != b'\xaa':
            raise TimeoutError("No response from sensor")
            
        d = self.ser.read(size=9)
        if len(d) != 9:
            raise TimeoutError(f"Incomplete response: expected 9 bytes, got {len(d)}")
            
        return byte + d
    
    def sensor_loop(self):
        """Background thread: 60s read cycle, 60s sleep cycle."""
        if not self.ser:
            return
        
        # Try to initialize sensor if not done during startup
        try:
            log.info("Background thread: attempting sensor initialization")
            self.cmd_set_sleep(0)
            time.sleep(2)
            self.ser.flushInput()
            self.cmd_set_mode(MODE_QUERY)
            log.info("Background thread: sensor initialized")
        except Exception as e:
            log.warning("Background thread: initialization failed, will retry in loop: %s", e)
        
        while self.running:
            try:
                # Wake up sensor
                log.info("Waking sensor for %ds reading period", self.read_period)
                self.cmd_set_sleep(0)
                time.sleep(1)  # Give sensor time to stabilize
                
                # Read for specified period
                start_time = time.time()
                samples = []
                
                while time.time() - start_time < self.read_period:
                    try:
                        pm25, pm10 = self.cmd_query_data()
                        if pm25 is not None and pm10 is not None:
                            samples.append((pm25, pm10))
                            if self.log_raw:
                                log.debug("Sample: PM2.5=%.1f µg/m³ PM10=%.1f µg/m³", pm25, pm10)
                    except Exception as e:
                        log.warning("Read error during sampling: %s", e)
                    
                    time.sleep(self.sample_interval)
                
                # Use last valid sample
                if samples:
                    pm25, pm10 = samples[-1]
                    with self.lock:
                        self.latest_pm25 = pm25
                        self.latest_pm10 = pm10
                        self.last_update = int(time.time())
                    
                    log.info("Reading period complete. Last values: PM2.5=%.1f, PM10=%.1f (from %d samples)",
                             pm25, pm10, len(samples))
                    
                    # Write to JSON
                    self.write_json(self.last_update, pm25, pm10)
                else:
                    log.warning("No valid samples collected during reading period")
                
                # Put sensor to sleep (turns off fan)
                log.info("Putting sensor to sleep for %ds", self.sleep_period)
                self.cmd_set_sleep(1)
                time.sleep(self.sleep_period)
                
            except Exception as e:
                log.error("Error in sensor loop: %s", e)
                time.sleep(10)  # Wait before retrying
    
    def new_loop_packet(self, event):
        """Add latest PM2.5 and PM10 values to loop packet."""
        with self.lock:
            if self.url and (self.last_update is None or
                    time.time() - self.last_update > 2 * self.http_poll_interval):
                return
            if self.latest_pm25 is not None and self.latest_pm10 is not None:
                event.packet['pm2_5'] = self.latest_pm25
                event.packet['pm10_0'] = self.latest_pm10
    
    def write_json(self, ts, pm25, pm10):
        """Write latest readings to particles.json (atomic update)."""
        data = {
            "dateTime": ts,
            "pm2_5": pm25,
            "pm10_0": pm10
        }
        
        try:
            dirpath = os.path.dirname(self.json_output)
            
            # Ensure directory exists
            os.makedirs(dirpath, mode=0o755, exist_ok=True)
            
            # Write to temporary file
            with tempfile.NamedTemporaryFile('w', dir=dirpath, delete=False) as tmpfile:
                json.dump(data, tmpfile)
                tmpname = tmpfile.name
            
            # Set file permissions (ownership changes removed to suppress warnings)
            os.chmod(tmpname, 0o644)
            
            # Atomic replace
            os.replace(tmpname, self.json_output)
            
        except Exception as e:
            log.error("Could not write particles.json: %s", e)
    
    def shutDown(self):
        """Clean shutdown."""
        log.info("Shutting down %s service", DRIVER_NAME)
        self.running = False
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        if self.ser:
            try:
                self.cmd_set_sleep(1)  # Put sensor to sleep before closing
            except:
                pass
            self.ser.close()
