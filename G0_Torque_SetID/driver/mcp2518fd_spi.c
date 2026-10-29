#include "mcp2518fd_spi.h"

/*
 * Minimal userspace MCP2518FD driver for G0 Classic CAN traffic.
 * Register layout and SPI commands follow Microchip DS20006027B.
 */

#include <errno.h>
#include <fcntl.h>
#include <linux/spi/spidev.h>
#include <stdbool.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define MCP2518FD_INSTRUCTION_RESET 0x00U
#define MCP2518FD_INSTRUCTION_WRITE 0x02U
#define MCP2518FD_INSTRUCTION_READ 0x03U

#define MCP2518FD_REG_CICON 0x000U
#define MCP2518FD_REG_CINBTCFG 0x004U
#define MCP2518FD_REG_CITREC 0x034U
#define MCP2518FD_REG_CIBDIAG1 0x03CU
#define MCP2518FD_REG_CIFIFOCON 0x050U
#define MCP2518FD_REG_CIFIFOSTA 0x054U
#define MCP2518FD_REG_CIFIFOUA 0x058U
#define MCP2518FD_REG_CIFLTCON 0x1D0U
#define MCP2518FD_REG_CIFLTOBJ 0x1F0U
#define MCP2518FD_REG_CIMASK 0x1F4U
#define MCP2518FD_REG_OSC 0xE00U
#define MCP2518FD_REG_ECCCON 0xE0CU
#define MCP2518FD_REG_DEVID 0xE14U

#define MCP2518FD_RAM_START 0x400U
#define MCP2518FD_RAM_SIZE 2048U
#define MCP2518FD_FIFO_STRIDE 12U
#define MCP2518FD_RX_FIFO 1U
#define MCP2518FD_TX_FIFO 2U
#define MCP2518FD_FIFO_OBJECT_SIZE 16U

#define MCP2518FD_FIFO_NOT_EMPTY_OR_NOT_FULL 0x01U
#define MCP2518FD_FIFO_RX_OVERFLOW 0x08U
#define MCP2518FD_FIFO_TX_ENABLE (1U << 7)
#define MCP2518FD_FIFO_UINC (1U << 8)
#define MCP2518FD_FIFO_TXREQ (1U << 9)
#define MCP2518FD_FIFO_RESET (1U << 10)
#define MCP2518FD_FIFO_SIZE_SHIFT 24U
#define MCP2518FD_FIFO_PAYLOAD_SHIFT 29U
#define MCP2518FD_FIFO_PRIORITY_SHIFT 16U

#define MCP2518FD_FILTER_ENABLE 0x80U
#define MCP2518FD_CICON_RESTRICT_RETRANSMISSION (1U << 16)

#define MCP2518FD_TREC_RX_ERROR_PASSIVE (1U << 19)
#define MCP2518FD_TREC_TX_ERROR_PASSIVE (1U << 20)
#define MCP2518FD_TREC_BUS_OFF (1U << 21)
#define MCP2518FD_BDIAG1_NO_ACK (1U << 18)

#define MCP2518FD_OSC_READY (1U << 10)
#define MCP2518FD_ECC_ENABLE 0x01U

#define MCP2518FD_MODE_CLASSIC 6U
#define MCP2518FD_MODE_MASK 0x07U
#define MCP2518FD_OPERATION_MODE_SHIFT 5U

#define MCP2518FD_MAX_TRANSFER (MCP2518FD_RAM_SIZE + 2U)

static uint32_t monotonic_ms(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint32_t)((uint64_t)now.tv_sec * 1000U + (uint64_t)now.tv_nsec / 1000000U);
}

static uint32_t load_le32(const uint8_t *bytes) {
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) | ((uint32_t)bytes[2] << 16) |
           ((uint32_t)bytes[3] << 24);
}

static void store_le32(uint8_t *bytes, uint32_t value) {
    bytes[0] = (uint8_t)value;
    bytes[1] = (uint8_t)(value >> 8);
    bytes[2] = (uint8_t)(value >> 16);
    bytes[3] = (uint8_t)(value >> 24);
}

