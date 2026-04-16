# 📊 Interpretación de Datos — Notebooks Jupyter

Esta carpeta contiene los notebooks Jupyter para el procesamiento y visualización de los datos de temperatura registrados por el firmware Arduino.

---

## 📁 Contenido

| Archivo                      | Descripción                                                              |
|------------------------------|--------------------------------------------------------------------------|
| `txtConverter.ipynb`         | Convierte archivos `.TXT` de datalog a formato `.CSV`                    |
| `csvGrapher.ipynb`           | Filtra el `.CSV` y genera un mapa de calor (*heatmap*)                   |
| `1730.TXT`                   | Datalog de ejemplo: 2025-08-07 19:14 → 2025-08-08 13:04 (~6989 filas)   |
| `20250808_1745-1750.TXT`     | Datalog de ejemplo: 2025-08-08 17:45 → 17:50 (intervalo corto)          |
| `Datalog_A.csv`              | CSV generado a partir de `1730.TXT`                                      |
| `Datalog_Filtered_A.csv`     | CSV filtrado (sin lecturas inválidas < −120 °C)                          |

---

## ⚙️ Requisitos

- Python 3.x
- Jupyter Lab o Jupyter Notebook

Instala las dependencias con:

```bash
pip install pandas seaborn matplotlib jupyterlab
```

---

## 🗂️ Flujo de Trabajo

```
datalog.txt
    │
    ▼
txtConverter.ipynb  ──►  Datalog.csv
                              │
                              ▼
                    csvGrapher.ipynb
                         ├──►  Datalog_Filtered.csv
                         └──►  Heatmap (visualización)
```

---

## 📓 `txtConverter.ipynb` — Conversión TXT → CSV

### Descripción

Convierte el archivo `.TXT` generado por el firmware Arduino a un archivo `.CSV` estructurado con columnas `Date`, `Time`, `Unit`, `S1`, `S2`, …, `S20`.

El notebook incluye dos variantes de conversión:

- **Celda 1 — Filtrado por rango de fechas:** Extrae únicamente las mediciones comprendidas entre una fecha de inicio y una fecha de fin especificadas.
- **Celda 2 — Conversión directa:** Convierte todo el archivo `.TXT` sin filtrar por fecha, usando expresiones regulares para parsear los valores de cada sensor.

### Variables de Configuración

**Celda 1 (filtrado por rango de fechas):**

| Variable       | Descripción                          |
|----------------|--------------------------------------|
| `start_year`   | Año de inicio del rango              |
| `start_month`  | Mes de inicio del rango              |
| `start_day`    | Día de inicio del rango              |
| `end_year`     | Año de fin del rango                 |
| `end_month`    | Mes de fin del rango                 |
| `end_day`      | Día de fin del rango                 |
| `input_filename`  | Nombre del archivo `.TXT` de entrada |
| `output_filename` | Nombre del archivo `.CSV` de salida  |

**Celda 2 (conversión directa):**

| Variable            | Descripción                          |
|---------------------|--------------------------------------|
| `input_filename`    | Nombre del archivo `.TXT` de entrada |
| `output_filename`   | Nombre del archivo `.CSV` de salida  |

### Salida

Archivo `.CSV` con las columnas: `Date`, `Time`, `Unit`, `S1`, `S2`, …, `S20`.

---

## 📓 `csvGrapher.ipynb` — Filtrado y Visualización

### Descripción

Procesa el archivo `.CSV` en dos etapas:

1. **Filtrado (Celda 1):** Elimina las filas que contengan al menos una lectura de temperatura por debajo del umbral configurado (−120 °C por defecto). Los valores de −127 °C corresponden a errores de comunicación del sensor DS18B20 y deben ser descartados.

2. **Visualización (Celda 2):** Genera un mapa de calor (*heatmap*) con `seaborn`, mostrando la variación de temperatura de los 20 sensores a lo largo del tiempo.

### Variables de Configuración

**Celda 1 — Filtrado:**

| Variable               | Descripción                                              |
|------------------------|----------------------------------------------------------|
| `input_csv_filename`   | CSV de entrada (sin filtrar)                             |
| `output_csv_filename`  | CSV de salida (filtrado)                                 |
| `temperature_threshold`| Umbral mínimo de temperatura; filas con valores inferiores son eliminadas (default: `−120.0`) |

**Celda 2 — Visualización:**

| Variable             | Descripción                    |
|----------------------|--------------------------------|
| `input_csv_filename` | CSV de entrada para graficar   |

### Parámetros del Heatmap

| Parámetro        | Valor                                          |
|------------------|------------------------------------------------|
| Remuestreo       | Promedio cada 10 segundos                      |
| Escala de color  | `coolwarm` (azul = frío, rojo = caliente)      |
| Anotaciones      | Valor de temperatura en cada celda (1 decimal) |
| Eje X            | Tiempo                                         |
| Eje Y            | Sensor (S1 a S20)                              |

---

## 📝 Notas

- Coloca los archivos de datos (`.TXT` o `.CSV`) en la **misma carpeta** que los notebooks antes de ejecutarlos.
- Las lecturas inválidas más comunes son `−127 °C` (error de bus OneWire) y `85 °C` (temperatura de encendido del sensor). Se recomienda revisar los datos si aparecen valores de `85 °C`.
