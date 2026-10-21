#
# Modified 2026-10-22 by weewx-packages.
# installer for the weewx-NovaSDS011 extension - see the readme.txt and CREDITS
# files for more details....
#
#-----
# 
# Copyright 2025 Ian Millard
#-----

from weecfg.extension import ExtensionInstaller

def loader():
    return NovaSDS011Installer()

class NovaSDS011Installer(ExtensionInstaller):
    def __init__(self):
        super(NovaSDS011Installer, self).__init__(
            version="1.1.0",
            name='NovaSDS011',
            description='Collects 2.5 and 10.0 particle data from SDS011 particle sensor.',
            author="Ian Millard",
            author_email="ianmillard@icloud.com",
            process_services='user.novaSDS011.NovaSDS011Service',
            config={
                'NovaSDS011': {
                    'port' : '/dev/ttyUSB0',
                    'timeout' : '3.0',
                    'json_output' : '/var/www/html/divumwx/jsondata/particles.txt',
                    'log_raw' : 'True',
                    'read_period' : '60',    # seconds to actively read
                    'sleep_period' : '60',    # seconds to sleep (fan off)
                    'sample_interval' : '2',    # seconds between samples when reading
                    }},
            files=[('bin/user', ['bin/user/novaSDS011.py'])]
            )