static int spi_transfer(mcp2518fd_spi_t *device, const uint8_t *tx, uint8_t *rx, size_t size) {
    struct spi_ioc_transfer transfer;
    memset(&transfer, 0, sizeof(transfer));
    transfer.tx_buf = (uintptr_t)tx;
    transfer.rx_buf = (uintptr_t)rx;
    transfer.len = (uint32_t)size;
    transfer.speed_hz = device->spi_speed_hz;
    transfer.bits_per_word = 8;

    return ioctl(device->fd, SPI_IOC_MESSAGE(1), &transfer) == (int)size ? 0 : -1;
}

static dhw_error_code_t reset_device(mcp2518fd_spi_t *device) {
    uint8_t tx[2] = {(uint8_t)(MCP2518FD_INSTRUCTION_RESET << 4), 0};
    uint8_t rx[2] = {0};

    if (spi_transfer(device, tx, rx, sizeof(tx)) < 0)
        return DHW_ERR_SPI_BUS;

    usleep(10000);
    return DHW_OK;
}

static dhw_error_code_t read_bytes(mcp2518fd_spi_t *device, uint16_t address, uint8_t *data,
                                   size_t size) {
    if (!data || size > MCP2518FD_RAM_SIZE)
        return DHW_ERR_INVALID_ARGUMENT;

    uint8_t tx[MCP2518FD_MAX_TRANSFER] = {0};
    uint8_t rx[MCP2518FD_MAX_TRANSFER] = {0};
    tx[0] = (uint8_t)((MCP2518FD_INSTRUCTION_READ << 4) | ((address >> 8) & 0x0FU));
    tx[1] = (uint8_t)address;

    if (spi_transfer(device, tx, rx, size + 2U) < 0)
        return DHW_ERR_SPI_BUS;

    memcpy(data, &rx[2], size);
    return DHW_OK;
}

static dhw_error_code_t write_bytes(mcp2518fd_spi_t *device, uint16_t address,
                                    const uint8_t *data, size_t size) {
    if (!data || size > MCP2518FD_RAM_SIZE)
        return DHW_ERR_INVALID_ARGUMENT;

    uint8_t tx[MCP2518FD_MAX_TRANSFER] = {0};
    uint8_t rx[MCP2518FD_MAX_TRANSFER] = {0};
    tx[0] = (uint8_t)((MCP2518FD_INSTRUCTION_WRITE << 4) | ((address >> 8) & 0x0FU));
    tx[1] = (uint8_t)address;
    memcpy(&tx[2], data, size);

    return spi_transfer(device, tx, rx, size + 2U) < 0 ? DHW_ERR_SPI_BUS : DHW_OK;
}

static dhw_error_code_t read_byte(mcp2518fd_spi_t *device, uint16_t address, uint8_t *value) {
    return read_bytes(device, address, value, 1);
}

static dhw_error_code_t write_byte(mcp2518fd_spi_t *device, uint16_t address, uint8_t value) {
    return write_bytes(device, address, &value, 1);
}

static dhw_error_code_t read_word(mcp2518fd_spi_t *device, uint16_t address, uint32_t *value) {
    uint8_t bytes[4];
    dhw_error_code_t error = read_bytes(device, address, bytes, sizeof(bytes));
    if (error == DHW_OK)
        *value = load_le32(bytes);
    return error;
}

static dhw_error_code_t write_word(mcp2518fd_spi_t *device, uint16_t address, uint32_t value) {
    uint8_t bytes[4];
    store_le32(bytes, value);
    return write_bytes(device, address, bytes, sizeof(bytes));
}

static dhw_error_code_t wait_for_mode(mcp2518fd_spi_t *device, uint8_t expected_mode) {
    const uint32_t deadline = monotonic_ms() + 100U;
    do {
        uint8_t mode = 0;
        dhw_error_code_t error = read_byte(device, MCP2518FD_REG_CICON + 2U, &mode);
        if (error != DHW_OK)
            return error;
        if (((mode >> MCP2518FD_OPERATION_MODE_SHIFT) & MCP2518FD_MODE_MASK) == expected_mode)
            return DHW_OK;
        usleep(1000);
    } while ((int32_t)(deadline - monotonic_ms()) > 0);

    return DHW_ERR_TIMEOUT;
}

