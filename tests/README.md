# Pruebas

Pruebas automáticas del monitor y del fichaje: no usan la red ni datos reales (`fixture.py` genera fichas inventadas).
Ejecútalas con `tests/run.sh` desde la carpeta del proyecto: construye la imagen y lanza cada fichero en un contenedor desechable sin red.
Las pruebas antiguas corren con `FICHAJE_HILO=0` (botones leídos desde el bucle); `test_hilo.py` prueba el hilo de escucha real.
Cada línea sale como `PASS …` o `FAIL …`; el script termina con error si algo falla.
