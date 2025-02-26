import sys
import json
import random
from io import BytesIO
import matplotlib.pyplot as plt

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QGraphicsScene, QGraphicsView, QVBoxLayout,
    QWidget, QAction, QFileDialog, QToolBar, QDockWidget, QTextEdit, QColorDialog,
    QLabel, QLineEdit, QPushButton, QGraphicsRectItem, QGraphicsTextItem,
    QGraphicsEllipseItem, QSizePolicy, QGraphicsLineItem, QMessageBox
)
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QColor, QPen, QBrush, QPixmap, QImage, QPainter

# -------------------------------------------
# Custom QGraphicsView subclass for panning.
# -------------------------------------------
class MyGraphicsView(QGraphicsView):
    def __init__(self, *args, **kwargs):
        super(MyGraphicsView, self).__init__(*args, **kwargs)
        self._isPanning = False
        self._panStart = QPointF()

    def mousePressEvent(self, event):
        # If click on empty area (no item clicked) then start panning.
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item is None:
                self._isPanning = True
                self.setCursor(Qt.ClosedHandCursor)
                self._panStart = event.pos()
                event.accept()
                return
        super(MyGraphicsView, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._isPanning:
            delta = self.mapToScene(event.pos()) - self.mapToScene(self._panStart)
            self._panStart = event.pos()
            self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
            self.translate(delta.x() * -1, delta.y() * -1)
            event.accept()
            return
        super(MyGraphicsView, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._isPanning:
            self._isPanning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super(MyGraphicsView, self).mouseReleaseEvent(event)

# -------------------------------------------
# ClickableLine for connections with crash prevention.
# -------------------------------------------
class ClickableLine(QGraphicsLineItem):
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            scene = self.scene()
            if scene is None or not hasattr(scene, "editor"):
                return
            conn = self.connection_info
            try:
                scene.removeItem(self)
            except Exception as e:
                print("Error removing connection line:", e)
            editor = scene.editor
            if conn in editor.connections:
                editor.connections.remove(conn)
            print("Зв'язок видалено.")
        super().mousePressEvent(event)

# -------------------------------------------
# GraphConnection represents a connection between two anchor handles.
# -------------------------------------------
class GraphConnection:
    def __init__(self, start_anchor, scene):
        self.start_anchor = start_anchor
        self.end_anchor = None
        self.line_item = None
        self.scene = scene

    def create_line_item(self):
        start_point = self.start_anchor.sceneBoundingRect().center()
        pen = QPen(Qt.darkGreen, 2)
        self.line_item = ClickableLine(start_point.x(), start_point.y(), start_point.x(), start_point.y())
        self.line_item.setPen(pen)
        self.line_item.setFlags(ClickableLine.ItemIsSelectable)
        self.line_item.connection_info = self
        self.scene.addItem(self.line_item)

    def update_line_item(self, current_pos=None):
        if not self.line_item:
            return
        start_point = self.start_anchor.sceneBoundingRect().center()
        if self.end_anchor:
            end_point = self.end_anchor.sceneBoundingRect().center()
        elif current_pos is not None:
            end_point = current_pos
        else:
            end_point = start_point
        self.line_item.setLine(start_point.x(), start_point.y(), end_point.x(), end_point.y())

# -------------------------------------------
# AnchorHandle for starting/ending connections.
# -------------------------------------------
class AnchorHandle(QGraphicsEllipseItem):
    HANDLE_SIZE = 8

    def __init__(self, parent_block, orientation, editor):
        """
        orientation: one of "top", "bottom", "left", "right"
        """
        super().__init__(0, 0, self.HANDLE_SIZE, self.HANDLE_SIZE, parent_block)
        self.parent_block = parent_block
        self.orientation = orientation
        self.editor = editor
        self.setBrush(QBrush(QColor("blue")))
        self.setFlag(QGraphicsEllipseItem.ItemIsSelectable, False)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.LeftButton)

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor("red")))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(QColor("blue")))
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.editor.startConnection(self)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            items_at_pos = self.editor.scene.items(event.scenePos())
            target_anchor = None
            for item in items_at_pos:
                if isinstance(item, AnchorHandle) and item != self:
                    target_anchor = item
                    break
            if target_anchor:
                self.editor.endConnection(target_anchor)
                event.accept()
            else:
                self.editor.cancelConnection()
                event.accept()
        else:
            super().mouseReleaseEvent(event)

