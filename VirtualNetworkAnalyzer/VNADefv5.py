import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import serial
import numpy as np
import time
import struct
import json
import csv
import uuid
from datetime import datetime
from pathlib import Path
from scipy.signal import find_peaks

EPS = 1e-12

def _as_1d_complex(x, name):
    arr = np.asarray(x, dtype=np.complex128).reshape(-1)
    if arr.size == 0:
        raise ValueError(f"{name} está vacío")
    if not (np.all(np.isfinite(arr.real)) and np.all(np.isfinite(arr.imag))):
        raise ValueError(f"{name} contiene valores no finitos")
    return arr

def _as_1d_float(x, name):
    arr = np.asarray(x, dtype=np.float64).reshape(-1)
    if arr.size == 0:
        raise ValueError(f"{name} está vacío")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} contiene valores no finitos")
    return arr


# ══════════════════════════════════════════════════════════════════════════════
#
#   ██████╗ ██████╗ ███╗   ██╗███████╗██╗ ██████╗
#  ██╔════╝██╔═══██╗████╗  ██║██╔════╝██║██╔════╝
#  ██║     ██║   ██║██╔██╗ ██║█████╗  ██║██║  ███╗
#  ██║     ██║   ██║██║╚██╗██║██╔══╝  ██║██║   ██║
#  ╚██████╗╚██████╔╝██║ ╚████║██║     ██║╚██████╔╝
#   ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝     ╚═╝ ╚═════╝
#
#  Modifica SÓLO este bloque antes de ejecutar.
#
# ══════════════════════════════════════════════════════════════════════════════

# ─── Hardware ────────────────────────────────────────────────────────────────
PORT = '/dev/ttyACM0'
BAUD = 115200

# ─── Rango de frecuencia ─────────────────────────────────────────────────────
START_FREQ = 100_000_000      # Hz → 100 MHz
STOP_FREQ  = 4_400_000_000    # Hz → 4.4 GHz

# ─── Modo de sweep ───────────────────────────────────────────────────────────
#
#   "full"        → Un solo sweep de POINTS puntos (rápido, baja resolución).
#                   Calibración: 1 perfil por rango+puntos.
#
#   "segmented"   → Múltiples sweeps de ≤ SEGMENT_MAX_POINTS puntos c/u,
#                   unidos con corrección de continuidad.

#                   Mejor resolución espectral. Calibración: 1 perfil por
#                   rango+paso+max_puntos.
#
#   "interleaved" → N_INTERLEAVE pasadas segmentadas con offset de frecuencia
#                   sistemático entre ellas. Las pasadas se fusionan y ordenan.
#                   Resultado: resolución efectiva = SEGMENT_STEP_MHZ/N_INTERLEAVE,
#                   SIN bordes de segmento entre pasadas.
#                   Calibración: 1 perfil por rango+paso+N+max_puntos.
#                   ⚠ Tiempo total ≈ N_INTERLEAVE × tiempo segmented.
#
# IMPORTANTE SOBRE CALIBRACIÓN:
#   Cada combinación de (SWEEP_MODE + parámetros de frecuencia) genera un
#   perfil de calibración independiente. Cambiar cualquier parámetro marcado
#   con [CAL] invalida la calibración anterior y dispara el wizard automáticamente.
#
SWEEP_MODE = "segmented"    # "full" | "segmented" | "interleaved"

# ─── Configuración FULL ─────────────────────────────────────────── [CAL] ───
POINTS = 101    # puntos para modo "full"

# ─── Configuración SEGMENTED ─────────────────────────────────────── [CAL] ──
SEGMENT_STEP_MHZ   = 10.0   # MHz entre puntos consecutivos  [CAL
SEGMENT_MAX_POINTS = 101    # puntos máximos por bloque hardware [CAL]

# Puntos descartados al inicio de cada segmento (>= 2 recomendado).
# Elimina el transitorio de resintonización del PLL entre bloques.
SEGMENT_DROP_HEAD  = 2

# Corrección de continuidad en bordes de segmento.
# Compara el borde compartido entre segmentos y aplica un factor complejo
# suavizado sobre SEGMENT_STITCH_SMOOTH_PTS puntos para eliminar el salto.
SEGMENT_STITCH_CORRECT    = True
SEGMENT_STITCH_SMOOTH_PTS = 5

# ─── Configuración INTERLEAVED ───────────────────────────────────── [CAL] ──
#
#   Cada pasada i parte desde START_FREQ + i × (SEGMENT_STEP_MHZ / N_INTERLEAVE)
#   y avanza con paso SEGMENT_STEP_MHZ. La resolución efectiva resultante es:
#       Δf_efectivo = SEGMENT_STEP_MHZ / N_INTERLEAVE
#
#   Ejemplo: SEGMENT_STEP_MHZ=10, N_INTERLEAVE=5 → Δf=2 MHz, ~2150 puntos.
#
#   ⚠ Recalibrar si cambia N_INTERLEAVE, SEGMENT_STEP_MHZ o SEGMENT_MAX_POINTS.
#
N_INTERLEAVE = 5    # número de pasadas entrelazadas  [CAL]

# ─── Tiempo de estabilización ─────────────────────────────────────────────────
# Espera tras reconfigurar el VNA antes de leer (ms).
# Regla práctica: ~8 ms × POINTS_POR_BLOQUE ≥ 800 ms mínimo.
SWEEP_SETTLE_MS = max(800, SEGMENT_MAX_POINTS * 8)

# Sweeps de calentamiento (hardware) descartados antes de leer datos.
# Absorbe la inercia térmica del PLL al cambiar de rango.
SEGMENT_WARMUP_SWEEPS = 1

# ─── Promediado y apilamiento ─────────────────────────────────────────────────
#
#   SAMPLES_PER_POINT  → Hardware averaging (registro 0x22 del VNA).
#       1  = sin promediado, más rápido.
#       4–8 = mejor SNR, N× más lento.
#       Si se aumenta, multiplicar SWEEP_SETTLE_MS × SAMPLES_PER_POINT.
#
#   SWEEP_AVG_COUNT    → Software averaging: repite la lectura N veces y combina.
#       1  = sin repetición.
#       ≥3 = permite usar la mediana (ver USE_MEDIAN_STACK).
#
#   USE_MEDIAN_STACK   → Si True Y SWEEP_AVG_COUNT ≥ 3: combina las N lecturas
#       con la mediana de componente (real e imaginario por separado).
#       Rechaza picos espúreos individuales mejor que la media aritmética.
#       Si False: usa la media aritmética (comportamiento original).
#
SAMPLES_PER_POINT  = 1      # Hardware averaging por punto (1–8)
SWEEP_AVG_COUNT    = 1      # Sweeps de software promediados (1 = desactivado)
USE_MEDIAN_STACK   = True   # True = mediana cuando SWEEP_AVG_COUNT ≥ 3

# ─── Warmup de arranque ────────────────────────────────────────────────────────
#
#   Antes de calibrar o medir, el VNA realiza sweeps dummy durante
#   VNA_WARMUP_SECONDS segundos para estabilizar térmicamente el oscilador.
#   El PLL del NanoVNA V2 puede derivar 5–10 ppm/°C → 22–44 kHz a 4.4 GHz.
#   Recomendado: 120 s para alta precisión, 30 s para uso general.
#
VNA_WARMUP_ENABLE  = True   # True = activar warmup al inicio
VNA_WARMUP_SECONDS = 60     # segundos de calentamiento (30–180 recomendado)

# ─── Calibración THRU (S21) ─────────────────────────────────────────────────
# False: omite captura THRU en recalibraciones rápidas (reusa THRU previo o 1+0j)
# True : pide THRU en el wizard y recalibra también S21.
ENABLE_THRU_RECAL  = False

# ─── Verificación post-calibración ────────────────────────────────────────────
#
#   True  → Al finalizar el wizard, mide la carga LOAD una segunda vez y calcula
#            el error residual de calibración (RMS del S11 corregido).
#            Un cable bien calibrado debería dar S11_cal ≈ 0 + 0j sobre la carga.
#            La desviación real te indica el piso de error del sistema antes de
#            medir cualquier cable.
#            Añade ~30 s al proceso de calibración.
#
#   False → Sin verificación. Calibración termina tras capturar OPEN/SHORT/LOAD.
#
CAL_VERIFY_ENABLE = True

# ─── Supresión del transitorio de conector en TDR ─────────────────────────────
#
#   El conector del puerto 1 genera un pico en el TDR a distancia ≈ 0 m que
#   puede ser confundido con el extremo del cable, produciendo longitudes
#   reportadas incorrectas (ej: 0.006 m en lugar de 0.36 m).
#
#   TDR_MIN_CABLE_LEN_M → distancia mínima (m) desde la que el algoritmo
#   buscará el pico principal. Aumentar si los cables son muy cortos (> 5 cm)
#   y el conector sigue dominando. Reducir si los cables son < 5 cm.
#   Valor 0.0 = comportamiento original (busca desde el inicio).
#
TDR_SUPPRESS_CONNECTOR = True     # True = aplica la distancia mínima de búsqueda
TDR_MIN_CABLE_LEN_M    = 0.06    # metros — omite el transitorio del conector

# ─── Advertencias de fiabilidad ───────────────────────────────────────────────
#
#   WARN_RESOLUTION_MISMATCH → avisa si el modo "full" (baja resolución espectral)
#       se usa con cables cuya longitud eléctrica excede WARN_RESOLUTION_MIN_LEN_M.
#       En esos casos, el patrón de oscilación de RL/Z tiene menos de ~5 muestras
#       por ciclo y los promedios de impedancia son poco representativos.
#       Sugerencia automática: cambiar a modo "segmented".
#
#   WARN_GD_STABILITY → avisa al inicio si SWEEP_AVG_COUNT < 3 en modos segmented
#       o interleaved. El GD calculado por np.gradient es ruidoso con una sola
#       toma; la mediana de ≥3 sweeps lo estabiliza significativamente.
#
WARN_RESOLUTION_MISMATCH  = True   # True = avisa en terminal tras la medición
WARN_RESOLUTION_MIN_LEN_M = 0.20   # umbral de longitud eléctrica (metros)
WARN_GD_STABILITY         = True   # True = avisa al inicio si SW avg < 3

# ─── TDR ──────────────────────────────────────────────────────────────────────
#
#   TDR_WINDOW          → Función de ventana aplicada a S11 antes de la IFFT.
#       "blackman"  → Mayor atenuación de sidelobes (−92 dB). Recomendado.
#       "hanning"   → Balance bueno entre resolución y sidelobes (−43 dB).
#       "hamming"   → Similar a hanning, sidelobe ligeramente mayor.
#       "bartlett"  → Ventana triangular, sidelobes moderados.
#       "none"      → Sin ventana (rectangular). Mayor resolución pero
#                     sidelobes altos que pueden enmascarar fallas cercanas.
#
#   TDR_ZERO_PAD_FACTOR → Multiplicador de ceros para la IFFT.
#       4  = buena interpolación para cables > 30 cm.
#       8  = mejor para cables muy cortos (< 15 cm) donde los picos
#            del TDR son difíciles de separar.
#       16 = máxima interpolación, costo computacional mayor.
#
TDR_WINDOW          = "blackman"   # "blackman"|"hanning"|"hamming"|"bartlett"|"none"
TDR_ZERO_PAD_FACTOR = 8            # multiplicador de zero-padding (4, 8, 16)

# ─── Cable ───────────────────────────────────────────────────────────────────
# Factor de velocidad del dieléctrico. Tabla de referencia:
#   RG-316  → 0.70   RG-58  → 0.66   LMR-400 → 0.85
#   RG-6    → 0.82   RG-213 → 0.66   LMR-240 → 0.84
VF = 0.70

# ─── Umbrales para clasificación de calidad ──────────────────────────────────
# ─── Umbrales de detección de anomalías ──────────────────────────────────────
#
#   Usados exclusivamente para generar advertencias informativas.
#   No producen veredictos PASS/FAIL — solo señalan estadísticas que
#   se desvían notablemente de lo esperable en uso general.
#
#   Ajustar con holgura: el objetivo es detectar problemas reales
#   (cable roto, conector suelto, cortocircuito), no evaluar calidad RF.
#
THRESHOLDS = {
    "rl_avg_warn_db":    10.0,   # RL promedio muy baja → posible mal contacto
    "rl_min_warn_db":     6.0,   # RL mínima extrema → posible cortocircuito
    "vswr_max_warn":      4.0,   # VSWR muy alto → reflexión severa
    "il_avg_warn_db":     8.0,   # IL promedio alta → pérdidas significativas
    "il_max_warn_db":    15.0,   # IL pico muy alto → posible rotura parcial
    "z_nom_ohm":         50.0,   # impedancia nominal de referencia
    "z_tol_warn_ohm":    20.0,   # desviación de Z que vale la pena señalar
    "disconnected_rl":    2.0,   # RL < 2 dB → cable probablemente desconectado
}

# ─── Debug de detección de fallas en frecuencia ─────────────────────────────
# False: salida compacta (solo conteo/rangos básicos)
# True : salida detallada (top MHz, causas por punto y sección detallada en CSV)
FREQ_FAULT_DEBUG = True

# ─── Generación de gráfico ───────────────────────────────────────────────────
#
#   True  → Genera el archivo PNG del gráfico junto al CSV en cada medición.
#            El gráfico incluye los 6 subplots (RL, VSWR, Z, IL, TDR, GD) con
#            las bandas rojas de zonas instrumentales y el título con resumen.
#            Requiere matplotlib. Añade ~1–2 s por medición.
#
#   False → Solo genera el CSV. Útil en sesiones de catalogado masivo donde
#           el técnico trabaja directamente con la ficha, o en sistemas sin
#           pantalla. El gráfico se puede generar a posteriori desde el CSV.
#
SAVE_PLOT = False

# ─── Anotación de zonas instrumentales ───────────────────────────────────────
#
#   True  → Activa el sistema de anotación de zonas de error del NanoVNA V2 Plus4.
#
#            Principio fundamental: los datos medidos NUNCA se modifican.
#            Las zonas instrumentales se anotan y señalizan, no se eliminan.
#
#            Efecto sobre cada subsistema:
#              • Datos crudos: íntegros, sin alteración en ningún caso.
#              • PASS/FAIL y stats (avg/min/max): calculados excluyendo las zonas
#                instrumentales (el técnico ve la nota en terminal y CSV).
#              • Conteo de fallas: excluye puntos en zonas instrumentales.
#              • Group Delay: desenvuelto con _stitch_phase — cosido global de
#                fase entre segmentos usando predicción de pendiente (k×2π exacto).
#                Los puntos en zonas instrumentales quedan NaN en group_delay_ns.
#                group_delay_ns_plot: interpolación lineal solo para el gráfico,
#                marcada como sintética en CSV y en el subplot.
#              • Gráficas: bandas rojas semitransparentes con etiqueta de zona
#                en todos los subplots de frecuencia. La curva de datos no se
#                interrumpe (se usa group_delay_ns_plot para GD).
#              • CSV: columnas 'instrument_zone' (nombre de la zona o vacío) e
#                'instrument_confidence' (4=alta/7datasets, 3=media, 0=normal).
#
#   False → Sin anotaciones, sin sombreado. Comportamiento idéntico a v5.
#
INSTRUMENT_MASK_ENABLE = True

# ─── Bandas de frecuencia para desglose ──────────────────────────────────────
BANDS = {
    "VHF  (100–300 MHz)": (100e6,  300e6),
    "UHF  (300–800 MHz)": (300e6,  800e6),
    "SHF  (800MHz–1GHz)": (800e6, 1000e6),
}

# ─── Rutas de salida ──────────────────────────────────────────────────────────
APP_NAME         = "CableMaster_Data"
DESKTOP          = Path.home() / "Desktop" / APP_NAME
CAL_DIR          = DESKTOP / "calibration"
CAL_PROFILES_DIR = CAL_DIR / "profiles"
READINGS_DIR     = DESKTOP / "readings"
MASTER_LOG       = DESKTOP / "master_summary.csv"

# Nombre de perfil manual. None → generado automáticamente (recomendado).
CAL_PROFILE_OVERRIDE = None

