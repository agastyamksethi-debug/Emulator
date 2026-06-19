/*
 * ESP32 Arduino Library Header
 * Complete API wrapper for simulated Arduino sketch execution
 */

#ifndef _ESP32_ARDUINO_H_
#define _ESP32_ARDUINO_H_

#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

// ─────────────────────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────────────────────

// GPIO Modes
#define INPUT           0
#define OUTPUT          1
#define INPUT_PULLUP    2
#define INPUT_PULLDOWN  3
#define ANALOG          5
#define PWM             6

// Logic Levels
#define LOW             0
#define HIGH            1

// ADC Attenuation
#define ADC_0db         0
#define ADC_2_5db       1
#define ADC_6db         2
#define ADC_11db        3

// Interrupt Modes
#define DISABLE         0
#define RISING          1
#define FALLING         2
#define CHANGE          3
#define ONLOW           4
#define ONHIGH          5
#define ONLOW_WE        12
#define ONHIGH_WE       13

// UART Interfaces
#define UART0           0
#define UART1           1
#define UART2           2

// I2C Interfaces
#define I2C0            0
#define I2C1            1

// SPI Interfaces
#define SPI_2           HSPI
#define SPI_3           VSPI
#define HSPI            1
#define VSPI            2

// SPI Modes
#define SPI_MODE0       0
#define SPI_MODE1       1
#define SPI_MODE2       2
#define SPI_MODE3       3

// ─────────────────────────────────────────────────────────────
// DIGITAL I/O
// ─────────────────────────────────────────────────────────────

void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t val);
int digitalRead(uint8_t pin);

// ─────────────────────────────────────────────────────────────
// ANALOG I/O
// ─────────────────────────────────────────────────────────────

void analogWrite(uint8_t pin, int val);
int analogRead(uint8_t pin);
void analogReference(uint8_t mode);

// ─────────────────────────────────────────────────────────────
// ADC (Analog-to-Digital Converter)
// ─────────────────────────────────────────────────────────────

void analogReadResolution(uint8_t bits);
void analogSetWidth(uint8_t bits);
void analogSetClockDiv(uint8_t clockDiv);
void analogSetAttenuation(uint8_t attenuation);
void analogSetPinAttenuation(uint8_t pin, uint8_t attenuation);
int analogRead(uint8_t pin);
int analogReadMilliVolts(uint8_t pin);

// ─────────────────────────────────────────────────────────────
// DAC (Digital-to-Analog Converter)
// ─────────────────────────────────────────────────────────────

void dacWrite(uint8_t pin, uint8_t value);

// ─────────────────────────────────────────────────────────────
// PWM / LEDC (LED Controller)
// ─────────────────────────────────────────────────────────────

void ledcSetup(uint8_t channel, uint32_t freq, uint8_t resolution_bits);
void ledcAttachPin(uint8_t pin, uint8_t channel);
void ledcDetachPin(uint8_t pin);
void ledcWrite(uint8_t channel, uint32_t duty);
uint32_t ledcRead(uint8_t channel);
uint32_t ledcReadFreq(uint8_t channel);
double ledcReadResolution(uint8_t channel);
uint32_t ledcChangeFrequency(uint8_t channel, uint32_t freq, uint8_t resolution_bits);

// ─────────────────────────────────────────────────────────────
// TONE / SOUND OUTPUT
// ─────────────────────────────────────────────────────────────

void tone(uint8_t pin, unsigned int frequency, unsigned long duration = 0);
void noTone(uint8_t pin);

// ─────────────────────────────────────────────────────────────
// TIME FUNCTIONS
// ─────────────────────────────────────────────────────────────

unsigned long millis(void);
unsigned long micros(void);
void delay(uint32_t ms);
void delayMicroseconds(uint32_t us);

// ─────────────────────────────────────────────────────────────
// INTERRUPTS
// ─────────────────────────────────────────────────────────────

typedef void (*voidFuncPtr)(void);
typedef void (*voidFuncPtrArg)(void *);

void attachInterrupt(uint8_t pin, voidFuncPtr handler, int mode);
void attachInterruptArg(uint8_t pin, voidFuncPtrArg handler, void *arg, int mode);
void detachInterrupt(uint8_t pin);
void detachInterrupt(uint8_t pin);
void interrupts(void);
void noInterrupts(void);

// ─────────────────────────────────────────────────────────────
// TIMER INTERFACE
// ─────────────────────────────────────────────────────────────

typedef struct hw_timer_s {
    uint32_t index;
    uint32_t reserved;
} hw_timer_t;

