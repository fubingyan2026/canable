"""Fill-light plugin entry point and translations."""
from cangui.i18n import _
from cangui.plugin_host import Plugin

from .widget import FillLightPanel

_I18N = {
    'FillLight.Title': ('补光灯控制', 'Fill Light'),
    'FillLight.Control': ('亮度控制', 'Brightness Control'),
    'FillLight.Hint': ('主界面请选择 CAN FD、仲裁速率 1 Mbps。本插件固定发送标准帧、DLC=8、BRS=0；控制 ID 0x220，状态 ID 0x221。',
                       'Select CAN FD and 1 Mbps nominal bitrate in the main window. This plugin uses standard frames, DLC=8, BRS=0; control ID 0x220, status ID 0x221.'),
    'FillLight.Target': ('目标亮度（PWM 占空比）', 'Target brightness (PWM duty cycle)'),
    'FillLight.Apply': ('应用亮度 / 重发', 'Apply / Resend'),
    'FillLight.On': ('开灯', 'Turn On'),
    'FillLight.Off': ('关灯', 'Turn Off'),
    'FillLight.Preset': ('{value}%', '{value}%'),
    'FillLight.Auto': ('调整后自动发送', 'Send automatically after adjustment'),
    'FillLight.Board': ('控制板状态', 'Controller Status'),
    'FillLight.Connection': ('控制板在线状态', 'Controller connection'),
    'FillLight.Accepted': ('板端目标亮度', 'Board target brightness'),
    'FillLight.Motor': ('电机汇总状态', 'Motor summary'),
    'FillLight.Uptime': ('MCU 运行时间', 'MCU uptime'),
    'FillLight.UptimeValue': ('{seconds:.3f} 秒', '{seconds:.3f} s'),
    'FillLight.NoData': ('—', '—'),
    'FillLight.Disconnected': ('CAN 未连接', 'CAN disconnected'),
    'FillLight.Unknown': ('未确认在线（等待首帧心跳）', 'Unconfirmed (waiting for first heartbeat)'),
    'FillLight.Online': ('在线，最近心跳 {age:.1f} 秒前', 'Online, last heartbeat {age:.1f} s ago'),
    'FillLight.Offline': ('控制板失联（超过 1.5 秒无合法心跳）', 'Controller offline (no valid heartbeat for 1.5 s)'),
    'FillLight.Ready': ('设置亮度后点击应用；开灯、关灯和预设按钮立即发送。',
                        'Set brightness and click Apply; On, Off and preset buttons send immediately.'),
    'FillLight.Waiting': ('已提交 {value:.1f}%，等待新的状态快照核对目标值。',
                          'Queued {value:.1f}%; waiting for a new status snapshot to check the target.'),
    'FillLight.Matched': ('新状态快照的目标值已匹配：{value:.1f}%。',
                          'Target in the new status snapshot matches: {value:.1f}%.'),
    'FillLight.Mismatch': ('等待目标值匹配；板端当前报告 {value:.1f}%。',
                           'Waiting for target match; board currently reports {value:.1f}%.'),
    'FillLight.Timeout': ('目标核对超时，请检查状态后点击应用重发。',
                          'Target check timed out; check status and click Apply to resend.'),
    'FillLight.NeedFd': ('请先在主界面启用 CAN FD。', 'Enable CAN FD in the main window first.'),
    'FillLight.NeedBitrate': ('请使用 1 Mbps 仲裁速率连接控制板。', 'Connect using a 1 Mbps nominal bitrate.'),
    'FillLight.Note': ('板端亮度为已接受的目标 PWM，不是实测亮度。非零调光约 0.3 秒接近目标，关灯立即执行。断开连接或关闭插件后，控制板保持最后设置值；重新连接不会自动发送。',
                       'The board reports accepted target PWM, not measured light output. Nonzero changes approach the target in about 0.3 s; Off acts immediately. Disconnecting or closing the plugin leaves the last setting on the board; reconnecting sends nothing automatically.'),
    'FillLight.Motor.0': ('关闭', 'OFF'),
    'FillLight.Motor.1': ('未就绪 / 未全部使能', 'Not ready / not all enabled'),
    'FillLight.Motor.2': ('正常且已使能', 'Normal and enabled'),
    'FillLight.Motor.3': ('电机升级中', 'Motor upgrade in progress'),
    'FillLight.Motor.4': ('电机故障 / 反馈超时', 'Motor fault / feedback timeout'),
}


class FillLightPlugin(Plugin):
    name = 'fill_light'
    version = '0.1.0'

    def __init__(self):
        super().__init__()
        self._panel = None

    def init(self, ctx):
        for key, (zh, en) in _I18N.items():
            ctx.register_i18n(key, zh, en)

    def display_title(self):
        return _('FillLight.Title')

    def build_widget(self, ctx):
        self._panel = FillLightPanel(ctx)
        return self._panel

    def on_activated(self):
        if self._panel is not None:
            self._panel.on_activated()

    def on_deactivating(self):
        if self._panel is not None:
            self._panel.on_deactivating()

    def teardown_widget(self, widget):
        widget.deleteLater()
        self._panel = None

    def on_connect(self):
        if self._panel is not None:
            self._panel.on_connect()

    def on_disconnect(self):
        if self._panel is not None:
            self._panel.on_disconnect()

    def on_frames(self, frames):
        if self._panel is not None:
            self._panel.on_frames(frames)

    def refresh_language(self):
        if self._panel is not None:
            self._panel.refresh_language()


def create_plugin():
    return FillLightPlugin()
