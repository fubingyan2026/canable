#pragma once
#include "mcp2518fd_spi.h"
#include <math.h>
#include <string.h>

#define MAX_SENSOR_ID 47U

static inline uint32_t request_id(unsigned id) { return 0x500U + id * 16U; }
static inline uint32_t response_id(unsigned id) { return 0x400U + id * 16U; }

static inline bool measurement_matches(const mcp2518fd_frame_t *f, unsigned id) {
    if (f->extended || f->can_id != response_id(id) || f->dlc < 7 || f->dlc > 8 ||
        f->data[0] != 4 || f->data[1] != 0 || f->data[2] != 0)
        return false;
    uint32_t bits = (uint32_t)f->data[3] << 24 | (uint32_t)f->data[4] << 16 |
                    (uint32_t)f->data[5] << 8 | f->data[6];
    float value;
    memcpy(&value, &bits, 4);
    return isfinite(value);
}

static inline mcp2518fd_frame_t set_id_command(unsigned current, unsigned target) {
    mcp2518fd_frame_t f = {.can_id = request_id(current), .dlc = 7,
                         .data = {0x10, 0, 0x90}, .extended = false};
    float value = (float)target;
    uint32_t bits;
    memcpy(&bits, &value, 4);
    for (unsigned i = 0; i < 4; ++i)
        f.data[3 + i] = (uint8_t)(bits >> (24 - i * 8));
    return f;
}
