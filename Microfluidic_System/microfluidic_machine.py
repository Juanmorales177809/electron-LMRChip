import time

from grbl_controller import GrblController


class MicrofluidicMachine:
    """Controls carousel calibration, tube selection, and needle movement."""

    CAROUSEL_OFFSET = 4.0
    TUBE_COUNT = 12
    TUBE_SPACING = -30.0
    NEEDLE_TRAVEL = 37.0
    NEEDLE_LOWERING_DELAY = 1.0

    def __init__(self, grbl: GrblController):
        self.grbl = grbl
        self.is_calibrated = False
        self.current_tube = None
        self.needle_is_lowered = False

    def calibrate(self) -> None:
        """Run homing and leave the carousel aligned with tube 1."""
        self.is_calibrated = False
        self.current_tube = None
        self.needle_is_lowered = False

        self.grbl.unlock()
        self.grbl.home()
        self.grbl.wait_until_idle()

        self.grbl.move_x(self.CAROUSEL_OFFSET)
        self.grbl.wait_until_idle()

        self.current_tube = 1
        self.is_calibrated = True

    def run_tube(self, tube_number: int) -> None:
        """Select a tube, wait one second, and lower the needle."""
        self._require_calibration()

        if not 1 <= tube_number <= self.TUBE_COUNT:
            raise ValueError("El numero de tubo debe estar entre 1 y 12.")

        if tube_number == self.current_tube and self.needle_is_lowered:
            return

        if tube_number != self.current_tube:
            # The carousel must never rotate while the needle is lowered.
            if self.needle_is_lowered:
                self.raise_needle()

            tube_difference = tube_number - self.current_tube
            carousel_movement = tube_difference * self.TUBE_SPACING

            self.grbl.move_x(carousel_movement)
            self.grbl.wait_until_idle()
            self.current_tube = tube_number

        time.sleep(self.NEEDLE_LOWERING_DELAY)
        self.lower_needle()

    def lower_needle(self) -> None:
        """Lower the needle exactly 37 mm by sending Y-37."""
        self._require_calibration()

        if self.needle_is_lowered:
            raise RuntimeError("La aguja ya esta abajo.")

        self.grbl.move_y(-self.NEEDLE_TRAVEL)
        self.grbl.wait_until_idle()
        self.needle_is_lowered = True

    def raise_needle(self) -> None:
        """Raise the needle exactly 37 mm by sending Y+37."""
        self._require_calibration()

        if not self.needle_is_lowered:
            raise RuntimeError("La aguja ya esta arriba.")

        self.grbl.move_y(self.NEEDLE_TRAVEL)
        self.grbl.wait_until_idle()
        self.needle_is_lowered = False

    def _require_calibration(self) -> None:
        if not self.is_calibrated or self.current_tube is None:
            raise RuntimeError("Primero debes calibrar la maquina.")
