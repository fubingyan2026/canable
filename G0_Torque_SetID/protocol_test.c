#include "protocol.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    assert(request_id(1) == 0x510 && request_id(2) == 0x520);
    assert(request_id(MAX_SENSOR_ID) == 0x7f0 && request_id(48) > 0x7ff);
    const mcp2518fd_frame_t one = set_id_command(2, 1);
    const mcp2518fd_frame_t two = set_id_command(1, 2);
    assert(one.can_id == 0x520 && !one.extended && one.dlc == 7);
    assert(one.data[3] == 0x3f && one.data[4] == 0x80);
    assert(two.data[3] == 0x40 && two.data[4] == 0);
    for (unsigned id = 1; id <= MAX_SENSOR_ID; ++id) {
        mcp2518fd_frame_t f = set_id_command(id, id);
        assert(f.can_id <= 0x7ff && !f.extended);
        f.can_id = response_id(id);
        f.data[0] = 4; f.data[2] = 0;
        assert(measurement_matches(&f, id));
        f.extended = true;
        assert(!measurement_matches(&f, id));
        f.extended = false; f.dlc = 6;
        assert(!measurement_matches(&f, id));
        f.dlc = 7; f.data[3] = 0x7f; f.data[4] = 0x80; f.data[5] = f.data[6] = 0;
        assert(!measurement_matches(&f, id));
    }
    puts("protocol tests OK");
}
