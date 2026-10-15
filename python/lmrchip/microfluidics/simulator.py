"""Explicit GRBL simulator for development without a connected machine."""

import time


class SimulatedGrblController:
    def __init__(self, port="SIMULATED", **_options):
        self.port = port
        self.is_connected = False

    def connect(self):
        if self.port != "SIMULATED":
            raise RuntimeError("Simulator only accepts the SIMULATED port.")
        self.is_connected = True

    def close(self): self.is_connected = False
    def unlock(self): return ["ok"]
    def home(self): return ["ok"]
    def move_x(self, value=1): return ["ok"]
    def move_y(self, value=1): return ["ok"]
    def move_z(self, value=1): return ["ok"]
    def move_a(self, value=1): return ["ok"]
    def wait_until_idle(self, timeout=60.0, poll_interval=0.1):
        time.sleep(0.02)
        return "<Idle|MPos:0.000,0.000,0.000>"
    def get_status(self, timeout=2.0): return "<Idle|MPos:0.000,0.000,0.000>"
