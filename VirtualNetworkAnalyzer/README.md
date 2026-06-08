# 📡 Virtual Network Analyzer (CableMaster Pro v12)

Guía operativa de `VNADefv12.py` para caracterización de cables coaxiales con **NanoVNA V2 Plus4**.

---

## 1) Alcance

El script realiza este flujo completo:

1. Conexión al NanoVNA por puerto serie.
2. Calibración SOLT (OPEN/SHORT/LOAD, con THRU opcional).
3. Medición S11/S21 del cable.
4. Cálculo automático de métricas eléctricas y físicas.
5. Exportación de resultados en CSV, resumen maestro y plot opcional.

---

## 2) Requisitos previos

### Hardware

- NanoVNA V2 Plus4.
- Cable USB de datos (no solo carga).
- Estándares de calibración: **OPEN / SHORT / LOAD (50 Ω)**.
- THRU (si se usa `ENABLE_THRU_RECAL=True`).

### Software

- Python 3.8+.
- Dependencias:

```bash
pip install pyserial numpy scipy matplotlib
```

---

## 3) Configuración obligatoria antes de ejecutar

Editar **solo el bloque `CONFIG`** al inicio de:

`/tmp/workspace/MikeCxC99/Particulas/VirtualNetworkAnalyzer/VNADefv12.py`

Parámetros mínimos a revisar:

- `PORT` y `BAUD` (conexión serial).
- `START_FREQ` y `STOP_FREQ` (rango de trabajo).
- `SWEEP_MODE` (`full`, `segmented`, `interleaved`).
- `VF` (factor de velocidad del cable).
- `SAMPLES_PER_POINT` y `SWEEP_AVG_COUNT` (estabilidad/ruido).
- `SAVE_PLOT` (si se guarda PNG por medición).

> Valor por defecto actual: `PORT='/dev/ttyACM0'`, `BAUD=115200`.

---

## 4) Puerto de conexión (nuevo usuario)

Ejemplos típicos de puerto:

- Linux: `/dev/ttyACM0` o `/dev/ttyUSB0`
- macOS: `/dev/cu.usbmodem*`
- Windows: `COM3`, `COM4`, etc.

Comando útil en Linux/macOS para listar puertos:

```bash
python -m serial.tools.list_ports
```

Si el puerto no coincide, actualizar `PORT` en el bloque `CONFIG`.

---

## 5) Checklist previo a la ejecución (outline)

Antes de correr el script, un usuario nuevo debe validar:

1. **Conexión física**
   - NanoVNA encendido.
   - Cable USB de datos conectado correctamente.
   - El sistema detecta el puerto serie esperado.

2. **Parámetros de configuración**
   - `PORT`/`BAUD` correctos.
   - Rango de frecuencia (`START_FREQ`/`STOP_FREQ`) acorde al cable.
   - `SWEEP_MODE` apropiado para el nivel de detalle deseado.
   - `VF` coherente con la hoja técnica del cable.

3. **Calibración**
   - Estándares OPEN/SHORT/LOAD en buen estado.
   - Perfil de calibración compatible con la configuración actual.
   - Si cambias parámetros marcados para calibración, recalibrar.

4. **Entorno de salida**
   - Permisos de escritura en `~/Desktop/CableMaster_Data/`.
   - Espacio disponible para CSV/PNG.

---

## 6) Ejecución

```bash
python /tmp/workspace/MikeCxC99/Particulas/VirtualNetworkAnalyzer/VNADefv12.py
```

Durante la ejecución, el script:

- gestiona/reutiliza perfil de calibración;
- solicita acciones del operador para el wizard de calibración;
- pide conexión del cable a medir;
- guarda resultados automáticamente.

---

## 7) Cómo funciona el output de datos

### Carpeta base de salida

`~/Desktop/CableMaster_Data/`

### Archivos generados

- `calibration/profiles/*.json`: perfiles de calibración.
- `readings/<HHMMSS>_<ID>.csv`: reporte técnico completo por cable.
- `readings/<HHMMSS>_<ID>_plot.png`: gráfico (solo si `SAVE_PLOT=True`).
- `master_summary.csv`: resumen acumulado de todas las mediciones.

### Estructura del CSV individual (`readings/*.csv`)

El CSV está dividido en secciones legibles por encabezados `##`:

1. `## IDENTIFICACIÓN`
2. `## CARACTERIZACIÓN DEL CABLE`
3. `## PERFIL POR BANDA`
4. `## MÉTRICAS GLOBALES`
5. `## ANOMALÍAS Y OBSERVACIONES`
6. `## DATOS POR FRECUENCIA`
7. `## TDR`
8. `## DATOS CRUDOS VNA`
9. `## FRECUENCIAS CON ANOMALÍA (debug)` (solo si está habilitado)

### Lectura rápida para diagnóstico

- Revisar primero `## ANOMALÍAS Y OBSERVACIONES` (incluye interpretación automática).
- Confirmar desempeño global en `## MÉTRICAS GLOBALES`.
- Si hay alertas, validar detalle en `## DATOS POR FRECUENCIA`.
- Usar `instrument_zone` e `instrument_confidence` para distinguir posibles artefactos instrumentales de fallas reales.

### `master_summary.csv`

Contiene una fila por medición con métricas clave (RL, VSWR, IL, Z0, anomalías, fallas TDR, modo, perfil de calibración y nombre de CSV) para comparación histórica entre cables.

---

## 8) Recomendaciones operativas

- Mantener warmup y calibración consistentes entre mediciones.
- No mezclar dictamen técnico sin revisar `instrument_zone` cuando existan advertencias.
- Para análisis comparativo, usar `master_summary.csv` como índice principal y abrir CSV individual solo para detalle.
