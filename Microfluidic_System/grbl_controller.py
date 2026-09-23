import time
import serial


class GrblController:
    """Handles the serial connection and basic GRBL commands."""

    def __init__(
        self,
        port: str = "COM10",
        baudrate: int = 115200,
        timeout: float = 1,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_connection = None

    @property
    def is_connected(self) -> bool:
        return self.serial_connection is not None and self.serial_connection.is_open

    def connect(self) -> None:
        if self.is_connected:
            print("Ya hay conexion serial.")
            return

        self.serial_connection = serial.Serial(
            self.port,
            self.baudrate,
            timeout=self.timeout,
        )
        time.sleep(2)
        self.serial_connection.reset_input_buffer()

    def close(self) -> None:
        if self.serial_connection is not None:
            self.serial_connection.close()
            self.serial_connection = None

    def send_command(self, command: str) -> list[str]:
        """Send one GRBL command and wait for its ok response."""
        if not self.is_connected:
            raise RuntimeError("No hay conexion con GRBL.")

        full_command = (command + "\n").encode("ascii")
        print(f"Enviando a GRBL: {full_command}")
        self.serial_connection.write(full_command)

        lines = []

        while True:
            line = self.serial_connection.readline().decode(errors="ignore").strip()

            if line:
                lines.append(line)

            if line == "ok":
                return lines

            if line.startswith("error") or line.startswith("ALARM"):
                raise RuntimeError(f"GRBL respondio: {line}")

    def get_status(self, timeout: float = 2.0) -> str:
        """Request and return one real-time GRBL status report."""
        if not self.is_connected:
            raise RuntimeError("No hay conexion con GRBL.")

        self.serial_connection.write(b"?")
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            line = self.serial_connection.readline().decode(errors="ignore").strip()

            if line.startswith("<") and line.endswith(">"):
                return line

            if line.startswith("ALARM"):
                raise RuntimeError(f"GRBL respondio: {line}")

        raise TimeoutError("GRBL no respondio a la consulta de estado.")

    """Wait until GRBL confirms that all physical motion has finished."""
    def wait_until_idle(
        self,
        timeout: float = 60.0,
        poll_interval: float = 0.1) -> str:
        
        deadline = time.monotonic() + timeout
        last_status = "sin respuesta"

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()

            try:
                last_status = self.get_status(timeout=min(2.0, remaining))
            except TimeoutError:
                continue

            machine_state = last_status[1:].split("|", 1)[0]

            if machine_state == "Idle":
                return last_status

            if machine_state == "Alarm":
                raise RuntimeError(f"GRBL esta en alarma: {last_status}")

            time.sleep(min(poll_interval, remaining))

        raise TimeoutError(
            f"GRBL no llego al estado Idle. Ultimo estado: {last_status}")

    def get_settings(self) -> list[str]:
        return self.send_command("$$")

    def unlock(self) -> list[str]:
        return self.send_command("$X")

    def home(self) -> list[str]:
        return self.send_command("$H")

    def move_x(self, step_mm: float = 1) -> list[str]:
        return self.send_command(f"$J=G21G91X{step_mm}F2000")

    def move_y(self, step_mm: float = 1) -> list[str]:
        return self.send_command(f"$J=G21G91Y{step_mm}F800")

    def move_z(self, step_mm: float = 1) -> list[str]:
        return self.send_command(f"$J=G21G91Z{step_mm}F800")

    def move_a(self, step_mm: float = 1) -> list[str]:
        return self.send_command(f"$J=G21G91A{step_mm}F800")