# -------------------------------------------
# GraphBlock represents a block on the scene.
# -------------------------------------------
class GraphBlock(QGraphicsRectItem):
    def __init__(self, rect, title="Block", editor=None):
        super().__init__(rect)
        self.block_id = None
        # Allow selection but movement is controlled by the locked flag.
        self.setFlags(QGraphicsRectItem.ItemIsSelectable | QGraphicsRectItem.ItemSendsScenePositionChanges)
        self.setFlag(QGraphicsRectItem.ItemIsMovable, True)
        self.editor = editor
        self.title = title
        self.content = ""
        self.color = "#ffffff"  # default white
        self.textItem = QGraphicsTextItem(title, self)
        self.textItem.setDefaultTextColor(Qt.black)
        self.centerText()
        self.anchors = {}
        for orient in ["top", "bottom", "left", "right"]:
            self.anchors[orient] = AnchorHandle(self, orient, editor)
        self.updateAnchors()
        self.locked = False  # False means movable.
    
    def centerText(self):
        rect = self.rect()
        textRect = self.textItem.boundingRect()
        x = rect.x() + (rect.width() - textRect.width()) / 2
        y = rect.y() + (rect.height() - textRect.height()) / 2
        self.textItem.setPos(x, y)
    
    def setTitle(self, title):
        self.title = title
        self.textItem.setPlainText(title)
        self.centerText()
    
    def setBlockRect(self, newRect):
        self.setRect(newRect)
        self.centerText()
        self.updateAnchors()
    
    def updateAnchors(self):
        r = self.rect()
        size = AnchorHandle.HANDLE_SIZE
        self.anchors["top"].setPos(r.width()/2 - size/2, -size/2)
        self.anchors["bottom"].setPos(r.width()/2 - size/2, r.height()-size/2)
        self.anchors["left"].setPos(-size/2, r.height()/2 - size/2)
        self.anchors["right"].setPos(r.width()-size/2, r.height()/2 - size/2)
    
    def mousePressEvent(self, event):
        # Always allow selection, so user can unfix via the edit panel.
        if self.editor:
            if not self.editor.editDock.isVisible():
                self.editor.editDock.show()
            # Reset latex preview when a new block is selected.
            self.editor.setCurrentBlock(self)
            self.editor.latexEdit.show()
            self.editor.previewLabel.hide()
        super().mousePressEvent(event)
    
    def itemChange(self, change, value):
        if change == QGraphicsRectItem.ItemPositionChange and self.locked:
            return self.pos()  # Prevent movement.
        if change == QGraphicsRectItem.ItemPositionHasChanged and self.editor:
            self.editor.updateConnectionsForBlock(self)
        return super().itemChange(change, value)

# -------------------------------------------
# GraphCluster represents a grouping of blocks.
# -------------------------------------------
class GraphCluster(QGraphicsRectItem):
    def __init__(self, blocks, title="Cluster", editor=None):
        bounding_rect = self.computeBoundingRect(blocks)
        super().__init__(bounding_rect)
        self.setFlags(QGraphicsRectItem.ItemIsSelectable | QGraphicsRectItem.ItemSendsScenePositionChanges)
        self.setFlag(QGraphicsRectItem.ItemIsMovable, True)
        self.editor = editor
        self.title = title
        self.color = "#ffeeaa"  # default cluster color
        self.blocks = blocks  # list of blocks in the cluster
        self.textItem = QGraphicsTextItem(title, self)
        self.textItem.setDefaultTextColor(Qt.black)
        self.centerText()
        self.setBrush(QBrush(QColor(self.color)))
        self.setZValue(-1)
        self.locked = False  # False means movable.
    
    def computeBoundingRect(self, blocks):
        if not blocks:
            return QRectF()
        rect = blocks[0].sceneBoundingRect()
        for blk in blocks[1:]:
            rect = rect.united(blk.sceneBoundingRect())
        rect.adjust(-10, -10, 10, 10)
        return rect
    
    def centerText(self):
        rect = self.rect()
        textRect = self.textItem.boundingRect()
        x = rect.x() + (rect.width() - textRect.width()) / 2
        y = rect.y() + (rect.height() - textRect.height()) / 2
        self.textItem.setPos(x, y)
    
    def setTitle(self, title):
        self.title = title
        self.textItem.setPlainText(title)
        self.centerText()
    
    def setClusterRect(self, newRect):
        self.setRect(newRect)
        self.centerText()
    
    def mousePressEvent(self, event):
        # Always allow selection, even when locked.
        if self.editor:
            if not self.editor.editDock.isVisible():
                self.editor.editDock.show()
            self.editor.setCurrentCluster(self)
            self.editor.latexEdit.show()
            self.editor.previewLabel.hide()
        super().mousePressEvent(event)
    
    def itemChange(self, change, value):
        if change == QGraphicsRectItem.ItemPositionChange and self.locked:
            return self.pos()  # Prevent movement.
        if change == QGraphicsRectItem.ItemPositionHasChanged and self.editor:
            self.editor.updateConnectionsForCluster(self)
        return super().itemChange(change, value)