hw_timer_t * timerBegin(uint8_t num, uint16_t divider, bool countUp);
void timerEnd(hw_timer_t * timer);
void timerWrite(hw_timer_t * timer, uint64_t val);
uint64_t timerRead(hw_timer_t * timer);
void timerAlarmWrite(hw_timer_t * timer, uint64_t alarm_value, bool autoreload);
void timerAttachInterrupt(hw_timer_t * timer, void (*userFunc)(void), bool edge);
void timerDetachInterrupt(hw_timer_t * timer);
void timerAlarmEnable(hw_timer_t * timer);
void timerAlarmDisable(hw_timer_t * timer);

// ─────────────────────────────────────────────────────────────
// TOUCH SENSOR
// ─────────────────────────────────────────────────────────────

uint16_t touchRead(uint8_t pin);
void touchAttachInterrupt(uint8_t pin, void (*userFunc)(void), uint16_t threshold);
void touchDetachInterrupt(uint8_t pin);

// ─────────────────────────────────────────────────────────────
// UART INTERFACE
// ─────────────────────────────────────────────────────────────

class HardwareSerial {
public:
    HardwareSerial(uint8_t uart_num);
    void begin(unsigned long baud, uint32_t config = 0, int8_t rxPin = -1, int8_t txPin = -1);
    void end(void);
    size_t write(const uint8_t *buffer, size_t size);
    size_t write(uint8_t c);
    int read(void);
    int peek(void);
    void flush(void);
    int available(void);
    void setTimeout(unsigned long timeout);

    // Print interface
    size_t print(const char *str);
    size_t println(const char *str);
    size_t print(int val);
    size_t println(int val);

private:
    uint8_t _uart_num;
};

extern HardwareSerial Serial;   // UART0
extern HardwareSerial Serial1;  // UART1
extern HardwareSerial Serial2;  // UART2

// ─────────────────────────────────────────────────────────────
// I2C INTERFACE
// ─────────────────────────────────────────────────────────────

class TwoWire {
public:
    TwoWire(uint8_t i2c_num);
    void begin(int sda = -1, int scl = -1, uint32_t frequency = 100000);
    void end(void);
    void setClock(uint32_t clock);
    void setTimeOut(uint16_t timeOut);
    uint32_t getClock();

    void beginTransmission(uint8_t address);
    uint8_t endTransmission(bool sendStop = true);
    uint8_t requestFrom(uint8_t address, uint8_t size, bool sendStop = true);

    size_t write(uint8_t data);
    size_t write(const uint8_t *data, size_t len);
    int read(void);
    int available(void);

private:
    uint8_t _i2c_num;
};

extern TwoWire Wire;   // I2C0
extern TwoWire Wire1;  // I2C1

// ─────────────────────────────────────────────────────────────
// SPI INTERFACE
// ─────────────────────────────────────────────────────────────

class SPIClass {
public:
    SPIClass(uint8_t spi_num);
    void begin(int sck = -1, int miso = -1, int mosi = -1, int ss = -1);
    void end(void);
    void setFrequency(uint32_t freq);
    void setClockDivider(uint32_t clockDiv);
    void setDataMode(uint8_t dataMode);
    void setBitOrder(uint8_t bitOrder);
    void setHwCs(bool use);
    void setCS(int cs);
    uint8_t transfer(uint8_t data);
    uint16_t transfer16(uint16_t data);
    uint32_t transfer32(uint32_t data);
    void transferBytes(const uint8_t *data, uint8_t *out, uint32_t size);
    void transferBits(uint32_t data, uint32_t *out, uint8_t bits);
    void write(const uint8_t *data, uint32_t size);

private:
    uint8_t _spi_num;
};

extern SPIClass SPI;    // SPI1 (VSPI)
extern SPIClass SPI1;   // SPI2 (HSPI)

// ─────────────────────────────────────────────────────────────
// SYSTEM FUNCTIONS
// ─────────────────────────────────────────────────────────────

uint32_t getChipId(void);
uint32_t getCpuFrequencyMhz(void);
uint32_t getAPBFrequency(void);
uint32_t getCrystalFrequency(void);
uint32_t getHeapSize(void);
uint32_t getFreeHeap(void);
uint32_t getMaxAllocHeap(void);
uint32_t getSketchSize(void);
uint32_t getFreeSketchSpace(void);
uint8_t *getSdkVersion(void);
const char *getChipModel(void);
uint8_t getChipCores(void);
uint32_t getChipRevision(void);

void setCpuFrequencyMhz(uint32_t freq);
void sleepDelay(uint32_t ms);
void lightSleep(uint32_t time_in_ms);
void deepSleep(uint32_t time_in_us);
void wake(void);

#endif // _ESP32_ARDUINO_H_
