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
 *   READY                        setup() done    (no response)
 */

#include <cstdio>
#include <cstdlib>
#include <cstring>

// ── Arduino constants ────────────────────────────────────────────────────────
#define HIGH          1
#define LOW           0
#define INPUT         0
#define OUTPUT        1
#define INPUT_PULLUP  2
#define INPUT_PULLDOWN 3
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

// ── Timing ───────────────────────────────────────────────────────────────────
inline void delay(unsigned long ms) {
    char msg[32];
    snprintf(msg, sizeof(msg), "DELAY %lu", ms);
    _sim_writeln(msg);
    _sim_recv_ok();
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
    int  available()                       { _sim_writeln("SER_AVAIL"); return _sim_recv_int(); }
    int  read()                            { _sim_writeln("SER_READ");  return _sim_recv_int(); }
};

inline _SerialClass Serial;
