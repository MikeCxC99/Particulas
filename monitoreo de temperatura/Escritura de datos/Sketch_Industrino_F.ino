#include <OneWire.h>
#include <DallasTemperature.h>
#include <SPI.h>
#include <SD.h>
#include <Wire.h>
#include <RTClib.h>  // Librería compatible con DS3231

#define ONE_WIRE_BUS 2
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

int numberOfDevices;
DeviceAddress tempDeviceAddress;
const int chipSelect = 53;

RTC_DS3231 rtc;

// Direcciones de sensores DS18B20 ordenadas (nombre real)
DeviceAddress sensoresOrdenados[] = {
  // Cortos (CC)
  {0x28, 0x09, 0xFC, 0x46, 0xD4, 0x3B, 0x39, 0x4D},  // CC1 = S1
  {0x28, 0xDB, 0x35, 0x94, 0x97, 0x0F, 0x03, 0x33},  // CC2 = S2
  {0x28, 0x0D, 0x9A, 0x45, 0xD4, 0x67, 0x59, 0xCB},  // CC3 = S3
  {0x28, 0xAD, 0xBF, 0x46, 0xD4, 0x79, 0x0C, 0xE1},  // CC4 = S4
  {0x28, 0x74, 0x65, 0x94, 0x97, 0x0E, 0x03, 0x1A},  // CC5 = S5
  {0x28, 0x27, 0xEF, 0x45, 0xD4, 0x43, 0x3C, 0xAD},  // CC6 = S6
  {0x28, 0x2A, 0x69, 0x46, 0xD4, 0x07, 0x7F, 0x3C},  // CC7 = S7
  {0x28, 0x1D, 0xD6, 0x45, 0xD4, 0xC0, 0x7B, 0x47},  // CC8 = S8
  {0x28, 0xB5, 0x50, 0x46, 0xD4, 0x31, 0x05, 0xDF},  // CC9 = S9
  {0x28, 0xAB, 0x5C, 0x46, 0xD4, 0x24, 0x5C, 0xE2},  // CC10 = S10
  {0x28, 0xE5, 0x10, 0x45, 0xD4, 0x3F, 0x6D, 0xEB},  // CC11 = S11

  // Largos (CL)
  {0x28, 0x3A, 0xC6, 0x68, 0xB2, 0x23, 0x06, 0xB4},  // CL1 = S12 
  {0x28, 0x76, 0xBC, 0x8E, 0xB2, 0x23, 0x06, 0x2C},  // CL2 = S13
  {0x28, 0x3F, 0x8F, 0xB9, 0xB2, 0x23, 0x06, 0xCB},  // CL3 = S14
  {0x28, 0x88, 0xFF, 0xE0, 0xB2, 0x23, 0x06, 0x6F},  // CL4 = S15
  {0x28, 0x26, 0x25, 0xDD, 0xB2, 0x23, 0x06, 0x16},  // CL5 = S16
  {0x28, 0xC8, 0xBD, 0x89, 0xB0, 0x23, 0x09, 0x7D},  // CL6 = S17
  {0x28, 0x4B, 0x69, 0xEB, 0xB2, 0x23, 0x06, 0x16},  // CL7 = S18
  {0x28, 0x28, 0xCB, 0xF6, 0xB2, 0x23, 0x06, 0x99},  // CL8 = S19
  {0x28, 0x76, 0x14, 0xBB, 0xB2, 0x23, 0x06, 0xE8}   // CL9 = S20
};

const int numSensores = sizeof(sensoresOrdenados) / sizeof(sensoresOrdenados[0]);

void setup() {
  Serial.begin(9600);
  while (!Serial);
  delay(200);

  Serial.println("RTC DS3231 Read Test");
  Serial.println("--------------------");
  Serial.println("Conectado");
  Serial.print("Buscando tarjeta SD...");

  if (!SD.begin(chipSelect)) {
    Serial.println("Error, No encontrada.");
    while (1); // Detiene ejecución si no hay SD
  }
  Serial.println("Tarjeta SD encontrada.");

  Wire.begin();

  if (!rtc.begin()) {
    Serial.println("No se encontró el RTC");
    while (1);
  }

  // rtc.adjust(DateTime(2025, 8, 5, 16, 02, 00));

  sensors.begin();
  numberOfDevices = sensors.getDeviceCount();

  Serial.print("Buscando sensores...");
  Serial.print("Se encontraron ");
  Serial.print(numberOfDevices, DEC);
  Serial.println(" sensores.");

  for (int i = 0; i < numSensores; i++) {
    Serial.print("Se encontró S");
    Serial.print(i + 1);
    Serial.print(" con dirección: ");
    printAddress(sensoresOrdenados[i]);
    Serial.println();
  }
}

void loop() {
  delay(1000);
  DateTime now = rtc.now();

  sensors.requestTemperatures();

  String dataString = "";

  // Agrega fecha y hora al principio
  dataString += format2digits(now.year());
  dataString += "-";
  dataString += format2digits(now.month());
  dataString += "-";
  dataString += format2digits(now.day());
  dataString += ",";
  dataString += format2digits(now.hour());
  dataString += ":";
  dataString += format2digits(now.minute());
  dataString += ":";
  dataString += format2digits(now.second());
  dataString += ",";
  dataString += " Unidad: C°,";

  for (int i = 0; i < numSensores; i++) {
    float tempC = sensors.getTempC((uint8_t*)sensoresOrdenados[i]);

    dataString += "S";
    dataString += String(i + 1);  // CC1, CC2, ...
    dataString += ": ";
    dataString += String(tempC, 2);
  }

  // Elimina la última coma para que no quede colgando
  if (dataString.endsWith(",")) {
    dataString.remove(dataString.length() - 1);
    dataString += ".";
  }

  File dataFile = SD.open("datalog.txt", FILE_WRITE);

  if (dataFile) {
    dataFile.println(dataString);
    dataFile.close();
    Serial.println(dataString);

  } else {
    Serial.println("error abriendo datalog.txt");
    while (1);
  }

  Serial.println(" ");
  delay(7000);
}

void printAddress(DeviceAddress deviceAddress) {
  for (uint8_t i = 0; i < 8; i++) {
    if (deviceAddress[i] < 16) Serial.print("0");
    Serial.print(deviceAddress[i], HEX);
  }
}

String format2digits(int number) {
  if (number < 10) return "0" + String(number);
  return String(number);
}

