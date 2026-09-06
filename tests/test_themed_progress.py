"""Visual progress textures cannot invent progress or outlive their task."""
import pytest
from PySide6.QtCore import Qt, QTimer


def make_progress(qtbot, theme_id, reduced=True):
    from moyle_steg.progress import ThemedProgressBar
    from moyle_steg.theme import get_theme
    bar = ThemedProgressBar()
    qtbot.addWidget(bar)
    bar.resize(360, 16)
    bar.setTextVisible(False)
    bar.set_appearance(get_theme(theme_id), reduced)
    bar.setRange(0, 1000)
    bar.setValue(0)
    bar.show()
    return bar


def sample(bar, fraction):
    image = bar.grab().toImage()
    return image.pixelColor(round((image.width() - 1) * fraction), image.height() // 2)


@pytest.mark.parametrize('theme_id', ['midnight', 'blossom', 'terminal'])
def test_painted_fill_follows_real_work_in_each_theme(qtbot, theme_id):
    bar = make_progress(qtbot, theme_id)
    base = [sample(bar, x) for x in (.125, .5, .875)]
    bar.setValue(250)
    quarter = [sample(bar, x) for x in (.125, .5, .875)]
    assert quarter[0] != base[0]
    assert quarter[1:] == base[1:]
    assert (bar.minimum(), bar.maximum(), bar.value(), bar.text()) == (0, 1000, 250, '25%')
    bar.setValue(750)
    assert sample(bar, .5) != base[1]
    assert sample(bar, .875) == base[2]
    assert not bar._animation_timer.isActive()


@pytest.mark.parametrize('theme_id', ['midnight', 'blossom', 'terminal'])
def test_indeterminate_texture_moves_without_changing_range_or_value(qtbot, theme_id):
    from moyle_steg.theme import get_theme
    bar = make_progress(qtbot, theme_id, reduced=False)
    bar.setRange(0, 0)
    bar.set_running(True)
    qtbot.waitUntil(bar._animation_timer.isActive)
    original = (bar.minimum(), bar.maximum(), bar.value(), bar.text())
    values = []
    bar.valueChanged.connect(values.append)
    first = bar.grab().toImage()
    qtbot.wait(180)
    assert bar.grab().toImage() != first
    assert (bar.minimum(), bar.maximum(), bar.value(), bar.text()) == original
    assert values == []
    bar.set_appearance(get_theme(theme_id), True)
    assert not bar._animation_timer.isActive()
    still = bar.grab().toImage()
    qtbot.wait(100)
    assert bar.grab().toImage() == still


@pytest.mark.parametrize('theme_id', ['midnight', 'blossom', 'terminal'])
def test_hidden_cancelled_disabled_and_complete_progress_never_loops(qtbot, theme_id):
    bar = make_progress(qtbot, theme_id, reduced=False)
    bar.setValue(400)
    assert not bar._animation_timer.isActive()
    bar.set_running(True)
    qtbot.waitUntil(bar._animation_timer.isActive)
    bar.hide()
    assert not bar._animation_timer.isActive()
    bar.show()
    qtbot.waitUntil(bar._animation_timer.isActive)
    bar.setEnabled(False)
    assert not bar._animation_timer.isActive()
    bar.setEnabled(True)
    qtbot.waitUntil(bar._animation_timer.isActive)
    # Cancellation uses this same integration call, with no progress mutation.
    bar.set_running(False)
    phase = bar._phase
    qtbot.wait(100)
    assert not bar._animation_timer.isActive()
    assert bar._phase == phase and bar.value() == 400
    bar.set_running(True)
    bar.setValue(1000)
    assert not bar._animation_timer.isActive()
    assert len(bar.findChildren(QTimer)) == 1
    bar.close()
    assert not bar._animation_timer.isActive()


def test_theme_switches_keep_geometry_value_and_distinct_static_textures(qtbot):
    from moyle_steg.theme import get_theme
    bar = make_progress(qtbot, 'midnight')
    bar.setValue(700)
    geometry = bar.geometry()
    images = []
    for theme_id in ('midnight', 'blossom', 'terminal'):
        bar.set_appearance(get_theme(theme_id), True)
        assert bar.geometry() == geometry and bar.value() == 700
        image = bar.grab().toImage()
        # A flat rectangle in a different color is not a themed texture.
        colors = {image.pixelColor(x, y).rgba() for y in range(2, image.height() - 2)
                  for x in range(8, int(image.width() * .65))}
        assert len(colors) >= 4, (theme_id, len(colors))
        assert image not in images
        images.append(image)


@pytest.mark.parametrize('reversed_by', ['inverted', 'right_to_left'])
def test_standard_reversed_progress_direction_is_preserved(qtbot, reversed_by):
    bar = make_progress(qtbot, 'blossom')
    if reversed_by == 'inverted':
        bar.setInvertedAppearance(True)
    else:
        bar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    empty_left, empty_right = sample(bar, .125), sample(bar, .875)
    bar.setValue(250)
    assert sample(bar, .125) == empty_left
    assert sample(bar, .875) != empty_right


def test_parent_minimization_and_restore_stop_and_resume_only_active_task(qtbot):
    from PySide6.QtWidgets import QWidget, QVBoxLayout
    from moyle_steg.progress import ThemedProgressBar
    owner = QWidget()
    qtbot.addWidget(owner)
    layout = QVBoxLayout(owner)
    bar = ThemedProgressBar()
    layout.addWidget(bar)
    bar.setRange(0, 100)
    bar.setValue(45)
    bar.set_running(True)
    owner.show()
    qtbot.waitUntil(bar._animation_timer.isActive)
    owner.showMinimized()
    qtbot.waitUntil(lambda: not bar._animation_timer.isActive())
    owner.showNormal()
    qtbot.waitUntil(bar._animation_timer.isActive)
    bar.set_running(False)
    owner.hide()
    owner.show()
    assert not bar._animation_timer.isActive()


def test_vertical_progress_preserves_bottom_to_top_fill(qtbot):
    bar = make_progress(qtbot, 'midnight')
    bar.setOrientation(Qt.Orientation.Vertical)
    bar.resize(16, 200)
    empty = bar.grab().toImage()
    bar.setValue(250)
    filled = bar.grab().toImage()
    x = filled.width() // 2
    assert filled.pixelColor(x, int(filled.height() * .875)) != empty.pixelColor(x, int(empty.height() * .875))
    assert filled.pixelColor(x, int(filled.height() * .125)) == empty.pixelColor(x, int(empty.height() * .125))


def meteor_core(image):
    """Locate the visible star, independently of the painter's coordinates."""
    edge = round(8 * image.devicePixelRatio())
    return [(x, y) for y in range(image.height()) for x in range(edge, image.width() - edge)
            if image.pixelColor(x, y).red() >= 215
            and image.pixelColor(x, y).green() >= 205
            and image.pixelColor(x, y).blue() >= 235]


@pytest.mark.parametrize('value', [250, 750])
def test_midnight_is_one_whole_meteor_at_the_true_progress_front(qtbot, value):
    bar = make_progress(qtbot, 'midnight')
    bar.setValue(value)
    image = bar.grab().toImage()
    points = meteor_core(image)
    assert points
    xs, ys = {x for x, _ in points}, {y for _, y in points}
    groups = 1 + sum(right - left > 2 for left, right in zip(sorted(xs), sorted(xs)[1:]))
    assert groups == 1, 'The progress bar must have one star, not multiple moving particles'
    ratio = image.devicePixelRatio()
    expected = image.width() * value / 1000 - 4.4 * ratio
    assert abs((min(xs) + max(xs)) / 2 - expected) <= 3 * ratio
    assert max(ys) - min(ys) >= 5 * ratio, 'The whole star must be visible at 16 logical pixels'


def test_midnight_completed_region_is_a_tapered_fading_tail_not_a_filled_rectangle(qtbot):
    bar = make_progress(qtbot, 'midnight')
    empty = bar.grab().toImage()
    bar.setValue(750)
    image = bar.grab().toImage()
    completed = image.width() * .75
    columns = [round(completed * fraction) for fraction in (.15, .70)]
    changed = []
    for x in columns:
        changed.append(sum(max(abs(image.pixelColor(x, y).red() - empty.pixelColor(x, y).red()),
                               abs(image.pixelColor(x, y).green() - empty.pixelColor(x, y).green()),
                               abs(image.pixelColor(x, y).blue() - empty.pixelColor(x, y).blue())) > 8
                           for y in range(image.height())))
    assert changed[0] < changed[1] < image.height() - 2, changed


def test_meteor_animation_never_moves_the_star_without_real_progress(qtbot):
    bar = make_progress(qtbot, 'midnight', reduced=False)
    bar.setValue(750)
    bar.set_running(True)
    first = meteor_core(bar.grab().toImage())
    qtbot.wait(180)
    second = meteor_core(bar.grab().toImage())
    first_center = (min(x for x, _ in first) + max(x for x, _ in first)) / 2
    second_center = (min(x for x, _ in second) + max(x for x, _ in second)) / 2
    assert abs(first_center - second_center) <= 1
    assert bar.value() == 750