# -------------------------------------------
# CustomScene to manage interactive connection dragging and background clicks.
# -------------------------------------------
class CustomScene(QGraphicsScene):
    def __init__(self, editor, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
    
    def mouseMoveEvent(self, event):
        if self.editor.current_connection:
            self.editor.current_connection.update_line_item(current_pos=event.scenePos())
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        if self.editor.current_connection:
            items_at_pos = self.items(event.scenePos())
            target_anchor = None
            for item in items_at_pos:
                if isinstance(item, AnchorHandle):
                    target_anchor = item
                    break
            if target_anchor:
                # Handled by AnchorHandle.
                pass
            else:
                self.editor.cancelConnection()
        super().mouseReleaseEvent(event)

# -------------------------------------------
# Main GraphEditor class.
# -------------------------------------------
class GraphEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Графічний редактор")
        self.resize(1200, 800)
        self.block_id_counter = 1
        self.cluster_id_counter = 1
        self.blocks = {}      # block_id -> GraphBlock
        self.clusters = {}    # cluster_id -> GraphCluster
        self.connections = [] # list of GraphConnection objects
        self.currentBlock = None      # currently selected block
        self.currentCluster = None    # currently selected cluster
        self.editLocked = False       # edit panel locked
        self.current_connection = None  # active connection being drawn
        self.initUI()
    
    def initUI(self):
        self.scene = CustomScene(self, 0, 0, 3000, 3000)
        # Use our custom view which supports panning.
        self.view = MyGraphicsView(self.scene, self)
        self.view.setRenderHints(QPainter.Antialiasing)
        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setCentralWidget(self.view)
        
        self.createMenus()
        self.createToolBar()
        self.createEditPanel()
    
    def createMenus(self):
        menubar = self.menuBar()
        fileMenu = menubar.addMenu("Файл")
        newAction = QAction("Новий", self)
        openAction = QAction("Відкрити", self)
        saveAction = QAction("Зберегти", self)
        
        newAction.triggered.connect(self.newFile)
        openAction.triggered.connect(self.openFile)
        saveAction.triggered.connect(self.saveFile)
        
        fileMenu.addAction(newAction)
        fileMenu.addAction(openAction)
        fileMenu.addAction(saveAction)
    
    def createToolBar(self):
        toolbar = QToolBar("Інструменти", self)
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        
        # Removed detach/attach buttons here.
        addBlockAction = QAction("Додати блок", self)
        deleteAction = QAction("Видалити", self)
        groupAction = QAction("Групувати", self)
        changeColorAction = QAction("Змінити колір", self)
        zoomInAction = QAction("Збільшити", self)
        zoomOutAction = QAction("Зменшити", self)
        
        addBlockAction.triggered.connect(self.addBlock)
        deleteAction.triggered.connect(self.deleteSelected)
        groupAction.triggered.connect(self.groupSelectedBlocks)
        changeColorAction.triggered.connect(self.changeColor)
        zoomInAction.triggered.connect(lambda: self.view.scale(1.15, 1.15))
        zoomOutAction.triggered.connect(lambda: self.view.scale(1/1.15, 1/1.15))
        
        toolbar.addAction(addBlockAction)
        toolbar.addAction(deleteAction)
        toolbar.addAction(groupAction)
        toolbar.addAction(changeColorAction)
        toolbar.addAction(zoomInAction)
        toolbar.addAction(zoomOutAction)
    
    def createEditPanel(self):
        self.editDock = QDockWidget("Редагування", self)
        self.editDock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.editDock.setFeatures(QDockWidget.DockWidgetClosable)
        self.editDock.visibilityChanged.connect(self.onEditDockVisibilityChanged)
        editWidget = QWidget()
        layout = QVBoxLayout()
        
        self.titleEdit = QLineEdit()
        self.titleEdit.setPlaceholderText("Заголовок")
        
        # LaTeX code editing and preview.
        self.latexEdit = QTextEdit()
        self.latexEdit.setPlaceholderText("Введіть LaTeX код тут")
        self.latexEdit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.previewLabel = QLabel()
        self.previewLabel.setAlignment(Qt.AlignCenter)
        self.previewLabel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.previewLabel.hide()
        self.previewButton = QPushButton("Переглянути LaTeX")
        self.previewButton.clicked.connect(self.previewLatex)
        self.editLatexButton = QPushButton("Редагувати LaTeX")
        self.editLatexButton.clicked.connect(self.editLatex)
        
        self.widthEdit = QLineEdit()
        self.widthEdit.setPlaceholderText("Ширина")
        self.heightEdit = QLineEdit()
        self.heightEdit.setPlaceholderText("Висота")
        
        saveEditButton = QPushButton("Зберегти зміни")
        saveEditButton.clicked.connect(self.saveEdit)
        lockButton = QPushButton("Заблокувати редагування")
        lockButton.setCheckable(True)
        lockButton.toggled.connect(self.onLockToggled)
        
        # New detach/attach buttons for clusters.
        self.detachClusterButton = QPushButton("Відкріпити блоки")
        self.detachClusterButton.clicked.connect(self.detachClusterBlocks)
        self.attachClusterButton = QPushButton("Прикріпити блоки")
        self.attachClusterButton.clicked.connect(self.attachClusterBlocks)
        # Show these buttons only when a cluster is selected.
        self.detachClusterButton.hide()
        self.attachClusterButton.hide()
        
        # Fix/unfix buttons remain here.
        self.fixButton = QPushButton("Закріпити об'єкт")
        self.fixButton.clicked.connect(self.fixCurrent)
        self.unfixButton = QPushButton("Відкріпити об'єкт")
        self.unfixButton.clicked.connect(self.unfixCurrent)
        
        layout.addWidget(QLabel("Заголовок:"))
        layout.addWidget(self.titleEdit)
        layout.addWidget(QLabel("LaTeX код:"))
        layout.addWidget(self.latexEdit)
        layout.addWidget(self.previewLabel)
        layout.addWidget(self.previewButton)
        layout.addWidget(self.editLatexButton)
        layout.addWidget(QLabel("Ширина:"))
        layout.addWidget(self.widthEdit)
        layout.addWidget(QLabel("Висота:"))
        layout.addWidget(self.heightEdit)
        layout.addWidget(saveEditButton)
        layout.addWidget(lockButton)
        layout.addWidget(self.fixButton)
        layout.addWidget(self.unfixButton)
        layout.addWidget(self.detachClusterButton)
        layout.addWidget(self.attachClusterButton)
        
        editWidget.setLayout(layout)
        self.editDock.setWidget(editWidget)
        self.editDock.hide()
        self.addDockWidget(Qt.RightDockWidgetArea, self.editDock)
    
    def previewLatex(self):
        latex_code = self.latexEdit.toPlainText()
        if not latex_code.strip():
            QMessageBox.warning(self, "Помилка", "LaTeX код порожній!")
            return
        try:
            fig = plt.figure(figsize=(0.01, 0.01))
            fig.text(0, 0, r"${}$".format(latex_code), fontsize=20)
            buf = BytesIO()
            plt.axis("off")
            plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.1)
            plt.close(fig)
            buf.seek(0)
            image = QImage.fromData(buf.getvalue())
            pixmap = QPixmap.fromImage(image)
            self.previewLabel.setPixmap(pixmap)
            self.latexEdit.hide()
            self.previewLabel.show()
        except Exception as e:
            QMessageBox.critical(self, "Помилка", f"Помилка відтворення LaTeX: {e}")
    
    def editLatex(self):
        self.previewLabel.hide()
        self.latexEdit.show()
    
    def onEditDockVisibilityChanged(self, visible):
        if not visible:
            self.editLocked = False
            self.currentBlock = None
            self.currentCluster = None
    
    def onLockToggled(self, locked):
        self.editLocked = locked
        if locked:
            print("Редагування заблоковано для поточного об'єкта.")
        else:
            print("Редагування розблоковано. Натисніть об'єкт для редагування.")
    
    def setCurrentBlock(self, block):
        if not self.editLocked:
            self.currentBlock = block
            self.currentCluster = None
            self.titleEdit.setText(block.title)
            self.latexEdit.setPlainText(block.content)
            self.latexEdit.show()
            self.previewLabel.hide()
            r = block.rect()
            self.widthEdit.setText(str(int(r.width())))
            self.heightEdit.setText(str(int(r.height())))
            self.detachClusterButton.hide()
            self.attachClusterButton.hide()
    
    def setCurrentCluster(self, cluster):
        if not self.editLocked:
            self.currentCluster = cluster
            self.currentBlock = None
            self.titleEdit.setText(cluster.title)
            self.latexEdit.setPlainText("")
            self.latexEdit.show()
            self.previewLabel.hide()
            r = cluster.rect()
            self.widthEdit.setText(str(int(r.width())))
            self.heightEdit.setText(str(int(r.height())))
            self.detachClusterButton.show()
            self.attachClusterButton.show()
    
    def addBlock(self):
        rect = QRectF(0, 0, 150, 80)
        block = GraphBlock(rect, "Новий блок", editor=self)
        block.block_id = self.block_id_counter
        self.blocks[self.block_id_counter] = block
        self.block_id_counter += 1
        x = random.randint(0, 400)
        y = random.randint(0, 300)
        block.setPos(x, y)
        block.setBrush(QBrush(QColor(block.color)))
        self.scene.addItem(block)
        if not self.editDock.isVisible():
            self.editDock.show()
        self.setCurrentBlock(block)
        print(f"Додано блок {block.block_id} на позиції: ({x}, {y})")
    
    def deleteSelected(self):
        for item in self.scene.selectedItems():
            if isinstance(item, GraphBlock):
                if item.block_id in self.blocks:
                    conns_to_remove = [conn for conn in self.connections 
                                       if conn.start_anchor.parent_block == item or 
                                       (conn.end_anchor and conn.end_anchor.parent_block == item)]
                    for conn in conns_to_remove:
                        if conn.line_item:
                            self.scene.removeItem(conn.line_item)
                        if conn in self.connections:
                            self.connections.remove(conn)
                    self.scene.removeItem(item)
                    del self.blocks[item.block_id]
                    print(f"Видалено блок {item.block_id}")
            elif isinstance(item, GraphCluster):
                for blk in item.blocks:
                    blk.setParentItem(None)
                for key, val in list(self.clusters.items()):
                    if val == item:
                        del self.clusters[key]
                        break
                self.scene.removeItem(item)
                print(f"Видалено кластер {item.title}")
    
    def groupSelectedBlocks(self):
        selected_blocks = [item for item in self.scene.selectedItems() if isinstance(item, GraphBlock)]
        if len(selected_blocks) < 2:
            print("Потрібно вибрати щонайменше 2 блоки для групування.")
            return
        cluster = GraphCluster(selected_blocks, title=f"Кластер {self.cluster_id_counter}", editor=self)
        self.clusters[self.cluster_id_counter] = cluster
        self.cluster_id_counter += 1
        for blk in selected_blocks:
            blk.setParentItem(cluster)
        self.scene.addItem(cluster)
        print("Створено кластер із блоків:", [blk.block_id for blk in selected_blocks])
    
    def detachClusterBlocks(self):
        # Detach blocks from the current cluster without deleting the cluster.
        if self.currentCluster:
            for blk in self.currentCluster.blocks:
                blk.setParentItem(None)
            self.currentCluster.blocks = []
            self.currentCluster.setRect(QRectF())
            print(f"Відкріплено всі блоки з кластера {self.currentCluster.title}")
    
    def attachClusterBlocks(self):
        # Attach blocks within the cluster's bounding area.
        if self.currentCluster:
            attached = []
            cluster_rect = self.currentCluster.sceneBoundingRect()
            for block in self.blocks.values():
                if block.parentItem() is None and cluster_rect.contains(block.scenePos()):
                    block.setParentItem(self.currentCluster)
                    attached.append(block.block_id)
                    if block not in self.currentCluster.blocks:
                        self.currentCluster.blocks.append(block)
            print(f"Прикріплено блоки {attached} до кластера {self.currentCluster.title}")
    
    def fixCurrent(self):
        # Fix (lock) the current block or cluster so that it cannot be moved.
        if self.currentBlock:
            self.currentBlock.locked = True
            self.currentBlock.setFlag(QGraphicsRectItem.ItemIsMovable, False)
            print(f"Блок {self.currentBlock.block_id} закріплено.")
        elif self.currentCluster:
            self.currentCluster.locked = True
            self.currentCluster.setFlag(QGraphicsRectItem.ItemIsMovable, False)
            print(f"Кластер {self.currentCluster.title} закріплено.")
    
    def unfixCurrent(self):
        # Unfix (unlock) the current block or cluster so it can be moved.
        if self.currentBlock:
            self.currentBlock.locked = False
            self.currentBlock.setFlag(QGraphicsRectItem.ItemIsMovable, True)
            print(f"Блок {self.currentBlock.block_id} відкріплено.")
        elif self.currentCluster:
            self.currentCluster.locked = False
            self.currentCluster.setFlag(QGraphicsRectItem.ItemIsMovable, True)
            print(f"Кластер {self.currentCluster.title} відкріплено.")
    
    def startConnection(self, anchor):
        if self.current_connection:
            return
        self.current_connection = GraphConnection(anchor, self.scene)
        self.current_connection.create_line_item()
        print(f"Почато з'єднання з анкера {anchor.orientation} блоку {anchor.parent_block.block_id}")
    
    def endConnection(self, anchor):
        if not self.current_connection:
            return
        if anchor.parent_block != self.current_connection.start_anchor.parent_block:
            self.current_connection.end_anchor = anchor
            self.current_connection.update_line_item()
            self.connections.append(self.current_connection)
            print(f"З'єднання створено між блоком {self.current_connection.start_anchor.parent_block.block_id} ({self.current_connection.start_anchor.orientation}) та блоком {anchor.parent_block.block_id} ({anchor.orientation})")
        else:
            self.cancelConnection()
        self.current_connection = None
    
    def cancelConnection(self):
        if self.current_connection and self.current_connection.line_item:
            self.scene.removeItem(self.current_connection.line_item)
        self.current_connection = None
        print("З'єднання скасовано.")
    
    def changeColor(self):
        color = QColorDialog.getColor()
        if color.isValid():
            if self.currentBlock:
                self.currentBlock.color = color.name()
                self.currentBlock.setBrush(QBrush(color))
                print("Змінено колір блоку на:", color.name())
            if self.currentCluster:
                self.currentCluster.color = color.name()
                self.currentCluster.setBrush(QBrush(color))
                print("Змінено колір кластера на:", color.name())
    
    def updateConnectionsForBlock(self, block):
        for conn in self.connections:
            if conn.start_anchor.parent_block == block or (conn.end_anchor and conn.end_anchor.parent_block == block):
                conn.update_line_item()
        if self.current_connection and self.current_connection.start_anchor.parent_block == block:
            self.current_connection.update_line_item()
    
    def updateConnectionsForCluster(self, cluster):
        for blk in cluster.blocks:
            self.updateConnectionsForBlock(blk)
    
    def newFile(self):
        self.scene.clear()
        self.blocks.clear()
        self.clusters.clear()
        self.connections.clear()
        self.block_id_counter = 1
        self.cluster_id_counter = 1
        self.currentBlock = None
        self.currentCluster = None
        print("Новий файл")
    
    def openFile(self):
        options = QFileDialog.Options()
        filename, _ = QFileDialog.getOpenFileName(self, "Відкрити файл", "", "JSON Files (*.json);;All Files (*)", options=options)
        if filename:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.newFile()
            for block_data in data.get("blocks", []):
                rect = QRectF(0, 0, block_data["width"], block_data["height"])
                block = GraphBlock(rect, block_data["title"], editor=self)
                block.block_id = block_data["id"]
                block.content = block_data.get("content", "")
                block.color = block_data.get("color", "#ffffff")
                block.setBrush(QBrush(QColor(block.color)))
                block.setPos(block_data["x"], block_data["y"])
                block.locked = block_data.get("locked", False)
                if block.locked:
                    block.setFlag(QGraphicsRectItem.ItemIsMovable, False)
                self.blocks[block.block_id] = block
                self.scene.addItem(block)
                if block.block_id >= self.block_id_counter:
                    self.block_id_counter = block.block_id + 1
            for cluster_data in data.get("clusters", []):
                cluster_blocks = []
                for bid in cluster_data.get("block_ids", []):
                    if bid in self.blocks:
                        cluster_blocks.append(self.blocks[bid])
                if cluster_blocks:
                    cluster = GraphCluster(cluster_blocks, title=cluster_data["title"], editor=self)
                    cluster.color = cluster_data.get("color", "#ffeeaa")
                    cluster.setBrush(QBrush(QColor(cluster.color)))
                    cluster.locked = cluster_data.get("locked", False)
                    if cluster.locked:
                        cluster.setFlag(QGraphicsRectItem.ItemIsMovable, False)
                    self.clusters[cluster_data["id"]] = cluster
                    self.scene.addItem(cluster)
            for conn_data in data.get("connections", []):
                start_id = conn_data["start_block_id"]
                end_id = conn_data["end_block_id"]
                start_orientation = conn_data["start_anchor"]
                end_orientation = conn_data["end_anchor"]
                if start_id in self.blocks and end_id in self.blocks:
                    start_block = self.blocks[start_id]
                    end_block = self.blocks[end_id]
                    start_anchor = start_block.anchors.get(start_orientation)
                    end_anchor = end_block.anchors.get(end_orientation)
                    conn = GraphConnection(start_anchor, self.scene)
                    conn.end_anchor = end_anchor
                    conn.create_line_item()
                    conn.update_line_item()
                    self.connections.append(conn)
            print("Відкрито файл:", filename)
    
    def saveFile(self):
        options = QFileDialog.Options()
        filename, _ = QFileDialog.getSaveFileName(self, "Зберегти файл", "", "JSON Files (*.json);;All Files (*)", options=options)
        if filename:
            data = {"blocks": [], "clusters": [], "connections": []}
            for block in self.blocks.values():
                pos = block.scenePos()
                rect = block.rect()
                block_data = {
                    "id": block.block_id,
                    "title": block.title,
                    "content": block.content,
                    "x": pos.x(),
                    "y": pos.y(),
                    "width": rect.width(),
                    "height": rect.height(),
                    "color": block.color,
                    "locked": block.locked
                }
                data["blocks"].append(block_data)
            for cid, cluster in self.clusters.items():
                cluster_data = {
                    "id": cid,
                    "title": cluster.title,
                    "color": cluster.color,
                    "block_ids": [blk.block_id for blk in cluster.blocks],
                    "locked": cluster.locked
                }
                data["clusters"].append(cluster_data)
            for conn in self.connections:
                if not conn.end_anchor:
                    continue
                conn_data = {
                    "start_block_id": conn.start_anchor.parent_block.block_id,
                    "start_anchor": conn.start_anchor.orientation,
                    "end_block_id": conn.end_anchor.parent_block.block_id,
                    "end_anchor": conn.end_anchor.orientation
                }
                data["connections"].append(conn_data)
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print("Збережено файл:", filename)
    
    def saveEdit(self):
        if self.currentBlock:
            title = self.titleEdit.text()
            content = self.latexEdit.toPlainText()
            try:
                width = float(self.widthEdit.text())
                height = float(self.heightEdit.text())
            except ValueError:
                width, height = self.currentBlock.rect().width(), self.currentBlock.rect().height()
            self.currentBlock.setTitle(title)
            self.currentBlock.content = content
            newRect = QRectF(0, 0, width, height)
            self.currentBlock.setBlockRect(newRect)
            print("Збережено зміни для блоку:", title)
        elif self.currentCluster:
            title = self.titleEdit.text()
            try:
                width = float(self.widthEdit.text())
                height = float(self.heightEdit.text())
            except ValueError:
                width, height = self.currentCluster.rect().width(), self.currentCluster.rect().height()
            self.currentCluster.setTitle(title)
            newRect = QRectF(self.currentCluster.rect().x(), self.currentCluster.rect().y(), width, height)
    
    def wheelEvent(self, event):
        factor = 1.15
        if event.angleDelta().y() > 0:
            self.view.scale(factor, factor)
        else:
            self.view.scale(1/factor, 1/factor)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    editor = GraphEditor()
    editor.show()
    sys.exit(app.exec_())