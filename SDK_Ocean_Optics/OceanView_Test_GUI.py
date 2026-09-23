import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import time
from concurrent.futures import ThreadPoolExecutor

import matplotlib
matplotlib.use("TkAgg")

# 2. Ahora sí, tus importaciones originales
import tkinter as tk
from tkinter import messagebox, ttk
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from Espectrometro import Spectrometer
from ResonanceTracker import ResonanceTracker


class OceanViewTestGUI(tk.Tk):
    def __init__(self):
        print("  [DEBUG] Iniciando ventana principal (Tk)...")
        super().__init__()

        self.title("USB4000 Transmission Test")
        self.geometry("1280x820")
        self.minsize(980, 620)

        self.optical = None
        self.current_spectrum = None
        self.transmission = None
        self.tracker = None
        self.tracking_active = False
        self.tracking_future = None
        self.tracking_after_id = None
        self.tracking_started_at = None
        self.tracking_times = []
        self.tracking_wavelengths = []
        self.executor = ThreadPoolExecutor(max_workers=1)

        self.integration_time_var = tk.IntVar(value=100)
        self.scans_to_average_var = tk.IntVar(value=10)
        self.delay_var = tk.DoubleVar(value=0.05)
        self.boxcar_width_var = tk.IntVar(value=2)
        self.x_min_var = tk.DoubleVar(value=400)
        self.x_max_var = tk.DoubleVar(value=800)

        self.search_min_var = tk.DoubleVar(value=650)
        self.search_max_var = tk.DoubleVar(value=750)
        self.fit_radius_nm_var = tk.DoubleVar(value=1.5)
        self.smoothing_window_var = tk.IntVar(value=9)
        self.tracking_window_var = tk.DoubleVar(value=15.0)
        self.tracking_interval_var = tk.IntVar(value=250)

        self.status_var = tk.StringVar(value="Ready.")

        print("  [DEBUG] Construyendo Layout de la interfaz...")
        self._build_layout()
        
        self._set_measurement_buttons_state(tk.DISABLED)
        print("  [DEBUG] Inicialización de ventana terminada con éxito.")

    def _build_layout(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self, padding=12)
        sidebar.grid(row=0, column=0, sticky="ns")

        plot_area = ttk.Frame(self, padding=(0, 12, 12, 12))
        plot_area.grid(row=0, column=1, sticky="nsew")
        plot_area.columnconfigure(0, weight=1)
        plot_area.rowconfigure(0, weight=1)

        print("    -> Creando barra lateral y botones...")
        self._build_controls(sidebar)
        
        print("    -> Creando gráficos de Matplotlib...")
        self._build_plot(plot_area)
        
        print("    -> Creando barra de estado...")
        self._build_status_bar()

    def _build_controls(self, parent):
        connection_frame = ttk.LabelFrame(parent, text="Device", padding=10)
        connection_frame.pack(fill="x", pady=(0, 10))

        self.connect_button = ttk.Button(
            connection_frame, text="Connect", command=self.connect_device
        )
        self.connect_button.pack(fill="x")
        self.close_button = ttk.Button(
            connection_frame, text="Close", command=self.close_device
        )
        self.close_button.pack(fill="x", pady=(6, 0))

        acquisition_frame = ttk.LabelFrame(parent, text="Acquisition", padding=10)
        acquisition_frame.pack(fill="x", pady=(0, 10))

        self._add_spinbox(acquisition_frame, "Integration (ms)", self.integration_time_var, 1, 10000)
        self._add_spinbox(acquisition_frame, "Scans average", self.scans_to_average_var, 1, 100)
        self._add_spinbox(acquisition_frame, "Delay (s)", self.delay_var, 0.0, 2.0, increment=0.01)
        self._add_spinbox(acquisition_frame, "Boxcar width", self.boxcar_width_var, 0, 20)

        calibration_frame = ttk.LabelFrame(parent, text="Transmission Calibration", padding=10)
        calibration_frame.pack(fill="x", pady=(0, 10))

        self.background_button = ttk.Button(
            calibration_frame,
            text="Measure Background",
            command=lambda: self.measure("background"),
        )
        self.background_button.pack(fill="x")

        self.reference_button = ttk.Button(
            calibration_frame,
            text="Measure Reference",
            command=lambda: self.measure("reference"),
        )
        self.reference_button.pack(fill="x", pady=(6, 0))

        self.sample_button = ttk.Button(
            calibration_frame,
            text="Measure Sample",
            command=lambda: self.measure("sample"),
        )
        self.sample_button.pack(fill="x", pady=(6, 0))

        self.transmission_button = ttk.Button(
            calibration_frame,
            text="Calculate Transmission",
            command=self.calculate_transmission,
        )
        self.transmission_button.pack(fill="x", pady=(6, 0))

        view_frame = ttk.LabelFrame(parent, text="View", padding=10)
        view_frame.pack(fill="x")

        self._add_spinbox(view_frame, "X min (nm)", self.x_min_var, 0, 1200)
        self._add_spinbox(view_frame, "X max (nm)", self.x_max_var, 0, 1200)
        ttk.Button(view_frame, text="Apply Range", command=self.apply_axis_range).pack(fill="x", pady=(8, 0))
        ttk.Button(view_frame, text="Clear Plot", command=self.clear_plot).pack(fill="x", pady=(6, 0))

        tracking_frame = ttk.LabelFrame(parent, text="LMR Tracking", padding=10)
        tracking_frame.pack(fill="x", pady=(10, 0))

        self._add_compact_spinbox(tracking_frame, "Initial LMR min (nm)", self.search_min_var, 0, 1200)
        self._add_compact_spinbox(tracking_frame, "Initial LMR max (nm)", self.search_max_var, 0, 1200)
        self._add_compact_spinbox(tracking_frame, "Fit radius (nm)", self.fit_radius_nm_var, 0.1, 50, 0.1)
        self._add_compact_spinbox(tracking_frame, "Smoothing points", self.smoothing_window_var, 0, 101, 2)
        self._add_compact_spinbox(tracking_frame, "Local search +/- (nm)", self.tracking_window_var, 0, 200, 0.5)
        self._add_compact_spinbox(tracking_frame, "Interval (ms)", self.tracking_interval_var, 0, 10000, 50)

        ttk.Button(
            tracking_frame,
            text="Parameter help",
            command=self.show_tracking_help,
        ).pack(fill="x", pady=(8, 0))

        self.tracking_start_button = ttk.Button(
            tracking_frame, text="Start Tracking", command=self.start_tracking
        )
        self.tracking_start_button.pack(fill="x", pady=(6, 0))
        self.tracking_stop_button = ttk.Button(
            tracking_frame, text="Stop Tracking", command=self.stop_tracking, state=tk.DISABLED
        )
        self.tracking_stop_button.pack(fill="x", pady=(6, 0))

    def _add_spinbox(self, parent, label, variable, from_, to, increment=1):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)

        ttk.Label(row, text=label).pack(anchor="w")
        spinbox = ttk.Spinbox(
            row,
            from_=from_,
            to=to,
            increment=increment,
            textvariable=variable,
            width=14,
        )
        spinbox.pack(fill="x")

    def _add_compact_spinbox(self, parent, label, variable, from_, to, increment=1):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label).pack(side="left")
        ttk.Spinbox(
            row,
            from_=from_,
            to=to,
            increment=increment,
            textvariable=variable,
            width=9,
        ).pack(side="right")

    def show_tracking_help(self):
        messagebox.showinfo(
            "LMR tracking parameters",
            "VIEW X MIN / X MAX\n"
            "Only controls the wavelength range shown on the graph.\n\n"
            "INITIAL LMR MIN / MAX\n"
            "Selects which resonance is acquired in the first spectrum. Once "
            "locked, the resonance can move beyond this initial interval.\n\n"
            "FIT RADIUS (NM)\n"
            "Spectral distance on each side of the minimum used for the "
            "quadratic fit. The number of detector points is calculated automatically.\n\n"
            "LOCAL SEARCH +/- (NM)\n"
            "After the first detection, the next LMR is searched around the "
            "last valid position. For example, 15 means last position +/-15 nm."
        )

    def _build_plot(self, parent):
        self.figure = Figure(figsize=(8, 7), dpi=100)
        self.axis = self.figure.add_subplot(211)
        self.resonance_axis = self.figure.add_subplot(212)
        self.figure.subplots_adjust(hspace=0.42)

        self.axis.set_title("Real-time spectrum")
        self.axis.set_xlabel("Wavelength (nm)")
        self.axis.set_ylabel("Intensity / Transmission")
        self.axis.grid(True, alpha=0.3)

        self.resonance_axis.set_title("Resonance wavelength over time")
        self.resonance_axis.set_xlabel("Time (s)")
        self.resonance_axis.set_ylabel("Resonance wavelength (nm)")
        self.resonance_axis.grid(True, alpha=0.3)

        self.canvas = FigureCanvasTkAgg(self.figure, master=parent)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        toolbar_frame = ttk.Frame(parent)
        toolbar_frame.grid(row=1, column=0, sticky="ew")
        NavigationToolbar2Tk(self.canvas, toolbar_frame)

    def _build_status_bar(self):
        status_bar = ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w", padding=6)
        status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")

    def connect_device(self):
        try:
            self.optical = Spectrometer(
                integration_time=self.integration_time_var.get(),
                scans_to_average=self.scans_to_average_var.get(),
                delay=self.delay_var.get(),
                boxcar_width=self.boxcar_width_var.get(),
            )
            self.optical.connect()
            self._set_measurement_buttons_state(tk.NORMAL)
            wavelength_steps = np.diff(self.optical.wavelengths)
            valid_steps = wavelength_steps[np.isfinite(wavelength_steps) & (wavelength_steps > 0)]
            median_step = float(np.median(valid_steps)) if valid_steps.size else np.nan
            self.status_var.set(
                f"Spectrometer connected: {self.optical.wavelengths.size} wavelength points | "
                f"median sampling {median_step:.4f} nm/point."
            )
        except Exception as error:
            self.optical = None
            self.status_var.set(f"Connection error: {error}")

    def close_device(self):
        if self.optical is not None:
            self.optical.close()
            self.optical = None

        self._set_measurement_buttons_state(tk.DISABLED)
        self.status_var.set("Spectrometer closed.")

    def measure(self, measurement_type):
        if self.optical is None:
            self.status_var.set("Connect the spectrometer first.")
            return

        try:
            self._update_acquisition_settings()
            spectrum = self.optical.measure(measurement_type)
            self.current_spectrum = spectrum
            saturation = self.optical.check_saturation(spectrum)

            self.plot_spectrum(
                self.optical.wavelengths,
                spectrum,
                title=f"{measurement_type.capitalize()} Spectrum",
                ylabel="Intensity (counts)",
            )

            self.status_var.set(
                f"{measurement_type.capitalize()} measured. "
                f"Max: {saturation['max_counts']:.0f} counts."
            )
        except Exception as error:
            self.status_var.set(f"Measurement error: {error}")

    def calculate_transmission(self):
        if self.optical is None:
            self.status_var.set("Connect the spectrometer first.")
            return

        try:
            self.transmission = self.optical.calculate_transmission()
            self.plot_spectrum(
                self.optical.wavelengths,
                self.transmission,
                title="Transmission",
                ylabel="Transmission (%)",
                color="tab:green",
            )
            diagnostics = self.optical.transmission_diagnostics
            valid_percent = 100 * diagnostics["valid_points"] / diagnostics["total_points"]
            self.status_var.set(
                f"Transmission calculated. Valid pixels: {valid_percent:.1f}% | "
                f"Values limited to 0-100%: {diagnostics['clipped_points']}"
            )
        except Exception as error:
            self.status_var.set(f"Transmission error: {error}")

    def start_tracking(self):
        if self.optical is None:
            self.status_var.set("Connect the spectrometer first.")
            return
        if self.optical.background is None or self.optical.reference is None:
            self.status_var.set("Measure background and reference before tracking.")
            return

        try:
            self._update_acquisition_settings()
            self.tracker = ResonanceTracker(
                search_min_nm=self.search_min_var.get(),
                search_max_nm=self.search_max_var.get(),
                fit_half_window_nm=self.fit_radius_nm_var.get(),
                smoothing_window=self.smoothing_window_var.get(),
                tracking_half_window_nm=self.tracking_window_var.get(),
            )
        except Exception as error:
            self.status_var.set(f"Tracking configuration error: {error}")
            return

        self.tracking_active = True
        self.tracking_started_at = time.perf_counter()
        self.tracking_times = []
        self.tracking_wavelengths = []
        self._reset_resonance_plot()
        self._set_tracking_state(True)
        self.status_var.set("LMR tracking started.")
        self._schedule_tracking()

    def stop_tracking(self):
        self.tracking_active = False
        if self.tracking_future is None:
            self._set_tracking_state(False)
            self.status_var.set(self._tracking_stopped_message())
        else:
            self.status_var.set("Stopping after the current acquisition...")

    def _schedule_tracking(self):
        self.tracking_after_id = None
        if not self.tracking_active or self.tracking_future is not None:
            return
        self.tracking_future = self.executor.submit(self._tracking_worker)
        self.tracking_after_id = self.after(30, self._poll_tracking)

    def _poll_tracking(self):
        self.tracking_after_id = None
        if self.tracking_future is None:
            return
        if not self.tracking_future.done():
            self.tracking_after_id = self.after(30, self._poll_tracking)
            return

        future = self.tracking_future
        self.tracking_future = None
        try:
            transmission, result = future.result()
        except Exception as error:
            self.tracking_active = False
            self._set_tracking_state(False)
            self.status_var.set(f"Tracking error: {error}")
            return

        if not self.tracking_active:
            self._set_tracking_state(False)
            self.status_var.set(self._tracking_stopped_message())
            return

        self.transmission = transmission
        elapsed = time.perf_counter() - self.tracking_started_at
        self._plot_tracking_result(transmission, result, elapsed)

        if result.valid:
            self.status_var.set(
                f"LMR: {result.wavelength:.3f} nm | "
                f"T: {result.transmission:.2f}% | R2: {result.r_squared:.4f}"
            )
        else:
            self.status_var.set(f"LMR not detected: {result.reason}")

        interval = max(0, self.tracking_interval_var.get())
        self.tracking_after_id = self.after(interval, self._schedule_tracking)

    def _tracking_worker(self):
        transmission = self.optical.acquire_transmission()
        result = self.tracker.update(self.optical.wavelengths, transmission)
        return transmission, result

    def _plot_tracking_result(self, transmission, result, elapsed):
        self.tracking_times.append(elapsed)
        self.tracking_wavelengths.append(
            result.wavelength if result.valid else np.nan
        )

        self.axis.clear()
        self.axis.plot(
            self.optical.wavelengths,
            transmission,
            color="tab:green",
            linewidth=1.0,
            label="Transmission",
        )
        if result.valid:
            self.axis.plot(
                result.fit_wavelengths,
                result.fit_transmission,
                color="tab:orange",
                linewidth=2.0,
                label="Quadratic fit",
            )
            self.axis.scatter(
                [result.wavelength],
                [result.transmission],
                color="tab:red",
                s=45,
                zorder=5,
                label=f"LMR {result.wavelength:.3f} nm",
            )
            self.axis.axvline(result.wavelength, color="tab:red", alpha=0.35, linestyle="--")

        self.axis.set_title("LMR Resonance Tracking")
        self.axis.set_xlabel("Wavelength (nm)")
        self.axis.set_ylabel("Transmission (%)")
        self.axis.set_ylim(0, 100)
        self.axis.grid(True, alpha=0.3)
        # The visible graph range is independent from the internal LMR search
        # interval.  Only the controls in the View section set the x axis.
        self.apply_axis_range(redraw=False)
        if result.valid:
            self.axis.legend(loc="best")

        self.resonance_axis.clear()
        self.resonance_axis.plot(
            self.tracking_times,
            self.tracking_wavelengths,
            color="tab:blue",
            linewidth=1.4,
            marker="o",
            markersize=3,
        )
        self.resonance_axis.set_title("Resonance wavelength over time")
        self.resonance_axis.set_xlabel("Time (s)")
        self.resonance_axis.set_ylabel("Resonance wavelength (nm)")
        self.resonance_axis.grid(True, alpha=0.3)
        self.resonance_axis.set_xlim(left=0)
        self.canvas.draw_idle()

    def _reset_resonance_plot(self):
        self.resonance_axis.clear()
        self.resonance_axis.set_title("Resonance wavelength over time")
        self.resonance_axis.set_xlabel("Time (s)")
        self.resonance_axis.set_ylabel("Resonance wavelength (nm)")
        self.resonance_axis.grid(True, alpha=0.3)
        self.resonance_axis.set_xlim(left=0)
        self.canvas.draw_idle()

    def _set_tracking_state(self, active):
        normal_or_disabled = tk.DISABLED if active else tk.NORMAL
        self.connect_button.configure(state=normal_or_disabled)
        self.close_button.configure(state=normal_or_disabled)
        self.background_button.configure(state=normal_or_disabled)
        self.reference_button.configure(state=normal_or_disabled)
        self.sample_button.configure(state=normal_or_disabled)
        self.transmission_button.configure(state=normal_or_disabled)
        self.tracking_start_button.configure(state=normal_or_disabled)
        self.tracking_stop_button.configure(state=tk.NORMAL if active else tk.DISABLED)

    def _tracking_stopped_message(self):
        return "LMR tracking stopped."

    def plot_spectrum(self, wavelengths, values, title, ylabel, color="tab:blue"):
        self.axis.clear()
        self.axis.plot(wavelengths, values, color=color, linewidth=1.2)
        self.axis.set_title(title)
        self.axis.set_xlabel("Wavelength (nm)")
        self.axis.set_ylabel(ylabel)
        if ylabel == "Transmission (%)":
            self.axis.set_ylim(0, 100)
        self.axis.grid(True, alpha=0.3)
        self.apply_axis_range(redraw=False)
        self.canvas.draw_idle()

    def apply_axis_range(self, redraw=True):
        x_min = self.x_min_var.get()
        x_max = self.x_max_var.get()

        if x_min < x_max:
            self.axis.set_xlim(x_min, x_max)

        if redraw:
            self.canvas.draw_idle()

    def clear_plot(self):
        self.tracking_times = []
        self.tracking_wavelengths = []
        self.axis.clear()
        self.axis.set_title("Real-time spectrum")
        self.axis.set_xlabel("Wavelength (nm)")
        self.axis.set_ylabel("Intensity / Transmission")
        self.axis.grid(True, alpha=0.3)
        self._reset_resonance_plot()
        self.canvas.draw_idle()
        self.status_var.set("Plot cleared.")

    def _update_acquisition_settings(self):
        self.optical.integration_time = self.integration_time_var.get()
        self.optical.scans_to_average = self.scans_to_average_var.get()
        self.optical.delay = self.delay_var.get()
        self.optical.boxcar_width = self.boxcar_width_var.get()

        if self.optical.spec is not None:
            self.optical.spec.integration_time_micros(
                int(self.optical.integration_time * 1000)
            )

    def _set_measurement_buttons_state(self, state):
        self.background_button.configure(state=state)
        self.reference_button.configure(state=state)
        self.sample_button.configure(state=state)
        self.transmission_button.configure(state=state)
        self.tracking_start_button.configure(state=state)

    def destroy(self):
        self.tracking_active = False
        if self.tracking_after_id is not None:
            try:
                self.after_cancel(self.tracking_after_id)
            except tk.TclError:
                pass
            self.tracking_after_id = None
        self.executor.shutdown(wait=True, cancel_futures=True)
        if self.optical is not None:
            self.optical.close()
            self.optical = None
        super().destroy()


if __name__ == "__main__":
    print("1. El programa empezó a ejecutarse...")
    
    try:
        app = OceanViewTestGUI()
        print("2. La interfaz gráfica se cargó en memoria...")
        
        app.mainloop()
        print("3. La ventana se cerró.")
        
    except Exception as e:
        print(f"Ocurrió un error oculto: {e}")
