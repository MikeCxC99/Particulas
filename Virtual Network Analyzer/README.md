# 📡 CableMaster Pro — Virtual Network Analyzer (VNADefv5)

[![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=flat&logo=python)](https://www.python.org/)
[![Hardware](https://img.shields.io/badge/Hardware-NanoVNA%20V2%20Plus4-orange?style=flat)]()
[![Estado](https://img.shields.io/badge/Estado-WIP-red?style=flat)]()

> ⚠️ **Trabajo en Progreso (WIP)**  
> El script funciona correctamente en la mayoría de las frecuencias, pero se han detectado lecturas anómalas en ciertas frecuencias que aún están bajo investigación. Los datos en dichas frecuencias deben interpretarse con precaución hasta resolverlo.

Herramienta de línea de comandos para **caracterizar cables coaxiales** usando un NanoVNA V2 Plus4 conectado por USB. Automatiza la calibración SOLT, la adquisición de parámetros S y el cálculo de todas las métricas RF relevantes, guardando resultados en CSV estructurado y gráfica PNG.

---

## 📋 Tabla de Contenidos

1. [Hardware Requerido](#-hardware-requerido)
2. [Software y Dependencias](#-software-y-dependencias)
3. [Instalación](#-instalación)
4. [Configuración](#️-configuración)
5. [Modos de Sweep](#-modos-de-sweep)
6. [Calibración SOLT](#-calibración-solt)
7. [Uso](#-uso)
8. [Salidas Generadas](#-salidas-generadas)
9. [Métricas Calculadas](#-métricas-calculadas)
10. [Arquitectura del Código](#-arquitectura-del-código)
11. [Problemas Conocidos (WIP)](#-problemas-conocidos-wip)

---

## 🔧 Hardware Requerido

| Componente | Descripción |
|---|---|
| **VNA** | NanoVNA V2 Plus4 |
| **Cable USB** | Para conexión al PC (el NanoVNA expone un puerto serial CDC) |
| **Estándares de calibración** | OPEN, SHORT, LOAD (50 Ω) — kit SMA o tipo N según conectores del cable a medir |
| **Adaptador THRU** *(opcional)* | Cable de referencia para calibración S21 (solo si `ENABLE_THRU_RECAL = True`) |
| **Cables a medir** | Cables coaxiales con conector en el Puerto 1 (CH0) del NanoVNA |

---

## 💻 Software y Dependencias

- **Python 3.8+**
- Librerías:

| Librería | Propósito |
|---|---|
| `pyserial` | Comunicación serial con el NanoVNA |
| `numpy` | Álgebra vectorial y procesamiento de señales |
| `scipy` | Detección de picos en el TDR (`find_peaks`) |
| `matplotlib` | Generación de gráficas PNG |

---

## 📦 Instalación

```bash
pip install pyserial numpy scipy matplotlib
```

---

## ⚙️ Configuración

Todo el bloque de configuración está al **inicio del archivo** (`VNADefv5.py`, líneas 47–216), claramente delimitado entre dos líneas de ═══. Solo es necesario editar este bloque antes de ejecutar.

### Hardware

```python
PORT = '/dev/ttyACM0'   # Linux/Mac. En Windows: 'COM3', 'COM4', etc.
BAUD = 115200
```

### Rango de Frecuencia

```python
START_FREQ = 100_000_000      # 100 MHz
STOP_FREQ  = 4_400_000_000    # 4.4 GHz
```

### Modo de Sweep

```python
SWEEP_MODE = "interleaved"    # "full" | "segmented" | "interleaved"
```

Ver la sección [Modos de Sweep](#-modos-de-sweep) para comparativa detallada.

### Promediado

```python
SAMPLES_PER_POINT = 1     # Hardware averaging (1–8). Más = mejor SNR, más lento.
SWEEP_AVG_COUNT   = 1     # Software averaging (repeticiones). ≥3 habilita mediana.
USE_MEDIAN_STACK  = True  # True = mediana de componentes (rechaza picos espúreos).
```

### Warmup

```python
VNA_WARMUP_ENABLE  = True   # Activa sweeps dummy de estabilización al inicio.
VNA_WARMUP_SECONDS = 60     # Tiempo de calentamiento (30–180 s recomendado).
```

### TDR

```python
TDR_WINDOW          = "blackman"   # Función de ventana: "blackman"|"hanning"|"hamming"|"bartlett"|"none"
TDR_ZERO_PAD_FACTOR = 8            # Multiplicador de zero-padding (4, 8, 16)
```

### Cable

```python
VF = 0.70   # Factor de velocidad del dieléctrico. RG-316→0.70, RG-58→0.66, LMR-400→0.85
```

### Umbrales de Clasificación

```python
THRESHOLDS = {
    "rl_min_pass_db":  20.0,  # RL promedio mínima para PASS
    "rl_min_warn_db":  15.0,  # RL mínima antes de FAIL
    "vswr_max_pass":    1.5,  # VSWR máximo para PASS
    "vswr_max_warn":    2.0,  # VSWR máximo antes de FAIL
    "il_max_pass_db":   3.0,  # Insertion Loss máx para PASS
    "il_max_warn_db":   6.0,  # Insertion Loss máx antes de FAIL
    "z_nom_ohm":       50.0,  # Impedancia nominal
    "z_tol_pass_ohm":   5.0,  # Tolerancia de impedancia para PASS (±Ω)
    "z_tol_warn_ohm":  10.0,  # Tolerancia antes de FAIL
    "disconnected_rl":  2.0,  # RL por debajo de la cual se detecta desconexión
}
```

> **Nota sobre calibración:** Los parámetros marcados con `[CAL]` en los comentarios del código generan un *perfil de calibración* único. Cambiar cualquiera de ellos invalida la calibración guardada y el wizard se ejecutará automáticamente en el próximo arranque.

---

## 📡 Modos de Sweep

### `"full"` — Sweep simple
Un único barrido de `POINTS` puntos sobre todo el rango. Es el modo más rápido pero con la menor resolución espectral.

```
100 MHz ──────────────────────────────── 4.4 GHz
         (POINTS puntos, 1 solo sweep)
```

### `"segmented"` — Sweep segmentado
El rango se divide en bloques de hasta `SEGMENT_MAX_POINTS` puntos con paso `SEGMENT_STEP_MHZ`. Los bloques se concatenan con corrección de continuidad en los bordes (stitch correction). Mayor resolución que `full`, pero más tiempo de adquisición.

**Parámetros relevantes:**
- `SEGMENT_STEP_MHZ` — Paso en MHz entre puntos consecutivos `[CAL]`
- `SEGMENT_MAX_POINTS` — Máximo de puntos por bloque hardware `[CAL]`
- `SEGMENT_DROP_HEAD` — Puntos descartados al inicio de cada segmento (elimina transitorio de resintonización del PLL)
- `SEGMENT_STITCH_CORRECT` — Activa/desactiva la corrección de continuidad entre bordes

### `"interleaved"` — Sweep entrelazado *(modo recomendado)*
Realiza `N_INTERLEAVE` pasadas segmentadas, cada una desplazada un offset de `SEGMENT_STEP_MHZ / N_INTERLEAVE` MHz respecto a la anterior. Las pasadas se fusionan y ordenan, obteniendo una resolución efectiva de:

```
Δf_efectivo = SEGMENT_STEP_MHZ / N_INTERLEAVE
```

**Ejemplo:** `SEGMENT_STEP_MHZ=10, N_INTERLEAVE=5` → Δf efectivo = 2 MHz, ~2150 puntos totales.

Al no haber bordes de segmento *entre* pasadas (cada pasada cubre frecuencias distintas), se eliminan los artefactos de stitching inter-pasada. El tiempo total es proporcional a `N_INTERLEAVE`.

| Modo | Resolución | Velocidad | Artefactos de borde |
|---|---|---|---|
| `full` | Baja | ⚡ Rápido | Ninguno |
| `segmented` | Media–alta | 🐢 Lento | Posibles en bordes de segmento |
| `interleaved` | Alta | 🐢🐢 Más lento | Mínimos (solo dentro de cada pasada) |

---

## 🧪 Calibración SOLT

El script implementa una **calibración OSL de 3 términos para S11** y una **normalización de magnitud/fase para S21** (THRU).

### Modelo OSL (S11)

```
S11_cal = (Sm - e00) / (e10·e01 + e11·(Sm - e00))
```

donde `e00`, `e11` y `e10·e01` son los tres coeficientes de error calculados a partir de las mediciones OPEN, SHORT y LOAD.

### Normalización THRU (S21)

```
S21_cal_mag   = |S21_raw| / |THRU_ref|
S21_cal_phase = ∠S21_raw - ∠THRU_ref
```

### Perfiles de Calibración

Cada combinación de parámetros `[CAL]` genera un perfil independiente guardado como archivo JSON en:

```
~/Desktop/CableMaster_Data/calibration/profiles/<nombre_perfil>.json
```

El nombre se genera automáticamente. Ejemplos:
- `full_100_4400MHz_p101`
- `seg_100_4400MHz_s10MHz_p101`
- `intlv_100_4400MHz_s10MHz_n5_p101`

Al cargar un perfil, el script valida **modo, rango de frecuencias, paso, N_INTERLEAVE y longitud del vector**. Cualquier incompatibilidad lanza el wizard automáticamente.

### Wizard de Calibración (interactivo)

```
══════════════════════════════════════════════════
  CALIBRACIÓN SOLT — NanoVNA V2 Plus4
══════════════════════════════════════════════════

  ➤  [Puerto 1] Conecte OPEN y presione ENTER...
  ➤  [Puerto 1] Conecte SHORT y presione ENTER...
  ➤  [Puerto 1] Conecte LOAD y presione ENTER...
  (➤  [P1→P2] Conecte THRU y presione ENTER...)  ← solo si ENABLE_THRU_RECAL=True
```

---

## 🚀 Uso

1. **Conectar** el NanoVNA V2 Plus4 por USB.
2. **Editar** el bloque CONFIG al inicio del script (mínimo: `PORT`, `START_FREQ`, `STOP_FREQ`, `VF`).
3. **Ejecutar:**

```bash
python VNADefv5.py
```

4. El script imprime la configuración activa y lista los perfiles de calibración disponibles.
5. Si hay una calibración válida, pregunta si recalibrar; de lo contrario, lanza el wizard.
6. **Bucle de medición:** para cada cable, conectar al Puerto 1 (CH0) y presionar ENTER.
7. Los resultados se guardan automáticamente. Al finalizar, responder `n` a la pregunta de continuar.

---

## 📂 Salidas Generadas

Todos los archivos se guardan en `~/Desktop/CableMaster_Data/`:

```
CableMaster_Data/
├── calibration/
│   └── profiles/
│       └── <nombre_perfil>.json       # Perfil de calibración
├── readings/
│   ├── <HHMMSS>_<ID>.csv             # Datos completos de la medición
│   └── <HHMMSS>_<ID>_plot.png        # Gráfica de 6 paneles
└── master_summary.csv                 # Log acumulativo de todas las mediciones
```

### CSV Individual (estructura por secciones)

| Sección | Contenido |
|---|---|
| `## RESUMEN` | Veredicto, longitudes, métricas promedio, configuración |
| `## DESGLOSE POR BANDA` | Métricas por banda VHF / UHF / SHF |
| `## DATOS CRUDOS VNA` | Valores enteros del FIFO (fwd/refl/thru, re/im) |
| `## DATOS POR FRECUENCIA` | S11, S21, RL, VSWR, Z, IL, group delay por punto |
| `## TDR` | Distancia (m) vs magnitud IFFT |
| `## FRECUENCIAS CON FALLA` | Puntos anómalos con causa y score (solo si `FREQ_FAULT_DEBUG=True`) |

### Gráfica PNG (6 paneles)

| Panel | Métrica |
|---|---|
| Superior izquierdo | Return Loss (dB) vs frecuencia |
| Superior centro | VSWR vs frecuencia |
| Superior derecho | Re(Z) e Im(Z) en Ω vs frecuencia |
| Inferior izquierdo | Insertion Loss (dB) vs frecuencia |
| Inferior centro | TDR — magnitud vs distancia (m) |
| Inferior derecho | Retardo de grupo (ns) vs frecuencia |

### Master Log (`master_summary.csv`)

Una fila por medición con todas las métricas clave, el perfil de calibración y la ruta al CSV individual. Permite comparar múltiples cables en una sola hoja.

---

## 📊 Métricas Calculadas

| Métrica | Símbolo / Fórmula | Descripción |
|---|---|---|
| Return Loss | `RL = -20·log10(\|S11\|)` dB | Potencia reflejada en el puerto de entrada |
| VSWR | `(1+\|S11\|)/(1-\|S11\|)` | Relación de onda estacionaria de voltaje |
| Impedancia compleja | `Z = 50·(1+S11)/(1-S11)` Ω | Parte real, imaginaria y módulo |
| Reflexión de potencia | `\|S11\|² × 100` % | Porcentaje de potencia reflejada |
| Insertion Loss | `IL = -20·log10(\|S21_cal\|)` dB | Pérdida de inserción calibrada |
| Longitud física (TDR) | IFFT de S11 con ventana y zero-padding | Distancia al pico principal en metros |
| Longitud eléctrica | Mediana del retardo de grupo positivo × c × VF | Longitud óptica calculada desde S21 |
| Retardo de grupo | `τ = -dφ/dω / (2π)` ns | Derivada de la fase de S21 respecto a la frecuencia |
| Fallas TDR | Picos secundarios en la IFFT | Posición en metros de discontinuidades en el cable |
| Puntos con falla (frecuencia) | OR de máscaras RL/VSWR/IL/Z | Frecuencias individuales fuera de umbrales |

### Clasificación de Veredicto

| Veredicto | Condición |
|---|---|
| ✅ `PASS` | Todas las métricas dentro de umbrales PASS |
| ⚠️ `WARN` | Al menos una métrica entre PASS y WARN |
| ❌ `FAIL` | Al menos una métrica fuera del umbral WARN |
| ❌ `FAIL` | RL promedio < 2 dB (cable desconectado / circuito abierto) |

---

## 🏗️ Arquitectura del Código

```
VNADefv5.py
│
├── Bloque CONFIG (líneas 47–216)
│   └── Todas las constantes ajustables por el usuario
│
├── Sistema de perfiles de calibración
│   ├── _active_profile_name()       → nombre único del perfil activo
│   ├── _active_cal_file()           → ruta al JSON de calibración
│   ├── list_calibration_profiles()  → lista perfiles guardados
│   └── _validate_runtime_config()   → valida parámetros antes de arrancar
│
├── Helpers de sweep segmentado/entrelazado
│   ├── _build_segment_plan()        → genera lista de (start, stop, pts)
│   ├── _segment_boundary_indices()  → índices de borde para enmascarar group delay
│   ├── _count_segmented_points()    → cuenta puntos post-drop
│   └── _expected_total_points()     → predicción determinística del tamaño del vector
│
├── class NanoVNA_V2                 → capa de hardware
│   ├── warmup()                     → sweeps dummy de estabilización
│   ├── _measure_block()             → sweep de un bloque + promediado SW
│   ├── _measure_segmented()         → concatenación de bloques con stitch correction
│   ├── _measure_interleaved()       → N pasadas segmentadas fusionadas
│   ├── measure()                    → punto de entrada público (despacha por modo)
│   └── _parse_fifo()                → desempaqueta los 32 bytes/punto del NanoVNA
│
├── class Calibration                → calibración SOLT
│   ├── solve()                      → calcula coeficientes OSL + referencia THRU
│   ├── apply()                      → aplica corrección a S11 y S21 raw
│   ├── save() / load()              → persistencia JSON
│   └── _validate_compatibility()    → comprueba que el perfil coincide con la config actual
│
├── Zona de cálculo
│   ├── compute_all_metrics()        → calcula RL, VSWR, Z, IL, TDR, group delay, bandas
│   ├── _detect_frequency_faults()   → detecta y clasifica frecuencias problemáticas
│   ├── _classify()                  → asigna veredicto PASS/WARN/FAIL
│   └── helpers de formato           → _format_freq_ranges_mhz(), _format_top_fault_freqs()
│
├── Exportación
│   ├── save_individual_csv()        → CSV estructurado en 6 secciones
│   ├── append_master_log()          → fila en el log acumulativo
│   └── save_plot()                  → gráfica PNG de 6 paneles (fondo oscuro)
│
├── run_calibration_wizard()         → wizard interactivo SOLT
│
└── main()                           → arranque, calibración, bucle de medición
```

---

## ⚠️ Problemas Conocidos (WIP)

- **Lecturas anómalas en ciertas frecuencias:** Se han observado datos que no corresponden a la respuesta esperada del cable en algunas frecuencias del barrido. La causa probable es una combinación de artefactos de resintonización del PLL del NanoVNA y/o interferencias de la etapa de RF a frecuencias específicas. Se está investigando si ajustes en `SWEEP_SETTLE_MS`, `SEGMENT_DROP_HEAD` o `SAMPLES_PER_POINT` resuelven el problema.
- **Corrección THRU simplificada:** La calibración S21 normaliza solo magnitud y fase del THRU; no implementa un modelo de 2 puertos completo (12 términos). Para aplicaciones que requieran S21 de alta precisión, se recomienda usar un VNA con calibración SOLT completa de 2 puertos.
- **Longitud eléctrica:** El cálculo basado en el retardo de grupo puede ser impreciso en cables muy cortos (< 20 cm) o cuando el group delay tiene mucha varianza entre frecuencias.

---

## 📝 Notas Adicionales

- El script requiere que el NanoVNA V2 Plus4 esté conectado **antes** de ejecutar. No hay reconexión automática.
- En Windows, el puerto suele ser `COM3` o `COM4`; verificar en el Administrador de dispositivos.
- Los perfiles de calibración son **específicos por configuración**. Al cambiar el rango de frecuencias o el modo, la calibración anterior no es válida y el wizard se lanzará automáticamente.
- Para cables de tipo RG-58 usar `VF = 0.66`; para RG-316 usar `VF = 0.70`; para LMR-400 usar `VF = 0.85`.
- El tiempo total de una sesión con `SWEEP_MODE="interleaved"` y `N_INTERLEAVE=5` es aproximadamente 5× el tiempo de un sweep segmentado equivalente.
