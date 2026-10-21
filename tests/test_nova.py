# Copyright 2026 weewx-packages
# Distributed under the terms of the GNU Public License (GPLv3)
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import pty
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import weewx
import weewx.units

spec = importlib.util.spec_from_file_location('nova', Path(__file__).parents[1] / 'bin/user/novaSDS011.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def endpoint():
    payload = {'age': '26', 'sensordatavalues': [{'value_type': 'SDS_P1', 'value': '5.75'}, {'value_type': 'SDS_P2', 'value': '0'}]}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:%d/data.json' % server.server_port, payload
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def service(monkeypatch, tmp_path, **config):
    monkeypatch.setattr(m.threading.Thread, 'start', lambda _: None)
    return m.NovaSDS011Service(Mock(), {'NovaSDS011': dict(json_output=str(tmp_path / 'particles.json'), **config)})


def test_local_http_data_without_serial(monkeypatch, tmp_path, endpoint):
    url, _ = endpoint
    serial_open = Mock(side_effect=RuntimeError('HTTP must not open serial'))
    monkeypatch.setattr(m.serial, 'Serial', serial_open)
    instance = service(monkeypatch, tmp_path, url=url)
    assert instance.ser is None
    serial_open.assert_not_called()
    assert instance.query_http() == (0, 5.75)
    instance.shutDown()


@pytest.mark.parametrize('bad', ['NaN', '-1', 'infinity'])
def test_invalid_concentration_rejected(monkeypatch, tmp_path, endpoint, bad):
    url, payload = endpoint
    payload['sensordatavalues'][0]['value'] = bad
    instance = service(monkeypatch, tmp_path, url=url)
    with pytest.raises(ValueError, match='Invalid particulate'):
        instance.query_http()


def test_stale_response_rejected(monkeypatch, tmp_path, endpoint):
    url, payload = endpoint
    payload['age'] = '121'
    instance = service(monkeypatch, tmp_path, url=url)
    with pytest.raises(ValueError, match='stale'):
        instance.query_http()


def test_cached_values_expire_and_zero_is_injected(monkeypatch, tmp_path):
    instance = service(monkeypatch, tmp_path, url='http://127.0.0.1/data.json')
    instance.latest_pm25, instance.latest_pm10 = 0, 5.75
    instance.last_update = 100
    monkeypatch.setattr(m.time, 'time', lambda: 101)
    event = SimpleNamespace(packet={})
    instance.new_loop_packet(event)
    assert event.packet == {'pm2_5': 0, 'pm10_0': 5.75}
    monkeypatch.setattr(m.time, 'time', lambda: 221)
    event.packet = {}
    instance.new_loop_packet(event)
    assert event.packet == {}


def test_real_serial_port_opens_once(monkeypatch, tmp_path):
    master, slave = pty.openpty()
    monkeypatch.setattr(m.NovaSDS011Service, 'initialize_sensor', lambda _: None)
    try:
        instance = service(monkeypatch, tmp_path, port=os.ttyname(slave), timeout=.01)
        assert instance.ser.is_open
        assert instance.thread is not None
        monkeypatch.setattr(instance, 'cmd_set_sleep', lambda _: None)
        instance.shutDown()
        assert not instance.ser.is_open
    finally:
        os.close(master)
        os.close(slave)


def test_builtin_concentration_units():
    for name in ['pm2_5', 'pm10_0']:
        for unit_system in [weewx.US, weewx.METRIC, weewx.METRICWX]:
            assert weewx.units.getStandardUnitType(unit_system, name) == ('microgram_per_meter_cubed', 'group_concentration')


def test_http_loop_stores_and_stops(monkeypatch, tmp_path):
    instance = service(monkeypatch, tmp_path, url='http://127.0.0.1/data.json')
    instance.query_http = Mock(return_value=(1, 2))
    instance.stop_event = Mock()
    instance.stop_event.is_set.side_effect = [False, True]
    instance.http_loop()
    assert instance.latest_pm25 == 1
    assert json.loads((tmp_path / 'particles.json').read_text())['pm10_0'] == 2
    instance.stop_event.wait.assert_called_once_with(60)


def test_request_timeout_is_explicit(monkeypatch, tmp_path):
    instance = service(monkeypatch, tmp_path, url='http://127.0.0.1/data.json', timeout=.1)
    monkeypatch.setattr(m.urllib.request, 'urlopen', Mock(side_effect=TimeoutError('slow sensor')))
    with pytest.raises(TimeoutError):
        instance.query_http()
    m.urllib.request.urlopen.assert_called_once_with(instance.url, timeout=.1)