for _d in (CAL_PROFILES_DIR, READINGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
#  Fin del bloque de configuración
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
#  Máscara de frecuencias instrumentales (NanoVNA V2 Plus4)
#
#  Zonas identificadas por análisis cruzado de 7 mediciones (abril–mayo 2026).
#  Cada tupla: (f_inicio_MHz, f_fin_MHz, descripción, confianza_sobre_7)
#
#  Prioridad ★ = 4/7 datasets afectados  ● = 3/7
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
#  Zonas de error instrumental (NanoVNA V2 Plus4)
#
#  Identificadas por análisis cruzado de 7 mediciones (abril–mayo 2026).
#  Cada tupla: (f_inicio_MHz, f_fin_MHz, nombre_corto, descripción_completa, confianza)
#
#  confianza: número de datasets (sobre 7) donde la anomalía fue confirmada.
#  ★ = 4/7 (alta prioridad)   ● = 3/7 (media)
# ══════════════════════════════════════════════════════════════════════════════

VNA_ERROR_ZONES = [
    # (f_lo, f_hi, nombre_corto, descripción, confianza)
    # ── Alta prioridad (4/7 datasets) ────────────────────────────────────────
    (1125, 1155, "LO ×1",      "LO interno / armónico fundamental — IL spike hasta 11 dB",    4),
    (3090, 3145, "LO ×2.75",   "Armónico LO ×2.75 — IL spike hasta 21 dB (más intenso)",      4),
    (3350, 3400, "LO ×3",      "Armónico LO ×3 — RL dip hasta 12 dB",                         4),
    (3890, 3925, "GD prd #4",  "Serie GD periódica @~970 MHz — RL + GD spike",                4),
    (4190, 4240, "Borde sup",  "Borde superior del rango — RL dip hasta 16 dB",               4),
    # ── Prioridad media (3/7 datasets) ───────────────────────────────────────
    (2120, 2165, "PLL 2 GHz",  "Cruce divisor PLL ~2 GHz — RL + IL spike",                    3),
    (2760, 2795, "RL dip",     "RL dip moderado reproducible",                                3),
    (4120, 4145, "IL alta",    "IL spike zona alta",                                          3),
    # ── Serie periódica de GD (~970 MHz entre picos) ─────────────────────────
    ( 295,  320, "GD prd #1",  "GD spike periódico #1 (~305 MHz)",                            3),
    (1945, 1965, "GD prd #2",  "GD spike periódico #2 (~1955 MHz)",                           3),
    (2905, 2925, "GD prd #3",  "GD spike periódico #3 (~2915 MHz)",                           3),
]


def annotate_instrument_zones(freq_mhz: np.ndarray):
    """
    Devuelve dos arrays paralelos a freq_mhz:
      zone_name : str  — nombre corto de la zona, o '' si el punto es confiable.
      zone_conf : int  — confianza (3 o 4), o 0 si el punto es confiable.

    Los datos medidos NO se modifican. Esta función solo produce etiquetas.
    """
    n = len(freq_mhz)
    zone_name = np.full(n, '', dtype=object)
    zone_conf = np.zeros(n, dtype=np.int8)

    if not INSTRUMENT_MASK_ENABLE:
        return zone_name, zone_conf

    for f_lo, f_hi, nombre, _, conf in VNA_ERROR_ZONES:
        hit = (freq_mhz >= f_lo) & (freq_mhz <= f_hi)
        zone_name[hit] = nombre
        zone_conf[hit] = conf

    return zone_name, zone_conf


def build_instrument_mask(freq_mhz: np.ndarray,
                          priority_min: int = 3) -> np.ndarray:
    """
    Devuelve bool array: True = punto confiable (fuera de zona de error).
    Usado exclusivamente para excluir zonas del cálculo de stats y detección
    de anomalías. No modifica ningún dato medido.
    """
    valid = np.ones(len(freq_mhz), dtype=bool)
    if not INSTRUMENT_MASK_ENABLE:
        return valid
    for f_lo, f_hi, _, _, conf in VNA_ERROR_ZONES:
        if conf >= priority_min:
            valid &= ~((freq_mhz >= f_lo) & (freq_mhz <= f_hi))
    return valid


def _stitch_phase(phase: np.ndarray,
                  instr_mask: np.ndarray,
                  slope_pts: int = 8) -> np.ndarray:
    """
    Desenvuelve la fase de S21 manteniendo continuidad global entre segmentos.

    Principio
    ---------
    La fase real de S21 en un cable de transmisión es una función monótona
    decreciente (miles de grados a lo largo del rango). El VNA entrega solo el
    valor módulo 2π (envuelto entre -π y +π). El unwrap estándar resuelve esta
    ambigüedad para datos continuos; aquí además hay "huecos" (zonas
    instrumentales) donde la fase puede haber acumulado varios ciclos de 2π
    sin que el algoritmo lo vea.

    Para cada hueco se hace:
      1. Ajustar una recta a los últimos `slope_pts` puntos válidos antes del
         hueco → estima la pendiente de fase del cable (dφ/df).
      2. Extrapolar esa recta hasta el primer punto válido después del hueco
         → obtener la fase "esperada" en ese punto.
      3. Calcular el múltiplo de 2π más cercano que lleva la fase medida del
         VNA a la fase esperada → aplicar ese offset entero a todo el segmento
         siguiente.

    El offset siempre es exactamente k × 2π (k entero). Los valores medidos
    del VNA quedan intactos; solo se desambigua el ciclo de envoltura.
    Las zonas instrumentales quedan como NaN en el resultado — sin valores
    sintéticos.

    Parámetros
    ----------
    phase      : array de fase en radianes, medida directa del VNA.
    instr_mask : bool array, True = punto confiable.
    slope_pts  : nº de puntos válidos para estimar la pendiente antes de cada
                 hueco. Mínimo recomendado: 5. Aumentar si el GD es muy ruidoso.

    Devuelve
    --------
    Array del mismo tamaño con la fase global desenvuelta.
    Puntos en zonas instrumentales → NaN.
    """
    if not INSTRUMENT_MASK_ENABLE:
        return np.unwrap(phase)

    n      = len(phase)
    result = np.full(n, np.nan)

    # Identificar segmentos contiguos de puntos válidos
    segs = []
    in_seg, seg_start = False, 0
    for i in range(n + 1):
        valid = (i < n) and bool(instr_mask[i])
        if valid and not in_seg:
            seg_start = i; in_seg = True
        elif not valid and in_seg:
            segs.append((seg_start, i)); in_seg = False

    if not segs:
        return result

    # Primer segmento: unwrap estándar, sin referencia previa
    s0, e0 = segs[0]
    if e0 - s0 >= 2:
        result[s0:e0] = np.unwrap(phase[s0:e0])
    elif e0 - s0 == 1:
        result[s0] = phase[s0]

    # Segmentos siguientes: coser con predicción de pendiente
    for k in range(1, len(segs)):
        s_cur, e_cur = segs[k]
        s_prev, e_prev = segs[k - 1]

        # Fase ya desenvuelta del segmento anterior (referencia)
        prev_unwrapped = result[s_prev:e_prev]
        prev_ok = np.isfinite(prev_unwrapped)

        if prev_ok.sum() >= 2:
            # Tomar los últimos slope_pts puntos del segmento anterior
            tail = prev_unwrapped[prev_ok][-slope_pts:]
            # Frecuencias correspondientes (índices dentro del array global)
            idx_prev = np.where(np.isfinite(result[s_prev:e_prev]))[0] + s_prev
            freq_tail = np.arange(len(tail), dtype=float)  # índices relativos

            if len(tail) >= 2:
                # Recta de regresión sobre índices (la escala real de frecuencia
                # no importa aquí, solo la pendiente en índices)
                slope = np.polyfit(np.arange(len(tail)), tail, 1)[0]
            else:
                slope = 0.0

            # Distancia en índices desde el último punto previo hasta el
            # primer punto del segmento actual
            last_prev_idx = idx_prev[-1]
            gap = s_cur - last_prev_idx          # tamaño del hueco en índices
            phase_expected = tail[-1] + slope * gap

        else:
            # Sin referencia previa: usar la fase medida sin corrección
            phase_expected = phase[s_cur]

        # Fase medida del VNA en el primer punto del segmento actual
        phase_measured = phase[s_cur]

        # Múltiplo de 2π que minimiza la diferencia con la fase esperada
        diff = phase_expected - phase_measured
        k_offset = int(np.round(diff / (2 * np.pi)))
        offset   = k_offset * 2 * np.pi

        # Desenrollar el segmento actual localmente y aplicar el offset global
        if e_cur - s_cur >= 2:
            result[s_cur:e_cur] = np.unwrap(phase[s_cur:e_cur]) + offset
        elif e_cur - s_cur == 1:
            result[s_cur] = phase[s_cur] + offset

    return result


def _interpolate_for_plot(freq_mhz: np.ndarray,
                          values: np.ndarray) -> np.ndarray:
    """
    Rellena NaN con interpolación lineal entre vecinos para uso EXCLUSIVO
    en la visualización gráfica. El resultado se almacena en columnas _plot
    del CSV, nunca sobrescribe los valores medidos.

    Los NaN en los extremos (sin vecino válido) se propagan sin cambio.
    """
    result = values.copy().astype(float)
    finite = np.isfinite(result)
    if finite.all() or finite.sum() < 2:
        return result
    good = np.where(finite)[0]
    bad  = np.where(~finite)[0]
    result[bad] = np.interp(freq_mhz[bad], freq_mhz[good], result[good])
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  Sistema de perfiles de calibración
# ══════════════════════════════════════════════════════════════════════════════

def _active_profile_name() -> str:
    """
    Nombre único de calibración codificado desde los parámetros activos.

    Cambiar CUALQUIER parámetro marcado [CAL] produce un nombre diferente,
    lo que fuerza automáticamente una nueva calibración.

    Ejemplos:
      full_100_4400MHz_p101
      seg_100_4400MHz_s10MHz_p101
      intlv_100_4400MHz_s10MHz_n5_p101
    """
    if CAL_PROFILE_OVERRIDE is not None:
        name = str(CAL_PROFILE_OVERRIDE).strip()
        return name if name else "custom_profile"

    s = int(START_FREQ // 1_000_000)
    e = int(STOP_FREQ  // 1_000_000)
    mode = SWEEP_MODE.lower()

    if mode == "full":
        return f"full_{s}_{e}MHz_p{POINTS}"

    step = int(round(SEGMENT_STEP_MHZ))

    if mode == "segmented":
        return f"seg_{s}_{e}MHz_s{step}MHz_p{SEGMENT_MAX_POINTS}"

    if mode == "interleaved":
        return f"intlv_{s}_{e}MHz_s{step}MHz_n{N_INTERLEAVE}_p{SEGMENT_MAX_POINTS}"

    return f"custom_{s}_{e}MHz"


def _active_cal_file() -> Path:
    return CAL_PROFILES_DIR / f"{_active_profile_name()}.json"


def list_calibration_profiles() -> list:
    return sorted(p.stem for p in CAL_PROFILES_DIR.glob("*.json"))


def _validate_runtime_config():
    """
    Valida parámetros críticos para evitar divisiones por cero o loops inválidos.
    Lanza ValueError si encuentra una configuración no segura.
    """
    mode = SWEEP_MODE.lower()
    valid_modes = {"full", "segmented", "interleaved"}
    if mode not in valid_modes:
        raise ValueError(
            f"SWEEP_MODE inválido: '{SWEEP_MODE}'. "
            f"Use uno de: {sorted(valid_modes)}"
        )

    if START_FREQ >= STOP_FREQ:
        raise ValueError("START_FREQ debe ser menor que STOP_FREQ")

    if POINTS < 3:
        raise ValueError("POINTS debe ser >= 3")

    if mode in ("segmented", "interleaved"):
        if SEGMENT_STEP_MHZ <= 0:
            raise ValueError("SEGMENT_STEP_MHZ debe ser > 0")
        step_hz = int(round(SEGMENT_STEP_MHZ * 1e6))
        if step_hz < 1:
            raise ValueError(
                "SEGMENT_STEP_MHZ es demasiado pequeño: redondea a 0 Hz"
            )
        if SEGMENT_MAX_POINTS < 2:
            raise ValueError("SEGMENT_MAX_POINTS debe ser >= 2")

    if mode == "interleaved":
        if N_INTERLEAVE < 1:
            raise ValueError("N_INTERLEAVE debe ser >= 1")
        step_hz = int(round(SEGMENT_STEP_MHZ * 1e6))
        if step_hz % N_INTERLEAVE != 0:
            eff_exact_mhz = SEGMENT_STEP_MHZ / N_INTERLEAVE
            eff_real_mhz = (step_hz // N_INTERLEAVE) / 1e6
            print(
                "  ⚠ Aviso: SEGMENT_STEP_MHZ/N_INTERLEAVE no es entero en Hz; "
                "se usará offset truncado. "
                f"efectivo real={eff_real_mhz:.6f} MHz "
                f"(ideal={eff_exact_mhz:.6f} MHz)"
            )


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers de sweep segmentado / entrelazado
# ══════════════════════════════════════════════════════════════════════════════

def _build_segment_plan(start_hz, stop_hz, step_hz, max_points):
    """
    Devuelve lista de (seg_start, seg_stop, seg_points).
    Segmentos consecutivos comparten el punto de borde (eliminado con DROP_HEAD).
    """
    if int(step_hz) <= 0:
        raise ValueError("step_hz debe ser > 0")
    if int(max_points) < 2:
        raise ValueError("max_points debe ser >= 2")

    seg_span = int(step_hz) * (int(max_points) - 1)
    cur      = int(start_hz)
    stop_hz  = int(stop_hz)
    plan     = []
    while cur < stop_hz:
        seg_stop = min(cur + seg_span, stop_hz)
        seg_pts  = int((seg_stop - cur) // int(step_hz)) + 1
        seg_pts  = max(2, min(int(max_points), seg_pts))
        plan.append((cur, seg_stop, seg_pts))
        if seg_stop >= stop_hz:
            break
        cur = seg_stop
    return plan


def _segment_boundary_indices(plan, drop_n):
    """
    Índices (en el vector post-drop concatenado) donde empieza cada segmento
    desde el 2.º en adelante. Usado para enmascarar el group delay en bordes.
    """
    idxs = []
    cur  = 0
    for i, (_, _, pts) in enumerate(plan):
        keep = pts if i == 0 else max(0, pts - drop_n)
        if i > 0:
            idxs.append(cur)
        cur += keep
    return idxs


def _count_segmented_points(start_hz, stop_hz, step_hz, max_pts, drop_n):
    """Calcula cuántos puntos produce un sweep segmentado (post-drop)."""
    plan  = _build_segment_plan(start_hz, stop_hz, step_hz, max_pts)
    d     = max(1, drop_n)
    total = 0
    for i, (_, _, pts) in enumerate(plan):
        total += pts if i == 0 else max(0, pts - d)
    return total


def _expected_total_points() -> int:
    """
    Calcula determinísticamente cuántos puntos tendrá el vector final.
    Debe coincidir exactamente con lo que producen los métodos de medición,
    de modo que la validación de calibración sea correcta.
    """
    mode    = SWEEP_MODE.lower()
    step_hz = int(round(SEGMENT_STEP_MHZ * 1e6))
    drop_n  = max(1, SEGMENT_DROP_HEAD)

    if mode == "full":
        return POINTS

    if mode == "segmented":
        return _count_segmented_points(
            START_FREQ, STOP_FREQ, step_hz, SEGMENT_MAX_POINTS, drop_n)

    if mode == "interleaved":
        # Simula la concatenación y el trim a [START_FREQ, STOP_FREQ].
        offset_step_hz = step_hz // N_INTERLEAVE
        all_freqs = []
        for i in range(N_INTERLEAVE):
            f_start_i = START_FREQ + i * offset_step_hz
            f_stop_i  = STOP_FREQ  + i * offset_step_hz
            plan = _build_segment_plan(f_start_i, f_stop_i, step_hz, SEGMENT_MAX_POINTS)
            for j, (seg_s, seg_e, pts) in enumerate(plan):
                start_idx = 0 if j == 0 else drop_n
                seg_freqs = seg_s + step_hz * np.arange(start_idx, pts)
                all_freqs.append(seg_freqs)
        all_freqs = np.sort(np.concatenate(all_freqs))
        mask = (all_freqs >= START_FREQ) & (all_freqs <= STOP_FREQ)
        return int(mask.sum())

    return POINTS


# ══════════════════════════════════════════════════════════════════════════════
#  Capa de Hardware
# ══════════════════════════════════════════════════════════════════════════════

class NanoVNA_V2:
    def __init__(self, port):
        print(f"🔌 Conectando a {port}...")
        self.ser = serial.Serial(port, BAUD, timeout=3)
        self.ser.dtr = True
        self.last_native = None
        self.last_freqs  = None
        # Estado interno del stitching (se reinicia por cada sweep segmentado)
        self._last_seg_tail_s11  = None
        self._last_seg_tail_s21  = None
        self._last_seg_tail_freq = None
        time.sleep(0.5)
        self.ser.write(bytes([0x0D]))
        resp = self.ser.read(1)
        print(f"{'✅ Handshake OK' if resp else '⚠️  Sin respuesta de handshake — continuando'}")

    # ── Warmup de arranque ────────────────────────────────────────────────────
    def warmup(self, seconds: int):
        """
        Realiza sweeps dummy durante `seconds` segundos para estabilizar el PLL
        y reducir la deriva térmica del oscilador antes de calibrar o medir.
        """
        if seconds <= 0:
            return
        print(f"\n  ⏳ Calentando VNA durante {seconds} s "
              f"(estabilización del oscilador)...")
        step_hz = int(round(SEGMENT_STEP_MHZ * 1e6))
        dummy_pts = min(SEGMENT_MAX_POINTS, 101)
        dummy_step = (int(STOP_FREQ) - int(START_FREQ)) // (dummy_pts - 1)

        # Configurar un sweep rápido dummy
        self.ser.write(struct.pack('<BBQ', 0x23, 0x00, int(START_FREQ)))
        self.ser.write(struct.pack('<BBQ', 0x23, 0x10, int(dummy_step)))
        self.ser.write(struct.pack('<BBH', 0x21, 0x20, int(dummy_pts)))
        self.ser.write(struct.pack('<BBH', 0x21, 0x22, 1))

        settle_s  = max(0.8, dummy_pts * 0.008)
        t_start   = time.time()
        n_sweeps  = 0
        while (time.time() - t_start) < seconds:
            self.ser.write(bytes([0x20, 0x30, 0x00]))
            time.sleep(settle_s)
            self.ser.write(struct.pack('<BBH', 0x18, 0x30, dummy_pts))
            self.ser.read(dummy_pts * 32)   # descartar
            n_sweeps += 1
            elapsed = time.time() - t_start
            remaining = max(0, seconds - elapsed)
            print(f"\r  ⏳ Warmup: {elapsed:.0f}/{seconds} s  "
                  f"({n_sweeps} sweeps)  restante: {remaining:.0f} s   ",
                  end="", flush=True)
        print(f"\r  ✅ Warmup completado ({n_sweeps} sweeps en {seconds} s){' '*20}")

    # ── Bloque individual ─────────────────────────────────────────────────────
    def _measure_block(self, start_hz, stop_hz, points, label="", warmup=True):
        """
        Realiza un sweep en el rango dado.
        Aplica SWEEP_AVG_COUNT repeticiones combinadas por media o mediana.
        Devuelve (s11, s21, freqs, native).
        """
        if points < 3:
            raise ValueError("points debe ser >= 3")

        step = (int(stop_hz) - int(start_hz)) // (int(points) - 1)

        # Configurar el VNA
        self.ser.write(struct.pack('<BBQ', 0x23, 0x00, int(start_hz)))
        self.ser.write(struct.pack('<BBQ', 0x23, 0x10, int(step)))
        self.ser.write(struct.pack('<BBH', 0x21, 0x20, int(points)))
        self.ser.write(struct.pack('<BBH', 0x21, 0x22, int(SAMPLES_PER_POINT)))

        settle_s = SWEEP_SETTLE_MS / 1000.0

        # Sweeps de calentamiento por bloque (absorbe inercia del PLL al saltar)
        if warmup:
            for _ in range(max(0, SEGMENT_WARMUP_SWEEPS)):
                self.ser.write(bytes([0x20, 0x30, 0x00]))
                time.sleep(settle_s)
                self.ser.write(struct.pack('<BBH', 0x18, 0x30, points))
                self.ser.read(points * 32)

        n_avg = max(1, SWEEP_AVG_COUNT)

        if n_avg == 1:
            # Camino rápido: un solo sweep
            self.ser.write(bytes([0x20, 0x30, 0x00]))
            time.sleep(settle_s)
            self.ser.write(struct.pack('<BBH', 0x18, 0x30, points))
            raw = self.ser.read(points * 32)
            if len(raw) != points * 32:
                raise RuntimeError(
                    f"Lectura incompleta: {len(raw)} B (esperado {points * 32}). "
                    f"Aumenta SWEEP_SETTLE_MS (actual={SWEEP_SETTLE_MS} ms) "
                    f"o SAMPLES_PER_POINT={SAMPLES_PER_POINT}."
                )
            s11, s21 = self._parse_fifo(raw, points)
        else:
            # Apilamiento múltiple → media o mediana
            s11_stack = np.zeros((n_avg, points), dtype=np.complex128)
            s21_stack = np.zeros_like(s11_stack)

            for k in range(n_avg):
                self.ser.write(bytes([0x20, 0x30, 0x00]))
                time.sleep(settle_s)
                self.ser.write(struct.pack('<BBH', 0x18, 0x30, points))
                raw = self.ser.read(points * 32)
                if len(raw) != points * 32:
                    raise RuntimeError(
                        f"Lectura incompleta en repetición {k+1}/{n_avg}: "
                        f"{len(raw)} B (esperado {points * 32}). "
                        f"Aumenta SWEEP_SETTLE_MS={SWEEP_SETTLE_MS} ms."
                    )
                s11_k, s21_k = self._parse_fifo(raw, points)
                s11_stack[k] = s11_k
                s21_stack[k] = s21_k

            # Combinación: mediana si está habilitada y hay suficientes muestras,
            # media aritmética en caso contrario.
            if USE_MEDIAN_STACK and n_avg >= 3:
                s11 = (np.median(s11_stack.real, axis=0)
                       + 1j * np.median(s11_stack.imag, axis=0))
                s21 = (np.median(s21_stack.real, axis=0)
                       + 1j * np.median(s21_stack.imag, axis=0))
            else:
                s11 = s11_stack.mean(axis=0)
                s21 = s21_stack.mean(axis=0)

        freqs = start_hz + step * np.arange(points, dtype=np.float64)

        if label:
            print(" hecho")

        return s11, s21, freqs, self.last_native

    # ── Sweep segmentado ──────────────────────────────────────────────────────
    def _measure_segmented(self, cal=None, label="",
                           start_hz=None, stop_hz=None):
        """
        Mide en segmentos y los concatena con corrección de continuidad.

        start_hz / stop_hz: permiten pasar un rango diferente al global,
        usado por _measure_interleaved para las pasadas con offset.
        """
        s_hz    = int(start_hz) if start_hz is not None else int(START_FREQ)
        e_hz    = int(stop_hz)  if stop_hz  is not None else int(STOP_FREQ)
        step_hz = int(round(SEGMENT_STEP_MHZ * 1e6))
        plan    = _build_segment_plan(s_hz, e_hz, step_hz, SEGMENT_MAX_POINTS)
        drop_n  = max(1, SEGMENT_DROP_HEAD)

        # Reiniciar estado de stitching para esta pasada
        self._last_seg_tail_s11  = None
        self._last_seg_tail_s21  = None
        self._last_seg_tail_freq = None

        s11_segs, s21_segs, freq_segs = [], [], []
        native_all = {}

        for idx, (seg_start, seg_stop, seg_pts) in enumerate(plan):
            seg_lbl = (f"{label} [{idx+1}/{len(plan)}]" if label
                       else f"Seg {idx+1}/{len(plan)}")
            if label:
                print(f"   ⏳ {seg_lbl}...", end="", flush=True)

            s11_i, s21_i, freq_i, nat_i = self._measure_block(
                seg_start, seg_stop, seg_pts, label="", warmup=True
            )

            # Acumular datos nativos (ADC)
            if nat_i is not None:
                if not native_all:
                    native_all = {k: [] for k in nat_i}
                slice_i = (nat_i if idx == 0
                           else {k: v[drop_n:] for k, v in nat_i.items()})
                for k in native_all:
                    native_all[k].append(slice_i[k])

            if idx == 0:
                self._last_seg_tail_s11  = s11_i[-drop_n:].copy() if drop_n > 0 else None
                self._last_seg_tail_s21  = s21_i[-drop_n:].copy() if drop_n > 0 else None
                self._last_seg_tail_freq = freq_i[-drop_n:].copy() if drop_n > 0 else None
                s11_segs.append(s11_i)
                s21_segs.append(s21_i)
                freq_segs.append(freq_i)
            else:
                # Corrección de continuidad en el punto de borde compartido
                if (SEGMENT_STITCH_CORRECT
                        and self._last_seg_tail_s11 is not None
                        and len(s11_i) > drop_n):
                    ref_s11  = self._last_seg_tail_s11[-1]
                    ref_s21  = self._last_seg_tail_s21[-1]
                    cur_s11  = s11_i[0]
                    cur_s21  = s21_i[0]
                    corr_s11 = _safe_complex_ratio(ref_s11, cur_s11)
                    corr_s21 = _safe_complex_ratio(ref_s21, cur_s21)
                    smooth_pts = min(SEGMENT_STITCH_SMOOTH_PTS + drop_n, len(s11_i))
                    for k in range(smooth_pts):
                        alpha     = 1.0 - (k / smooth_pts)
                        s11_i[k] *= 1.0 + (corr_s11 - 1.0) * alpha
                        s21_i[k] *= 1.0 + (corr_s21 - 1.0) * alpha

                self._last_seg_tail_s11  = s11_i[-drop_n:].copy() if drop_n > 0 else None
                self._last_seg_tail_s21  = s21_i[-drop_n:].copy() if drop_n > 0 else None

                s11_segs.append(s11_i[drop_n:])
                s21_segs.append(s21_i[drop_n:])
                freq_segs.append(freq_i[drop_n:])

            if label:
                print(" ✓")

        self.last_freqs  = np.concatenate(freq_segs)
        self.last_native = (
            {k: np.concatenate(v) for k, v in native_all.items()}
            if native_all else None
        )
        return np.concatenate(s11_segs), np.concatenate(s21_segs)

    # ── Sweep entrelazado ─────────────────────────────────────────────────────
    def _measure_interleaved(self, label=""):
        """
        Realiza N_INTERLEAVE pasadas segmentadas con offset de frecuencia
        sistemático y las fusiona en un único vector ordenado por frecuencia.

        Offset de la pasada i:  i × (SEGMENT_STEP_MHZ / N_INTERLEAVE) MHz

        Resolución efectiva:    SEGMENT_STEP_MHZ / N_INTERLEAVE MHz
        Puntos totales ≈        N_INTERLEAVE × puntos_segmentado

        No hay bordes de segmento entre pasadas porque cada pasada cubre
        frecuencias distintas; el stitch correction actúa sólo dentro de
        cada pasada individualmente.
        """
        if N_INTERLEAVE < 1:
            raise ValueError("N_INTERLEAVE debe ser >= 1")

        step_hz        = int(round(SEGMENT_STEP_MHZ * 1e6))
        offset_step_hz = step_hz // N_INTERLEAVE

        all_freq, all_s11, all_s21 = [], [], []
        native_all_passes = {}

        for i in range(N_INTERLEAVE):
            offset_hz = i * offset_step_hz
            f_start_i = int(START_FREQ) + offset_hz
            f_stop_i  = int(STOP_FREQ)  + offset_hz

            if label:
                print(f"   ⏳ Interleave {i+1}/{N_INTERLEAVE} "
                      f"(offset +{offset_hz/1e6:.1f} MHz)...", flush=True)

            s11_i, s21_i = self._measure_segmented(
                cal=None, label=(label if label else ""),
                start_hz=f_start_i, stop_hz=f_stop_i
            )
            freq_i = self.last_freqs.copy()

            all_freq.append(freq_i)
            all_s11.append(s11_i)
            all_s21.append(s21_i)

            # Acumular nativo
            if self.last_native is not None:
                if not native_all_passes:
                    native_all_passes = {k: [] for k in self.last_native}
                for k in native_all_passes:
                    if k in self.last_native:
                        native_all_passes[k].append(self.last_native[k])

        # Fusionar y ordenar por frecuencia
        freqs = np.concatenate(all_freq)
        s11   = np.concatenate(all_s11)
        s21   = np.concatenate(all_s21)
        idx   = np.argsort(freqs, kind='stable')
        freqs, s11, s21 = freqs[idx], s11[idx], s21[idx]

        # Recortar al rango [START_FREQ, STOP_FREQ] exacto
        mask = (freqs >= START_FREQ) & (freqs <= STOP_FREQ)

        self.last_freqs  = freqs[mask]
        self.last_native = (
            {k: np.concatenate(v)[idx][mask]
             for k, v in native_all_passes.items()}
            if native_all_passes else None
        )
        return s11[mask], s21[mask]

    # ── Punto de entrada público ──────────────────────────────────────────────
    def measure(self, points=None, label="", cal=None):
        """
        Realiza la medición según SWEEP_MODE activo.
        Devuelve (s11_raw, s21_raw). Guarda freqs en self.last_freqs.
        """
        mode = SWEEP_MODE.lower()

        if mode == "segmented":
            return self._measure_segmented(cal=cal, label=label)

        if mode == "interleaved":
            return self._measure_interleaved(label=label)

        # Modo "full"
        pts = points if points is not None else POINTS
        s11, s21, freqs, _ = self._measure_block(
            START_FREQ, STOP_FREQ, pts, label)
        self.last_freqs = freqs
        return s11, s21

    # ── Parser FIFO ───────────────────────────────────────────────────────────
    def _parse_fifo(self, raw, points):
        """
        Desempaqueta el FIFO de 32 bytes por punto del NanoVNA V2.

        Formato por punto (32 bytes, little-endian):
          offset  0–7  : forward channel  (re, im) — s32
          offset  8–15 : reflect channel  (re, im) — s32  → S11
          offset 16–23 : through channel  (re, im) — s32  → S21
          offset 24–31 : reservados
        """
        s11 = np.zeros(points, dtype=np.complex128)
        s21 = np.zeros(points, dtype=np.complex128)

        fwd_re  = np.zeros(points, np.int32);  fwd_im  = np.zeros(points, np.int32)
        refl_re = np.zeros(points, np.int32);  refl_im = np.zeros(points, np.int32)
        thru_re = np.zeros(points, np.int32);  thru_im = np.zeros(points, np.int32)
        res0    = np.zeros(points, np.uint32); res1    = np.zeros(points, np.uint32)

        for i in range(points):
            chunk = raw[i*32:(i+1)*32]
            if len(chunk) < 32:
                continue
            _fr, _fi = struct.unpack_from('<ii', chunk, 0)
            _rr, _ri = struct.unpack_from('<ii', chunk, 8)
            _tr, _ti = struct.unpack_from('<ii', chunk, 16)
            _r0, _r1 = struct.unpack_from('<II', chunk, 24)
            fwd_re[i],  fwd_im[i]  = _fr, _fi
            refl_re[i], refl_im[i] = _rr, _ri
            thru_re[i], thru_im[i] = _tr, _ti
            res0[i],    res1[i]    = _r0, _r1
            a1 = complex(_fr, _fi)
            if abs(a1) > EPS:
                s11[i] = complex(_rr, _ri) / a1
                s21[i] = complex(_tr, _ti) / a1

        self.last_native = {
            "fwd_re_i32":  fwd_re,  "fwd_im_i32":  fwd_im,
            "refl_re_i32": refl_re, "refl_im_i32": refl_im,
            "thru_re_i32": thru_re, "thru_im_i32": thru_im,
            "res0_u32":    res0,    "res1_u32":    res1,
        }
        return s11, s21


def _safe_complex_ratio(a, b):
    """Divide a/b de forma segura; retorna 1+0j si b≈0."""
    if abs(b) < 1e-15:
        return complex(1.0, 0.0)
    return a / b


# ══════════════════════════════════════════════════════════════════════════════
#  Calibración SOLT
# ══════════════════════════════════════════════════════════════════════════════

class Calibration:
    """
    Calibración SOLT 1-puerto (S11) + corrección de S21 relativa al THRU.

    S11 — modelo OSL de 3 términos:
        S11_cal = (Sm - e00) / (e10e01 + e11·(Sm - e00))

    S21 — normalización por magnitud y fase del THRU medido:
        S21_cal_mag   = |S21_raw| / |thru|
        S21_cal_phase = ∠S21_raw - ∠thru

    Compatibilidad de calibración:
    ─────────────────────────────
    La calibración es válida únicamente para la combinación exacta de
    parámetros con la que fue capturada.  Al cargar un perfil, se valida:
      • modo de sweep
      • rango de frecuencia (START_FREQ, STOP_FREQ)
      • paso de segmento (segmented y interleaved)
      • número de pasadas entrelazadas (interleaved)
      • longitud total del vector (control de integridad)
    Cualquier discrepancia lanza RuntimeError y dispara una nueva calibración.
    """

    def __init__(self):
        self.e00 = self.e11 = self.e10e01 = None
        self.thru_ref = self.thru_mag = self.thru_phase = None
        self.meta = {}

    def is_ready(self):
        return all(v is not None for v in (
            self.e00, self.e11, self.e10e01,
            self.thru_ref, self.thru_mag, self.thru_phase
        ))

    def solve(self, Mo, Ms, Ml, Mt=None):
        """Mo=OPEN, Ms=SHORT, Ml=LOAD, Mt=THRU (S21 raw, opcional)."""
        Mo = _as_1d_complex(Mo, "Mo"); Ms = _as_1d_complex(Ms, "Ms")
        Ml = _as_1d_complex(Ml, "Ml")
        if Mt is not None:
            Mt = _as_1d_complex(Mt, "Mt")
        n  = len(Mo)
        if Mt is not None:
            if not (len(Ms) == len(Ml) == len(Mt) == n):
                raise ValueError("Vectores de calibración con longitudes distintas")
        elif not (len(Ms) == len(Ml) == n):
            raise ValueError("Vectores de calibración con longitudes distintas")

        self.e00    = Ml.copy()
        denom       = np.where(np.abs(Mo - Ms) < 1e-10, (1e-10 + 0j), Mo - Ms)
        self.e11    = (Mo + Ms - 2 * Ml) / denom
        self.e10e01 = (2 * (Mo - Ml) * (Ml - Ms)) / denom

        if Mt is not None:
            self.thru_ref = Mt.copy()
        elif self.thru_ref is not None and len(self.thru_ref) == n:
            # Reusar THRU previo para ignorar su recalibración.
            self.thru_ref = self.thru_ref.copy()
        else:
            # Fallback neutro: no corrige S21 (magnitud=1, fase=0).
            self.thru_ref = np.ones(n, dtype=np.complex128)

        self.thru_mag   = np.abs(self.thru_ref)
        self.thru_phase = np.angle(self.thru_ref)

        mode = SWEEP_MODE.lower()
        self.meta = {
            # Identidad del perfil
            "profile_name":        _active_profile_name(),
            "mode":                mode,
            # Rango
            "start_hz":            START_FREQ,
            "stop_hz":             STOP_FREQ,
            # Parámetros de resolución (según modo)
            "points_full":         POINTS,
            "segment_step_mhz":    SEGMENT_STEP_MHZ,
            "segment_max_points":  SEGMENT_MAX_POINTS,
            "segment_drop_head":   SEGMENT_DROP_HEAD,
            "n_interleave":        N_INTERLEAVE,
            # Longitud real (control de integridad)
            "total_points":        n,
            # Parámetros informativos (no afectan compatibilidad)
            "samples_per_point":   SAMPLES_PER_POINT,
            "sweep_avg_count":     SWEEP_AVG_COUNT,
            "use_median_stack":    USE_MEDIAN_STACK,
            "tdr_window":          TDR_WINDOW,
            "tdr_zero_pad_factor": TDR_ZERO_PAD_FACTOR,
            "vf":                  VF,
            "cal_timestamp":       datetime.now().isoformat(),
            "thru_recalibrated":   Mt is not None,
        }

    def apply(self, s11_raw, s21_raw):
        """
        Aplica corrección. Retorna (s11_cal, s21_cal, il_db, s21_phase_rad).
        """
        if not self.is_ready():
            raise RuntimeError("Calibración no inicializada")
        s11_raw = _as_1d_complex(s11_raw, "s11_raw")
        s21_raw = _as_1d_complex(s21_raw, "s21_raw")
        if len(s11_raw) != len(self.e00) or len(s21_raw) != len(self.thru_ref):
            raise ValueError(
                f"Longitud de medición ({len(s11_raw)}) ≠ calibración "
                f"({len(self.e00)}). ¿Cambió la configuración de sweep?"
            )

        d      = self.e10e01 + self.e11 * (s11_raw - self.e00)
        safe_d = np.where(np.abs(d) < 1e-15, (1e-15 + 0j), d)
        s11_c  = (s11_raw - self.e00) / safe_d

        safe_mag      = np.where(self.thru_mag < 1e-10, 1e-10, self.thru_mag)
        s21_mag_cal   = np.abs(s21_raw) / safe_mag
        s21_phase_cal = np.angle(s21_raw) - self.thru_phase
        s21_c         = s21_mag_cal * np.exp(1j * s21_phase_cal)

        il_db = -20 * np.log10(np.clip(s21_mag_cal, 1e-12, None))
        return s11_c, s21_c, il_db, s21_phase_cal

    def save(self, cal_file=None):
        cal_file = Path(cal_file) if cal_file is not None else _active_cal_file()
        data = {
            "e00_re":  self.e00.real.tolist(),     "e00_im":  self.e00.imag.tolist(),
            "e11_re":  self.e11.real.tolist(),     "e11_im":  self.e11.imag.tolist(),
            "e10_re":  self.e10e01.real.tolist(),  "e10_im":  self.e10e01.imag.tolist(),
            "thru_re": self.thru_ref.real.tolist(),"thru_im": self.thru_ref.imag.tolist(),
            "meta":    self.meta,
        }
        with open(cal_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"💾 Calibración guardada → {cal_file}")

    def load(self, cal_file=None):
        cal_file = Path(cal_file) if cal_file is not None else _active_cal_file()
        with open(cal_file, 'r') as f:
            d = json.load(f)

        c = lambda re, im: (
            np.array(d[re], dtype=np.float64) + 1j * np.array(d[im], dtype=np.float64)
        )
        self.e00      = c("e00_re",  "e00_im")
        self.e11      = c("e11_re",  "e11_im")
        self.e10e01   = c("e10_re",  "e10_im")
        self.thru_ref = c("thru_re", "thru_im")
        self.thru_mag   = np.abs(self.thru_ref)
        self.thru_phase = np.angle(self.thru_ref)
        self.meta = d.get("meta", {})
        self._validate_compatibility()

        ts = datetime.fromtimestamp(cal_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"✅ Calibración cargada  perfil={_active_profile_name()}  ({ts})")

    def _validate_compatibility(self):
        """
        Valida que la calibración cargada sea compatible con la configuración actual.
        Lanza RuntimeError con mensaje descriptivo si hay incompatibilidad.
        """
        m    = self.meta
        mode = SWEEP_MODE.lower()

        if not m:
            return  # calibración legacy sin meta → aceptar con advertencia

        # ── 1. Modo de sweep ──────────────────────────────────────────────────
        saved_mode = m.get("mode", mode)
        if saved_mode != mode:
            raise RuntimeError(
                f"Modo de calibración '{saved_mode}' ≠ modo actual '{mode}'.\n"
                f"  → Recalibre en modo '{mode}' o cambie SWEEP_MODE a '{saved_mode}'."
            )

        # ── 2. Rango de frecuencia ────────────────────────────────────────────
        if m.get("start_hz") is not None and m["start_hz"] != START_FREQ:
            raise RuntimeError(
                f"Inicio de frecuencia de calibración "
                f"{m['start_hz']/1e6:.0f} MHz ≠ actual {START_FREQ/1e6:.0f} MHz."
            )
        if m.get("stop_hz") is not None and m["stop_hz"] != STOP_FREQ:
            raise RuntimeError(
                f"Fin de frecuencia de calibración "
                f"{m['stop_hz']/1e6:.0f} MHz ≠ actual {STOP_FREQ/1e6:.0f} MHz."
            )

        # ── 3. Parámetros específicos del modo ────────────────────────────────
        if mode == "full":
            saved_pts = m.get("points_full")
            if saved_pts is not None and saved_pts != POINTS:
                raise RuntimeError(
                    f"Calibración tiene {saved_pts} pts (full) ≠ actual {POINTS} pts."
                )

        elif mode in ("segmented", "interleaved"):
            saved_step = m.get("segment_step_mhz")
            if saved_step is not None and abs(saved_step - SEGMENT_STEP_MHZ) > 0.01:
                raise RuntimeError(
                    f"Paso de segmento de calibración {saved_step} MHz "
                    f"≠ actual {SEGMENT_STEP_MHZ} MHz."
                )
            saved_max = m.get("segment_max_points")
            if saved_max is not None and saved_max != SEGMENT_MAX_POINTS:
                raise RuntimeError(
                    f"Max puntos/segmento de calibración {saved_max} "
                    f"≠ actual {SEGMENT_MAX_POINTS}."
                )

            if mode == "interleaved":
                saved_n = m.get("n_interleave")
                if saved_n is not None and saved_n != N_INTERLEAVE:
                    raise RuntimeError(
                        f"N_INTERLEAVE de calibración {saved_n} "
                        f"≠ actual {N_INTERLEAVE}.\n"
                        f"  → Recalibre con N_INTERLEAVE={N_INTERLEAVE}."
                    )

        # ── 4. Integridad: longitud del vector ────────────────────────────────
        expected = _expected_total_points()
        actual   = len(self.e00)
        if actual != expected:
            # Intentar usar el total guardado como referencia secundaria
            stored_n = m.get("total_points")
            if stored_n is not None and actual != stored_n:
                raise RuntimeError(
                    f"Calibración tiene {actual} puntos; se esperan {expected} "
                    f"(guardado: {stored_n}). La configuración cambió. Recalibre."
                )
            elif stored_n is None:
                raise RuntimeError(
                    f"Calibración tiene {actual} puntos; se esperan {expected}. "
                    f"Recalibre."
                )
            # Si actual == stored_n pero ≠ expected → warning, no error
            print(f"  ⚠️  Longitud esperada calculada ({expected}) difiere de la "
                  f"guardada ({actual}). Se acepta la guardada.")


# ══════════════════════════════════════════════════════════════════════════════
#
#  ██████╗ █████╗ ██╗      ██████╗██╗   ██╗██╗      ██████╗ ███████╗
# ██╔════╝██╔══██╗██║     ██╔════╝██║   ██║██║     ██╔═══██╗██╔════╝
# ██║     ███████║██║     ██║     ██║   ██║██║     ██║   ██║███████╗
# ██║     ██╔══██║██║     ██║     ██║   ██║██║     ██║   ██║╚════██║
# ╚██████╗██║  ██║███████╗╚██████╗╚██████╔╝███████╗╚██████╔╝███████║
#  ╚═════╝╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═════╝ ╚══════╝ ╚═════╝ ╚══════╝
#
#  ZONA DE CÁLCULO — edita aquí las fórmulas y umbrales de clasificación.
#
# ══════════════════════════════════════════════════════════════════════════════

# Mapa de ventanas TDR disponibles
_TDR_WINDOWS = {
    "blackman": np.blackman,
    "hanning":  np.hanning,
    "hamming":  np.hamming,
    "bartlett": np.bartlett,
    "none":     lambda n: np.ones(n),
}


def _contiguous_regions(mask):
    """Devuelve pares (inicio, fin_exclusivo) de regiones True contiguas."""
    m = np.asarray(mask, dtype=bool).reshape(-1)
    if m.size == 0:
        return []
    x = m.astype(np.int8)
    d = np.diff(np.pad(x, (1, 1), mode='constant'))
    starts = np.where(d == 1)[0]
    ends   = np.where(d == -1)[0]
    return list(zip(starts, ends))


def _format_freq_ranges_mhz(freqs_hz, mask, min_points=1):
    """
    Compacta puntos en rangos de frecuencia, útil para reportar fallas.
    Formato: "fini-ffin MHz (Npts); ..."
    """
    f = _as_1d_float(freqs_hz, "freqs_hz")
    m = np.asarray(mask, dtype=bool).reshape(-1)
    if len(m) != len(f) or len(f) == 0:
        return ""

    pieces = []
    for s, e in _contiguous_regions(m):
        npts = e - s
        if npts < int(min_points):
            continue
        f0 = f[s] / 1e6
        f1 = f[e - 1] / 1e6
        if npts == 1:
            pieces.append(f"{f0:.1f} MHz")
        else:
            pieces.append(f"{f0:.1f}-{f1:.1f} MHz ({npts} pts)")
    return "; ".join(pieces)


def _format_top_fault_freqs(freqs_hz, score, mask, top_n=12):
    """Lista compacta de frecuencias más severas según score combinado."""
    f = _as_1d_float(freqs_hz, "freqs_hz")
    s = _as_1d_float(score, "score")
    m = np.asarray(mask, dtype=bool).reshape(-1)
    if not (len(f) == len(s) == len(m)):
        return ""

    idx = np.where(m)[0]
    if idx.size == 0:
        return ""

    rank = idx[np.argsort(s[idx])[::-1]]
    top = rank[:max(1, int(top_n))]
    return "; ".join(f"{f[i]/1e6:.1f}" for i in top)


def _characterize_cable(freqs_hz, rl_db, vswr, il_db, z_re, z_im,
                        instr_mask, vf=0.70):
    """
    Caracterización autónoma del cable a partir de los datos calibrados.
    Produce métricas interpretables sin necesidad de los gráficos.

    Devuelve un dict con:
      length_resonance_m  — longitud estimada por espaciado de resonancias RL
      z_char_ohm          — impedancia característica real (mediana Z_re válida)
      z_iqr               — IQR de Z_re (indicador de uniformidad)
      z_std               — desviación estándar de Z_re
      refl_pct_p50/p90/max — reflexión de potencia en percentiles
      il_per_band         — dict banda → IL avg (perfil de pérdidas)
      il_slope_db_per_ghz — tendencia lineal de IL vs frecuencia
      resonance_period_mhz — período de oscilación dominante de RL
    """
    C   = 3e8
    mhz = freqs_hz / 1e6
    valid = instr_mask & np.isfinite(rl_db)

    # ── Longitud por resonancias de RL ────────────────────────────────────────
    length_res_m       = 0.0
    resonance_period   = 0.0
    if valid.sum() >= 6:
        from scipy.ndimage import uniform_filter1d
        fv  = mhz[valid]; rv = rl_db[valid]
        sm  = uniform_filter1d(rv, size=max(3, len(rv)//20))
        dips = [fv[i] for i in range(1, len(sm)-1)
                if sm[i] < sm[i-1] and sm[i] < sm[i+1]]
        if len(dips) >= 3:
            spacings       = np.diff(dips)
            resonance_period = float(np.median(spacings))
            length_res_m   = C * vf / (2 * resonance_period * 1e6)

    # ── Impedancia característica ─────────────────────────────────────────────
    zv = z_re[valid & np.isfinite(z_re)]
    z_char   = float(np.median(zv))      if len(zv) > 0 else 0.0
    z_iqr    = float(np.subtract(*np.percentile(zv, [75, 25]))) if len(zv) > 0 else 0.0
    z_std_v  = float(np.std(zv))         if len(zv) > 0 else 0.0

    # ── Reflexión de potencia en percentiles ──────────────────────────────────
    rl_v    = rl_db[valid]
    refl_pct = 10**(-rl_v/10) * 100
    r_p50  = float(np.percentile(refl_pct, 50))
    r_p90  = float(np.percentile(refl_pct, 90))
    r_max  = float(np.max(refl_pct))

    # ── Pérdidas por banda (IL) ───────────────────────────────────────────────
    BANDS = [
        ("VHF 100–500 MHz",   100,   500),
        ("UHF 500–1000 MHz",  500,  1000),
        ("L   1.0–2.0 GHz",  1000,  2000),
        ("S   2.0–3.0 GHz",  2000,  3000),
        ("C   3.0–4.4 GHz",  3000,  4400),
    ]
    il_per_band = {}
    band_centers = []
    band_il_avgs = []
    for label, flo, fhi in BANDS:
        bm = valid & np.isfinite(il_db) & (mhz >= flo) & (mhz <= fhi)
        if bm.sum() >= 2:
            avg = float(np.mean(il_db[bm]))
            il_per_band[label] = round(avg, 3)
            band_centers.append((flo + fhi) / 2)
            band_il_avgs.append(avg)
        else:
            il_per_band[label] = None

    # Tendencia de IL (regresión lineal simple sobre centros de banda)
    il_slope = 0.0
    if len(band_centers) >= 3:
        xs = np.array(band_centers) / 1000  # GHz
        ys = np.array(band_il_avgs)
        coeffs = np.polyfit(xs, ys, 1)
        il_slope = float(coeffs[0])         # dB/GHz

    return {
        "length_resonance_m":   round(length_res_m, 4),
        "resonance_period_mhz": round(resonance_period, 1),
        "z_char_ohm":           round(z_char, 2),
        "z_iqr_ohm":            round(z_iqr,  2),
        "z_std_ohm":            round(z_std_v, 2),
        "refl_pct_p50":         round(r_p50,   3),
        "refl_pct_p90":         round(r_p90,   3),
        "refl_pct_max":         round(r_max,   3),
        "il_per_band":          il_per_band,
        "il_slope_db_per_ghz":  round(il_slope, 4),
    }


def _detect_frequency_faults(freqs, rl_db, vswr, il_db, z_mag,
                             instr_mask=None):
    """
    Detecta frecuencias problemáticas combinando métricas críticas.
    Devuelve máscara booleana, score de severidad y métricas de resumen.

    instr_mask : bool array (True = punto confiable). Los puntos en zonas
                 instrumentales se fuerzan a valores "perfectos" antes de
                 evaluar fallas, de modo que no contaminen el conteo de
                 fallas reales del cable. Los datos originales no se tocan.
    """
    th = THRESHOLDS

    if instr_mask is not None and INSTRUMENT_MASK_ENABLE:
        rl_eval   = np.where(instr_mask, rl_db,  th["rl_min_warn_db"] + 1.0)
        vswr_eval = np.where(instr_mask, vswr,   1.0)
        il_eval   = np.where(instr_mask, il_db,  0.0)
        z_eval    = np.where(instr_mask, z_mag,  th["z_nom_ohm"])
    else:
        rl_eval, vswr_eval, il_eval, z_eval = rl_db, vswr, il_db, z_mag

    freq_mask_rl   = rl_eval < th["rl_min_warn_db"]
    freq_mask_vswr = vswr_eval > th["vswr_max_warn"]
    freq_mask_il   = il_eval > th["il_max_warn_db"]
    freq_mask_z    = np.abs(z_eval - th["z_nom_ohm"]) > th["z_tol_warn_ohm"]

    # Score aditivo normalizado para priorizar frecuencias más críticas.
    score = (
        np.maximum(0.0, (th["rl_min_warn_db"] - rl_eval) / max(th["rl_min_warn_db"], EPS))
        + np.maximum(0.0, (vswr_eval - th["vswr_max_warn"]) / max(th["vswr_max_warn"], EPS))
        + np.maximum(0.0, (il_eval - th["il_max_warn_db"]) / max(th["il_max_warn_db"], EPS))
        + np.maximum(
            0.0,
            (np.abs(z_eval - th["z_nom_ohm"]) - th["z_tol_warn_ohm"])
            / max(th["z_tol_warn_ohm"], EPS),
        )
    )

    fault_mask = freq_mask_rl | freq_mask_vswr | freq_mask_il | freq_mask_z
    ranges_txt = _format_freq_ranges_mhz(freqs, fault_mask, min_points=1)
    top_txt    = _format_top_fault_freqs(freqs, score, fault_mask, top_n=12)

    reason_counts = {
        "rl_warn_pts":   int(np.count_nonzero(freq_mask_rl)),
        "vswr_warn_pts": int(np.count_nonzero(freq_mask_vswr)),
        "il_warn_pts":   int(np.count_nonzero(freq_mask_il)),
        "z_warn_pts":    int(np.count_nonzero(freq_mask_z)),
    }

    # Tabla detallada por punto para exportación y comparación entre cables.
    details = []
    idx_fault = np.where(fault_mask)[0]
    for i in idx_fault:
        reasons = []
        if freq_mask_rl[i]:
            reasons.append("RL")
        if freq_mask_vswr[i]:
            reasons.append("VSWR")
        if freq_mask_il[i]:
            reasons.append("IL")
        if freq_mask_z[i]:
            reasons.append("Z")
        details.append({
            "idx": int(i),
            "freq_hz": float(freqs[i]),
            "freq_mhz": float(freqs[i] / 1e6),
            "reasons": "+".join(reasons),
            "score": float(score[i]),
            "rl_db": float(rl_db[i]),
            "vswr": float(vswr[i]),
            "il_db": float(il_db[i]),
            "z_mag_ohm": float(z_mag[i]),
        })

    return {
        "mask": fault_mask,
        "score": score,
        "ranges_txt": ranges_txt,
        "top_txt": top_txt,
        "reason_counts": reason_counts,
        "details": details,
    }


def compute_all_metrics(s11_c, s21_c, il_db, s21_phase, freqs, vf,
                        s11_raw=None, s21_raw=None, boundary_indices=None):
    """
    Calcula todas las métricas derivadas a partir de los parámetros S calibrados.

    TDR: usa la ventana y el zero-padding definidos en TDR_WINDOW y
         TDR_ZERO_PAD_FACTOR del bloque de configuración.

    boundary_indices: lista de índices de bordes de segmento para enmascarar
                      el group delay y las líneas verticales del gráfico.
    """
    s11_c     = _as_1d_complex(s11_c,   "s11_c")
    s21_c     = _as_1d_complex(s21_c,   "s21_c")
    il_db     = _as_1d_float(il_db,     "il_db")
    s21_phase = _as_1d_float(s21_phase, "s21_phase")
    freqs     = _as_1d_float(freqs,     "freqs")
    n = len(freqs)

    if not (len(s11_c) == len(s21_c) == len(il_db) == len(s21_phase) == n):
        raise ValueError("Todos los vectores deben tener igual longitud")
    if np.any(np.diff(freqs) <= 0):
        raise ValueError("freqs debe ser estrictamente creciente")

    Z0 = 50.0

    # ── S11 derivados ─────────────────────────────────────────────────────────
    s11_mag       = np.clip(np.abs(s11_c), 0, 0.9999)
    rl_db         = -20 * np.log10(s11_mag + 1e-12)
    vswr          = (1 + s11_mag) / np.clip(1 - s11_mag, 1e-6, None)
    s11_phase_deg = np.angle(s11_c, deg=True)

    one_minus = np.where(np.abs(1 - s11_c) < 1e-9, (1e-9 + 0j), 1 - s11_c)
    z_c    = Z0 * (1 + s11_c) / one_minus
    z_real = z_c.real
    z_imag = z_c.imag
    z_mag  = np.abs(z_c)

    power_refl_pct = s11_mag ** 2 * 100

    # ── Fallas por frecuencia ────────────────────────────────────────────────
    # Anotaciones instrumentales (etiquetas, no filtros de datos)
    zone_names, zone_confs = annotate_instrument_zones(freqs / 1e6)
    instr_mask = build_instrument_mask(freqs / 1e6)
    freq_faults = _detect_frequency_faults(freqs, rl_db, vswr, il_db, z_mag,
                                           instr_mask=instr_mask)

    # ── TDR ───────────────────────────────────────────────────────────────────
    # Interpolar a rejilla uniforme si el vector no lo es
    # (ocurre en modo interleaved si los offsets no son exactamente divisores)
    df = np.diff(freqs)
    if not np.allclose(df, df[0], rtol=1e-3, atol=1.0):
        f_u   = np.linspace(freqs[0], freqs[-1], n)
        s11_u = (np.interp(f_u, freqs, s11_c.real)
                 + 1j * np.interp(f_u, freqs, s11_c.imag))
    else:
        f_u   = freqs
        s11_u = s11_c

    bw = freqs[-1] - freqs[0]

    # Ventana TDR configurable
    win_key    = TDR_WINDOW.lower() if isinstance(TDR_WINDOW, str) else "blackman"
    window_fn  = _TDR_WINDOWS.get(win_key, np.blackman)
    window     = window_fn(n)

    zpad       = max(1, int(TDR_ZERO_PAD_FACTOR))
    n_fft      = zpad * n
    s11_pad    = np.zeros(n_fft, dtype=np.complex128)
    s11_pad[:n] = s11_u * window

    tdr_complex = np.fft.ifft(s11_pad)
    tdr         = np.abs(tdr_complex)

    # Resolución temporal: dist_step depende del ancho de banda y del zpad
    dist_step_zp = (3e8 * vf) / (2 * bw * zpad)
    dist_axis    = np.arange(n_fft) * dist_step_zp

    # Pico principal (longitud del cable)
    half = n_fft // 2
    # Distancia mínima de búsqueda: omite el transitorio del conector si está activo
    if TDR_SUPPRESS_CONNECTOR and TDR_MIN_CABLE_LEN_M > 0:
        skip = max(2, int(TDR_MIN_CABLE_LEN_M / dist_step_zp))
    else:
        skip = max(2, int(0.0 / dist_step_zp))
    tdr_search       = tdr[skip:half]
    primary_peak_idx = int(np.argmax(tdr_search) + skip)
    cable_length_m   = max(0.0, dist_axis[primary_peak_idx])

    # Fallas secundarias
    threshold_faults = 0.3 * tdr[primary_peak_idx]
    fault_peaks_idx, _ = find_peaks(
        tdr[skip:half],
        height=threshold_faults,
        distance=max(3, int(0.05 / dist_step_zp)),
        prominence=threshold_faults * 0.5,
    )
    fault_peaks_idx = fault_peaks_idx + skip
    fault_peaks_idx = [i for i in fault_peaks_idx if i != primary_peak_idx]
    faults = [(dist_axis[i], float(tdr[i])) for i in fault_peaks_idx]

    # ── Retardo de grupo → longitud eléctrica ─────────────────────────────────
    #
    #   La fase de S21 se desenvuelve con continuidad global entre segmentos
    #   usando _stitch_phase. El offset de cada hueco es exactamente k×2π
    #   (k entero) calculado por predicción de pendiente — sin valores
    #   sintéticos intermedios.
    #
    #   group_delay_ns      → medición honesta; NaN en zonas instrumentales.
    #   group_delay_ns_plot → interpolación de NaN, exclusiva para el gráfico.
    #
    s21_phase_unwrap = _stitch_phase(s21_phase, instr_mask)

    if n > 10:
        phase_filled  = np.where(np.isfinite(s21_phase_unwrap),
                                 s21_phase_unwrap, 0.0)
        dphi_df       = np.gradient(phase_filled, freqs)
        group_delay_s = -dphi_df / (2 * np.pi)

        # Repropagar NaN de zonas instrumentales
        group_delay_s = np.where(np.isfinite(s21_phase_unwrap),
                                 group_delay_s, np.nan)

        # NaN adicionales en bordes de segmento
        if boundary_indices:
            for b in boundary_indices:
                lo = max(0, b - 2); hi = min(n, b + 3)
                group_delay_s[lo:hi] = np.nan

        group_delay_ns      = group_delay_s * 1e9
        group_delay_ns_plot = _interpolate_for_plot(freqs / 1e6,
                                                    group_delay_ns)

        # Longitud eléctrica: mediana del GD en puntos válidos y positivos.
        # Con la fase global continua el GD ya no tiene saltos artificiales.
        gd_valid = group_delay_s[np.isfinite(group_delay_s) & instr_mask]
        gd_pos   = gd_valid[gd_valid > 0]
        elec_length_m = (float(np.median(gd_pos) * 3e8 * vf)
                         if len(gd_pos) > 0 else 0.0)
        elec_length_m = max(0.0, elec_length_m)
    else:
        group_delay_ns      = np.full(n, np.nan)
        group_delay_ns_plot = np.zeros(n)
        elec_length_m       = 0.0

    # ── Desglose por banda ────────────────────────────────────────────────────
    band_stats = {}
    for band_name, (f_lo, f_hi) in BANDS.items():
        mask = (freqs >= f_lo) & (freqs <= f_hi)
        if mask.sum() == 0:
            continue
        band_stats[band_name] = {
            "avg_rl_db": round(float(np.mean(rl_db[mask])), 2),
            "avg_vswr":  round(float(np.mean(vswr[mask])),  3),
            "avg_il_db": round(float(np.mean(il_db[mask])), 2),
            "avg_z_mag": round(float(np.mean(z_mag[mask])), 2),
            "min_rl_db": round(float(np.min(rl_db[mask])),  2),
            "max_vswr":  round(float(np.max(vswr[mask])),   3),
        }

    # ── Detección de anomalías (informativa, sin veredicto) ───────────────────
    anomaly_warnings = _check_anomalies(rl_db, vswr, il_db, z_mag, s11_mag,
                                        instr_mask=instr_mask)

    # Helpers para stats con y sin máscara
    def _masked_mean(arr):
        v = arr[instr_mask] if INSTRUMENT_MASK_ENABLE and instr_mask.any() else arr
        return float(np.mean(v)) if len(v) > 0 else float(np.mean(arr))

    def _masked_min(arr):
        v = arr[instr_mask] if INSTRUMENT_MASK_ENABLE and instr_mask.any() else arr
        return float(np.min(v)) if len(v) > 0 else float(np.min(arr))

    def _masked_max(arr):
        v = arr[instr_mask] if INSTRUMENT_MASK_ENABLE and instr_mask.any() else arr
        return float(np.max(v)) if len(v) > 0 else float(np.max(arr))

    # ── Resumen ───────────────────────────────────────────────────────────────
    summary = {
        "cable_length_m":      round(cable_length_m,              3),
        "elec_length_m":       round(elec_length_m,               3),
        "avg_rl_db":           round(_masked_mean(rl_db),         2),
        "min_rl_db":           round(_masked_min(rl_db),          2),
        "avg_vswr":            round(_masked_mean(vswr),          3),
        "max_vswr":            round(_masked_max(vswr),           3),
        "avg_z_mag_ohm":       round(_masked_mean(z_mag),         2),
        "avg_z_real_ohm":      round(_masked_mean(z_real),        2),
        "avg_il_db":           round(_masked_mean(il_db),         2),
        "max_il_db":           round(_masked_max(il_db),          2),
        "avg_power_refl_pct":  round(_masked_mean(power_refl_pct),2),
        "num_fault_freq_points":    int(np.count_nonzero(freq_faults["mask"])),
        "fault_freq_ranges_mhz":   freq_faults["ranges_txt"],
        "fault_freqs_top_mhz":     freq_faults["top_txt"],
        "fault_freq_reason_counts": (
            f"RL={freq_faults['reason_counts']['rl_warn_pts']};"
            f"VSWR={freq_faults['reason_counts']['vswr_warn_pts']};"
            f"IL={freq_faults['reason_counts']['il_warn_pts']};"
            f"Z={freq_faults['reason_counts']['z_warn_pts']}"
        ),
        "num_instrument_pts":      int(np.count_nonzero(~instr_mask)),
        "anomaly_warnings":        anomaly_warnings,
        "num_anomalies":           len(anomaly_warnings),
        "num_faults_detected":     len(faults),
        "fault_positions_m":       ";".join(f"{dist:.2f}" for dist, _ in faults),
        "band_stats":              band_stats,
        "cable_char":              _characterize_cable(
            freqs, rl_db, vswr, il_db, z_real, z_imag, instr_mask, vf=vf
        ),
    }
    # Interpretación textual — generada después de cable_char
    summary["interpretation"] = _generate_interpretation(summary)

    # ── Arrays por punto ──────────────────────────────────────────────────────
    arrays = {
        "s11_real":          s11_c.real,
        "s11_imag":          s11_c.imag,
        "s11_mag":           np.abs(s11_c),
        "s11_phase_deg":     s11_phase_deg,
        "return_loss_db":    rl_db,
        "vswr":              vswr,
        "z_real_ohm":        z_real,
        "z_imag_ohm":        z_imag,
        "z_mag_ohm":         z_mag,
        "power_refl_pct":    power_refl_pct,
        "s21_mag":           np.abs(s21_c),
        "s21_phase_deg":     np.angle(s21_c, deg=True),
        "insertion_loss_db": il_db,
        "group_delay_ns":    group_delay_ns,
        "freq_fault_mask":        freq_faults["mask"],
        "freq_fault_score":       freq_faults["score"],
        "instrument_zone":        zone_names,
        "instrument_confidence":  zone_confs,
        "group_delay_ns_plot":    group_delay_ns_plot,
        "tdr_dist_m":             dist_axis,
        "tdr_magnitude":          tdr,
    }

    def _fill_raw(raw_arr, name, size):
        if raw_arr is not None:
            a = _as_1d_complex(np.asarray(raw_arr), name)
            return a.real, a.imag, np.abs(a), np.angle(a, deg=True)
        return (np.full(size, np.nan),) * 4

    rr, ri, rm, rp = _fill_raw(s11_raw, "s11_raw", n)
    arrays["raw_s11_real"] = rr; arrays["raw_s11_imag"] = ri
    arrays["raw_s11_mag"]  = rm; arrays["raw_s11_phase_deg"] = rp

    rr, ri, rm, rp = _fill_raw(s21_raw, "s21_raw", n)
    arrays["raw_s21_real"] = rr; arrays["raw_s21_imag"] = ri
    arrays["raw_s21_mag"]  = rm; arrays["raw_s21_phase_deg"] = rp

    arrays["freq_fault_details"] = freq_faults["details"]

    return summary, arrays


def _check_anomalies(rl_db, vswr, il_db, z_mag, s11_mag,
                     instr_mask=None):
    """
    Evalúa las métricas en busca de valores anómalos para uso general.
    Devuelve una lista de strings descriptivos (vacía = sin anomalías).
    No emite veredictos — solo señala estadísticas llamativas.
    """
    th = THRESHOLDS
    warnings = []

    def _mv(arr):
        if instr_mask is not None and INSTRUMENT_MASK_ENABLE and instr_mask.any():
            return arr[instr_mask & np.isfinite(arr)]
        return arr[np.isfinite(arr)]

    avg_rl  = float(np.mean(_mv(rl_db)))
    min_rl  = float(np.min(_mv(rl_db)))
    max_vs  = float(np.max(_mv(vswr)))
    avg_il  = float(np.mean(_mv(il_db)))
    max_il  = float(np.max(_mv(il_db)))
    avg_z   = float(np.mean(_mv(z_mag)))

    if avg_rl < th["disconnected_rl"]:
        warnings.append(
            f"⚠️  RL promedio muy baja ({avg_rl:.1f} dB) — "
            f"cable posiblemente desconectado o en cortocircuito")
    elif avg_rl < th["rl_avg_warn_db"]:
        warnings.append(
            f"⚠️  RL promedio baja ({avg_rl:.1f} dB) — "
            f"reflexión notable, verificar conectores")

    if min_rl < th["rl_min_warn_db"]:
        warnings.append(
            f"⚠️  RL mínima muy baja ({min_rl:.1f} dB) en algún punto — "
            f"verificar si está fuera de zona instrumental")

    if max_vs > th["vswr_max_warn"]:
        warnings.append(
            f"⚠️  VSWR máximo alto ({max_vs:.2f}) — "
            f"reflexión severa en alguna frecuencia")

    if avg_il > th["il_avg_warn_db"]:
        warnings.append(
            f"⚠️  Insertion Loss promedio alta ({avg_il:.1f} dB) — "
            f"posibles pérdidas significativas en el cable")
    if max_il > th["il_max_warn_db"]:
        warnings.append(
            f"⚠️  Insertion Loss máxima muy alta ({max_il:.1f} dB) — "
            f"posible rotura o daño parcial")

    z_dev = abs(avg_z - th["z_nom_ohm"])
    if z_dev > th["z_tol_warn_ohm"]:
        warnings.append(
            f"⚠️  Impedancia promedio ({avg_z:.1f} Ω) se aleja "
            f"{z_dev:.1f} Ω de los {th['z_nom_ohm']:.0f} Ω nominales")

    return warnings


def _generate_interpretation(summary: dict) -> str:
    """
    Genera una línea de interpretación textual en lenguaje técnico simple,
    legible por un técnico sin formación RF avanzada.

    Usa las métricas de la ficha (characterization + global stats + fallas TDR)
    para producir una frase de una o dos oraciones que resuma el estado del cable
    y su aptitud para uso general.
    """
    cc      = summary.get("cable_char", {})
    n_faults = summary.get("num_faults_detected", 0)
    fault_pos = summary.get("fault_positions_m", "")
    refl_p50 = cc.get("refl_pct_p50", 0)
    refl_p90 = cc.get("refl_pct_p90", 0)
    z0       = cc.get("z_char_ohm", 50)
    il_slope = cc.get("il_slope_db_per_ghz", 0)
    avg_il   = summary.get("avg_il_db", 0)
    length   = cc.get("length_resonance_m", 0)
    n_anom   = summary.get("num_anomalies", 0)

    parts = []

    # ── Transmisión ──────────────────────────────────────────────────────────
    if abs(avg_il) < 1.0 and refl_p90 < 5:
        parts.append("Cable transmite correctamente en todo el rango medido")
    elif abs(avg_il) < 3.0 and refl_p90 < 15:
        parts.append("Transmisión aceptable con reflexión moderada")
    else:
        parts.append("Pérdidas o reflexión elevadas — revisar conectores y continuidad")

    # ── Reflexión ────────────────────────────────────────────────────────────
    if refl_p90 < 3:
        parts.append(f"reflexión < 3% en el 90% del rango")
    elif refl_p90 < 10:
        parts.append(f"reflexión < {refl_p90:.0f}% en el 90% del rango")
    else:
        parts.append(f"reflexión hasta {refl_p90:.0f}% en zonas de alta VSWR")

    # ── Impedancia ───────────────────────────────────────────────────────────
    z_dev = abs(z0 - 50)
    if z_dev < 3:
        parts.append("impedancia nominal (~50 Ω)")
    elif z_dev < 8:
        parts.append(f"impedancia levemente elevada ({z0:.0f} Ω)")
    else:
        parts.append(f"impedancia fuera de nominal ({z0:.0f} Ω — desadaptación notable)")

    # ── Tendencia de pérdidas con frecuencia ─────────────────────────────────
    if il_slope < -0.5:
        parts.append(f"pérdidas crecen {abs(il_slope):.1f} dB/GHz (atenuación por frecuencia)")

    # ── Fallas físicas ───────────────────────────────────────────────────────
    falla_txt = ""
    if n_faults > 0:
        falla_txt = (f" ATENCIÓN: {n_faults} discontinuidad(es) detectada(s) "
                     f"por TDR en {fault_pos} m.")

    # ── Longitud ─────────────────────────────────────────────────────────────
    len_txt = f" Longitud estimada: {length*100:.0f} cm." if length > 0 else ""

    # Construir frase final
    main = ", ".join(parts) + "."
    return main + len_txt + falla_txt

# ══════════════════════════════════════════════════════════════════════════════
#  Fin de la zona de cálculo
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
#  Exportación CSV
# ══════════════════════════════════════════════════════════════════════════════

def _mode_description() -> str:
    """Descripción corta del modo activo para cabeceras."""
    mode = SWEEP_MODE.lower()
    if mode == "full":
        return f"full/{POINTS}pts"
    step = int(round(SEGMENT_STEP_MHZ))
    if mode == "segmented":
        avg_desc = (f"avg{SWEEP_AVG_COUNT}{'(median)' if USE_MEDIAN_STACK and SWEEP_AVG_COUNT >= 3 else '(mean)'}"
                    if SWEEP_AVG_COUNT > 1 else "avg1")
        return f"seg/s{step}MHz_p{SEGMENT_MAX_POINTS}_{avg_desc}"
    if mode == "interleaved":
        avg_desc = (f"avg{SWEEP_AVG_COUNT}{'(median)' if USE_MEDIAN_STACK and SWEEP_AVG_COUNT >= 3 else '(mean)'}"
                    if SWEEP_AVG_COUNT > 1 else "avg1")
        return (f"intlv/s{step}MHz_n{N_INTERLEAVE}_"
                f"Δ{SEGMENT_STEP_MHZ/N_INTERLEAVE:.1f}MHz_{avg_desc}")
    return mode


def save_individual_csv(path, cable_id, ts, summary, arrays, freqs, vf,
                        native_data=None):
    cc  = summary["cable_char"]
    bs  = summary["band_stats"]

    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)

        # ══════════════════════════════════════════════════════════════════════
        # SECCIÓN 1 — IDENTIFICACIÓN
        # ══════════════════════════════════════════════════════════════════════
        w.writerow(["## IDENTIFICACIÓN"])
        w.writerow(["Campo", "Valor"])
        for row in [
            ("Cable ID",              cable_id),
            ("Timestamp",             ts),
            ("Perfil calibración",    _active_profile_name()),
            ("Modo sweep",            _mode_description()),
            ("Rango frecuencia [MHz]",
             f"{START_FREQ/1e6:.0f} – {STOP_FREQ/1e6:.0f}"),
            ("Puntos totales",        len(freqs)),
            ("Factor velocidad (VF)", vf),
            ("Warmup previo",         f"{VNA_WARMUP_SECONDS} s"
             if VNA_WARMUP_ENABLE else "No"),
            ("SW avg / HW avg",
             f"{SWEEP_AVG_COUNT} sweeps"
             f"{' (mediana)' if USE_MEDIAN_STACK and SWEEP_AVG_COUNT>=3 else ' (media)'}"
             f" / {SAMPLES_PER_POINT} samples"),
            ("Anotación instrumental", "ON" if INSTRUMENT_MASK_ENABLE else "OFF"),
        ]:
            w.writerow(row)

        # ══════════════════════════════════════════════════════════════════════
        # SECCIÓN 2 — CARACTERIZACIÓN FÍSICA DEL CABLE
        # Métricas derivadas, interpretables sin el gráfico.
        # ══════════════════════════════════════════════════════════════════════
        w.writerow([])
        w.writerow(["## CARACTERIZACIÓN DEL CABLE"])
        w.writerow(["Campo", "Valor", "Nota"])
        for row in [
            ("Longitud física (TDR) [m]",
             summary["cable_length_m"],
             "Pico principal del dominio temporal"),
            ("Longitud por resonancias RL [m]",
             cc["length_resonance_m"],
             f"Espaciado médio de dips = {cc['resonance_period_mhz']:.0f} MHz"),
            ("Impedancia característica Z0 [Ω]",
             cc["z_char_ohm"],
             f"Mediana Z_re (IQR ±{cc['z_iqr_ohm']/2:.1f} Ω, std {cc['z_std_ohm']:.1f} Ω)"),
            ("Uniformidad de Z (std) [Ω]",
             cc["z_std_ohm"],
             "< 5 Ω: muy uniforme | 5–15 Ω: normal | > 15 Ω: revisar"),
            ("Reflexión de potencia p50 [%]",
             cc["refl_pct_p50"],
             "50% del tiempo la reflexión es menor a este valor"),
            ("Reflexión de potencia p90 [%]",
             cc["refl_pct_p90"],
             "90% del tiempo la reflexión es menor a este valor"),
            ("Reflexión de potencia máxima [%]",
             cc["refl_pct_max"],
             "Peor punto en todo el rango (exc. zonas instrumentales)"),
            ("Tendencia IL [dB/GHz]",
             cc["il_slope_db_per_ghz"],
             "Pérdidas adicionales por GHz de subida en frecuencia"),
        ]:
            w.writerow(row)

        # ══════════════════════════════════════════════════════════════════════
        # SECCIÓN 3 — PERFIL POR BANDA
        # ══════════════════════════════════════════════════════════════════════
        w.writerow([])
        w.writerow(["## PERFIL POR BANDA"])
        w.writerow(["Banda",
                    "RL avg [dB]", "RL min [dB]",
                    "VSWR avg", "VSWR max",
                    "IL avg [dB]", "Z mag avg [Ω]",
                    "Refl avg [%]"])
        for band, bst in bs.items():
            rl_a = bst.get("avg_rl_db", "")
            refl = round(10**(-float(rl_a)/10)*100, 2) if rl_a != "" else ""
            w.writerow([band,
                        bst.get("avg_rl_db", ""),
                        bst.get("min_rl_db", ""),
                        bst.get("avg_vswr",  ""),
                        bst.get("max_vswr",  ""),
                        bst.get("avg_il_db", ""),
                        bst.get("avg_z_mag", ""),
                        refl])

        # ══════════════════════════════════════════════════════════════════════
        # SECCIÓN 4 — MÉTRICAS GLOBALES
        # ══════════════════════════════════════════════════════════════════════
        w.writerow([])
        w.writerow(["## MÉTRICAS GLOBALES"])
        w.writerow(["Campo", "Valor"])
        for row in [
            ("RL promedio [dB]",          summary["avg_rl_db"]),
            ("RL mínima [dB]",            summary["min_rl_db"]),
            ("VSWR promedio",             summary["avg_vswr"]),
            ("VSWR máximo",               summary["max_vswr"]),
            ("Impedancia |Z| avg [Ω]",    summary["avg_z_mag_ohm"]),
            ("Impedancia Re(Z) avg [Ω]",  summary["avg_z_real_ohm"]),
            ("Insertion Loss avg [dB]",   summary["avg_il_db"]),
            ("Insertion Loss máx [dB]",   summary["max_il_db"]),
            ("Reflexión potencia avg [%]",summary["avg_power_refl_pct"]),
            ("Potencia transmitida avg [%]",
             round(100 - summary["avg_power_refl_pct"], 2)),
        ]:
            w.writerow(row)

        # ══════════════════════════════════════════════════════════════════════
        # SECCIÓN 5 — ANOMALÍAS Y OBSERVACIONES
        # ══════════════════════════════════════════════════════════════════════
        w.writerow([])
        w.writerow(["## ANOMALÍAS Y OBSERVACIONES"])
        w.writerow(["Tipo", "Detalle"])

        # Interpretación automática — primera línea, la más visible
        w.writerow(["Interpretación", summary.get("interpretation", "")])
        w.writerow([])

        if summary["anomaly_warnings"]:
            for w_str in summary["anomaly_warnings"]:
                w.writerow(["Anomalía métrica", w_str])
        else:
            w.writerow(["Métricas globales", "Sin anomalías detectadas"])

        if summary["num_faults_detected"]:
            w.writerow(["Falla TDR",
                        f"{summary['num_faults_detected']} falla(s) "
                        f"@ {summary['fault_positions_m']} m"])
        else:
            w.writerow(["TDR", "Sin fallas detectadas"])

        if INSTRUMENT_MASK_ENABLE and summary["num_instrument_pts"] > 0:
            zones_hit = sorted(set(
                z for z in arrays["instrument_zone"] if z))
            w.writerow(["Zonas instrumentales",
                        f"{summary['num_instrument_pts']} pts en "
                        f"{len(zones_hit)} zona(s): "
                        f"{', '.join(zones_hit)}"])
            w.writerow(["Nota",
                        "Puntos en zonas rojas excluidos de métricas globales. "
                        "Ver columna instrument_zone en datos por frecuencia."])

        # ══════════════════════════════════════════════════════════════════════
        # SECCIÓN 6 — DATOS POR FRECUENCIA (tabla principal de medición)
        # Cada fila = un punto de frecuencia. Columnas group_delay_ns_plot
        # son sintéticas (interpoladas); group_delay_ns son las medidas reales.
        # ══════════════════════════════════════════════════════════════════════
        w.writerow([])
        w.writerow(["## DATOS POR FRECUENCIA"])
        w.writerow([
            "idx", "freq_mhz",
            "return_loss_db", "vswr", "power_refl_pct",
            "z_real_ohm", "z_imag_ohm", "z_mag_ohm",
            "insertion_loss_db",
            "group_delay_ns", "group_delay_ns_plot",
            "s11_real", "s11_imag", "s11_mag", "s11_phase_deg",
            "s21_mag",  "s21_phase_deg",
            "instrument_zone", "instrument_confidence",
            "raw_s11_real", "raw_s11_imag", "raw_s11_mag", "raw_s11_phase_deg",
            "raw_s21_real", "raw_s21_imag", "raw_s21_mag", "raw_s21_phase_deg",
        ])

        def _f(v, dec):
            try:
                fv = float(v)
                return "" if np.isnan(fv) else round(fv, dec)
            except Exception:
                return ""

        n_pts = len(freqs)
        for i in range(n_pts):
            w.writerow([
                i,
                round(freqs[i]/1e6, 4),
                _f(arrays["return_loss_db"][i],    3),
                _f(arrays["vswr"][i],              4),
                _f(arrays["power_refl_pct"][i],    4),
                _f(arrays["z_real_ohm"][i],        3),
                _f(arrays["z_imag_ohm"][i],        3),
                _f(arrays["z_mag_ohm"][i],         3),
                _f(arrays["insertion_loss_db"][i], 3),
                _f(arrays["group_delay_ns"][i],    3),
                _f(arrays["group_delay_ns_plot"][i], 3),
                _f(arrays["s11_real"][i],          7),
                _f(arrays["s11_imag"][i],          7),
                _f(arrays["s11_mag"][i],           7),
                _f(arrays["s11_phase_deg"][i],     3),
                _f(arrays["s21_mag"][i],           7),
                _f(arrays["s21_phase_deg"][i],     3),
                arrays["instrument_zone"][i],
                int(arrays["instrument_confidence"][i]),
                _f(arrays["raw_s11_real"][i],      7),
                _f(arrays["raw_s11_imag"][i],      7),
                _f(arrays["raw_s11_mag"][i],       7),
                _f(arrays["raw_s11_phase_deg"][i], 3),
                _f(arrays["raw_s21_real"][i],      7),
                _f(arrays["raw_s21_imag"][i],      7),
                _f(arrays["raw_s21_mag"][i],       7),
                _f(arrays["raw_s21_phase_deg"][i], 3),
            ])

        # ══════════════════════════════════════════════════════════════════════
        # SECCIÓN 7 — TDR
        # ══════════════════════════════════════════════════════════════════════
        w.writerow([])
        w.writerow([f"## TDR  ventana={TDR_WINDOW}  zero-pad×{TDR_ZERO_PAD_FACTOR}"])
        w.writerow(["distancia_m", "magnitud_tdr"])
        half = len(arrays["tdr_dist_m"]) // 2
        for i in range(half):
            w.writerow([round(float(arrays["tdr_dist_m"][i]),    4),
                        round(float(arrays["tdr_magnitude"][i]), 8)])

        # ══════════════════════════════════════════════════════════════════════
        # SECCIÓN 8 — DATOS CRUDOS VNA (archivo, trazabilidad)
        # ══════════════════════════════════════════════════════════════════════
        w.writerow([])
        w.writerow(["## DATOS CRUDOS VNA"])
        w.writerow(["idx", "freq_mhz",
                    "fwd_re_i32", "fwd_im_i32",
                    "refl_re_i32", "refl_im_i32",
                    "thru_re_i32", "thru_im_i32",
                    "res0_u32", "res1_u32"])
        for i in range(n_pts):
            row = [i, round(freqs[i]/1e6, 4)]
            if native_data is not None:
                row += [int(native_data[k][i]) for k in
                        ("fwd_re_i32","fwd_im_i32","refl_re_i32","refl_im_i32",
                         "thru_re_i32","thru_im_i32","res0_u32","res1_u32")]
            else:
                row += [""] * 8
            w.writerow(row)

        # ══════════════════════════════════════════════════════════════════════
        # SECCIÓN 9 — FRECUENCIAS CON ANOMALÍA (debug, si activo)
        # ══════════════════════════════════════════════════════════════════════
        if FREQ_FAULT_DEBUG:
            w.writerow([])
            w.writerow(["## FRECUENCIAS CON ANOMALÍA (debug)"])
            w.writerow(["idx", "freq_mhz", "causas", "score",
                        "rl_db", "vswr", "il_db", "z_mag_ohm"])
            for row in arrays.get("freq_fault_details", []):
                w.writerow([
                    row["idx"], round(row["freq_mhz"], 4),
                    row["reasons"], round(row["score"], 4),
                    round(row["rl_db"],     3),
                    round(row["vswr"],      4),
                    round(row["il_db"],     3),
                    round(row["z_mag_ohm"], 3),
                ])

    print(f"📊 CSV guardado → {path}")


def append_master_log(cable_id, ts, summary, vf, csv_path):
    file_exists = MASTER_LOG.exists()
    cc = summary["cable_char"]
    fieldnames = [
        "Timestamp","ID",
        "Longitud_TDR_m","Longitud_Res_m","Periodo_Res_MHz",
        "Z0_Ohm","Z_IQR_Ohm","Z_Std_Ohm",
        "RL_avg_dB","RL_min_dB","VSWR_avg","VSWR_max",
        "IL_avg_dB","IL_max_dB","IL_Slope_dB_per_GHz",
        "Refl_p50_pct","Refl_p90_pct","Refl_max_pct",
        "N_Anomalias","Anomalias",
        "Fallas_TDR","Pos_Fallas_m",
        "Modo","Perfil_Cal","Puntos","VF",
        "SW_Avg","HW_Avg","Mediana",
        "Archivo_CSV",
    ]
    bs  = summary["band_stats"]
    row = {
        "Timestamp":           ts,
        "ID":                  cable_id,
        "Longitud_TDR_m":      summary["cable_length_m"],
        "Longitud_Res_m":      cc["length_resonance_m"],
        "Periodo_Res_MHz":     cc["resonance_period_mhz"],
        "Z0_Ohm":              cc["z_char_ohm"],
        "Z_IQR_Ohm":           cc["z_iqr_ohm"],
        "Z_Std_Ohm":           cc["z_std_ohm"],
        "RL_avg_dB":           summary["avg_rl_db"],
        "RL_min_dB":           summary["min_rl_db"],
        "VSWR_avg":            summary["avg_vswr"],
        "VSWR_max":            summary["max_vswr"],
        "IL_avg_dB":           summary["avg_il_db"],
        "IL_max_dB":           summary["max_il_db"],
        "IL_Slope_dB_per_GHz": cc["il_slope_db_per_ghz"],
        "Refl_p50_pct":        cc["refl_pct_p50"],
        "Refl_p90_pct":        cc["refl_pct_p90"],
        "Refl_max_pct":        cc["refl_pct_max"],
        "N_Anomalias":         summary["num_anomalies"],
        "Anomalias":           " | ".join(summary["anomaly_warnings"])
                               if summary["anomaly_warnings"] else "OK",
        "Fallas_TDR":          summary["num_faults_detected"],
        "Pos_Fallas_m":        summary["fault_positions_m"] or "Ninguna",
        "Modo":                _mode_description(),
        "Perfil_Cal":          _active_profile_name(),
        "Puntos":              summary.get("n_points", ""),
        "VF":                  vf,
        "SW_Avg":              SWEEP_AVG_COUNT,
        "HW_Avg":              SAMPLES_PER_POINT,
        "Mediana":             USE_MEDIAN_STACK and SWEEP_AVG_COUNT >= 3,
        "Archivo_CSV":         csv_path.name,
    }
    with open(MASTER_LOG, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
    print(f"📋 Master log actualizado → {MASTER_LOG}")


# ══════════════════════════════════════════════════════════════════════════════
#  Gráfica
# ══════════════════════════════════════════════════════════════════════════════

def save_plot(path, cable_id, ts, summary, arrays, freqs,
              boundary_indices=None):
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), facecolor='#0d1117')
    total_mhz = (freqs[-1] - freqs[0]) / 1e6 if len(freqs) > 1 else 0

    # Línea 2 del título: describe el modo de medición con todos sus parámetros
    mode     = SWEEP_MODE.lower()
    avg_info = ""
    if SWEEP_AVG_COUNT > 1:
        combo = "mediana" if (USE_MEDIAN_STACK and SWEEP_AVG_COUNT >= 3) else "media"
        avg_info = f" | SW-avg:{SWEEP_AVG_COUNT}({combo})"
    if SAMPLES_PER_POINT > 1:
        avg_info += f" | HW-avg:{SAMPLES_PER_POINT}"

    if mode == "full":
        mode_str = f"Modo: full  {POINTS} pts{avg_info}"
    elif mode == "segmented":
        mode_str = (f"Modo: segmented  Δf={SEGMENT_STEP_MHZ:.0f} MHz  "
                    f"drop={SEGMENT_DROP_HEAD}{avg_info}")
    else:
        eff_step = SEGMENT_STEP_MHZ / N_INTERLEAVE
        mode_str = (f"Modo: interleaved  N={N_INTERLEAVE}  "
                    f"Δf_ef={eff_step:.1f} MHz{avg_info}")

    tdr_info = f"TDR: ventana={TDR_WINDOW} zpad×{TDR_ZERO_PAD_FACTOR}"

    mask_tag = "  [anotación ON]" if INSTRUMENT_MASK_ENABLE else ""
    n_anom   = summary.get("num_anomalies", 0)
    anom_tag = f"  ⚠️ {n_anom} anomalía(s)" if n_anom else ""

    # Longitud eléctrica: solo mostrar en header cuando hay falla TDR,
    # para que funcione como segunda estimación de localización de falla.
    # En casos normales solo contamina con el valor erróneo del GD.
    n_faults = summary.get("num_faults_detected", 0)
    if n_faults > 0:
        fault_pos = summary.get("fault_positions_m", "")
        elec_tag  = (f"  |  Elec: {summary['elec_length_m']:.3f} m "
                     f"[ref falla]")
    else:
        elec_tag = ""

    fig.suptitle(
        f"ID: {cable_id}  |  {ts}  |  "
        f"TDR: {summary['cable_length_m']:.3f} m"
        f"{elec_tag}{anom_tag}\n"
        f"{mode_str}  |  {tdr_info}  |  "
        f"Rango: {freqs[0]/1e6:.1f}–{freqs[-1]/1e6:.1f} MHz  "
        f"{total_mhz:.0f} MHz  {len(freqs)} pts  |  {_active_profile_name()}"
        f"{mask_tag}",
        color='#c9d1d9', fontsize=8.5, family='monospace'
    )
    fmhz = freqs / 1e6
    f_min, f_max = fmhz[0], fmhz[-1]

    def _ax(ax, title, xlabel, ylabel):
        ax.set_facecolor('#161b22')
        ax.tick_params(colors='#8b949e', labelsize=8)
        for s in ax.spines.values():
            s.set_edgecolor('#30363d')
        ax.set_title(title, color='#c9d1d9', fontsize=9)
        ax.set_xlabel(xlabel, color='#8b949e', fontsize=8)
        ax.set_ylabel(ylabel, color='#8b949e', fontsize=8)
        ax.grid(True, color='#30363d', lw=0.5, ls='--')

    def _vlines(ax, bidxs, fmhz):
        if bidxs:
            for b in bidxs:
                if 0 < b < len(fmhz):
                    ax.axvline(fmhz[b], color='#555', lw=0.6, ls=':', alpha=0.5)

    def _shade_mask_zones(ax, add_labels=False):
        """Sombrea las zonas de error instrumental con etiqueta opcional."""
        if not INSTRUMENT_MASK_ENABLE:
            return
        first = True
        for f_lo, f_hi, nombre, _, _ in VNA_ERROR_ZONES:
            if f_hi < f_min or f_lo > f_max:
                continue
            lo  = max(f_lo, f_min)
            hi  = min(f_hi, f_max)
            lbl = "Zona instrumental" if first else None
            ax.axvspan(lo, hi, alpha=0.12, color='#f85149',
                       lw=0, label=lbl, zorder=0)
            if add_labels:
                mid = (lo + hi) / 2
                ylims = ax.get_ylim()
                y_pos = ylims[1] - (ylims[1] - ylims[0]) * 0.04
                ax.text(mid, y_pos, nombre,
                        ha='center', va='top', fontsize=5.5,
                        color='#f85149', alpha=0.85,
                        rotation=90, clip_on=True)
            first = False

    # Return Loss
    axes[0,0].plot(fmhz, arrays["return_loss_db"],
                   color='#58a6ff', lw=1.2, alpha=0.8, label='RL')
    axes[0,0].scatter(fmhz, arrays["return_loss_db"],
                      color='#58a6ff', s=10, alpha=0.5, zorder=3)
    axes[0,0].axhline(20, color='#3fb950', ls='--', lw=0.8, label='20 dB PASS')
    axes[0,0].axhline(15, color='#ffa657', ls='--', lw=0.8, label='15 dB WARN', alpha=0.7)
    _shade_mask_zones(axes[0,0], add_labels=True)
    _vlines(axes[0,0], boundary_indices, fmhz)
    _ax(axes[0,0], "Return Loss", "MHz", "dB")
    axes[0,0].legend(fontsize=7, labelcolor='#8b949e', framealpha=0.3, loc='best')

    # VSWR
    axes[0,1].plot(fmhz, arrays["vswr"],
                   color='#3fb950', lw=1.2, alpha=0.8, label='VSWR')
    axes[0,1].scatter(fmhz, arrays["vswr"],
                      color='#3fb950', s=10, alpha=0.5, zorder=3)
    axes[0,1].axhline(1.5, color='#ffa657', ls='--', lw=0.8, label='1.5 PASS')
    axes[0,1].axhline(2.0, color='#f85149', ls='--', lw=0.8, label='2.0 WARN')
    axes[0,1].set_ylim(1, min(5, float(np.percentile(arrays["vswr"], 99))))
    _shade_mask_zones(axes[0,1])
    _vlines(axes[0,1], boundary_indices, fmhz)
    _ax(axes[0,1], "VSWR", "MHz", "VSWR")
    axes[0,1].legend(fontsize=7, labelcolor='#8b949e', framealpha=0.3, loc='best')

    # Impedancia
    axes[0,2].plot(fmhz, arrays["z_real_ohm"],
                   color='#d2a8ff', lw=1.2, alpha=0.8, label='Re(Z)')
    axes[0,2].scatter(fmhz, arrays["z_real_ohm"],
                      color='#d2a8ff', s=10, alpha=0.5, zorder=3)
    axes[0,2].plot(fmhz, arrays["z_imag_ohm"],
                   color='#ffa657', lw=1.2, alpha=0.8, label='Im(Z)')
    axes[0,2].scatter(fmhz, arrays["z_imag_ohm"],
                      color='#ffa657', s=10, alpha=0.5, zorder=3)
    axes[0,2].axhline(50, color='#58a6ff', ls='--', lw=0.8, label='50 Ω nom')
    z_vals      = np.concatenate([arrays["z_real_ohm"], arrays["z_imag_ohm"]])
    p5, p95     = np.percentile(z_vals, 5), np.percentile(z_vals, 95)
    margin      = max(10, (p95 - p5) * 0.3)
    axes[0,2].set_ylim(p5 - margin, p95 + margin)
    _shade_mask_zones(axes[0,2])
    _vlines(axes[0,2], boundary_indices, fmhz)
    _ax(axes[0,2], "Impedancia", "MHz", "Ω")
    axes[0,2].legend(fontsize=7, labelcolor='#8b949e', framealpha=0.3, loc='best')

    # Insertion Loss
    il_plot = np.clip(arrays["insertion_loss_db"], -5, 30)
    axes[1,0].plot(fmhz, il_plot, color='#ff7b72', lw=1.2, alpha=0.8, label='IL')
    axes[1,0].scatter(fmhz, il_plot, color='#ff7b72', s=10, alpha=0.5, zorder=3)
    axes[1,0].axhline(3, color='#ffa657', ls='--', lw=0.8, label='3 dB PASS', alpha=0.7)
    axes[1,0].axhline(6, color='#f85149', ls='--', lw=0.8, label='6 dB WARN', alpha=0.7)
    _shade_mask_zones(axes[1,0])
    _vlines(axes[1,0], boundary_indices, fmhz)
    _ax(axes[1,0], "Insertion Loss (S21)", "MHz", "dB")
    axes[1,0].legend(fontsize=7, labelcolor='#8b949e', framealpha=0.3, loc='best')

    # TDR
    half = len(arrays["tdr_dist_m"]) // 2
    axes[1,1].plot(arrays["tdr_dist_m"][:half], arrays["tdr_magnitude"][:half],
                   color='#ffa657', lw=1.2)
    axes[1,1].axvline(summary["cable_length_m"], color='#f85149', ls='--', lw=1.0,
                      label=f"TDR: {summary['cable_length_m']:.3f} m")
    _ax(axes[1,1], f"TDR — Longitud  [{TDR_WINDOW}/×{TDR_ZERO_PAD_FACTOR}]",
        "Distancia (m)", "Magnitud")
    axes[1,1].legend(fontsize=7, labelcolor='#8b949e', framealpha=0.3, loc='best')

    # Group Delay — usa la versión interpolada (solo para visualización continua)
    # Los NaN originales (zonas instrumentales) están en arrays["group_delay_ns"]
    gd_plot = np.clip(arrays["group_delay_ns_plot"], -5, 20)
    axes[1,2].plot(fmhz, gd_plot, color='#56d364', lw=1.2, alpha=0.8, label='GD')
    axes[1,2].scatter(fmhz, gd_plot, color='#56d364', s=10, alpha=0.5, zorder=3)
    if INSTRUMENT_MASK_ENABLE:
        axes[1,2].text(
            0.99, 0.02,
            "líneas sólidas en zonas rojas = interpolado (sintético)",
            transform=axes[1,2].transAxes,
            ha='right', va='bottom', fontsize=5.5,
            color='#f85149', alpha=0.8,
        )
    _shade_mask_zones(axes[1,2])
    _vlines(axes[1,2], boundary_indices, fmhz)
    _ax(axes[1,2], "Retardo de Grupo", "MHz", "ns")
    axes[1,2].legend(fontsize=7, labelcolor='#8b949e', framealpha=0.3, loc='best')

    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
    plt.close()
    print(f"🖼️  Gráfica guardada → {path}")


# ══════════════════════════════════════════════════════════════════════════════
#  Wizard de Calibración
# ══════════════════════════════════════════════════════════════════════════════

def run_calibration_wizard(vna, cal, cal_file):
    """
    Guía interactiva de calibración SOLT.

    Para el modo "interleaved", cada estándar se mide con las N_INTERLEAVE
    pasadas, exactamente igual que las mediciones de producción.
    Esto garantiza que los vectores de calibración y medición tengan
    exactamente la misma grilla de frecuencias.
    """
    mode = SWEEP_MODE.lower()

    # Descripción de lo que se va a calibrar
    if mode == "interleaved":
        pts_est = _expected_total_points()
        cal_detail = (f"  Modo INTERLEAVED: {N_INTERLEAVE} pasadas × segmented\n"
                      f"  Δf efectivo = {SEGMENT_STEP_MHZ/N_INTERLEAVE:.1f} MHz\n"
                      f"  Puntos estimados: ~{pts_est}")
    elif mode == "segmented":
        pts_est = _expected_total_points()
        cal_detail = (f"  Modo SEGMENTED: Δf = {SEGMENT_STEP_MHZ:.0f} MHz\n"
                      f"  Puntos estimados: ~{pts_est}")
    else:
        cal_detail = f"  Modo FULL: {POINTS} puntos"

    print("\n" + "═" * 60)
    print(f"  CALIBRACIÓN SOLT — NanoVNA V2 Plus4")
    print(f"  Perfil: {_active_profile_name()}")
    print(f"  Archivo: {cal_file}")
    print(cal_detail)
    print("═" * 60)
    if ENABLE_THRU_RECAL:
        print("  Necesitas: estándar OPEN, SHORT, LOAD (50 Ω) y cable THRU.\n")
    else:
        print("  Necesitas: estándar OPEN, SHORT, LOAD (50 Ω).\n")
        print("  ℹ️  THRU desactivado por configuración (ENABLE_THRU_RECAL=False).\n")

    if mode == "interleaved":
        print(f"  ⚠️  Cada estándar se medirá {N_INTERLEAVE} veces (una por pasada).")
        print(f"     Tiempo estimado por estándar: "
              f"~{N_INTERLEAVE * (SEGMENT_MAX_POINTS * SWEEP_SETTLE_MS / 1000 / 60):.1f} min\n")

    stds = {}
    for name in ["OPEN", "SHORT", "LOAD"]:
        input(f"  ➤  [Puerto 1] Conecte {name} y presione ENTER...")
        s11, _ = vna.measure(label=f"Cal {name}")
        stds[name] = s11
        print(f"  ✅ {name} capturado  ({len(s11)} puntos)")

    if ENABLE_THRU_RECAL:
        input("  ➤  [P1→P2] Conecte adaptador THRU y presione ENTER...")
        _, s21_thru = vna.measure(label="Cal THRU")
        stds["THRU"] = s21_thru
        print(f"  ✅ THRU capturado  ({len(s21_thru)} puntos)")
        cal.solve(stds["OPEN"], stds["SHORT"], stds["LOAD"], stds["THRU"])
    else:
        cal.solve(stds["OPEN"], stds["SHORT"], stds["LOAD"])
    cal.save(cal_file)

    # ── Verificación post-calibración (opcional) ──────────────────────────────
    if CAL_VERIFY_ENABLE:
        print("\n  ─── Verificación post-calibración ────────────────────────")
        print("  ℹ️  Se medirá la carga LOAD una segunda vez para estimar el")
        print("     piso de error residual del sistema calibrado.")
        input("  ➤  [Puerto 1] Reconecte la LOAD (50 Ω) y presione ENTER...")
        s11_verify, _ = vna.measure(label="Verificando calibración")
        s11_v_cal, _, _, _ = cal.apply(s11_verify,
                                        np.ones(len(s11_verify), dtype=complex))
        # Un sistema perfecto daría S11_cal = 0+0j sobre la LOAD
        rms_err_lin  = float(np.sqrt(np.mean(np.abs(s11_v_cal) ** 2)))
        rms_err_db   = -20 * np.log10(rms_err_lin + 1e-12)
        max_err_db   = float(-20 * np.log10(np.max(np.abs(s11_v_cal)) + 1e-12))
        worst_freq   = float(cal.meta.get("start_hz", 0) +
                             (np.argmax(np.abs(s11_v_cal)) /
                              max(len(s11_v_cal) - 1, 1)) *
                             (cal.meta.get("stop_hz", 1) -
                              cal.meta.get("start_hz", 0))) / 1e6

        print(f"\n  📊 Error residual de calibración:")
        print(f"     RL residual RMS : {rms_err_db:.1f} dB  "
              f"({'✅ bueno' if rms_err_db > 28 else '⚠️  revisar apriete del conector' if rms_err_db > 22 else '❌ recalibrar'})")
        print(f"     RL residual mín : {max_err_db:.1f} dB  "
              f"(peor punto ≈ {worst_freq:.0f} MHz)")
        if rms_err_db <= 22:
            print("  ❌ Error alto — recalibrar con mayor cuidado en las")
            print("     conexiones. Verificar torque uniforme en OPEN/SHORT/LOAD.")
        elif rms_err_db <= 28:
            print("  ⚠️  Error moderado — aceptable para NanoVNA V2.")
            print("     Para mejorar: reconectar con mismo torque y misma orientación.")
        else:
            print("  ✅ Calibración verificada correctamente para NanoVNA V2.")

    print("\n✅ Calibración completa.\n")


# ══════════════════════════════════════════════════════════════════════════════
#  Aplicación Principal
# ══════════════════════════════════════════════════════════════════════════════

def main():
    _validate_runtime_config()

    print("\n" + "█" * 60)
    print("  CABLEMASTER PRO  v12.0")
    print("█" * 60)
    print(f"  Datos en : {DESKTOP}")

    # ── Resumen de configuración activa ───────────────────────────────────────
    mode = SWEEP_MODE.lower()
    print(f"\n  ┌─ Configuración de Sweep ─────────────────────────────")
    print(f"  │  Modo        : {SWEEP_MODE}")
    if mode == "full":
        print(f"  │  Puntos      : {POINTS}")
    elif mode == "segmented":
        n_pts = _expected_total_points()
        print(f"  │  Paso        : {SEGMENT_STEP_MHZ} MHz  |  ~{n_pts} puntos")
        print(f"  │  Drop head   : {SEGMENT_DROP_HEAD}  |  Stitch: {SEGMENT_STITCH_CORRECT}")
    elif mode == "interleaved":
        n_pts = _expected_total_points()
        eff   = SEGMENT_STEP_MHZ / N_INTERLEAVE
        print(f"  │  N pasadas   : {N_INTERLEAVE}  |  Δf base: {SEGMENT_STEP_MHZ} MHz")
        print(f"  │  Δf efectivo : {eff:.1f} MHz  |  ~{n_pts} puntos totales")

    print(f"  │  Rango       : {START_FREQ/1e6:.0f}–{STOP_FREQ/1e6:.0f} MHz")
    print(f"  │  VF          : {VF}")
    print(f"  ├─ Promediado ─────────────────────────────────────────")
    print(f"  │  HW avg      : {SAMPLES_PER_POINT} muestras/punto")
    stack_mode = ("mediana" if (USE_MEDIAN_STACK and SWEEP_AVG_COUNT >= 3) else "media")
    print(f"  │  SW avg      : {SWEEP_AVG_COUNT} sweeps  ({stack_mode})")
    print(f"  ├─ TDR ────────────────────────────────────────────────")
    print(f"  │  Ventana     : {TDR_WINDOW}")
    print(f"  │  Zero-pad    : ×{TDR_ZERO_PAD_FACTOR}")
    print(f"  ├─ Warmup ─────────────────────────────────────────────")
    print(f"  │  Activo      : {VNA_WARMUP_ENABLE}  |  Duración: {VNA_WARMUP_SECONDS} s")
    print(f"  ├─ Calibración ───────────────────────────────────────")
    print(f"  │  Recalibrar THRU: {ENABLE_THRU_RECAL}")
    mask_status = "ON" if INSTRUMENT_MASK_ENABLE else "OFF"
    n_zones = len(VNA_ERROR_ZONES)
    print(f"  ├─ Anotación instrumental ────────────────────────────")
    print(f"  │  Estado       : {mask_status}  ({n_zones} zonas definidas)")
    if INSTRUMENT_MASK_ENABLE:
        n4 = sum(1 for *_, c in VNA_ERROR_ZONES if c >= 4)
        n3 = sum(1 for *_, c in VNA_ERROR_ZONES if c == 3)
        print(f"  │  Alta prioridad (4/7): {n4}  Media (3/7): {n3}")
        print(f"  │  Datos crudos: intactos  |  GD: cosido global por pendiente")
    print(f"  ├─ Salida ────────────────────────────────────────────")
    print(f"  │  CSV          : siempre")
    print(f"  │  Gráfico PNG  : {'SI' if SAVE_PLOT else 'NO  (SAVE_PLOT=False)'}")
    print(f"  ├─ Fiabilidad ────────────────────────────────────────")
    tdr_supr = f"ON (skip < {TDR_MIN_CABLE_LEN_M*100:.0f} cm)" if TDR_SUPPRESS_CONNECTOR else "OFF"
    print(f"  │  Supresión conector TDR : {tdr_supr}")
    print(f"  │  Verif. post-cal        : {'ON' if CAL_VERIFY_ENABLE else 'OFF'}")
    print(f"  │  Aviso resolución       : {'ON' if WARN_RESOLUTION_MISMATCH else 'OFF'}"
          f"  (umbral: {WARN_RESOLUTION_MIN_LEN_M*100:.0f} cm)")
    # Advertencia de estabilidad de GD
    if WARN_GD_STABILITY and SWEEP_MODE.lower() in ("segmented", "interleaved"):
        if SWEEP_AVG_COUNT < 3:
            print(f"  │  ⚠️  GD stability: SWEEP_AVG_COUNT={SWEEP_AVG_COUNT} < 3")
            print(f"  │     El retardo de grupo en modo {SWEEP_MODE} puede ser ruidoso.")
            print(f"  │     Recomendado: SWEEP_AVG_COUNT=3, USE_MEDIAN_STACK=True")
    print(f"  └──────────────────────────────────────────────────────")

    # ── Perfiles de calibración disponibles ───────────────────────────────────
    profiles = list_calibration_profiles()
    active   = _active_profile_name()
    if profiles:
        print(f"\n  Perfiles de calibración disponibles:")
        for p in profiles:
            tag = " ← activo" if p == active else ""
            print(f"    • {p}{tag}")
    print()

    # ── Conectar VNA ──────────────────────────────────────────────────────────
    vna = NanoVNA_V2(PORT)

    # ── Warmup de arranque ────────────────────────────────────────────────────
    if VNA_WARMUP_ENABLE:
        vna.warmup(VNA_WARMUP_SECONDS)
    else:
        print("  ℹ️  Warmup desactivado (VNA_WARMUP_ENABLE = False)")

    # ── Gestión de calibración ────────────────────────────────────────────────
    cal            = Calibration()
    active_cal_file = _active_cal_file()
    print(f"  Perfil activo: {active}")

    if active_cal_file.exists():
        try:
            cal.load(active_cal_file)
            recal = input("  ¿Recalibrar este perfil? [s/N]: ").strip().lower()
            if recal == 's':
                run_calibration_wizard(vna, cal, active_cal_file)
        except RuntimeError as e:
            print(f"\n  ❌ Calibración incompatible: {e}")
            print("  → Iniciando wizard de calibración para el perfil actual.")
            run_calibration_wizard(vna, cal, active_cal_file)
        except Exception as e:
            print(f"  ⚠️  Error al cargar calibración ({e})")
            print("  → Iniciando wizard de calibración.")
            run_calibration_wizard(vna, cal, active_cal_file)
    else:
        print(f"  📭 No hay calibración para el perfil '{active}'.")
        run_calibration_wizard(vna, cal, active_cal_file)

    # ── Pre-calcular índices de borde de segmento ─────────────────────────────
    step_hz = int(round(SEGMENT_STEP_MHZ * 1e6))
    if mode == "segmented":
        plan              = _build_segment_plan(START_FREQ, STOP_FREQ, step_hz,
                                                SEGMENT_MAX_POINTS)
        seg_boundary_idxs = _segment_boundary_indices(plan, SEGMENT_DROP_HEAD)
    elif mode == "interleaved":
        # En modo interleaved los bordes son internos a cada pasada;
        # como las pasadas son a frecuencias distintas y la stitch correction
        # ya actúa dentro de cada pasada, no se dibujan bordes inter-pasada.
        # Se calculan los bordes de la primera pasada como referencia visual.
        plan_p0           = _build_segment_plan(START_FREQ, STOP_FREQ, step_hz,
                                                SEGMENT_MAX_POINTS)
        seg_boundary_idxs = _segment_boundary_indices(plan_p0, SEGMENT_DROP_HEAD)
        # Escalar los índices por N_INTERLEAVE ya que los puntos están entrelazados
        seg_boundary_idxs = [b * N_INTERLEAVE for b in seg_boundary_idxs]
    else:
        seg_boundary_idxs = []

    print(f"\n📂 Archivos en: {DESKTOP}")

    # ── Bucle de medición ─────────────────────────────────────────────────────
    while True:
        cable_id = str(uuid.uuid4())[:8].upper()
        ts       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(f"\n{'─' * 60}")
        print(f"  Cable ID: {cable_id}  |  {ts}")
        input("  ➤  Conecte el cable al puerto 1 (CH0) y presione ENTER...")

        # Medir
        s11_raw, s21_raw = vna.measure(label="Midiendo cable", cal=cal)
        freqs = (vna.last_freqs if vna.last_freqs is not None
                 else np.linspace(START_FREQ, STOP_FREQ, POINTS))
        native_data = vna.last_native

        # Calibrar
        if not cal.is_ready():
            raise RuntimeError("Calibración no disponible")
        s11_c, s21_c, il_db, s21_phase = cal.apply(s11_raw, s21_raw)

        # Detección rápida de cable desconectado
        avg_rl = float(np.mean(-20 * np.log10(np.abs(s11_c) + 1e-12)))
        if avg_rl < THRESHOLDS["disconnected_rl"]:
            print(f"\n  ⚠️  ADVERTENCIA: cable posiblemente desconectado "
                  f"(RL avg = {avg_rl:.1f} dB)")
            if input("  ¿Guardar de todas formas? [s/N]: ").strip().lower() != 's':
                print("  Medición descartada.")
                if input("  ¿Medir otro cable? [S/n]: ").lower() == 'n':
                    break
                continue

        # Calcular métricas
        summary, arrays = compute_all_metrics(
            s11_c, s21_c, il_db, s21_phase, freqs, VF,
            s11_raw=s11_raw, s21_raw=s21_raw,
            boundary_indices=seg_boundary_idxs,
        )
        summary["n_points"] = len(freqs)

        # ── Advertencia de resolución espectral ───────────────────────────────
        if (WARN_RESOLUTION_MISMATCH
                and SWEEP_MODE.lower() == "full"
                and summary["elec_length_m"] > WARN_RESOLUTION_MIN_LEN_M):
            cycles_per_span = (summary["elec_length_m"] / 0.7 * 2 *
                               (STOP_FREQ - START_FREQ) / 3e8)
            samp_per_cycle  = POINTS / max(cycles_per_span, 0.1)
            print(f"\n  ⚠️  RESOLUCIÓN: cable de {summary['elec_length_m']:.2f} m eléctricos "
                  f"con modo 'full' ({POINTS} pts).")
            print(f"     ~{samp_per_cycle:.1f} pts/ciclo de oscilación RL "
                  f"({'suficiente' if samp_per_cycle >= 5 else 'insuficiente — riesgo de aliasing'}).")
            if samp_per_cycle < 5:
                print(f"     → Cambiar a SWEEP_MODE='segmented' mejorará la precisión"
                      f" de RL, Z e IL para este cable.")

        # ── Mostrar en terminal ───────────────────────────────────────────────
        print(f"\n  💬 {summary.get('interpretation','')}")
        print(f"\n  📍 Longitud (TDR):        {summary['cable_length_m']:.3f} m")
        if summary["num_faults_detected"]:
            print(f"  📏 Longitud (eléctrica):  {summary['elec_length_m']:.3f} m  "
                  f"[referencia para localización de falla]")
        print(f"  📉 Return Loss:           {summary['avg_rl_db']:.1f} dB avg  |  "
              f"{summary['min_rl_db']:.1f} dB min")
        print(f"  📶 VSWR:                  {summary['avg_vswr']:.3f} avg  |  "
              f"{summary['max_vswr']:.3f} max")
        print(f"  ⚡ Impedancia:            Re={summary['avg_z_real_ohm']:.1f} Ω avg  "
              f"|Z|={summary['avg_z_mag_ohm']:.1f} Ω")
        print(f"  🔇 Insertion Loss:        {summary['avg_il_db']:.1f} dB avg  |  "
              f"{summary['max_il_db']:.1f} dB máx")
        print(f"  💡 Refl. potencia:        {summary['avg_power_refl_pct']:.1f}% avg")
        print(f"  📊 Puntos medidos:        {len(freqs)}")

        if summary["num_faults_detected"]:
            print(f"  🚨 Fallas TDR:            "
                  f"{summary['num_faults_detected']} @ {summary['fault_positions_m']} m")

        if INSTRUMENT_MASK_ENABLE and summary["num_instrument_pts"] > 0:
            n_zones_hit = len([z for z in set(arrays["instrument_zone"]) if z])
            print(f"  🔴 Zonas instrumentales:  {summary['num_instrument_pts']} pts "
                  f"en {n_zones_hit} zona(s) — ver bandas rojas en plot")

        if summary["anomaly_warnings"]:
            print(f"\n  ── Anomalías detectadas ({summary['num_anomalies']}) ──")
            for w in summary["anomaly_warnings"]:
                print(f"  {w}")
        else:
            print(f"\n  ✓  Sin anomalías en las métricas")

        # Guardar
        stem     = f"{datetime.now().strftime('%H%M%S')}_{cable_id}"
        csv_path = READINGS_DIR / f"{stem}.csv"

        save_individual_csv(csv_path, cable_id, ts, summary, arrays, freqs, VF,
                            native_data=native_data)
        append_master_log(cable_id, ts, summary, VF, csv_path)

        if SAVE_PLOT:
            plot_path = READINGS_DIR / f"{stem}_plot.png"
            save_plot(plot_path, cable_id, ts, summary, arrays, freqs,
                      boundary_indices=seg_boundary_idxs)
        else:
            print("  📊 Gráfico omitido (SAVE_PLOT=False)")

        if input("\n  ¿Medir otro cable? [S/n]: ").lower() == 'n':
            break

    print(f"\n✅ Sesión terminada. Archivos en: {DESKTOP}")


if __name__ == "__main__":
    main()