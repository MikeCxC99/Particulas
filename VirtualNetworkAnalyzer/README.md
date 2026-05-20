# 📡 CableMaster Pro — Virtual Network Analyzer (VNADefv12)

Documentación técnica para operación y uso de `VNADefv12.py` con **NanoVNA V2 Plus4**.

---

## 1) Objetivo

`VNADefv12.py` permite medir y diagnosticar cables coaxiales en laboratorio con un flujo guiado:

1. Conexión al VNA por puerto serie.
2. Calibración SOLT interactiva (OPEN/SHORT/LOAD y THRU opcional).
3. Medición S11/S21 del cable.
4. Cálculo automático de métricas eléctricas y físicas.
5. Exportación de resultados para trazabilidad técnica.

---

## 2) Contexto de versión (v5 eliminada)

La documentación previa de **v5** estaba en `Virtual Network Analyzer/README.md` (ruta antigua) y fue eliminada.

### Cambios relevantes al pasar de v5 a v12

- El código operativo actual es `VirtualNetworkAnalyzer/VNADefv12.py`.
- Se mantiene el enfoque de calibración y medición de v5, pero v12 añade mejoras de robustez:
  - **Perfiles de calibración** más estrictos por configuración activa.
  - **Máscara/anotación de zonas instrumentales** (las muestras no se borran; solo se etiquetan y excluyen de ciertos promedios).
  - **Cosido de fase** para group delay en mediciones segmentadas/interleaved.
  - **Detección y resumen técnico de anomalías** por frecuencia y por TDR.
  - **Ficha CSV más completa** para análisis por técnico.

Si tenías procedimientos basados en v5, puedes reutilizarlos con v12 ajustando rutas, parámetros del bloque CONFIG y revisando la sección de salida CSV.

---

## 3) Requisitos

### Hardware

- NanoVNA V2 Plus4
- Cable USB
- Estándares de calibración: OPEN / SHORT / LOAD (50 Ω)
- THRU (opcional, si `ENABLE_THRU_RECAL=True`)

### Software

- Python 3.8+
- Dependencias:

```bash
pip install pyserial numpy scipy matplotlib
```

---

## 4) Configuración previa (obligatoria)

Editar solo el bloque de configuración al inicio de:

`/home/runner/work/Particulas/Particulas/VirtualNetworkAnalyzer/VNADefv12.py`

Parámetros clave para operación técnica:

- `PORT`, `BAUD`: conexión serial.
- `START_FREQ`, `STOP_FREQ`: rango de barrido.
- `SWEEP_MODE`: `full`, `segmented` o `interleaved`.
- `VF`: factor de velocidad del cable.
- `SAMPLES_PER_POINT`, `SWEEP_AVG_COUNT`: estabilidad/ruido.
- `TDR_WINDOW`, `TDR_ZERO_PAD_FACTOR`: calidad de estimación de longitud/fallas.
- `SAVE_PLOT`: habilitar o no PNG.

---

## 5) Modos de medición

- **full**: rápido, menor resolución.
- **segmented**: mayor resolución, más tiempo.
- **interleaved**: mejor resolución efectiva (más tiempo de adquisición).

Regla práctica: para diagnóstico detallado, usar `segmented` o `interleaved`.

---

## 6) Calibración

En cada arranque, el script evalúa si existe un perfil de calibración compatible.

- Si existe: permite reutilizarlo o recalibrar.
- Si no existe o es incompatible: lanza wizard SOLT automáticamente.

Flujo típico del wizard:

1. Conectar OPEN y confirmar.
2. Conectar SHORT y confirmar.
3. Conectar LOAD y confirmar.
4. (Opcional) Conectar THRU y confirmar.
5. Guardado de perfil JSON en carpeta de calibración.

---

## 7) Ejecución

```bash
python /home/runner/work/Particulas/Particulas/VirtualNetworkAnalyzer/VNADefv12.py
```

En cada medición, el sistema solicita conectar el cable en P1/CH0 y genera automáticamente un ID de cable.

---

## 8) Qué calcula el sistema

Por cada cable se calculan, entre otros:

- Return Loss (RL)
- VSWR
- Impedancia compleja (Re/Im/|Z|)
- Insertion Loss (IL)
- Reflexión de potencia
- Longitud por TDR
- Retardo de grupo y longitud eléctrica
- Frecuencias anómalas y motivos (RL/VSWR/IL/Z)

Además, genera una interpretación textual para apoyo al técnico.

---

## 9) Salidas y trazabilidad

Directorio de trabajo por defecto:

`~/Desktop/CableMaster_Data/`

Archivos principales:

- `calibration/profiles/*.json`: perfiles de calibración.
- `readings/<HHMMSS>_<ID>.csv`: ficha técnica completa de la medición.
- `readings/<HHMMSS>_<ID>_plot.png`: gráfico (si `SAVE_PLOT=True`).
- `master_summary.csv`: registro acumulado de todas las mediciones.

---

## 10) Uso recomendado para técnico

1. Verificar puerto correcto y conectores firmes.
2. Hacer warmup y calibración con estándares en buen estado.
3. Medir cable y revisar en CSV:
   - `## CARACTERIZACIÓN DEL CABLE`
   - `## MÉTRICAS GLOBALES`
   - `## ANOMALÍAS Y OBSERVACIONES`
   - `## DATOS POR FRECUENCIA`
4. Si aparecen advertencias repetitivas en zonas instrumentales, contrastar con la columna `instrument_zone` antes de dictaminar falla real.

---

## 11) Notas operativas

- El sistema prioriza trazabilidad: conserva datos medidos y marca contexto instrumental.
- Cambios en parámetros de calibración generan perfil nuevo.
- Para campañas largas, usar `master_summary.csv` como índice general de calidad y comparar cables entre sí.
