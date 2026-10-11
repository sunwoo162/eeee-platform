"""Extract the desktop pet's reusable layers and render an asset reference table."""

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from app.desktop.pet_assets import PET_ASSET_TABLE


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "apps" / "eeee" / "app" / "desktop" / "assets"
OUT_DIR = ASSET_DIR / "pet"
SOURCE_FILES = {
    "idle": "cat-keyboard-idle.png",
    "left": "cat-keyboard-right.png",
    "right": "cat-keyboard-left.png",
    "left_alt": "cat-keyboard-right-alt.png",
    "right_alt": "cat-keyboard-left-alt.png",
    "gaze_left": "cat-keyboard-gaze-left.png",
    "gaze_right": "cat-keyboard-gaze-right.png",
}


def mask_path(frame: str) -> QPainterPath:
    path = QPainterPath()
    points = PET_ASSET_TABLE[frame]["paw_mask"]["points"]
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    path.closeSubpath()
    return path


def extract_layer(source_frame: str, hand: str, filename: str) -> tuple[Path, QRect]:
    source = QImage(str(ASSET_DIR / SOURCE_FILES[source_frame])).convertToFormat(
        QImage.Format.Format_ARGB32
    )
    path = mask_path(hand)
    bounds = path.boundingRect().toAlignedRect().adjusted(-8, -8, 8, 8)
    layer = QImage(bounds.size(), QImage.Format.Format_ARGB32)
    layer.fill(Qt.GlobalColor.transparent)
    painter = QPainter(layer)
    painter.setClipPath(path.translated(-bounds.left(), -bounds.top()))
    painter.drawImage(-bounds.left(), -bounds.top(), source)
    painter.end()
    target = OUT_DIR / filename
    layer.save(str(target))
    return target, bounds


def draw_cell(painter: QPainter, rect: QRect, title: str, subtitle: str, image: QImage) -> None:
    painter.setPen(QPen(QColor("#d8dee9"), 2))
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(rect, 18, 18)
    painter.setPen(QColor("#182230"))
    painter.setFont(QFont("Malgun Gothic", 20, QFont.Weight.Bold))
    painter.drawText(rect.adjusted(18, 16, -18, -rect.height() + 48), title)
    painter.setPen(QColor("#64748b"))
    painter.setFont(QFont("Malgun Gothic", 12))
    painter.drawText(rect.adjusted(18, 47, -18, -rect.height() + 72), subtitle)
    target = rect.adjusted(18, 82, -18, -18)
    pixmap = QPixmap.fromImage(image).scaled(
        target.size(),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter.drawPixmap(
        target.x() + (target.width() - pixmap.width()) // 2,
        target.y() + (target.height() - pixmap.height()) // 2,
        pixmap,
    )


def main() -> None:
    app = QApplication.instance() or QApplication([])
    # The headless build environment has no registered fonts. Load a Windows
    # font explicitly so the reference sheet remains readable in CI and in
    # exported artifacts.
    font_id = QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\malgun.ttf")
    font_family = QFontDatabase.applicationFontFamilies(font_id)[0] if font_id >= 0 else "Arial"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    extracted: dict[str, tuple[Path, QRect]] = {}
    for source_frame, hand, filename in (
        ("left", "left", "paw-left-rest.png"),
        ("right_alt", "left", "paw-left-press.png"),
        ("right", "right", "paw-right-rest.png"),
        ("left_alt", "right", "paw-right-press.png"),
    ):
        extracted[filename] = extract_layer(source_frame, hand, filename)
        pass

    body = QImage(str(ASSET_DIR / SOURCE_FILES["idle"]))
    gaze_left = QImage(str(ASSET_DIR / SOURCE_FILES["gaze_left"]))
    gaze_right = QImage(str(ASSET_DIR / SOURCE_FILES["gaze_right"]))
    sheet = QImage(QSize(1500, 1120), QImage.Format.Format_ARGB32)
    sheet.fill(QColor("#f4f7fb"))
    painter = QPainter(sheet)
    painter.setPen(QColor("#172033"))
    painter.setFont(QFont(font_family, 30, QFont.Weight.Bold))
    painter.drawText(50, 58, "EEEE Pet Asset Table")
    painter.setPen(QColor("#64748b"))
    painter.setFont(QFont(font_family, 15))
    painter.drawText(52, 88, "원본 픽셀 유지 | 몸체·키보드 고정 | 앞발 레이어만 교체")

    cells = [
        ("공통 몸체", "body-keyboard-base | idle", body),
        ("왼손 | 기본", "paw-left-rest", QImage(str(extracted["paw-left-rest.png"][0]))),
        ("왼손 | 누름", "paw-left-press", QImage(str(extracted["paw-left-press.png"][0]))),
        ("오른손 | 기본", "paw-right-rest", QImage(str(extracted["paw-right-rest.png"][0]))),
        ("오른손 | 누름", "paw-right-press", QImage(str(extracted["paw-right-press.png"][0]))),
        ("시선 | 왼쪽", "gaze-left", gaze_left),
        ("시선 | 오른쪽", "gaze-right", gaze_right),
    ]
    card_w, card_h = 440, 280
    positions = [(50, 125), (530, 125), (1010, 125), (50, 445), (530, 445), (1010, 445), (50, 765)]
    for (title, subtitle, image), (x, y) in zip(cells, positions):
        draw_cell(painter, QRect(x, y, card_w, card_h), title, subtitle, image)
    painter.end()
    sheet.save(str(OUT_DIR / "pet-asset-table.png"))
    print(OUT_DIR / "pet-asset-table.png")
    for path, bounds in extracted.values():
        print(path.name, bounds.getRect())


if __name__ == "__main__":
    main()

