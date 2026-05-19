# 🔬 Particulas — Instrumentación y Adquisición de Datos

[![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=flat&logo=python)](https://www.python.org/)
[![Arduino](https://img.shields.io/badge/Arduino-Industrino-00979D?style=flat&logo=arduino)](https://www.arduino.cc/)
[![License](https://img.shields.io/badge/Licencia-MIT-yellow?style=flat)](LICENSE)

Repositorio de herramientas de **instrumentación física** desarrolladas para proyectos de adquisición, análisis y visualización de datos en laboratorio. Actualmente contiene dos subsistemas independientes:

| Subsistema | Descripción breve | Estado |
|---|---|---|
| [Virtual Network Analyzer](./Virtual%20Network%20Analyzer/) | Medición de cables coaxiales con NanoVNA V2 | 🚧 WIP |
| [Monitoreo de Temperatura](./monitoreo%20de%20temperatura/) | Red de 20 sensores DS18B20 con registro en SD | ✅ Estable |

---

## 📁 Estructura del Repositorio

```
Particulas/
│
├── Virtual Network Analyzer/
│   ├── VNADefv5.py          # Script principal de medición (CableMaster Pro v5)
│   └── README.md            # Documentación completa del VNA
│
├── monitoreo de temperatura/
│   ├── Escritura de datos/
│   │   └── Sketch_Industrino_F.ino   # Firmware Arduino (adquisición)
│   ├── Interpretacion TXT/
│   │   ├── txtConverter.ipynb        # Notebook: conversión TXT → CSV
│   │   ├── csvGrapher.ipynb          # Notebook: filtrado y heatmap
│   │   └── *.TXT / *.csv            # Datos de ejemplo
│   └── README.md            # Documentación completa del sistema de temperatura
│
└── README.md                # Este archivo
```

---

## ⚡ Virtual Network Analyzer

**Script:** `Virtual Network Analyzer/VNADefv5.py`

Herramienta de línea de comandos para **caracterizar cables coaxiales** usando un NanoVNA V2 Plus4. Mide parámetros S (S11 / S21), calcula Return Loss, VSWR, impedancia, Insertion Loss, TDR y retardo de grupo; clasifica cada cable como PASS / WARN / FAIL y exporta resultados en CSV y PNG.

> ⚠️ **WIP** — Algunas frecuencias pueden arrojar datos inconsistentes. Ver la sección de problemas conocidos en la [documentación del VNA](./Virtual%20Network%20Analyzer/README.md).

**Requisitos principales:** Python 3.x · `pyserial` · `numpy` · `scipy` · `matplotlib`

---

## 🌡️ Monitoreo de Temperatura

**Firmware:** `monitoreo de temperatura/Escritura de datos/Sketch_Industrino_F.ino`  
**Análisis:** Notebooks Jupyter en `monitoreo de temperatura/Interpretacion TXT/`

Sistema de adquisición con **20 sensores DS18B20**, RTC DS3231 y almacenamiento en tarjeta SD montado sobre una placa Industrino (compatible Arduino Mega). Los datos se procesan con notebooks Python que convierten los logs a CSV y generan mapas de calor.

**Requisitos principales:** IDE Arduino · OneWire · DallasTemperature · RTClib · Python 3 · pandas · seaborn · matplotlib

---

## 🛠️ Inicio Rápido

### Virtual Network Analyzer

```bash
# Instalar dependencias
pip install pyserial numpy scipy matplotlib

# Editar el bloque CONFIG al inicio de VNADefv5.py (puerto, rango de frecuencias, modo)
# Ejecutar
python "Virtual Network Analyzer/VNADefv5.py"
```

### Monitoreo de Temperatura

```bash
# Instalar dependencias Python
pip install pandas seaborn matplotlib jupyterlab

# Abrir los notebooks
jupyter lab "monitoreo de temperatura/Interpretacion TXT/"
```

Para el firmware Arduino, ver instrucciones en el [README de temperatura](./monitoreo%20de%20temperatura/README.md).

---

## 📄 Licencia

MIT — libre para uso, modificación y distribución con atribución.
