# Validacion fisica pendiente

Esta lista no ha sido ejecutada porque la maquina no esta conectada. Debe
completarse con personal autorizado antes de usar el sistema en produccion.

## Preparacion

- Verificar drivers del PR-59, controlador GRBL y Ocean Optics.
- Confirmar que el paro fisico funciona y permanece accesible.
- Retirar obstaculos del carrusel y comprobar manualmente que la aguja esta arriba.
- Usar tubos de prueba sin muestras valiosas durante la primera validacion.

## Modulos individuales

- Conectar PR-59, iniciar 37 grados C y comparar con un instrumento de referencia.
- Detener temperatura y confirmar el estado real del controlador.
- Conectar el espectrometro, capturar fondo y referencia y revisar saturacion.
- Confirmar que el seguimiento LMR entrega una resonancia conocida.
- Conectar GRBL y ejecutar calibracion observando todo el recorrido.
- Seleccionar un tubo conocido y confirmar posicion, bajada y subida de aguja.

## Experimento integrado

- Ejecutar primero un solo tubo con tiempos cortos.
- Comprobar pausa: debe detener seguimiento, subir aguja y mantener temperatura.
- Comprobar reanudacion: debe repetir desde el inicio el tubo interrumpido.
- Comprobar cancelacion y un fallo controlado de comunicacion.
- Revisar `metadata.json`, CSV, eventos y espectros NPZ.
- Ejecutar despues dos tubos consecutivos y finalmente la secuencia completa.

Registrar fecha, operador, equipos, versiones, resultados y cualquier desviacion.
No marcar esta validacion como aprobada hasta completar todos los puntos.
