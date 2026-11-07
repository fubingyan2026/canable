"""Shared compact Qt layouts for plugin panels, without rebuilding controls."""
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QComboBox,
                                QFrame, QGridLayout, QGroupBox, QHeaderView,
                                QLayout, QLineEdit, QTabBar, QTabWidget,
                                QTableView, QToolButton, QVBoxLayout, QWidget)

from .i18n import _


def prepare_plugin_ui(widget):
    """Scope compact styling and spacing to this plugin's existing widget tree."""
    for child in [widget, *widget.findChildren(QWidget)]:
        child.setProperty("pluginCompact", True)
        if isinstance(child, QTableView):
            header = child.verticalHeader()
            header.setMinimumSectionSize(20)
            header.setDefaultSectionSize(min(24, header.defaultSectionSize()))
            child.horizontalHeader().setProperty("pluginCompact", True)
        if isinstance(child, (QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit,
                              QGroupBox, QHeaderView, QTabBar, QTableView)):
            child.style().unpolish(child)
            child.style().polish(child)
            QCoreApplication.sendEvent(child, QEvent(QEvent.StyleChange))
            child.updateGeometry()
    for layout in widget.findChildren(QLayout):
        margins = layout.contentsMargins()
        layout.setContentsMargins(min(6, margins.left()), min(4, margins.top()),
                                  min(6, margins.right()), min(4, margins.bottom()))
        if isinstance(layout, QGridLayout):
            layout.setHorizontalSpacing(min(4, max(0, layout.horizontalSpacing())))
            layout.setVerticalSpacing(min(3, max(0, layout.verticalSpacing())))
        elif layout.spacing() < 0 or layout.spacing() > 4:
            layout.setSpacing(4)


class SectionPage(QWidget):
    """A tab page exposing the same title API used by plugin group boxes."""

    def __init__(self, title):
        super().__init__()
        self.setTitle(title)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("pluginPage", True)

    def setTitle(self, title):
        self.setWindowTitle(title)

    def title(self):
        return self.windowTitle()


class SectionTabs(QTabWidget):
    """Native tabs for secondary tools; inactive pages do not reserve height."""

    def __init__(self):
        super().__init__()
        self.setDocumentMode(True)
        self.setUsesScrollButtons(True)
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def add_section(self, page):
        self.addTab(page, page.title())
        page.windowTitleChanged.connect(lambda title: self.setTabText(self.indexOf(page), title))

    def minimumSizeHint(self):
        page = self.currentWidget()
        if page is None:
            return super().minimumSizeHint()
        minimum = page.minimumSizeHint().expandedTo(page.minimumSize())
        return QSize(minimum.width() + 4,
                     minimum.height() + self.tabBar().sizeHint().height() + 4)

    def sizeHint(self):
        page = self.currentWidget()
        if page is None:
            return super().sizeHint()
        return page.sizeHint() + QSize(4, self.tabBar().sizeHint().height() + 4)


class DisclosureSection(QFrame):
    """A keyboard-accessible Qt disclosure that only hides its content."""

    def __init__(self, title, expanded=False):
        super().__init__()
        self.setObjectName("pluginDisclosure")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = QToolButton()
        self.header.setObjectName("disclosureHeader")
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setCheckable(True)
        self.body = QWidget()
        layout.addWidget(self.header)
        layout.addWidget(self.body)
        self.header.toggled.connect(self._set_expanded)
        self.setTitle(title)
        self.header.setChecked(expanded)
        self._set_expanded(expanded)

    def setTitle(self, title):
        self.header.setText(title)
        self.header.setToolTip(_("Plugin.ToggleSection"))

    def title(self):
        return self.header.text()

    def _set_expanded(self, expanded):
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.body.setVisible(expanded)
        self.updateGeometry()


class FlowLayout(QLayout):
    """Wrap a native Qt toolbar at control boundaries instead of clipping it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(4)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), measure=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect, measure=False):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        y, line_width, line_height = area.y(), 0, 0
        line = []
        for item in self._items:
            if item.isEmpty():
                continue
            size = item.sizeHint()
            gap = self.spacing() if line else 0
            if line and line_width + gap + size.width() > area.width():
                if not measure:
                    self._place_line(line, area.x(), y, area.width() - line_width)
                y += line_height + self.spacing()
                line, line_width, line_height, gap = [], 0, 0, 0
            line.append((item, size))
            line_width += gap + size.width()
            line_height = max(line_height, size.height())
        if not measure:
            self._place_line(line, area.x(), y, area.width() - line_width)
        return y + line_height - rect.y() + margins.bottom()

    def _place_line(self, line, x, y, extra):
        expanding = [item for item, size in line
                     if item.expandingDirections() & Qt.Horizontal]
        remaining = max(0, extra)
        for item, size in line:
            width = size.width()
            if item in expanding:
                growth = min(remaining // len(expanding), item.maximumSize().width() - width)
                width += growth
                remaining -= growth
                expanding.remove(item)
            item.setGeometry(QRect(QPoint(x, y), QSize(width, size.height())))
            x += width + self.spacing()
