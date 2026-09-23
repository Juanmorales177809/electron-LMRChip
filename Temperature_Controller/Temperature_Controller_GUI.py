"""Simple Tkinter test GUI for the TC-XX-PR-59 temperature controller."""

from __future__ import annotations

import re
import sys
import threading
import time
import traceback
from math import nan
from pathlib import Path
from queue import Empty, Queue
from tkinter import messagebox
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from serial.tools import list_ports


CONTROLLER_DIR = Path(
    r"C:\Users\juansebastian.soto\Desktop\Proyecto microfluidica\Temperature Controller"
)
if str(CONTROLLER_DIR) not in sys.path:
    sys.path.insert(0, str(CONTROLLER_DIR))

from Temperature_Controller import PR59Controller  # noqa: E402


READ_INTERVAL_S = 0.10
MONITOR_READ_INTERVAL_S = 2.0


def parse_a3_raw_values(line: str) -> list[float]:
    text = line.strip().removeprefix("[").removesuffix("]").strip()
    parts = re.split(r"\s+", text)
    if len(parts) != 13 or parts[0] != "3":
        return []

    try:
        return [float(x) for x in parts[3:13]]
    except ValueError:
        return []


class TemperatureControllerGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title("PR-59 Temperature Controller Test")
        self.geometry("1100x720")
        self.minsize(980, 620)

        self.controller: PR59Controller | None = None
        self.serial_lock = threading.Lock()
        self.reader_stop = threading.Event()
        self.reader_thread: threading.Thread | None = None
        self.queue: Queue[tuple] = Queue()

        self.connected = False
        self.running = False
        self.logging_enabled = False

        self.time_data: list[float] = []
        self.temp1_data: list[float] = []
        self.onboard_temp_data: list[float] = []
        self.setpoint_data: list[float] = []
        self.latest_onboard_temp: float | None = None
        self.latest_input_voltage: float | None = None
        self.latest_main_current: float | None = None

        self.port_var = tk.StringVar(value="COM13")
        self.setpoint_var = tk.DoubleVar(value=37.0)
        self.status_var = tk.StringVar(value="Ready.")

        self.sensor_vars = {
            "temp_sensor_1": tk.StringVar(value="--"),
            "temp_sensor_2": tk.StringVar(value="--"),
            "temp_sensor_3": tk.StringVar(value="--"),
            "temp_sensor_4": tk.StringVar(value="--"),
            "block_temp": tk.StringVar(value="--"),
            "ambient_temp": tk.StringVar(value="--"),
            "onboard_temp": tk.StringVar(value="--"),
            "active_temp": tk.StringVar(value="--"),
            "output": tk.StringVar(value="--"),
            "setpoint": tk.StringVar(value="--"),
            "input_voltage": tk.StringVar(value="--"),
            "main_current": tk.StringVar(value="--"),
            "raw": tk.StringVar(value="--"),
        }

        self._build_layout()
        self._refresh_ports()
        self._set_connected_state(False)
        self.after(100, self._process_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_layout(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        controls = ttk.Frame(self, padding=12)
        controls.grid(row=0, column=0, sticky="ns")

        plot_area = ttk.Frame(self, padding=(0, 12, 12, 12))
        plot_area.grid(row=0, column=1, sticky="nsew")
        plot_area.columnconfigure(0, weight=1)
        plot_area.rowconfigure(0, weight=1)

        self._build_controls(controls)
        self._build_plot(plot_area)

        status = ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w", padding=6)
        status.grid(row=1, column=0, columnspan=2, sticky="ew")

    def _build_controls(self, parent: ttk.Frame) -> None:
        connection = ttk.LabelFrame(parent, text="Conexion", padding=10)
        connection.pack(fill="x", pady=(0, 10))

        ttk.Label(connection, text="Puerto").pack(anchor="w")
        self.port_combo = ttk.Combobox(connection, textvariable=self.port_var, width=18)
        self.port_combo.pack(fill="x", pady=(0, 6))

        ttk.Button(connection, text="Refresh ports", command=self._refresh_ports).pack(fill="x")
        self.connect_button = ttk.Button(connection, text="Connect", command=self._connect)
        self.connect_button.pack(fill="x", pady=(6, 0))
        self.disconnect_button = ttk.Button(connection, text="Disconnect", command=self._disconnect)
        self.disconnect_button.pack(fill="x", pady=(6, 0))

        control = ttk.LabelFrame(parent, text="Control", padding=10)
        control.pack(fill="x", pady=(0, 10))

        ttk.Label(control, text="Setpoint (deg C)").pack(anchor="w")
        self.setpoint_spinbox = ttk.Spinbox(
            control,
            from_=0.0,
            to=100.0,
            increment=0.1,
            textvariable=self.setpoint_var,
            width=12,
        )
        self.setpoint_spinbox.pack(fill="x", pady=(0, 6))

        self.start_button = ttk.Button(control, text="Start", command=self._start_control)
        self.start_button.pack(fill="x")
        self.stop_button = ttk.Button(control, text="Stop", command=self._stop_control)
        self.stop_button.pack(fill="x", pady=(6, 0))

        sensors = ttk.LabelFrame(parent, text="Sensores", padding=10)
        sensors.pack(fill="x")

        rows = (
            ("Temp sensor 1 / bloque", "temp_sensor_1"),
            ("Temp sensor 2 / ambiente", "temp_sensor_2"),
            ("Temp sensor 3", "temp_sensor_3"),
            ("Temp sensor 4 / onboard", "temp_sensor_4"),
            ("Bloque", "block_temp"),
            ("Ambiente", "ambient_temp"),
            ("Onboard", "onboard_temp"),
            ("Active Ta", "active_temp"),
            ("Output", "output"),
            ("Setpoint", "setpoint"),
            ("Input voltage (V)", "input_voltage"),
            ("Main current (A)", "main_current"),
        )
        for label, key in rows:
            row = ttk.Frame(sensors)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=22).pack(side="left")
            ttk.Label(row, textvariable=self.sensor_vars[key], width=12, anchor="e").pack(side="right")

        raw_frame = ttk.LabelFrame(parent, text="A3 raw values", padding=10)
        raw_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(raw_frame, textvariable=self.sensor_vars["raw"], wraplength=260).pack(fill="x")

    def _build_plot(self, parent: ttk.Frame) -> None:
        self.figure = Figure(figsize=(7.5, 5), dpi=100)
        self.axis = self.figure.add_subplot(111)
        self.axis.set_title("Run temperature history")
        self.axis.set_xlabel("Time (s)")
        self.axis.set_ylabel("Temperature (deg C)")
        self.axis.grid(True, alpha=0.3)

        self.temp1_line, = self.axis.plot([], [], label="Temp 1 block", color="tab:red")
        self.onboard_temp_line, = self.axis.plot([], [], label="Temp 4 onboard", color="tab:blue")
        self.setpoint_line, = self.axis.plot([], [], label="Setpoint", color="black", linestyle="--")
        self.axis.legend(loc="upper right")

        self.canvas = FigureCanvasTkAgg(self.figure, master=parent)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    def _refresh_ports(self) -> None:
        ports = [port.device for port in list_ports.comports()]
        self.port_combo["values"] = ports
        if ports and self.port_var.get() not in ports:
            self.port_var.set(ports[0])

    def _connect(self) -> None:
        self._run_in_background(self._connect_worker)

    def _connect_worker(self) -> None:
        port = self.port_var.get().strip()
        if not port:
            self.queue.put(("error", "Select a serial port first."))
            return

        try:
            controller = PR59Controller()
            version = controller.connect(port=port, timeout=5.0)
            controller.ser.timeout = 0.3
            with self.serial_lock:
                self.controller = controller
                self.controller.start_stream()
            self.connected = True
            self.logging_enabled = True
            self.reader_stop.clear()
            self.queue.put(("clear_history",))
            self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.reader_thread.start()
            self.queue.put(("connected", f"Connected: {version}"))
        except Exception as error:
            self.queue.put(("error", f"Connection error: {error}"))

    def _disconnect(self) -> None:
        self._run_in_background(self._disconnect_worker)

    def _disconnect_worker(self) -> None:
        self.reader_stop.set()
        try:
            with self.serial_lock:
                if self.controller is not None:
                    self.controller.disconnect()
                    self.controller = None
            self.connected = False
            self.running = False
            self.logging_enabled = False
            self.queue.put(("disconnected", "Disconnected."))
        except Exception as error:
            self.queue.put(("error", f"Disconnect error: {error}"))

    def _start_control(self) -> None:
        self._run_in_background(self._start_worker)

    def _start_worker(self) -> None:
        try:
            setpoint = float(self.setpoint_var.get())
            with self.serial_lock:
                self._require_controller().start_control(setpoint)
            self.running = True
            self.logging_enabled = True
            self.queue.put(("status", f"Control started at {setpoint:.2f} deg C."))
        except Exception as error:
            self.queue.put(("error", f"Start error: {error}"))

    def _stop_control(self) -> None:
        self._run_in_background(self._stop_worker)

    def _stop_worker(self) -> None:
        try:
            with self.serial_lock:
                self._require_controller().stop_control()
                self._require_controller().start_stream()
            self.running = False
            self.logging_enabled = False
            self.queue.put(("status", "Control stopped. Run history is frozen. Sensor values still update."))
        except Exception as error:
            self.queue.put(("error", f"Stop error: {error}"))

    def _reader_loop(self) -> None:
        start = time.monotonic()
        next_monitor_read = 0.0

        while not self.reader_stop.is_set():
            try:
                with self.serial_lock:
                    controller = self._require_controller()
                    raw_line = controller._serial().read_until(b"\r").decode("ascii", errors="replace")
                    sample = controller._parse_a3_sample(raw_line)

                    now = time.monotonic()
                    if now >= next_monitor_read:
                        monitoring = controller.read_monitoring_values()
                        self.queue.put(("monitoring", monitoring))
                        next_monitor_read = now + MONITOR_READ_INTERVAL_S

                raw_values = parse_a3_raw_values(raw_line)
                if sample:
                    self.queue.put(("sample", time.monotonic() - start, sample, raw_values))
            except Exception as error:
                self.queue.put(("error", f"Read error: {error}"))
                time.sleep(1.0)
            time.sleep(READ_INTERVAL_S)

    def _process_queue(self) -> None:
        try:
            while True:
                event = self.queue.get_nowait()
                self._handle_event(event)
        except Empty:
            pass

        self.after(100, self._process_queue)

    def _handle_event(self, event: tuple) -> None:
        kind = event[0]
        if kind == "sample":
            _, elapsed, sample, raw_values = event
            self._update_sample(elapsed, sample, raw_values)
        elif kind == "monitoring":
            monitoring = event[1]
            self.latest_onboard_temp = monitoring["onboard_temp"]
            self.latest_input_voltage = monitoring["input_voltage"]
            self.latest_main_current = monitoring["main_current"]
            self.sensor_vars["temp_sensor_4"].set(self._format_value(self.latest_onboard_temp))
            self.sensor_vars["onboard_temp"].set(self._format_value(self.latest_onboard_temp))
            self.sensor_vars["input_voltage"].set(self._format_value(self.latest_input_voltage))
            self.sensor_vars["main_current"].set(self._format_value(self.latest_main_current))
        elif kind == "clear_history":
            self._clear_history()
        elif kind == "connected":
            self.status_var.set(event[1])
            self._set_connected_state(True)
        elif kind == "disconnected":
            self.status_var.set(event[1])
            self._set_connected_state(False)
        elif kind == "status":
            self.status_var.set(event[1])
            self._set_connected_state(self.connected)
        elif kind == "error":
            self.status_var.set(event[1])
            self._set_connected_state(self.connected)

    def _update_sample(self, elapsed: float, sample: dict, raw_values: list[float]) -> None:
        temp1 = sample.get("temp_sensor_1")
        active_temp = sample.get("active_temp")
        setpoint = sample.get("setpoint")

        self.sensor_vars["temp_sensor_1"].set(self._format_value(temp1))
        self.sensor_vars["temp_sensor_2"].set(self._format_value(sample.get("temp_sensor_2")))
        self.sensor_vars["temp_sensor_3"].set("not connected")
        self.sensor_vars["temp_sensor_4"].set(self._format_value(self.latest_onboard_temp))
        self.sensor_vars["block_temp"].set(self._format_value(sample.get("block_temp")))
        self.sensor_vars["ambient_temp"].set(self._format_value(sample.get("ambient_temp")))
        self.sensor_vars["onboard_temp"].set(self._format_value(self.latest_onboard_temp))
        self.sensor_vars["active_temp"].set(self._format_value(active_temp))
        self.sensor_vars["output"].set(self._format_value(sample.get("output")))
        self.sensor_vars["setpoint"].set(self._format_value(setpoint))
        self.sensor_vars["raw"].set(", ".join(f"A3[{i}]={value:.2f}" for i, value in enumerate(raw_values)))

        if not self.logging_enabled or temp1 is None or setpoint is None:
            return

        self.time_data.append(elapsed)
        self.temp1_data.append(temp1)
        self.onboard_temp_data.append(nan if self.latest_onboard_temp is None else self.latest_onboard_temp)
        self.setpoint_data.append(setpoint)
        self._redraw_plot()

    def _redraw_plot(self) -> None:
        times = list(self.time_data)
        if not times:
            return

        self.temp1_line.set_data(times, list(self.temp1_data))
        self.onboard_temp_line.set_data(times, list(self.onboard_temp_data))
        self.setpoint_line.set_data(times, list(self.setpoint_data))

        self.axis.relim()
        self.axis.autoscale_view()
        self.canvas.draw_idle()

    def _clear_history(self) -> None:
        self.time_data.clear()
        self.temp1_data.clear()
        self.onboard_temp_data.clear()
        self.setpoint_data.clear()
        self.latest_onboard_temp = None
        self.latest_input_voltage = None
        self.latest_main_current = None
        self.sensor_vars["input_voltage"].set("--")
        self.sensor_vars["main_current"].set("--")
        self.temp1_line.set_data([], [])
        self.onboard_temp_line.set_data([], [])
        self.setpoint_line.set_data([], [])
        self.axis.relim()
        self.axis.autoscale_view()
        self.canvas.draw_idle()

    def _set_connected_state(self, connected: bool) -> None:
        self.connect_button.configure(state=tk.DISABLED if connected else tk.NORMAL)
        self.disconnect_button.configure(state=tk.NORMAL if connected else tk.DISABLED)
        self.start_button.configure(state=tk.NORMAL if connected else tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL if connected else tk.DISABLED)
        self.port_combo.configure(state=tk.DISABLED if connected else "readonly")
        self.setpoint_spinbox.configure(state=tk.NORMAL if connected else tk.DISABLED)

    def _run_in_background(self, target) -> None:
        thread = threading.Thread(target=target, daemon=True)
        thread.start()

    def _require_controller(self) -> PR59Controller:
        if self.controller is None:
            raise RuntimeError("Controller is not connected.")
        return self.controller

    @staticmethod
    def _format_value(value: float | None) -> str:
        if value is None:
            return "--"
        return f"{value:.2f}"

    def _on_close(self) -> None:
        try:
            self.reader_stop.set()
            with self.serial_lock:
                if self.controller is not None:
                    self.controller.disconnect()
                    self.controller = None
        except Exception:
            traceback.print_exc()
        self.destroy()


if __name__ == "__main__":
    try:
        app = TemperatureControllerGUI()
        app.mainloop()
    except Exception:
        messagebox.showerror("PR-59 GUI Error", traceback.format_exc())
        raise