static dhw_error_code_t select_classic_mode(mcp2518fd_spi_t *device) {
    uint8_t request = 0;
    dhw_error_code_t error = read_byte(device, MCP2518FD_REG_CICON + 3U, &request);
    if (error != DHW_OK)
        return error;

    request = (uint8_t)((request & ~MCP2518FD_MODE_MASK) | MCP2518FD_MODE_CLASSIC);
    error = write_byte(device, MCP2518FD_REG_CICON + 3U, request);
    return error == DHW_OK ? wait_for_mode(device, MCP2518FD_MODE_CLASSIC) : error;
}

static dhw_error_code_t configure_bit_time(mcp2518fd_spi_t *device, uint32_t oscillator_hz,
                                           uint32_t can_bitrate) {
    if (oscillator_hz != 40000000U || can_bitrate != 1000000U)
        return DHW_ERR_INVALID_ARGUMENT;

    /* 40 MHz / (BRP 1 * 40 TQ) = 1 Mbit/s, sample point at 80%. */
    const uint32_t nbtcfg = (30U << 16) | (7U << 8) | 7U;
    return write_word(device, MCP2518FD_REG_CINBTCFG, nbtcfg);
}

static dhw_error_code_t configure_fifos_and_filter(mcp2518fd_spi_t *device) {
    const uint16_t rx_control =
        MCP2518FD_REG_CIFIFOCON + MCP2518FD_RX_FIFO * MCP2518FD_FIFO_STRIDE;
    const uint16_t tx_control =
        MCP2518FD_REG_CIFIFOCON + MCP2518FD_TX_FIFO * MCP2518FD_FIFO_STRIDE;

    const uint32_t rx_fifo = MCP2518FD_FIFO_RESET | (31U << MCP2518FD_FIFO_SIZE_SHIFT) |
                             (0U << MCP2518FD_FIFO_PAYLOAD_SHIFT);
    const uint32_t tx_fifo = MCP2518FD_FIFO_TX_ENABLE | MCP2518FD_FIFO_RESET |
                             (1U << MCP2518FD_FIFO_PRIORITY_SHIFT) |
                             (7U << MCP2518FD_FIFO_SIZE_SHIFT) |
                             (0U << MCP2518FD_FIFO_PAYLOAD_SHIFT);

    dhw_error_code_t error = write_word(device, rx_control, rx_fifo);
    if (error != DHW_OK)
        return error;
    error = write_word(device, tx_control, tx_fifo);
    if (error != DHW_OK)
        return error;

    error = write_word(device, MCP2518FD_REG_CIFLTOBJ, 0U);
    if (error != DHW_OK)
        return error;
    /* A zero mask accepts both standard and extended identifiers. */
    error = write_word(device, MCP2518FD_REG_CIMASK, 0U);
    if (error != DHW_OK)
        return error;
    return write_byte(device, MCP2518FD_REG_CIFLTCON,
                      MCP2518FD_FILTER_ENABLE | MCP2518FD_RX_FIFO);
}

dhw_error_code_t mcp2518fd_spi_open(mcp2518fd_spi_t *device, const char *path,
                                    uint32_t spi_speed_hz) {
    if (!device || !path || spi_speed_hz == 0)
        return DHW_ERR_INVALID_ARGUMENT;

    device->fd = open(path, O_RDWR | O_CLOEXEC);
    device->spi_speed_hz = spi_speed_hz;
    device->rx_overflow_count = 0U;
    if (device->fd < 0)
        return DHW_ERR_SPI_BUS;

    uint8_t mode = SPI_MODE_0;
    uint8_t bits = 8;
    if (ioctl(device->fd, SPI_IOC_WR_MODE, &mode) < 0 ||
        ioctl(device->fd, SPI_IOC_WR_BITS_PER_WORD, &bits) < 0 ||
        ioctl(device->fd, SPI_IOC_WR_MAX_SPEED_HZ, &device->spi_speed_hz) < 0) {
        mcp2518fd_spi_close(device);
        return DHW_ERR_SPI_BUS;
    }

    return DHW_OK;
}

