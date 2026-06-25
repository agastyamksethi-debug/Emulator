#pragma once
/**
 * sim_arduino.h — Fake Arduino.h for the PCB simulator.
 *
 * Every Arduino API call sends a line to Python over stdout and waits for
 * a response over stdin.  Python drives the simulation bus and responds.
 *
 * Protocol (C++ → Python, one line each):
 *   PM  <pin> <mode>              pinMode          → OK
 *   DW  <pin> <val>              digitalWrite     → OK
 *   DR  <pin>                    digitalRead      → <int>
 *   AR  <pin>                    analogRead       → <int>
 *   AW  <pin> <val>              analogWrite      → OK
 *   LEDC_SETUP <ch> <freq> <res> ledcSetup        → OK
 *   LEDC_ATTACH <pin> <ch>       ledcAttachPin    → OK
 *   LEDC_WRITE <ch> <duty>       ledcWrite        → OK
 *   LEDC_DETACH <pin>            ledcDetachPin    → OK
 *   DELAY <ms>                   delay()          → OK  (after sim advances)
 *   MILLIS                       millis()         → <int>
 *   SER <text>                   Serial.print     → OK
 *   SERLN <text>                 Serial.println   → OK
 *   SER_AVAIL                    Serial.available → <int>
 *   SER_READ                     Serial.read      → <int>
 *   I2CW <addr> <hexbytes>       Wire write txn   → <status int> (0 = ACK)
 *   I2CR <addr> <len>            Wire requestFrom → <hexbytes>
 *   READY                        setup() done    (no response)
 */

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>

// ── Arduino constants ────────────────────────────────────────────────────────
#define HIGH          1
#define LOW           0
#define INPUT         0
#define OUTPUT        1
#define INPUT_PULLUP  2
#define INPUT_PULLDOWN 3
#define DEC 10
#define HEX 16
#define OCT 8
#define BIN 2
#define RISING  1
#define FALLING 2
#define CHANGE  3
#define IRAM_ATTR
#define LED_BUILTIN   2
#define A0  36
#define A1  37
#define A2  38
#define A3  39
#define A4  32
#define A5  33

typedef unsigned long ulong;
typedef unsigned char byte;
typedef bool boolean;

