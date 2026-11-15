"""Группы вариантов строятся из каталога действий, заголовки нельзя назначить."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox
from actions.action_types import ACTION_GROUPS


class ActionPicker(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.addItem("Нет действия", "none")
        for category, entries in ACTION_GROUPS.items():
            self.addItem("— " + category + " —")
            header = self.model().item(self.count()-1)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            for key, title in entries:
                self.addItem(title, key)
        self.setMaxVisibleItems(15)
