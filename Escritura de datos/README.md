# 📟 Sketch Arduino — Escritura de Datos

Este firmware lee la temperatura de **20 sensores DS18B20** conectados en un bus OneWire, registra la fecha y hora con un módulo **RTC DS3231** y guarda los datos en una **tarjeta SD** en formato `.TXT`.

---

## ⚙️ Configuración de Hardware

| Parámetro                  | Valor                              |
|----------------------------|------------------------------------|
| **Pin OneWire (sensores)**  | `2`                                |
| **Pin CS (tarjeta SD)**     | `53`                               |
| **Módulo RTC**              | DS3231 (comunicación I²C)          |

### Sensores DS18B20

Los 20 sensores están identificados por su dirección única de 64 bits, definida en el arreglo `sensoresOrdenados[]`:

| Índice | ID en datos | Nombre real | Tipo de cable |
|--------|-------------|-------------|---------------|
| 0      | S1          | CC1         | Corto         |
| 1      | S2          | CC2         | Corto         |
| 2      | S3          | CC3         | Corto         |
| 3      | S4          | CC4         | Corto         |
| 4      | S5          | CC5         | Corto         |
| 5      | S6          | CC6         | Corto         |
| 6      | S7          | CC7         | Corto         |
| 7      | S8          | CC8         | Corto         |
| 8      | S9          | CC9         | Corto         |
| 9      | S10         | CC10        | Corto         |
| 10     | S11         | CC11        | Corto         |
| 11     | S12         | CL1         | Largo         |
| 12     | S13         | CL2         | Largo         |
| 13     | S14         | CL3         | Largo         |
| 14     | S15         | CL4         | Largo         |
| 15     | S16         | CL5         | Largo         |
| 16     | S17         | CL6         | Largo         |
| 17     | S18         | CL7         | Largo         |
| 18     | S19         | CL8         | Largo         |
| 19     | S20         | CL9         | Largo         |

---

## 📦 Librerías Requeridas

Instala las siguientes librerías desde el **Gestor de Librerías del IDE de Arduino**:

| Librería           | Autor              | Uso                                    |
|--------------------|--------------------|----------------------------------------|
| `OneWire`          | Paul Stoffregen    | Comunicación con sensores DS18B20      |
| `DallasTemperature`| Miles Burton       | Lectura de temperatura de los sensores |
| `RTClib`           | Adafruit           | Módulo RTC DS3231                      |
| `SPI`              | *(incluida)*       | Comunicación con tarjeta SD            |
| `SD`               | *(incluida)*       | Escritura en tarjeta SD                |
| `Wire`             | *(incluida)*       | Comunicación I²C con el RTC            |

---

## 🔄 Funcionamiento

### `setup()`

1. Inicializa la comunicación serie a 9600 baud.
2. Detecta e inicializa la tarjeta SD (se detiene si no se encuentra).
3. Inicializa el módulo RTC DS3231 (se detiene si no se encuentra).
4. Detecta los sensores DS18B20 e imprime sus direcciones por el puerto serie.

### `loop()`

Cada iteración del bucle principal (~8 segundos):

1. Espera 1 segundo.
2. Obtiene la fecha y hora actual del RTC.
3. Solicita la lectura de temperatura a todos los sensores del bus.
4. Construye una cadena de datos con el formato de salida.
5. Abre `datalog.txt` en la SD y escribe la línea de datos.
6. Imprime los datos por el puerto serie.
7. Espera 7 segundos adicionales.

---

## 📄 Formato de Salida

Cada línea escrita en `datalog.txt` tiene el siguiente formato:

```
YYYY-MM-DD,HH:MM:SS, Unidad: C°,S1: XX.XXS2: XX.XX ... S20: XX.XX.
```

**Ejemplo:**

```
2025-08-07,19:14:30, Unidad: C°,S1: 20.38S2: 20.00 S3: 20.25 ... S20: 20.00.
```

> **Nota:** Los valores de temperatura se reportan en grados Celsius con dos decimales.

---

## 🕰️ Ajuste del RTC

Para sincronizar la hora del módulo DS3231, descomenta la siguiente línea en `setup()` y ajusta la fecha y hora deseada:

```cpp
// rtc.adjust(DateTime(2025, 8, 5, 16, 02, 00));
```

⚠️ **Importante:** Después de cargar el sketch con esta línea activa y verificar que el RTC se sincronizó correctamente, vuelve a comentarla y recarga el sketch. De lo contrario, el RTC se reseteará a esa fecha cada vez que se reinicie la placa.
