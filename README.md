# 🌫️ weewx-NovaSDS011

A **WeeWX 5.1 service** for the **Nova SDS011 particulate sensor**.  
It injects real-time particulate matter values into WeeWX (`pm2_5`, `pm10_0`) and outputs a JSON snapshot (`particles.txt`) for dashboards or external scripts.

![WeeWX](https://img.shields.io/badge/WeeWX-5.1+-blue)  
![License](https://img.shields.io/badge/License-GPLv3-green)  
![Status](https://img.shields.io/badge/Status-Active-success)

---

## 📦 Features

- **Query mode operation** — polls the SDS011 sensor with proper sleep/wake cycles
- **60s read / 60s sleep cycle** — extends sensor life by turning off fan during sleep
- Injects **PM2.5** and **PM10.0** into WeeWX loop packets (and archive)
- Writes **`particles.txt`** with latest readings for web access
- **Atomic JSON file writes** with proper `www-data:www-data` ownership
- **Thread-safe operation** — background thread manages sensor, main thread serves WeeWX
- **Multiple samples per cycle** — collects samples every 2 seconds during read period
- Fully configurable via `weewx.conf`
- Clean install/uninstall using the **WeeWX extension system** (`weectl`)

---

## 📂 File Layout

```
weewx-NovaSDS011/
├── bin/
│   └── user/
│       └── novaSDS011.py     # Main service code
├── install.py                # Installer script for weectl
├── manifest.xml              # Extension metadata and default config
├── LICENSE                   # GPLv3 license
└── README.md                 # This file
```

---



## 🛠️ Installation

1. Activate your virtual environment (Only for users who installed WeeWX using PIP into a virtual environment):
   ```bash
   source ~/weewx-venv/bin/activate
   ```

2. Install via the WeeWX extension manager directly from GitHub:
   ```bash
   weectl extension install https://github.com/Millardiang/weewx-NovaSDS011/archive/refs/heads/main.zip
   ```

3. Verify the `[NovaSDS011]` stanza exists in `weewx.conf`.

4. Restart WeeWX:
   ```bash
   sudo systemctl restart weewx
   ```

5. Verify operation in the logs:
   ```bash
   sudo journalctl -u weewx -f
   ```
   You should see messages about the sensor waking, reading, and sleeping.

---
## ⚙️ Configuration

After installation, the following stanza is added to `weewx.conf`:

```ini
[Engine]
    [[Services]]
        data_services = user.novaSDS011.NovaSDS011Service

[NovaSDS011]
    # Serial port configuration
    port = /dev/ttyUSB0
    timeout = 3.0
    
    # Read/Sleep cycle configuration
    read_period = 60          # seconds to actively read samples
    sleep_period = 60         # seconds to sleep (fan off)
    sample_interval = 2       # seconds between samples during read period
    
    # JSON output configuration
    json_output = /var/www/html/divumwx/jsondata/particles.txt
    file_owner = www-data     # owner for JSON file
    file_group = www-data     # group for JSON file
    
    # Logging
    log_raw = True           # log each individual sample
```

### Options

| Option            | Default                                        | Description |
|-------------------|------------------------------------------------|-------------|
| `port`            | `/dev/ttyUSB0`                                | Serial port of SDS011 |
| `timeout`         | `3.0`                                         | Serial read timeout (seconds) |
| `read_period`     | `60`                                          | Duration (seconds) to actively sample sensor |
| `sleep_period`    | `60`                                          | Duration (seconds) sensor sleeps with fan off |
| `sample_interval` | `2`                                           | Seconds between samples during read period |
| `json_output`     | `/var/www/html/weewx/jsondata/particles.txt`  | Path to write JSON |
| `file_owner`      | `www-data`                                    | User ownership for JSON file |
| `file_group`      | `www-data`                                    | Group ownership for JSON file |
| `log_raw`         | `false`                                       | Log each individual sample to debug log |

---

## 📊 Output

### Database  
Stored in default WeeWX schema fields:  
- `pm2_5` — Particulate Matter 2.5 (µg/m³)
- `pm10_0` — Particulate Matter 10.0 (µg/m³)

### JSON  
Realtime `particles.txt` example:
```json
{
  "dateTime": 1738471834,
  "pm2_5": 12.3,
  "pm10_0": 24.7
}
```

- File is **overwritten** on each read cycle (no history)
- Owned by `www-data:www-data` for web server access
- Atomic writes prevent corruption during updates

---

## 🔄 How It Works

1. **Wake Cycle (60 seconds)**:
   - Service wakes the sensor (fan turns on)
   - Collects samples every 2 seconds
   - Keeps last valid reading

2. **Sleep Cycle (60 seconds)**:
   - Puts sensor to sleep (fan turns off)
   - Extends sensor lifespan by reducing wear
   - Cached values continue to be added to WeeWX loop packets

3. **WeeWX Integration**:
   - Latest readings are injected into every loop packet
   - Values are archived according to WeeWX configuration
   - JSON file is updated once per read cycle

---

## 🔧 Troubleshooting

### Permission Errors
If you see "Forbidden" errors accessing the JSON file:
- Ensure WeeWX is running as root (required for `chown` operations)
- Check directory permissions: `ls -la /var/www/html/weewx/jsondata/`
- Manually fix if needed: `sudo chown -R www-data:www-data /var/www/html/weewx/jsondata/`

### Serial Port Access
If the sensor can't be opened:
```bash
# Add weewx user to dialout group (if not running as root)
sudo usermod -a -G dialout weewx

# Check port permissions
ls -l /dev/ttyUSB0
```

### No Readings
- Check logs: `sudo journalctl -u weewx -n 100`
- Verify sensor is connected: `ls /dev/ttyUSB*`
- Enable debug logging: set `log_raw = true` in config
- Test sensor manually with provided test script

---

## 🔧 Uninstall

To remove:
```bash
weectl extension uninstall weewx-NovaSDS011
```

Then restart WeeWX:
```bash
sudo systemctl restart weewx
```

---

## 📝 License

This project is licensed under the terms of the [GNU GPL v3](./LICENSE).  
Copyright (C) 2025 **Ian Millard**

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## 📧 Support

For issues and questions, please use the [GitHub Issues](https://github.com/Millardiang/weewx-NovaSDS011/issues) page.

## Local HTTP sensors

On the `repair/sds011-http` branch, version 1.1.0 also accepts a
Sensor.Community sensor's local JSON endpoint. Set these options in `[NovaSDS011]`:

```ini
    url = http://192.168.178.49/data.json
    timeout = 3
    http_poll_interval = 60
```

With `url` set, the service opens no serial port. It reads `SDS_P2` as PM2.5 and
`SDS_P1` as PM10, in micrograms per cubic metre. Cached values expire after twice
the polling interval. Responses older than that, negative values and non-finite
concentrations are rejected. Shutdown interrupts the wait between HTTP polls.
The configured `json_output` still controls the optional dashboard snapshot.

This endpoint format differs from the remote Sensor.Community history and
OpenSenseMap sensor APIs. Those response formats need separate adapters.

Run `python -m pytest -q tests`. Tests use a local HTTP server, zero and invalid
measurements, and a real pseudo-terminal for serial-open behavior. WeeWX 5.2
already defines the `pm2_5`/`pm10_0` concentration units in every unit system.
