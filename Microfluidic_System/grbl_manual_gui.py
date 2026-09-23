import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

from grbl_controller import GrblController
from microfluidic_machine import MicrofluidicMachine


class GrblManualGui(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Sistema microfluidico")
        self.geometry("360x350")
        self.resizable(False, False)

        self.grbl = None
        self.machine = None

        self.port_var = tk.StringVar(value="COM10")
        self.tube_var = tk.IntVar(value=1)
        self.status_var = tk.StringVar(value="Desconectado")

        self._build_gui()
        self.protocol("WM_DELETE_WINDOW", self.close_app)

    def _build_gui(self):
        main_frame = ttk.Frame(self, padding=12)
        main_frame.pack(fill="both", expand=True)

        connection_frame = ttk.LabelFrame(main_frame, text="Conexion", padding=10)
        connection_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(connection_frame, text="Puerto COM").grid(row=0, column=0, sticky="w")
        ttk.Entry(connection_frame, textvariable=self.port_var, width=12).grid(
            row=0,
            column=1,
            padx=8,
        )
        ttk.Button(connection_frame, text="Conectar", command=self.connect_grbl).grid(
            row=0,
            column=2,
        )

        ttk.Button(connection_frame, text="Desconectar", command=self.disconnect_grbl).grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(8, 0),
        )

        system_frame = ttk.LabelFrame(main_frame, text="Sistema", padding=10)
        system_frame.pack(fill="x", pady=(0, 10))

        self.calibrate_button = ttk.Button(
            system_frame,
            text="Calibrar sistema",
            command=self.calibrate_system,
            state="disabled",
        )
        self.calibrate_button.pack(fill="x")

        carousel_frame = ttk.LabelFrame(main_frame, text="Carrusel", padding=10)
        carousel_frame.pack(fill="x")

        ttk.Label(carousel_frame, text="Tubo Eppendorf").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Spinbox(
            carousel_frame,
            from_=1,
            to=12,
            increment=1,
            textvariable=self.tube_var,
            width=6,
            state="readonly",
        ).grid(row=0, column=1, padx=8)

        self.run_button = ttk.Button(
            carousel_frame,
            text="Run",
            command=self.run_selected_tube,
            state="disabled",
        )
        self.run_button.grid(row=0, column=2, sticky="ew")
        carousel_frame.columnconfigure(2, weight=1)

        ttk.Label(
            main_frame,
            textvariable=self.status_var,
            relief="sunken",
            anchor="w",
            padding=6,
        ).pack(fill="x", pady=(10, 0))

    def connect_grbl(self):
        try:
            self.grbl = GrblController(port=self.port_var.get())
            self.grbl.connect()
            self.machine = MicrofluidicMachine(self.grbl)
            self.calibrate_button.config(state="normal")
            self.run_button.config(state="disabled")
            self.status_var.set(f"Conectado a {self.port_var.get()}")
        except Exception as error:
            self.grbl = None
            self.machine = None
            self.calibrate_button.config(state="disabled")
            self.run_button.config(state="disabled")
            self.show_error(error)

    def disconnect_grbl(self):
        if self.grbl is not None:
            self.grbl.close()

        self.grbl = None
        self.machine = None
        self.calibrate_button.config(state="disabled")
        self.run_button.config(state="disabled")
        self.status_var.set("Desconectado")

    def calibrate_system(self):
        if self.machine is None:
            self.show_error(RuntimeError("Primero conecta GRBL."))
            return

        self.status_var.set("Calibrando sistema...")
        self.update_idletasks()

        if self.run_command(self.machine.calibrate, "Sistema calibrado: tubo 1"):
            self.tube_var.set(1)
            self.run_button.config(state="normal")

    def run_selected_tube(self):
        if self.machine is None:
            self.show_error(RuntimeError("Primero conecta GRBL."))
            return

        tube_number = self.tube_var.get()
        self.status_var.set(f"Ejecutando posicion del tubo {tube_number}...")
        self.update_idletasks()

        self.run_command(
            lambda: self.machine.run_tube(tube_number),
            f"Tubo {tube_number}: aguja abajo",
        )

    def run_command(self, command_function, success_message):
        try:
            command_function()
            self.status_var.set(success_message)
            return True
        except Exception as error:
            self.show_error(error)
            return False

    def show_error(self, error):
        self.status_var.set(str(error))
        messagebox.showerror("Error", str(error))

    def close_app(self):
        self.disconnect_grbl()
        self.destroy()


if __name__ == "__main__":
    app = GrblManualGui()
    app.mainloop()
