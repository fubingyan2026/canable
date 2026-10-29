#ifndef G0_DHW_TYPES_H
#define G0_DHW_TYPES_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DHW_TORQUE_SENSOR_COUNT 2U
#define DHW_RGB_COUNT 2U

typedef uint64_t dhw_timestamp_us_t;
typedef uint32_t dhw_frame_seq_t;

typedef enum {
    DHW_OK = 0,
    DHW_ERR_NOT_INITIALIZED,
    DHW_ERR_INVALID_ARGUMENT,
    DHW_ERR_I2C_BUS,
    DHW_ERR_I2C_NACK,
    DHW_ERR_SPI_BUS,
    DHW_ERR_CAN_FRAME,
    DHW_ERR_CRC,
    DHW_ERR_FRAME_LOST,
    DHW_ERR_TIMEOUT,
    DHW_ERR_GPIO,
    DHW_ERR_DEVICE_FAULT,
    DHW_ERR_BUSY,
    DHW_ERR_STORAGE,
} dhw_error_code_t;

static inline const char *dhw_error_name(dhw_error_code_t code) {
    switch (code) {
    case DHW_OK:
        return "OK";
    case DHW_ERR_NOT_INITIALIZED:
        return "NOT_INITIALIZED";
    case DHW_ERR_INVALID_ARGUMENT:
        return "INVALID_ARGUMENT";
    case DHW_ERR_I2C_BUS:
        return "I2C_BUS";
    case DHW_ERR_I2C_NACK:
        return "I2C_NACK";
    case DHW_ERR_SPI_BUS:
        return "SPI_BUS";
    case DHW_ERR_CAN_FRAME:
        return "CAN_FRAME";
    case DHW_ERR_CRC:
        return "CRC";
    case DHW_ERR_FRAME_LOST:
        return "FRAME_LOST";
    case DHW_ERR_TIMEOUT:
        return "TIMEOUT";
    case DHW_ERR_GPIO:
        return "GPIO";
    case DHW_ERR_DEVICE_FAULT:
        return "DEVICE_FAULT";
    case DHW_ERR_BUSY:
        return "BUSY";
    case DHW_ERR_STORAGE:
        return "STORAGE";
    default:
        return "UNKNOWN";
    }
}

typedef enum {
    DHW_STATUS_NONE = 0U,
    DHW_STATUS_VALID = 1U << 0,
    DHW_STATUS_STALE = 1U << 1,
    DHW_STATUS_TIMEOUT = 1U << 2,
    DHW_STATUS_FRAME_LOST = 1U << 3,
    DHW_STATUS_CRC_ERROR = 1U << 4,
    DHW_STATUS_BUS_ERROR = 1U << 5,
    DHW_STATUS_ZEROED = 1U << 6,
} dhw_status_flags_t;

typedef struct {
    dhw_timestamp_us_t timestamp_us;
    dhw_frame_seq_t frame_seq;
    uint32_t status;
    dhw_error_code_t error_code;
    bool valid;
} dhw_meta_t;

typedef struct {
    float angle_deg;
    float angle_raw_deg;
    dhw_meta_t meta;
} dhw_encoder_data_t;

typedef struct {
    float mz_nm;
    float mz_raw_nm;
    dhw_meta_t meta;
} dhw_torque_data_t;

typedef struct {
    float mz_nm[DHW_TORQUE_SENSOR_COUNT];
    dhw_error_code_t error[DHW_TORQUE_SENSOR_COUNT];
    uint32_t received[DHW_TORQUE_SENSOR_COUNT];
    uint32_t rx_overflows;
} dhw_torque_poll_t;

typedef enum {
    DHW_BUTTON_RELEASED = 0,
    DHW_BUTTON_PRESSED = 1,
} dhw_button_value_t;

typedef struct {
    dhw_button_value_t value;
    dhw_meta_t meta;
} dhw_button_data_t;

typedef struct {
    dhw_encoder_data_t encoder;
    dhw_torque_data_t torque[DHW_TORQUE_SENSOR_COUNT];
    dhw_button_data_t button;
    dhw_timestamp_us_t snapshot_timestamp_us;
    dhw_frame_seq_t snapshot_seq;
} dhw_data_snapshot_t;

typedef struct {
    uint8_t red, green, blue;
} dhw_rgb_t;

#ifdef __cplusplus
}
#endif
#endif
