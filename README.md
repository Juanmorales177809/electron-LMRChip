# LMRChip Desktop

Aplicación de escritorio para integrar y automatizar el control del
dispositivo experimental **LMRChip**, orientada a investigadores que
trabajan con sensores *Lossy Mode Resonance (LMR)*.

## Objetivo

Desarrollar la aplicación unificada, reemplazando el uso separado de las
herramientas de control por una única interfaz de usuario basada en
**Electron**.

## Funcionalidades

-   Control de los movimientos mecatrónicos y posicionamiento mediante
    GRBL.
-   Control y monitoreo de temperatura de la celda microfluídica.
-   Gestión del autosampler y circulación de muestras.
-   Adquisición de espectros del sensor LMR.
-   Ejecución y seguimiento de secuencias experimentales desde una única
    interfaz.

## Arquitectura inicial

La aplicación será local y estará basada en **Electron**, comunicándose
con los distintos controladores e instrumentos conectados al computador
mediante el hub USB del dispositivo.

> El alcance inicial es integrar el hardware y las funcionalidades
> existentes; los protocolos, drivers y APIs específicos de cada
> instrumento se documentarán durante el desarrollo.

## Backend Python

La lógica de control y procesamiento está organizada en el paquete
`lmrchip`, ubicado en `python/lmrchip`:

- `lmrchip.microfluidics`: comunicación GRBL y movimientos de la máquina.
- `lmrchip.spectroscopy`: adquisición de espectros y seguimiento LMR.
- `lmrchip.temperature`: control del equipo PR-59.

El proyecto utiliza Python 3.13.16. Para instalar el backend en un entorno
virtual de Python 3.13:

```powershell
python -m pip install -e .
```

Las interfaces Tkinter anteriores se conservan temporalmente como herramientas
de diagnóstico. Sus dependencias gráficas opcionales se instalan con:

```powershell
python -m pip install -e ".[legacy-gui]"
```

Las pruebas no requieren hardware conectado:

```powershell
python -m unittest discover -s tests -v
```

## Electron

La aplicación de escritorio requiere Node.js 24 LTS. Para ejecutar el modo de
desarrollo con el controlador de temperatura simulado:

```powershell
$env:LMRCHIP_SIMULATE_TEMPERATURE = "1"
npm.cmd run dev
```

El simulador nunca se activa como reemplazo automático de un dispositivo real.
Sin esa variable, la aplicación enumera únicamente los puertos seriales reales.

El espectrómetro también dispone de un simulador explícito e independiente:

```powershell
$env:LMRCHIP_SIMULATE_SPECTROMETER = "1"
npm.cmd run dev
```

El sistema microfluídico se simula explícitamente con:

```powershell
$env:LMRCHIP_SIMULATE_MICROFLUIDICS = "1"
npm.cmd run dev
```

## Experimentos automatizados

Para probar un experimento completo sin hardware, deben activarse los tres
simuladores antes de iniciar Electron. La pantalla **Experimento** exige que el
control de temperatura este activo, que el espectrometro tenga fondo y
referencia, y que el sistema microfluidico este calibrado con la aguja arriba.

Cada ejecucion crea una carpeta `experimento_YYYYMMDD_HHMMSS` con:

- `metadata.json`: estado y configuracion, actualizado de forma atomica.
- `temperature.csv`: historial termico durante el experimento.
- `resonance.csv`: resultados del seguimiento LMR.
- `events.jsonl`: estados y errores de la secuencia.
- `spectra/*.npz`: espectros completos de cada adquisicion.

Durante una secuencia activa, las ordenes manuales que alteran los tres modulos
se bloquean. Al pausar o cancelar se detiene el seguimiento, se intenta subir la
aguja y se mantiene activo el control de temperatura.

## Empaquetado para Windows

El instalador incorpora Python 3.13.16 y las dependencias del backend. El equipo
destino no necesita una instalacion separada de Python. Para construir ambos
artefactos en Windows x64:

```powershell
npm.cmd run package:win
```

La primera construccion descarga el paquete integrable oficial de Python y
verifica su suma SHA-256 antes de instalar las dependencias. Los resultados se
guardan en `release/`:

- `LMRChip-Desktop-Setup-0.1.0-x64.exe`: instalador NSIS.
- `LMRChip-Desktop-Portable-0.1.0-x64.exe`: version portable.

Los drivers de los instrumentos no se instalan automaticamente. Los registros
rotativos `electron.log` y `python.log` se guardan en la carpeta de datos de la
aplicacion. La validacion fisica pendiente esta documentada en
`docs/VALIDACION_HARDWARE.md`.