dhw_error_code_t mcp2518fd_spi_initialize(mcp2518fd_spi_t *device, uint32_t oscillator_hz,
                                          uint32_t can_bitrate) {
    if (!device || device->fd < 0)
        return DHW_ERR_NOT_INITIALIZED;

    dhw_error_code_t error = reset_device(device);
    if (error != DHW_OK)
        return error;

    uint32_t device_id = 0;
    error = read_word(device, MCP2518FD_REG_DEVID, &device_id);
    if (error != DHW_OK || device_id == UINT32_MAX)
        return DHW_ERR_DEVICE_FAULT;

    uint32_t oscillator = 0;
    const uint32_t oscillator_deadline = monotonic_ms() + 100U;
    do {
        error = read_word(device, MCP2518FD_REG_OSC, &oscillator);
        if (error != DHW_OK)
            return error;
        if ((oscillator & MCP2518FD_OSC_READY) != 0)
            break;
        usleep(1000);
    } while ((int32_t)(oscillator_deadline - monotonic_ms()) > 0);
    if ((oscillator & MCP2518FD_OSC_READY) == 0)
        return DHW_ERR_DEVICE_FAULT;

    uint8_t ecc = 0;
    error = read_byte(device, MCP2518FD_REG_ECCCON, &ecc);
    if (error != DHW_OK)
        return error;
    error = write_byte(device, MCP2518FD_REG_ECCCON, ecc | MCP2518FD_ECC_ENABLE);
    if (error != DHW_OK)
        return error;

    uint8_t ram_chunk[64];
    memset(ram_chunk, 0xFF, sizeof(ram_chunk));
    for (uint16_t offset = 0; offset < MCP2518FD_RAM_SIZE; offset += sizeof(ram_chunk)) {
        error = write_bytes(device, MCP2518FD_RAM_START + offset, ram_chunk, sizeof(ram_chunk));
        if (error != DHW_OK)
            return error;
    }

    /* Preserve the production controller retransmission policy. */
    error = write_word(device, MCP2518FD_REG_CICON,
                       0x04980760U | MCP2518FD_CICON_RESTRICT_RETRANSMISSION);
    if (error != DHW_OK)
        return error;
    error = configure_bit_time(device, oscillator_hz, can_bitrate);
    if (error != DHW_OK)
        return error;
    error = configure_fifos_and_filter(device);
    if (error != DHW_OK)
        return error;
    return select_classic_mode(device);
}

dhw_error_code_t mcp2518fd_spi_send(mcp2518fd_spi_t *device,
                                    const mcp2518fd_frame_t *frame) {
    if (!device || device->fd < 0)
        return DHW_ERR_NOT_INITIALIZED;
    if (!frame || frame->dlc > 8U ||
        (!frame->extended && frame->can_id > 0x7FFU) ||
        (frame->extended && frame->can_id > 0x1FFFFFFFU))
        return DHW_ERR_INVALID_ARGUMENT;

    const uint16_t tx_status =
        MCP2518FD_REG_CIFIFOSTA + MCP2518FD_TX_FIFO * MCP2518FD_FIFO_STRIDE;
    const uint16_t tx_user_address =
        MCP2518FD_REG_CIFIFOUA + MCP2518FD_TX_FIFO * MCP2518FD_FIFO_STRIDE;
    const uint16_t tx_control =
        MCP2518FD_REG_CIFIFOCON + MCP2518FD_TX_FIFO * MCP2518FD_FIFO_STRIDE;

    uint8_t status = 0;
    dhw_error_code_t error = read_byte(device, tx_status, &status);
    if (error != DHW_OK)
        return error;
    if ((status & MCP2518FD_FIFO_NOT_EMPTY_OR_NOT_FULL) == 0)
        return DHW_ERR_TIMEOUT;

    uint32_t user_address = 0;
    error = read_word(device, tx_user_address, &user_address);
    if (error != DHW_OK)
        return error;

    uint8_t object[MCP2518FD_FIFO_OBJECT_SIZE] = {0};
    const uint32_t id_word = frame->extended
                                 ? ((frame->can_id >> 18) & 0x7FFU) |
                                       ((frame->can_id & 0x3FFFFU) << 11)
                                 : frame->can_id;
    const uint32_t control_word = frame->dlc | (frame->extended ? (1U << 4) : 0U);
    store_le32(&object[0], id_word);
    store_le32(&object[4], control_word);
    memcpy(&object[8], frame->data, frame->dlc);
    error = write_bytes(device, MCP2518FD_RAM_START + (user_address & 0x0FFFU), object,
                        sizeof(object));
    if (error != DHW_OK)
        return error;

    return write_byte(device, tx_control + 1U,
                      (uint8_t)((MCP2518FD_FIFO_UINC | MCP2518FD_FIFO_TXREQ) >> 8));
}

