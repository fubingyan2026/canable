"""Chinese / English translation module."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

class _Signal(QObject):
    lang_changed = Signal(str)

_signal = _Signal()
language_changed = _signal.lang_changed

_lang = "zh" 

_TR: dict[str, dict[str, str]] = {}


def _(key: str) -> str:
    entry = _TR.get(key)
    return entry.get(_lang, key) if entry else key


def set_language(lang: str):
    global _lang
    _lang = lang
    language_changed.emit(lang)


def get_language() -> str:
    return _lang


# ── register translations ────────────────────────────────────────────
_TR.update({
    # Menus
    "Menu.File":             {"zh": "文件(&F)",  "en": "&File"},
    "Menu.Windows":          {"zh": "窗口(&W)",  "en": "&Windows"},
    "Menu.Tools":            {"zh": "工具(&T)",  "en": "&Tools"},
    "Menu.Help":             {"zh": "帮助(&H)",  "en": "&Help"},
    "Menu.Plugins":          {"zh": "插件(&P)",  "en": "&Plugins"},
    "Menu.Language":         {"zh": "语言",      "en": "Language"},
    "Menu.Theme":           {"zh": "主题",      "en": "Theme"},

    # File menu items
    "File.OpenTrace":        {"zh": "打开 Trace(&O)…", "en": "&Open Trace…"},
    "File.SaveTrace":        {"zh": "保存 Trace(&S)…", "en": "&Save Trace…"},
    "File.Exit":             {"zh": "退出(&X)", "en": "E&xit"},

    # View / Windows menu items
    "Window.SendMessages":   {"zh": "发送消息", "en": "Send Messages"},
    "Window.Filters":        {"zh": "过滤器",  "en": "Filters"},

    # Tools menu items

    # Help menu items
    "Help.About":            {"zh": "关于 CANable 2.5", "en": "About CANable 2.5"},

    # Language names — 不再使用 i18n key，语言菜单项固定显示原生语种（中文/English）
    "Theme.Light":          {"zh": "浅色",     "en": "Light"},
    "Theme.Dark":           {"zh": "深色",     "en": "Dark"},

    # Trace column headers
    "Trace.No":              {"zh": "序号",        "en": "No."},
    "Trace.Time":            {"zh": "时间(s)",     "en": "Time (s)"},
    "Trace.Ch":              {"zh": "通道",        "en": "Ch"},
    "Trace.ID":              {"zh": "ID",          "en": "ID"},
    "Trace.Type":            {"zh": "类型",        "en": "Type"},
    "Trace.DLC":             {"zh": "DLC",         "en": "DLC"},
    "Trace.Data":            {"zh": "数据(hex)",   "en": "Data (hex)"},
    "Trace.Delta":           {"zh": "间隔(ms)",     "en": "dt (ms)"},
    "Trace.Period":          {"zh": "周期(ms)",    "en": "Period (ms)"},
    "Trace.Count":           {"zh": "计数",        "en": "Count"},

    # Trace toolbar
    "Trace.Clear":           {"zh": "清空",        "en": "Clear"},
    "Trace.Pause":           {"zh": "暂停",        "en": "Pause"},
    "Trace.Resume":          {"zh": "继续",        "en": "Resume"},
    "Trace.AutoScroll":      {"zh": "自动滚动",    "en": "Auto scroll"},
    "Trace.Collapse":        {"zh": "折叠 ID",     "en": "Collapse"},
    "Trace.Received":        {"zh": "已接收:",     "en": "Received:"},
    "Trace.UniqueIDs":       {"zh": "唯一 ID:",    "en": "Unique IDs:"},


    # Send panel
    "Send.Add":              {"zh": "添加",        "en": "Add"},
    "Send.Edit":             {"zh": "编辑",        "en": "Edit"},
    "Send.Delete":           {"zh": "删除",        "en": "Delete"},
    "Send.SendOnce":         {"zh": "发送一次",    "en": "Send once"},
    "Send.Start":            {"zh": "启动",        "en": "Start"},
    "Send.Stop":             {"zh": "停止",        "en": "Stop"},
    "Send.StartAll":         {"zh": "已启动周期发送", "en": "Periodic send started"},
    "Send.StopAll":          {"zh": "已停止周期发送", "en": "Periodic send stopped"},
    "Send.DialogTitle":      {"zh": "编辑发送报文", "en": "Edit Send Message"},
    "Send.Ready":            {"zh": "就绪",        "en": "Ready"},

    # Send panel table headers
    "Send.HdrName":        {"zh": "名称",    "en": "Name"},
    "Send.HdrID":            {"zh": "ID",      "en": "ID"},
    "Send.HdrType":          {"zh": "类型",    "en": "Type"},
    "Send.HdrDLC":           {"zh": "DLC",     "en": "DLC"},
    "Send.HdrData":          {"zh": "数据",    "en": "Data"},
    "Send.HdrPeriod":        {"zh": "周期",    "en": "Period"},
    "Send.HdrSent":          {"zh": "已发",    "en": "Sent"},
    "Send.HdrOn":            {"zh": "开启",    "en": "On"},

    # Send dialog form labels
    "Send.DlgID":            {"zh": "CAN ID (hex):",   "en": "CAN ID (hex):"},
    "Send.DlgName":        {"zh": "名称:",           "en": "Name:"},
    "Send.DlgType":          {"zh": "类型:",           "en": "Type:"},
    "Send.DlgExt":           {"zh": "扩展帧 (29-bit)",  "en": "Extended (29-bit)"},
    "Send.DlgRTR":           {"zh": "RTR 远程帧",      "en": "RTR"},
    "Send.DlgFD":            {"zh": "CAN FD",          "en": "CAN FD"},
    "Send.DlgBRS":           {"zh": "BRS",             "en": "BRS"},
    "Send.DlgDLC":           {"zh": "DLC:",            "en": "DLC:"},
    "Send.DlgData":          {"zh": "数据:",            "en": "Data:"},
    "Send.DlgPeriod":        {"zh": "周期(ms):",       "en": "Period (ms):"},
    "Send.FdDlcHEX":         {"zh": "十六进制，空格分隔", "en": "Hex, space separated"},

    # Filter panel
    "Filter.Add":            {"zh": "添加",        "en": "Add"},
    "Filter.Edit":           {"zh": "编辑",        "en": "Edit"},
    "Filter.Delete":         {"zh": "删除",        "en": "Delete"},
    "Filter.Clear":          {"zh": "清空",        "en": "Clear"},

    # Left panel
    "Left.Bus":              {"zh": "总线",            "en": "Bus"},
    "Left.Bitrate":          {"zh": "比特率:",         "en": "Bitrate:"},
    "Left.CANFD":            {"zh": "CAN FD",           "en": "CAN FD"},
    "Left.CANMode":          {"zh": "CAN模式:",        "en": "CAN Mode:"},
    "Left.BPS":              {"zh": "bps",              "en": "bps"},
    "Left.DataBitrate":      {"zh": "数据比特率:",     "en": "Data Bitrate:"},
    "Left.SamplePoint":      {"zh": "采样点:",         "en": "Sample Point:"},
    "Left.Sample87":         {"zh": "87.5% (默认)",    "en": "87.5% (default)"},
    "Left.Sample75":         {"zh": "75.0%",          "en": "75.0%"},
    "Left.Sample67":         {"zh": "66.7%",          "en": "66.7%"},
    "Left.Sample50":         {"zh": "50.0%",          "en": "50.0%"},
    "Left.Devices":          {"zh": "设备",            "en": "Devices"},
    "Left.Scan":             {"zh": "扫描设备",        "en": "Scan"},
    "Left.ConnectDevice":    {"zh": "连接设备",        "en": "Connect Device"},
    "Left.Disconnect":       {"zh": "断开",            "en": "Disconnect"},
    "Left.NoDeviceSelected": {"zh": "请先选择一个设备", "en": "Please select a device first"},
    "Left.NoDevice":         {"zh": "未发现 candleLight 设备", "en": "No candleLight device found"},
    "Left.RestoreSidebar":   {"zh": "恢复侧栏", "en": "Restore sidebar"},

    # Status bar
    "Status.Connected":      {"zh": "已连接",          "en": "Connected"},
    "Status.Disconnected":   {"zh": "未连接",          "en": "Not connected"},
    "Status.FPS":            {"zh": "帧/秒",           "en": "fps"},
    "Status.Load":           {"zh": "负载",            "en": "Load"},
    "Status.TotalFrames":    {"zh": "总帧数",          "en": "Total frames"},
    "Status.NoAck":          {"zh": "NO-ACK — 无设备应答", "en": "NO-ACK — no responding nodes"},

    # Error messages
    "Trace.Frames":        {"zh": "帧",           "en": "frames"},
    "Trace.ModeAll":       {"zh": "全部",         "en": "all"},
    "Trace.ModeCollapsed": {"zh": "折叠",         "en": "collapsed"},
    "Error.ConnectFailed":   {"zh": "连接失败",          "en": "Connection failed"},
    "About.Desc":           {"zh": "CANable 2.5 USB-CAN 适配器 上位机", "en": "CANable 2.5 USB-CAN Adapter GUI"},
    "About.Tech":           {"zh": "基于 PySide6 / Qt 6 + canable_sdk 驱动", "en": "Built with PySide6 / Qt 6 + canable_sdk driver"},
    # Filter panel
    "Filter.Drop":          {"zh": "丢弃",        "en": "Drop"},
    "Filter.Pass":          {"zh": "放行",        "en": "Pass"},
    "Filter.HdrIndex":      {"zh": "序号",      "en": "Index"},
    "Filter.HdrRange":      {"zh": "ID 范围",    "en": "ID Range"},
    "Filter.HdrType":       {"zh": "类型",       "en": "Type"},
    "Filter.HdrAction":     {"zh": "动作",       "en": "Action"},
    "Filter.DlgTitle":      {"zh": "编辑过滤规则","en": "Edit Filter Rule"},
    "Filter.DlgIDMin":      {"zh": "CAN ID 起始 (hex):", "en": "CAN ID Min (hex):"},
    "Filter.DlgIDMax":      {"zh": "CAN ID 结束 (hex):", "en": "CAN ID Max (hex):"},
    "Filter.DlgExt":        {"zh": "仅作用于扩展帧 (29-bit)", "en": "Extended only (29-bit)"},
    "Filter.DlgDiscard":    {"zh": "丢弃区间内的帧", "en": "Discard matching frames"},
    # Statistics panel
    "Stat.BusStatus":       {"zh": "总线状态",    "en": "Bus Status"},
    "Stat.TotalFrames":     {"zh": "总帧数",      "en": "Total"},
    "Stat.FPS":             {"zh": "帧率",        "en": "FPS"},
    "Stat.BusLoad":         {"zh": "总线负载",    "en": "Bus Load"},
    "Stat.UniqueID":        {"zh": "唯一 ID",     "en": "Unique IDs"},
    "Stat.IDDetail":        {"zh": "ID 详细",     "en": "ID Details"},
    "Stat.HdrID":           {"zh": "ID",          "en": "ID"},
    "Stat.HdrType":         {"zh": "类型",        "en": "Type"},
    "Stat.HdrCount":        {"zh": "计数",        "en": "Count"},
    "Stat.HdrPeriod":       {"zh": "周期(ms)",    "en": "Period (ms)"},
    "Stat.HdrLastDelta":    {"zh": "最近间隔(ms)","en": "Last Δt (ms)"},
    # Main window misc
    "Scan.Failed":          {"zh": "扫描失败",    "en": "Scan failed"},
    "Send.SelectRow":       {"zh": "请先选中一行", "en": "Please select a row first"},
    "Load.Failed":          {"zh": "加载失败",    "en": "Load failed"},

    # Worker errors
    "Error.FDNotSupported":     {"zh": "固件不支持 CAN FD，已回退到经典 CAN 模式，请取消勾选 CAN FD 选项", "en": "Firmware does not support CAN FD, reverted to Classic CAN. Uncheck CAN FD option"},
    "Error.CANErrorReg":        {"zh": "CAN 错误寄存器", "en": "CAN error register"},
    "Error.CANErrorRegHint":    {"zh": "非零表示物理层问题：检查 CANH/CANL 接线、120Ω 终端电阻、GND 共地", "en": "Non-zero means physical layer issue: check CANH/CANL wiring, 120Ω termination, GND"},
    "Status.ConnectedAt":       {"zh": "已连接 @", "en": "Connected @"},
    "Error.BitrateFailed":      {"zh": "设置波特率失败", "en": "Failed to set bitrate"},
    "Error.NotConnected":       {"zh": "未连接，无法发送", "en": "Not connected, cannot send"},
    "Error.SendFailedRecover":  {"zh": "发送失败: 控制器已自动恢复，请重试", "en": "Send failed: controller auto-recovered, please retry"},
    "Error.SendFailed":         {"zh": "发送失败", "en": "Send failed"},
    "Error.ReceiveError":       {"zh": "接收错误", "en": "Receive error"},
    "Error.BusOffRecover":      {"zh": "BUS-OFF, 已自动恢复控制器", "en": "BUS-OFF, controller auto-recovered"},
    "Status.Connecting":        {"zh": "正在连接…", "en": "Connecting…"},
    "Status.Disconnecting":     {"zh": "正在断开，请稍候…", "en": "Disconnecting, please wait…"},

    # File dialog titles
    "File.SaveTraceTitle":      {"zh": "保存 Trace", "en": "Save Trace"},
    "File.OpenTraceTitle":      {"zh": "加载 Trace", "en": "Open Trace"},
    "File.TraceSaved":          {"zh": "Trace 已保存到", "en": "Trace saved to"},

    # Trace misc
    "Trace.CollapseTooltip":    {"zh": "每个 CAN ID 仅显示最新帧", "en": "Show only latest frame per CAN ID"},
    "Trace.TabLabel":           {"zh": "跟踪", "en": "Trace"},

    # Send dialog
    "Send.NamePlaceholder":     {"zh": "名称 (可选)", "en": "Name (optional)"},

})
