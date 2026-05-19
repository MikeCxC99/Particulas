# 🌡️ Sistema de Monitoreo de Temperatura con Sensores DS18B20

[![Arduino](https://img.shields.io/badge/Arduino-Industrino-00979D?style=flat&logo=arduino)](https://www.arduino.cc/)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=flat&logo=python)](https://www.python.org/)
[![Jupyter](https://img.shields.io/badge/Jupyter-Notebook-F37626?style=flat&logo=jupyter)](https://jupyter.org/)

Sistema de adquisición y visualización de datos de temperatura basado en **20 sensores DS18B20**, un módulo RTC **DS3231** y almacenamiento en tarjeta SD. Incluye firmware Arduino para la captura de datos y notebooks Jupyter para su procesamiento y visualización como mapa de calor.

---

## 📁 Estructura del Repositorio

```
Particulas/
├── Escritura de datos/
│   └── Sketch_Industrino_F.ino      # Firmware Arduino para adquisición de datos
│
├── Interpretacion TXT/
│   ├── txtConverter.ipynb            # Notebook: Conversión de .TXT a .CSV
│   ├── csvGrapher.ipynb              # Notebook: Filtrado y visualización como heatmap
│   ├── 1730.TXT                      # Datalog de ejemplo (2025-08-07 a 2025-08-08)
│   ├── 20250808_1745-1750.TXT        # Datalog de ejemplo (intervalo corto)
│   ├── Datalog_A.csv                 # CSV generado desde 1730.TXT
│   └── Datalog_Filtered_A.csv        # CSV filtrado (sin lecturas inválidas)
│
└── README.md
```

---

## �� Hardware Requerido

| Componente         | Descripción                                                               |
|--------------------|---------------------------------------------------------------------------|
| **Placa**          | Industrino (compatible Arduino Mega)                                      |
| **Sensores**       | 20 × DS18B20 (11 cables cortos CC1–CC11, 9 cables largos CL1–CL9)        |
| **RTC**            | DS3231 (registro de fecha y hora, comunicación I²C)                       |
| **Almacenamiento** | Tarjeta SD (pin CS: 53)                                                   |

---

## 💻 Software Requerido

### Firmware (Arduino)

Librerías de Arduino necesarias (disponibles en el Gestor de Librerías del IDE):

- [`OneWire`](https://github.com/PaulStoffregen/OneWire) — comunicación con sensores DS18B20
- [`DallasTemperature`](https://github.com/milesburton/Arduino-Temperature-Control-Library) — lectura de temperatura
- `SPI` *(incluida en el IDE de Arduino)*
- `SD` *(incluida en el IDE de Arduino)*
- `Wire` *(incluida en el IDE de Arduino)*
- [`RTClib`](https://github.com/adafruit/RTClib) — módulo RTC DS3231

### Notebooks Python

- Python 3.x
- [Jupyter Lab](https://jupyterlab.readthedocs.io/) o [Jupyter Notebook](https://jupyter.org/)
- `pandas`, `seaborn`, `matplotlib`

Instalación de dependencias Python:

```bash
pip install pandas seaborn matplotlib jupyterlab
```

---

## 🚀 Uso

### 1. Adquisición de Datos (Arduino)

1. Instala las librerías de Arduino listadas arriba.
2. Abre `Escritura de datos/Sketch_Industrino_F.ino` en el IDE de Arduino.
3. Verifica y ajusta las direcciones de los sensores DS18B20 en el arreglo `sensoresOrdenados[]` si es necesario.
4. Para sincronizar el RTC, descomenta y ajusta la línea `rtc.adjust(...)` en `setup()`, carga el sketch, luego vuelve a comentarla.
5. Carga el sketch en la placa Industrino.
6. Los datos se guardarán automáticamente en `datalog.txt` en la tarjeta SD.

### 2. Conversión de TXT a CSV

1. Coloca el archivo `.TXT` a procesar en la misma carpeta que el notebook `txtConverter.ipynb`.
2. Abre `Interpretacion TXT/txtConverter.ipynb` en Jupyter.
3. Ajusta las variables de configuración al inicio de la celda:
   - `input_filename`: nombre del archivo `.TXT` de entrada.
   - `output_filename`: nombre del archivo `.CSV` de salida.
   - *(Opcional)* `start_year/month/day` y `end_year/month/day` para filtrar por rango de fechas.
4. Ejecuta el notebook. Se generará el archivo `.CSV` en la misma carpeta.

### 3. Filtrado y Visualización

1. Coloca el archivo `.CSV` generado en el paso anterior en la misma carpeta que `csvGrapher.ipynb`.
2. Abre `Interpretacion TXT/csvGrapher.ipynb` en Jupyter.
3. Ajusta las variables de configuración:
   - `input_csv_filename`: nombre del CSV de entrada.
   - `output_csv_filename`: nombre del CSV filtrado de salida.
   - `temperature_threshold`: umbral de temperatura mínima (default: `-120.0 °C`).
4. Ejecuta las celdas en orden:
   - **Celda 1:** filtra lecturas inválidas y guarda el CSV limpio.
   - **Celda 2:** genera y muestra el mapa de calor (*heatmap*).

---

## 📄 Formato de Datos

Los archivos `.TXT` generados por el firmware contienen una línea por medición:

```
YYYY-MM-DD,HH:MM:SS, Unidad: C°,S1: XX.XX, S2: XX.XX, ..., S20: XX.XX.
```

**Ejemplo:**

```
2025-08-07,19:14:30, Unidad: C°,S1: 20.38, S2: 20.00, S3: 20.25, ..., S20: 20.00.
```

Los archivos `.CSV` resultantes tienen columnas: `Date`, `Time`, `Unit`, `S1`, `S2`, …, `S20`.

---

## 📊 Visualización

El notebook `csvGrapher.ipynb` genera un **mapa de calor** (*heatmap*) que muestra la evolución temporal de la temperatura para cada sensor:

- **Eje X:** Tiempo (remuestreado cada 10 segundos)
- **Eje Y:** Sensor (S1 a S20)
- **Color:** Temperatura promedio en °C (escala `coolwarm`: azul = frío, rojo = caliente)

---

## 📡 Identificación de Sensores

| ID en datos | Nombre real | Tipo de cable |
|-------------|-------------|---------------|
| S1 – S11    | CC1 – CC11  | Corto (CC)    |
| S12 – S20   | CL1 – CL9   | Largo (CL)    |

---

## 📝 Notas

- El firmware registra una medición aproximadamente cada **8 segundos** (`delay(1000)` + `delay(7000)` + tiempo de conversión del sensor).
- Las lecturas de `-127 °C` o valores por debajo de `-120 °C` indican errores de comunicación del sensor y son eliminadas automáticamente por `csvGrapher.ipynb`.
- Para ajustar la hora del RTC DS3231, descomenta y modifica la siguiente línea en `setup()`, sube el sketch y vuelve a comentarla:
  ```cpp
  // rtc.adjust(DateTime(2025, 8, 5, 16, 02, 00));
  ```