static dhw_error_code_t receive_now(mcp2518fd_spi_t *device, mcp2518fd_frame_t *frame) {
    const uint16_t rx_status =
        MCP2518FD_REG_CIFIFOSTA + MCP2518FD_RX_FIFO * MCP2518FD_FIFO_STRIDE;
    const uint16_t rx_user_address =
        MCP2518FD_REG_CIFIFOUA + MCP2518FD_RX_FIFO * MCP2518FD_FIFO_STRIDE;
    const uint16_t rx_control =
        MCP2518FD_REG_CIFIFOCON + MCP2518FD_RX_FIFO * MCP2518FD_FIFO_STRIDE;

    uint8_t status = 0;
    dhw_error_code_t error = read_byte(device, rx_status, &status);
    if (error != DHW_OK)
        return error;
    if ((status & MCP2518FD_FIFO_RX_OVERFLOW) != 0U) {
        ++device->rx_overflow_count;
        error = write_byte(device, rx_status,
                           (uint8_t)(status & (uint8_t)~MCP2518FD_FIFO_RX_OVERFLOW));
        if (error != DHW_OK)
            return error;
    }
    if ((status & MCP2518FD_FIFO_NOT_EMPTY_OR_NOT_FULL) == 0)
        return DHW_ERR_TIMEOUT;

    uint32_t user_address = 0;
    error = read_word(device, rx_user_address, &user_address);
    if (error != DHW_OK)
        return error;

    uint8_t object[MCP2518FD_FIFO_OBJECT_SIZE] = {0};
    error = read_bytes(device, MCP2518FD_RAM_START + (user_address & 0x0FFFU), object,
                       sizeof(object));
    if (error != DHW_OK)
        return error;

    const uint32_t id = load_le32(&object[0]);
    const uint32_t control = load_le32(&object[4]);
    const uint8_t dlc = (uint8_t)(control & 0x0FU);
    const bool extended = (control & (1U << 4)) != 0;
    const bool can_fd = (control & (1U << 7)) != 0;
    error = write_byte(device, rx_control + 1U, (uint8_t)(MCP2518FD_FIFO_UINC >> 8));
    if (error != DHW_OK)
        return error;
    if (can_fd || dlc > 8U)
        return DHW_ERR_CAN_FRAME;

    const uint32_t sid = id & 0x7FFU;
    const uint32_t eid = (id >> 11) & 0x3FFFFU;
    frame->can_id = extended ? (sid << 18) | eid : sid;
    frame->dlc = dlc;
    frame->extended = extended;
    memset(frame->data, 0, sizeof(frame->data));
    memcpy(frame->data, &object[8], dlc);
    return DHW_OK;
}

dhw_error_code_t mcp2518fd_spi_receive(mcp2518fd_spi_t *device, mcp2518fd_frame_t *frame,
                                       uint32_t timeout_ms) {
    if (!device || device->fd < 0)
        return DHW_ERR_NOT_INITIALIZED;
    if (!frame)
        return DHW_ERR_INVALID_ARGUMENT;

    if (timeout_ms == 0U)
        return receive_now(device, frame);

    const uint32_t deadline = monotonic_ms() + timeout_ms;
    do {
        dhw_error_code_t error = receive_now(device, frame);
        if (error != DHW_ERR_TIMEOUT)
            return error;
        usleep(200);
    } while ((int32_t)(deadline - monotonic_ms()) > 0);

    return DHW_ERR_TIMEOUT;
}

