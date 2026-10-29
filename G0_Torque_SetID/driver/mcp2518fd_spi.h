#pragma once

#include "dhw_types.h"
#include <stddef.h>
#include <stdint.h>

typedef struct {
    int fd;
    uint32_t spi_speed_hz;
    uint32_t rx_overflow_count;
} mcp2518fd_spi_t;

typedef struct {
    uint32_t can_id;
    uint8_t dlc;
    uint8_t data[8];
    bool extended;
} mcp2518fd_frame_t;

typedef struct {
    uint8_t tx_fifo_status;
    uint8_t tx_error_count;
    uint8_t rx_error_count;
    uint32_t bus_diagnostic;
    bool no_ack;
    bool bus_off;
    bool tx_error_passive;
    bool rx_error_passive;
} mcp2518fd_diagnostics_t;

dhw_error_code_t mcp2518fd_spi_open(mcp2518fd_spi_t *device, const char *path,
                                    uint32_t spi_speed_hz);
dhw_error_code_t mcp2518fd_spi_initialize(mcp2518fd_spi_t *device, uint32_t oscillator_hz,
                                          uint32_t can_bitrate);
dhw_error_code_t mcp2518fd_spi_send(mcp2518fd_spi_t *device,
                                    const mcp2518fd_frame_t *frame);
dhw_error_code_t mcp2518fd_spi_receive(mcp2518fd_spi_t *device, mcp2518fd_frame_t *frame,
                                       uint32_t timeout_ms);
dhw_error_code_t mcp2518fd_spi_read_diagnostics(mcp2518fd_spi_t *device,
                                                mcp2518fd_diagnostics_t *diagnostics);
dhw_error_code_t mcp2518fd_spi_abort_transmit(mcp2518fd_spi_t *device);
dhw_error_code_t mcp2518fd_spi_drain_receive(mcp2518fd_spi_t *device);
uint32_t mcp2518fd_spi_take_rx_overflows(mcp2518fd_spi_t *device);
void mcp2518fd_spi_close(mcp2518fd_spi_t *device);
