#include "protocol.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static unsigned long long now_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (unsigned long long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

static bool read_line(char *line, size_t size) {
    if (!fgets(line, (int)size, stdin))
        return false;
    if (!strchr(line, '\n') && !feof(stdin)) {
        int c;
        while ((c = getchar()) != '\n' && c != EOF) {}
        return false;
    }
    line[strcspn(line, "\r\n")] = 0;
    return true;
}

static bool parse_id(const char *text, unsigned long *target) {
    while (isspace((unsigned char)*text)) ++text;
    if (*text == '-' || *text == '+') return false;
    char *end;
    errno = 0;
    *target = strtoul(text, &end, strncmp(text, "0x", 2) == 0 ||
                                 strncmp(text, "0X", 2) == 0 ? 16 : 10);
    if (end == text || errno) return false;
    while (isspace((unsigned char)*end)) ++end;
    return !*end && *target >= 1 && *target <= MAX_SENSOR_ID;
}

static bool confirm(const char *prompt) {
    char line[32];
    printf("%s 输入yes继续：", prompt);
    fflush(stdout);
    return read_line(line, sizeof(line)) && strcmp(line, "yes") == 0;
}

static dhw_error_code_t scan(mcp2518fd_spi_t *spi, unsigned *current) {
    unsigned found = 0;
    bool ambiguous = false;
    puts("扫描标准帧站号1～47（0x01～0x2F），约需3秒...");
    for (unsigned id = 1; id <= MAX_SENSOR_ID; ++id) {
        dhw_error_code_t error = mcp2518fd_spi_drain_receive(spi);
        if (error != DHW_OK) return error;
        const mcp2518fd_frame_t query = {.can_id = request_id(id), .dlc = 8,
                                       .data = {4, 0, 0, 0, 0, 0, 0, 0}, .extended = false};
        error = mcp2518fd_spi_send(spi, &query);
        if (error != DHW_OK) return error;
        const unsigned long long deadline = now_ms() + 50;
        unsigned replies = 0;
        while (now_ms() < deadline) {
            mcp2518fd_frame_t frame = {0};
            error = mcp2518fd_spi_receive(spi, &frame, 5);
            if (error == DHW_ERR_TIMEOUT) continue;
            if (error != DHW_OK) return error;
            if (measurement_matches(&frame, id)) ++replies;
        }
        // Do not leave an unanswered request retransmitting during the next probe.
        error = mcp2518fd_spi_abort_transmit(spi);
        if (error != DHW_OK) return error;
        if (replies) {
            ++found;
            *current = id;
            printf("发现ID=%u (0x%02X)，响应CAN=0x%03X，匹配回复=%u\n",
                   id, id, response_id(id), replies);
        }
        if (replies > 1) ambiguous = true;
    }
    if (found != 1 || ambiguous) {
        fprintf(stderr, "扫描不满足改号条件：响应ID数=%u，多回复=%s。未发送改号命令。\n"
                        "只保留一只传感器并停止主动上报后重试；无回复请检查线路/协议。\n",
                found, ambiguous ? "是" : "否");
        return DHW_ERR_DEVICE_FAULT;
    }
    return DHW_OK;
}

static dhw_error_code_t write_id(mcp2518fd_spi_t *spi, unsigned current, unsigned target) {
    dhw_error_code_t error = mcp2518fd_spi_drain_receive(spi);
    if (error != DHW_OK) return error;
    const mcp2518fd_frame_t command = set_id_command(current, target);
    error = mcp2518fd_spi_send(spi, &command);
    if (error != DHW_OK) return error;
    printf("TX queued: CAN=0x%03X DLC=7 DATA=", command.can_id);
    for (unsigned i = 0; i < command.dlc; ++i) printf("%02X ", command.data[i]);
    putchar('\n');
    const unsigned long long deadline = now_ms() + 1000;
    while (now_ms() < deadline) {
        mcp2518fd_frame_t frame = {0};
        error = mcp2518fd_spi_receive(spi, &frame, 10);
        if (error == DHW_ERR_TIMEOUT) continue;
        if (error != DHW_OK) return error;
        if (frame.extended || (frame.can_id != response_id(current) &&
            frame.can_id != response_id(target)) || frame.dlc < 3 ||
            memcmp(frame.data, command.data, 3) != 0) continue;
        const uint8_t success[] = {0x3f, 0x80, 0, 0};
        if (frame.dlc < 7 || memcmp(frame.data + 3, success, 4) != 0)
            return DHW_ERR_CAN_FRAME;
        return DHW_OK;
    }
    return DHW_ERR_TIMEOUT;
}

int main(int argc, char **argv) {
    unsigned long target = 0;
    const bool automatic = argc == 2;
    if (argc > 2 || (automatic && !parse_id(argv[1], &target))) {
        fprintf(stderr, "Usage: sudo %s [new_ID: 1..47 or 0x01..0x2F]\n", argv[0]);
        return 2;
    }
    puts("只用标准CAN帧；请求=0x500+ID*0x10，响应=0x400+ID*0x10。");
    puts("超过47的请求地址超出0x7FF，因此不扫描或设置48～255。");
    puts("警告：必须停止DHW/测试程序，物理断开另一只，仅接一只传感器。");
    if (automatic)
        printf("参数模式：目标ID=%lu，扫描通过后自动改号，不再询问确认。\n", target);
    if (!automatic && !confirm("确认满足上述条件？"))
        return 2;
    mcp2518fd_spi_t spi = {.fd = -1};
    dhw_error_code_t error = mcp2518fd_spi_open(&spi, "/dev/spidev1.0", 5000000);
    if (error == DHW_OK) error = mcp2518fd_spi_initialize(&spi, 40000000, 1000000);
    unsigned current = 0;
    if (error == DHW_OK) error = scan(&spi, &current);
    int result = 1;
    if (error != DHW_OK) {
        fprintf(stderr, "初始化/扫描 FAIL: %s(%d)\n", dhw_error_name(error), error);
        goto cleanup;
    }
    char line[64];
    result = 2;
    if (!automatic) {
        printf("当前ID=%u。输入目标ID 1～47（十进制或0x十六进制）：", current);
        fflush(stdout);
        if (!read_line(line, sizeof(line))) goto cleanup;
        if (!parse_id(line, &target)) {
            fprintf(stderr, "目标ID无效，未发送改号命令。\n");
            goto cleanup;
        }
    }
    printf("准备将ID %u改为%lu。\n", current, target);
    if (!automatic && !confirm("单个响应ID不能证明只有一个设备，确认继续改号？")) goto cleanup;
    error = write_id(&spi, current, (unsigned)target);
    result = error == DHW_OK ? 0 : 1;
    if (result == 0) printf("设置ID=%lu OK（收到写成功应答）\n", target);
    else fprintf(stderr, "设置ID FAIL: %s(%d)。地址仍可能已改变，请勿盲目重发。\n",
                 dhw_error_name(error), error);
cleanup:
    if (spi.fd >= 0) {
        error = mcp2518fd_spi_abort_transmit(&spi);
        if (error != DHW_OK) {
            fprintf(stderr, "停止CAN发送失败: %s(%d)\n", dhw_error_name(error), error);
            result = 1;
        }
    }
    mcp2518fd_spi_close(&spi);
    return result;
}
