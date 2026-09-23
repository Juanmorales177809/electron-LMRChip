from __future__ import annotations
import re
import time
from math import isfinite
import serial
from serial.tools import list_ports


class PR59Controller:

    # Fixed controller settings. The GUI should only provide R0/setpoint.
    FIXED_SETTINGS = (
                    (1, 8.0),  # kP
                    (2, 0.20),  # kI
                    (3, 14.0),  # kD
                    (4, 2.0),  # low-pass filter A
                    (5, 3.0),  # low-pass filter B
                    (6, 30.0),  # max output power
                    (7, 0.1),  # output dead band
                    (8, 10.0),  # integral limit
                    (9, 0.05),  # internal sample period
                    (10, 0.65),  # cooling gain
                    (11, 1.0),  # heating gain
                    (12, 0.1),  # decay when stopped
                    (13, 6))  # PID mode


    DEFAULT_MIN_SETPOINT = 10.0
    DEFAULT_MAX_SETPOINT = 80.0
    TEMP_SENSOR_REGISTERS = {
        1: 100,  # Temp 1 value
        2: 101,  # Temp 2 value
        3: 102,  # Temp 3 value
        4: 103,  # Temp FET / onboard value
    }

    def __init__(
        self,
        min_setpoint: float = DEFAULT_MIN_SETPOINT,
        max_setpoint: float = DEFAULT_MAX_SETPOINT,
    ) -> None:
        if min_setpoint >= max_setpoint:
            raise ValueError("min_setpoint must be lower than max_setpoint.")

        self.min_setpoint = min_setpoint
        self.max_setpoint = max_setpoint
        self.timeout = 5.0
        self.running = False
        self.streaming = False
        self.ser: serial.Serial | None = None

    def connect(self, port: str = "COM13", baudrate: int = 115200, timeout: float = 5.0) -> str:
        """Open the serial port and verify communication with the controller."""
        if getattr(self, "ser", None) and self.ser.is_open:
            raise RuntimeError("PR-59 is already connected. Disconnect before reconnecting.")

        self.timeout = timeout
        self.running = False
        self.streaming = False

        available_ports = [p.device for p in list_ports.comports()]
        if port.upper() not in {p.upper() for p in available_ports}:
            raise RuntimeError(f"Port {port} is not available. Available ports: {available_ports}")

        self.ser = serial.Serial(
            port,
            baudrate,
            bytesize=serial.EIGHTBITS,
            stopbits=serial.STOPBITS_ONE,
            parity=serial.PARITY_NONE,
            timeout=timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False)

        try:
            time.sleep(0.75)
            self.ser.reset_input_buffer()
            self.ser.write(b"\r")
            time.sleep(0.20)
            self.ser.reset_input_buffer()

            self.ser.write(b"$A\r")
            time.sleep(0.20)
            self.ser.reset_input_buffer()

            try:
                version = self.send_command("$V", timeout=timeout)
            except TimeoutError:
                time.sleep(0.20)
                self.ser.reset_input_buffer()
                version = self.send_command("$v", timeout=timeout)

            if not version.strip():
                raise RuntimeError("The PR-59 returned an empty version response.")
            return version
        except Exception:
            self.disconnect()
            raise

    def disconnect(self) -> None:
        """Stop the controller if needed and close the serial port."""
        try:
            if getattr(self, "running", False):
                self.stop_control()
            elif getattr(self, "streaming", False):
                self.stop_stream()
        finally:
            if getattr(self, "ser", None) and self.ser.is_open:
                self.ser.close()
            self.ser = None
            self.running = False
            self.streaming = False

    def send_command(self, command: str, timeout: float | None = None) -> str:
        """Send one ASCII command terminated with CR and read until the PR-59 prompt."""
        ser = self._serial()
        ser.reset_input_buffer()
        ser.write((command + "\r").encode("ascii"))

        raw = bytearray()
        limit = self.timeout if timeout is None else timeout
        start = time.monotonic()

        while time.monotonic() - start < limit:
            if ser.in_waiting:
                raw.extend(ser.read(ser.in_waiting))
                prompt_at = raw.find(b"\r\n> ")
                if prompt_at >= 0:
                    return self._clean_response(bytes(raw[:prompt_at]), command)
            else:
                time.sleep(0.005)

        preview = bytes(raw).decode("ascii", errors="replace").replace("\r", "\\r")
        raise TimeoutError(f"Timeout while waiting for {command!r}. Received: {preview!r}")
    
    def start_control(self, setpoint: float) -> None:
        """Write the setpoint and fixed settings, start PID control, then start data streaming."""
        self._validate_setpoint(setpoint)

        was_streaming = getattr(self, "streaming", False)
        if was_streaming:
            self.stop_stream()

        settings = ((0, setpoint), *self.FIXED_SETTINGS)
        for register, value in settings:
            self._write_register(register, value)

        response = self.send_command("$W", timeout=3.0)
        if "run" not in response.lower():
            raise RuntimeError(f"Unexpected start response: {response}")
        self.running = True
        self.start_stream()

    def stop_control(self) -> None:
        """Stop data streaming and clear the controller RUN flag."""
        if getattr(self, "streaming", False):
            self.stop_stream()

        response = self.send_command("$Q", timeout=3.0)
        if "stop" not in response.lower():
            raise RuntimeError(f"Unexpected stop response: {response}")
        self.running = False

    def set_setpoint(self, setpoint: float) -> None:
        """Update only the temperature setpoint while keeping the fixed settings unchanged."""
        self._validate_setpoint(setpoint)

        was_streaming = getattr(self, "streaming", False)
        if was_streaming:
            self.stop_stream()

        try:
            self._write_register(0, setpoint)
        finally:
            if was_streaming:
                self.start_stream()

    def start_stream(self) -> None:
        """Start the A3 stream used for plate and ambient temperature readings."""
        ser = self._serial()
        ser.reset_input_buffer()
        ser.write(b"$A3\r")
        time.sleep(0.10)
        self.streaming = True

    def stop_stream(self) -> None:
        """Stop any continuous stream from the controller."""
        if not getattr(self, "ser", None) or not self.ser.is_open:
            self.streaming = False
            return
        self.ser.write(b"$A\r")
        time.sleep(0.10)
        self.ser.reset_input_buffer()
        self.streaming = False

    def read_sample(self) -> dict | None:
        """Read one A3 sample with block temperature, ambient temperature, setpoint, and output."""
        if not getattr(self, "streaming", False):
            self.start_stream()
        line = self._serial().read_until(b"\r").decode("ascii", errors="replace")
        return self._parse_a3_sample(line)

    def read_temperature_sensor(self, sensor_number: int) -> float | None:
        """Read one temperature sensor from the PR-59 runtime registers."""
        try:
            register = self.TEMP_SENSOR_REGISTERS[sensor_number]
        except KeyError as error:
            raise ValueError("sensor_number must be 1, 2, 3, or 4.") from error

        return self._read_temperature_register(register)

    def read_onboard_temp(self) -> float | None:
        """Read the onboard Temp FET sensor, documented as runtime register R103."""
        return self.read_temperature_sensor(4)

    def read_monitoring_values(self) -> dict[str, float | None]:
        """Read onboard temperature, input voltage, and main load current."""
        was_streaming = getattr(self, "streaming", False)
        if was_streaming:
            self.stop_stream()

        try:
            onboard_temp = self._valid_temperature(self._read_runtime_register(103))
            return {
                "onboard_temp": onboard_temp,
                "input_voltage": self._read_runtime_register(150),
                "main_current": self._read_runtime_register(152),
            }
        finally:
            if was_streaming:
                self.start_stream()

    def read_all_temperature_sensors(self) -> dict[str, float | None]:
        """Read Temp 1, Temp 2, Temp 3, and onboard Temp 4 from runtime registers."""
        was_streaming = getattr(self, "streaming", False)
        if was_streaming:
            self.stop_stream()

        try:
            return {
                "temp_sensor_1": self._read_temperature_register(100),
                "temp_sensor_2": self._read_temperature_register(101),
                "temp_sensor_3": self._read_temperature_register(102),
                "temp_sensor_4": self._read_temperature_register(103),
            }
        finally:
            if was_streaming:
                self.start_stream()

    def _write_register(self, register: int, value: int | float) -> str:
        response = self.send_command(f"$R{register}={value:.9g}", timeout=3.0)
        self._require_successful_register_write(register, value, response)
        return response

    def _read_temperature_register(self, register: int) -> float | None:
        was_streaming = getattr(self, "streaming", False)
        if was_streaming:
            self.stop_stream()

        try:
            value = self._read_runtime_register(register)
            return self._valid_temperature(value)
        finally:
            if was_streaming:
                self.start_stream()

    def _read_runtime_register(self, register: int) -> float:
        response = self.send_command(f"$R{register}?", timeout=3.0)
        value = self._parse_register_float(response, register)
        if not isfinite(value):
            raise RuntimeError(f"R{register} returned a non-finite value: {value!r}")
        return value

    @staticmethod
    def _parse_register_float(response: str, register: int) -> float:
        for token in response.replace(",", " ").split():
            try:
                return float(token)
            except ValueError:
                continue

        raise RuntimeError(f"Could not parse numeric response from R{register}: {response!r}")

    def _validate_setpoint(self, setpoint: float) -> None:
        if not isfinite(setpoint):
            raise ValueError(f"Setpoint must be finite, got {setpoint!r}.")

        if not self.min_setpoint <= setpoint <= self.max_setpoint:
            raise ValueError(
                f"Setpoint {setpoint:.3g} is outside the safe range "
                f"{self.min_setpoint:.3g}-{self.max_setpoint:.3g} C."
            )

    @staticmethod
    def _require_successful_register_write(register: int, value: int | float, response: str) -> None:
        lowered = response.lower()
        error_words = ("error", "invalid", "fail", "unknown", "out of range")
        if any(word in lowered for word in error_words):
            raise RuntimeError(f"Failed to write R{register}={value:.9g}: {response}")

    @staticmethod
    def _parse_a3_sample(line: str) -> dict | None:
        text = line.strip().removeprefix("[").removesuffix("]").strip()
        parts = re.split(r"\s+", text)
        if len(parts) != 13 or parts[0] != "3":
            return None

        try:
            values = [float(x) for x in parts[3:13]]
        except ValueError:
            return None

        output = values[0]
        temp_sensor_1 = PR59Controller._valid_temperature(values[1])
        temp_sensor_2 = PR59Controller._valid_temperature(values[2])
        setpoint = values[3]
        active_temp = PR59Controller._valid_temperature(values[4])

        # Project wiring confirmed for now:
        # - Temp sensor 1 reads the block and is the control-critical sensor.
        # - Temp sensor 2 is reserved for ambient temperature, but is not installed yet.
        # - Temp sensor 3 is not connected.
        # - Temp sensor 4 is onboard, but it is not reported separately by A3.
        # A3 observed format: [3 ERR Mode Tc Ta1 Ta2 Tr Ta Tp Ti Td TLP_A TLP_B].
        # In A3, Ta is the active regulator temperature and can be equal to Ta1.
        # A value around -999.90 means the controller is reporting an invalid/missing sensor.
        return {
            "output": output,
            "setpoint": setpoint,
            "raw_values": values,
            "raw_line": line.strip(),
            "temp_sensor_1": temp_sensor_1,
            "temp_sensor_2": temp_sensor_2,
            "temp_sensor_3": None,
            "temp_sensor_4": None,
            "block_temp": temp_sensor_1,
            "ambient_temp": temp_sensor_2,
            "onboard_temp": None,
            "active_temp": active_temp,
            "T1": temp_sensor_1,
            "T2": temp_sensor_2,
            "Ta": active_temp,
            "P": values[5],
            "I": values[6],
            "D": values[7],
            "TLP_A": values[8],
            "TLP_B": values[9],
        }

    @staticmethod
    def _valid_temperature(value: float) -> float | None:
        if value <= -900:
            return None
        return value

    @staticmethod
    def _clean_response(raw: bytes, command: str) -> str:
        lines = raw.decode("ascii", errors="replace").replace("\r", "\n").splitlines()
        lines = [line.strip() for line in lines if line.strip()]
        if lines and lines[0] == command:
            lines.pop(0)
        return "\n".join(lines)

    def _serial(self) -> serial.Serial:
        if not getattr(self, "ser", None) or not self.ser.is_open:
            raise RuntimeError("PR-59 is not connected.")
        return self.ser