// ── IPC primitives ───────────────────────────────────────────────────────────
static inline void _sim_writeln(const char* line) {
    fputs(line, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

static inline void _sim_readline(char* buf, int size) {
    if (!fgets(buf, size, stdin)) { buf[0] = '\0'; return; }
    int n = (int)strlen(buf);
    if (n > 0 && buf[n-1] == '\n') buf[n-1] = '\0';
}

static inline void _sim_recv_ok(void) {
    char buf[8];
    _sim_readline(buf, sizeof(buf));
}

static inline int _sim_recv_int(void) {
    char buf[32];
    _sim_readline(buf, sizeof(buf));
    return atoi(buf);
}

// ── GPIO ─────────────────────────────────────────────────────────────────────
inline void pinMode(int pin, int mode) {
    char msg[32];
    snprintf(msg, sizeof(msg), "PM %d %d", pin, mode);
    _sim_writeln(msg);
    _sim_recv_ok();
}

inline void digitalWrite(int pin, int value) {
    char msg[32];
    snprintf(msg, sizeof(msg), "DW %d %d", pin, value);
    _sim_writeln(msg);
    _sim_recv_ok();
}

inline int digitalRead(int pin) {
    char msg[32];
    snprintf(msg, sizeof(msg), "DR %d", pin);
    _sim_writeln(msg);
    return _sim_recv_int();
}

inline int analogRead(int pin) {
    char msg[32];
    snprintf(msg, sizeof(msg), "AR %d", pin);
    _sim_writeln(msg);
    return _sim_recv_int();
}

inline void analogWrite(int pin, int value) {
    char msg[32];
    snprintf(msg, sizeof(msg), "AW %d %d", pin, value);
    _sim_writeln(msg);
    _sim_recv_ok();
}

inline void dacWrite(int pin, int value) { analogWrite(pin, value); }

// ── LEDC / PWM (ESP32) ───────────────────────────────────────────────────────
// Classic API: ledcSetup → ledcAttachPin → ledcWrite
inline void ledcSetup(int channel, double freq, int resolution_bits) {
    char msg[64];
    snprintf(msg, sizeof(msg), "LEDC_SETUP %d %.2f %d", channel, freq, resolution_bits);
    _sim_writeln(msg);
    _sim_recv_ok();
}

inline void ledcAttachPin(int pin, int channel) {
    char msg[32];
    snprintf(msg, sizeof(msg), "LEDC_ATTACH %d %d", pin, channel);
    _sim_writeln(msg);
    _sim_recv_ok();
}

inline void ledcWrite(int channel, int duty) {
    char msg[32];
    snprintf(msg, sizeof(msg), "LEDC_WRITE %d %d", channel, duty);
    _sim_writeln(msg);
    _sim_recv_ok();
}

inline void ledcDetachPin(int pin) {
    char msg[32];
    snprintf(msg, sizeof(msg), "LEDC_DETACH %d", pin);
    _sim_writeln(msg);
    _sim_recv_ok();
}

// ── External interrupts ──────────────────────────────────────────────────────
// ISRs run cooperatively: Python queues fired pins as the sim advances; the
// firmware drains them at each delay() (the safe service point).
typedef void (*_isr_fn)(void);
static _isr_fn _isr_table[48] = {0};

inline int digitalPinToInterrupt(int pin) { return pin; }

inline void attachInterrupt(int pin, _isr_fn isr, int mode) {
    if (pin >= 0 && pin < 48) _isr_table[pin] = isr;
    char msg[32];
    snprintf(msg, sizeof(msg), "IATT %d %d", pin, mode);
    _sim_writeln(msg);
    _sim_recv_ok();
}

inline void detachInterrupt(int pin) {
    if (pin >= 0 && pin < 48) _isr_table[pin] = 0;
    char msg[32];
    snprintf(msg, sizeof(msg), "IDET %d", pin);
    _sim_writeln(msg);
    _sim_recv_ok();
}

inline void interrupts(void)   {}
inline void noInterrupts(void) {}

static inline void _sim_service_isr(void) {
    for (;;) {
        _sim_writeln("IPOLL");
        int pin = _sim_recv_int();
        if (pin < 0) break;
        if (pin < 48 && _isr_table[pin]) _isr_table[pin]();
    }
}

// ── Timing ───────────────────────────────────────────────────────────────────
inline void delay(unsigned long ms) {
    char msg[32];
    snprintf(msg, sizeof(msg), "DELAY %lu", ms);
    _sim_writeln(msg);
    _sim_recv_ok();
    _sim_service_isr();
}

inline void delayMicroseconds(unsigned long us) {
    delay(us >= 1000UL ? us / 1000UL : 1UL);
}

inline unsigned long millis(void) {
    _sim_writeln("MILLIS");
    return (unsigned long)_sim_recv_int();
}

inline unsigned long micros(void) {
    return millis() * 1000UL;
}

// ── Serial ───────────────────────────────────────────────────────────────────
struct _SerialClass {
    void begin(unsigned long /*baud*/) {}

    void _emit(const char* text, bool newline) {
        char msg[512];
        snprintf(msg, sizeof(msg), newline ? "SERLN %s" : "SER %s", text);
        _sim_writeln(msg);
        _sim_recv_ok();
    }

    void print(const char* s)              { _emit(s, false); }
    void println(const char* s)            { _emit(s, true);  }
    void println()                         { _emit("", true); }
    void print(int v)                      { char b[32]; snprintf(b,32,"%d",v);    _emit(b, false); }
    void println(int v)                    { char b[32]; snprintf(b,32,"%d",v);    _emit(b, true);  }
    void print(long v)                     { char b[32]; snprintf(b,32,"%ld",v);   _emit(b, false); }
    void println(long v)                   { char b[32]; snprintf(b,32,"%ld",v);   _emit(b, true);  }
    void print(unsigned long v)            { char b[32]; snprintf(b,32,"%lu",v);   _emit(b, false); }
    void println(unsigned long v)          { char b[32]; snprintf(b,32,"%lu",v);   _emit(b, true);  }
    void print(double v, int p = 2)        { char b[32]; snprintf(b,32,"%.*f",p,v);_emit(b, false); }
    void println(double v, int p = 2)      { char b[32]; snprintf(b,32,"%.*f",p,v);_emit(b, true);  }

    // base-aware integer printing: Serial.print(x, HEX/DEC/OCT/BIN)
    void _emit_base(long v, int base, bool nl) {
        char b[40];
        if (base == 16)      snprintf(b, sizeof(b), "%lX", v);
        else if (base == 8)  snprintf(b, sizeof(b), "%lo", v);
        else if (base == 2) {
            unsigned long u = (unsigned long)v; int i = 0; char t[34];
            if (u == 0) t[i++] = '0';
            while (u) { t[i++] = char('0' + (u & 1)); u >>= 1; }
            int j = 0; while (i > 0) b[j++] = t[--i]; b[j] = '\0';
        }
        else                 snprintf(b, sizeof(b), "%ld", v);
        _emit(b, nl);
    }
    void print(int v, int base)            { _emit_base(v, base, false); }
    void println(int v, int base)          { _emit_base(v, base, true);  }
    void print(long v, int base)           { _emit_base(v, base, false); }
    void println(long v, int base)         { _emit_base(v, base, true);  }

    int  available()                       { _sim_writeln("SER_AVAIL"); return _sim_recv_int(); }
    int  read()                            { _sim_writeln("SER_READ");  return _sim_recv_int(); }
};

inline _SerialClass Serial;

// ── Wire / I2C ─────────────────────────────────────────────────────────────────
// Buffers the master's transaction, then exchanges it with Python over IPC.
// Typical use: beginTransmission → write(reg)[→write(val)…] → endTransmission,
// then requestFrom → read()×N.
struct _TwoWire {
    uint8_t _tx[64];
    int     _txlen = 0;
    uint8_t _addr  = 0;
    uint8_t _rx[64];
    int     _rxlen = 0;
    int     _rxpos = 0;

    void begin() {}
    void begin(int /*sda*/, int /*scl*/) {}
    void setClock(uint32_t /*hz*/) {}

    void beginTransmission(uint8_t addr) { _addr = addr; _txlen = 0; }

    size_t write(uint8_t b) {
        if (_txlen < (int)sizeof(_tx)) _tx[_txlen++] = b;
        return 1;
    }
    size_t write(int b) { return write((uint8_t)b); }
    size_t write(const uint8_t* d, size_t n) {
        for (size_t i = 0; i < n; i++) write(d[i]);
        return n;
    }

    uint8_t endTransmission(bool /*stop*/ = true) {
        char hex[140]; int p = 0;
        for (int i = 0; i < _txlen; i++)
            p += snprintf(hex + p, sizeof(hex) - p, "%02X", _tx[i]);
        hex[p] = '\0';
        char msg[180];
        snprintf(msg, sizeof(msg), "I2CW %d %s", _addr, hex);
        _sim_writeln(msg);
        return (uint8_t)_sim_recv_int();
    }

    uint8_t requestFrom(uint8_t addr, uint8_t len, bool /*stop*/ = true) {
        char msg[48];
        snprintf(msg, sizeof(msg), "I2CR %d %d", addr, len);
        _sim_writeln(msg);
        char resp[140];
        _sim_readline(resp, sizeof(resp));
        _rxlen = 0; _rxpos = 0;
        for (int i = 0; resp[i] && resp[i + 1] && _rxlen < (int)sizeof(_rx); i += 2) {
            char bs[3] = { resp[i], resp[i + 1], '\0' };
            _rx[_rxlen++] = (uint8_t)strtol(bs, nullptr, 16);
        }
        return (uint8_t)_rxlen;
    }
    uint8_t requestFrom(int addr, int len)            { return requestFrom((uint8_t)addr, (uint8_t)len); }

    int available() { return _rxlen - _rxpos; }
    int read()      { return _rxpos < _rxlen ? _rx[_rxpos++] : -1; }
};

inline _TwoWire Wire;
