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