dhw_error_code_t mcp2518fd_spi_read_diagnostics(
    mcp2518fd_spi_t *device, mcp2518fd_diagnostics_t *diagnostics) {
    if (!device || device->fd < 0)
        return DHW_ERR_NOT_INITIALIZED;
    if (!diagnostics)
        return DHW_ERR_INVALID_ARGUMENT;

    const uint16_t tx_status =
        MCP2518FD_REG_CIFIFOSTA + MCP2518FD_TX_FIFO * MCP2518FD_FIFO_STRIDE;
    uint8_t fifo_status = 0;
    uint32_t trec = 0;
    uint32_t bdiag1 = 0;

    dhw_error_code_t error = read_byte(device, tx_status, &fifo_status);
    if (error != DHW_OK)
        return error;
    error = read_word(device, MCP2518FD_REG_CITREC, &trec);
    if (error != DHW_OK)
        return error;
    error = read_word(device, MCP2518FD_REG_CIBDIAG1, &bdiag1);
    if (error != DHW_OK)
        return error;

    diagnostics->tx_fifo_status = fifo_status;
    diagnostics->tx_error_count = (uint8_t)(trec >> 8);
    diagnostics->rx_error_count = (uint8_t)trec;
    diagnostics->bus_diagnostic = bdiag1;
    diagnostics->no_ack = (bdiag1 & MCP2518FD_BDIAG1_NO_ACK) != 0U;
    diagnostics->bus_off = (trec & MCP2518FD_TREC_BUS_OFF) != 0U;
    diagnostics->tx_error_passive = (trec & MCP2518FD_TREC_TX_ERROR_PASSIVE) != 0U;
    diagnostics->rx_error_passive = (trec & MCP2518FD_TREC_RX_ERROR_PASSIVE) != 0U;

    /* CiBDIAG1 error bits are sticky. Clear them after taking this snapshot so
     * the next call describes the most recent transmission interval. */
    return write_word(device, MCP2518FD_REG_CIBDIAG1, 0U);
}

dhw_error_code_t mcp2518fd_spi_abort_transmit(mcp2518fd_spi_t *device) {
    if (!device || device->fd < 0)
        return DHW_ERR_NOT_INITIALIZED;

    const uint16_t tx_control =
        MCP2518FD_REG_CIFIFOCON + MCP2518FD_TX_FIFO * MCP2518FD_FIFO_STRIDE;

    /* Clearing TXREQ aborts the failed request. */
    dhw_error_code_t error = write_byte(device, tx_control + 1U, 0U);
    if (error != DHW_OK)
        return error;

    uint32_t deadline = monotonic_ms() + 10U;
    bool cleared = false;
    do {
        uint8_t control = 0;
        error = read_byte(device, tx_control + 1U, &control);
        if (error != DHW_OK)
            return error;
        if ((control & (uint8_t)(MCP2518FD_FIFO_TXREQ >> 8)) == 0U) {
            cleared = true;
            break;
        }
        usleep(100);
    } while ((int32_t)(deadline - monotonic_ms()) > 0);
    if (!cleared)
        return DHW_ERR_TIMEOUT;

    /* An attempts-exhausted message remains counted in the TX FIFO even after
     * TXREQ is cleared. Reset the FIFO pointers so the next one-second test
     * frame does not accumulate behind failed frames. FRESET is self-clearing. */
    error = write_byte(device, tx_control + 1U,
                       (uint8_t)(MCP2518FD_FIFO_RESET >> 8));
    if (error != DHW_OK)
        return error;

    deadline = monotonic_ms() + 10U;
    do {
        uint8_t control = 0;
        error = read_byte(device, tx_control + 1U, &control);
        if (error != DHW_OK)
            return error;
        if ((control & (uint8_t)(MCP2518FD_FIFO_RESET >> 8)) == 0U)
            return DHW_OK;
        usleep(100);
    } while ((int32_t)(deadline - monotonic_ms()) > 0);

    return DHW_ERR_TIMEOUT;
}

dhw_error_code_t mcp2518fd_spi_drain_receive(mcp2518fd_spi_t *device) {
    if (!device || device->fd < 0)
        return DHW_ERR_NOT_INITIALIZED;

    mcp2518fd_frame_t ignored;
    for (unsigned int count = 0; count < 32U; ++count) {
        dhw_error_code_t error = receive_now(device, &ignored);
        if (error == DHW_ERR_TIMEOUT)
            return DHW_OK;
        if (error != DHW_OK && error != DHW_ERR_CAN_FRAME)
            return error;
    }
    return DHW_OK;
}

uint32_t mcp2518fd_spi_take_rx_overflows(mcp2518fd_spi_t *device) {
    if (!device)
        return 0U;
    const uint32_t count = device->rx_overflow_count;
    device->rx_overflow_count = 0U;
    return count;
}

void mcp2518fd_spi_close(mcp2518fd_spi_t *device) {
    if (!device)
        return;
    if (device->fd >= 0)
        close(device->fd);
    device->fd = -1;
}
