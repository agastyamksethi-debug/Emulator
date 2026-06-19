/**
 * sim_main.cpp — Entry point for compiled Arduino sketches.
 *
 * Compiled together with a .ino sketch and sim_arduino.h.
 * setup() and loop() are defined in the sketch; this file provides main().
 *
 * Lifecycle:
 *   1. Disable I/O buffering so Python sees every line immediately.
 *   2. Call setup() — any Arduino API calls go through the IPC protocol.
 *   3. Send "READY\n" so Python knows setup() finished.
 *   4. Call loop() forever — Python drives time via DELAY responses.
 */

#include <cstdio>

void setup();
void loop();

int main() {
    // Unbuffered I/O — every fputc/fputs is visible to Python immediately.
    setvbuf(stdin,  nullptr, _IONBF, 0);
    setvbuf(stdout, nullptr, _IONBF, 0);

    setup();

    fputs("READY\n", stdout);
    fflush(stdout);

    while (true) {
        loop();
    }

    return 0;
}
