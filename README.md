# 🔬 Particulas — Instrumentación y Adquisición de Datos

Repositorio de herramientas de instrumentación física para laboratorio. Incluye dos subsistemas:

- **Virtual Network Analyzer (CableMaster Pro v12)**: caracterización de cables coaxiales con NanoVNA V2 Plus4.
- **Monitoreo de Temperatura**: adquisición con 20 sensores DS18B20 y postproceso en notebooks.

---

## 📁 Estructura

```text
Particulas/
├── VirtualNetworkAnalyzer/
│   ├── VNADefv12.py
│   └── README.md
├── monitoreo de temperatura/
│   ├── Escritura de datos/
│   │   ├── Sketch_Industrino_F.ino
│   │   └── README.md
│   ├── Interpretacion TXT/
│   │   ├── txtConverter.ipynb
│   │   ├── csvGrapher.ipynb
│   │   └── README.md
│   └── README.md
└── README.md
```

---

## 📡 Virtual Network Analyzer (v12)

- **Script principal**: `VirtualNetworkAnalyzer/VNADefv12.py`
- **Documentación técnica completa**: `VirtualNetworkAnalyzer/README.md`

La versión actual automatiza calibración SOLT, medición S11/S21, cálculo de métricas RF (RL, VSWR, impedancia, IL, TDR, group delay), detección de anomalías y exportación de resultados en CSV (y PNG opcional).

> ℹ️ Si venías usando la documentación de **v5**, fue eliminada del directorio antiguo `Virtual Network Analyzer/`. Se documentó la migración y diferencias en el README de `VirtualNetworkAnalyzer/`.

---

## 🌡️ Monitoreo de Temperatura

- **Firmware**: `monitoreo de temperatura/Escritura de datos/Sketch_Industrino_F.ino`
- **Procesamiento**: notebooks en `monitoreo de temperatura/Interpretacion TXT/`
- **Documentación**: `monitoreo de temperatura/README.md`

Sistema basado en 20 sensores DS18B20, RTC DS3231 y registro en SD para análisis posterior en Python.

---

## 🛠️ Inicio rápido

### Virtual Network Analyzer

```bash
pip install pyserial numpy scipy matplotlib
python /home/runner/work/Particulas/Particulas/VirtualNetworkAnalyzer/VNADefv12.py
```

Antes de ejecutar, ajustar el bloque de configuración al inicio del script (`PORT`, rango de frecuencia, modo de sweep, VF, etc.).

### Monitoreo de Temperatura

```bash
pip install pandas seaborn matplotlib jupyterlab
jupyter lab "/home/runner/work/Particulas/Particulas/monitoreo de temperatura/Interpretacion TXT/"
```

---

## 📄 Licencia

MIT.
