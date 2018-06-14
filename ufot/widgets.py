import pyqtgraph as pg
import pyqtgraph.opengl as gl
import logging
import numpy as np
from PyQt5 import QtGui, QtCore
import dxchange as dx
import ufot.util as util
import tifffile

LOG = logging.getLogger(__name__)


def remove_extrema(data):
    upper = np.percentile(data, 99)
    lower = np.percentile(data, 1)
    data[data > upper] = upper
    data[data < lower] = lower
    return data

def create_volume(data):
    gradient = (data - np.roll(data, 1))**2
    cmin = gradient.min()
    div = gradient.max() - cmin
    gradient = (gradient - cmin) / div * 255

    volume = np.empty(data.shape + (4, ), dtype=np.ubyte)
    volume[..., 0] = data
    volume[..., 1] = data
    volume[..., 2] = data
    volume[..., 3] = gradient
    return volume

def read_tiff(filename):
    tiff = tifffile.TiffFile(filename)
    array = tiff.asarray()
    return array.T

class ProjectionViewer(QtGui.QWidget):
    """
    Present a sequence of files that can be browsed with a slider.

    To get the currently selected position connect to the *slider* attribute's
    valueChanged signal.
    """

    def __init__(self, parent=None):
        super(ProjectionViewer, self).__init__(parent)
        image_view = pg.ImageView()
        image_view.getView().setAspectLocked(True)
        self.image_item = image_view.getImageItem()

        self.slider = QtGui.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self.update_image)

        self.main_layout = QtGui.QVBoxLayout(self)
        self.main_layout.addWidget(image_view)
        self.main_layout.addWidget(self.slider)
        self.setLayout(self.main_layout)
        self.filenames = None
        self.ffc_correction = False

    def load_files(self, filenames, ffc_correction):
        """Load *filenames* for display."""
        self.filenames = filenames
        self.ffc_correction = ffc_correction

        proj, flat, dark, theta = dx.read_aps_32id(filenames, proj=(0, 1))

        #self.slider.setRange(0, len(theta) - 1)
        self.slider.setRange(0, util.get_dx_dims(str(filenames), 'data')[0] - 1)
        self.slider.setSliderPosition(0)
        self.update_image()

    def update_image(self):
        """Update the currently display image."""
        if self.filenames:
            pos = self.slider.value()
            proj, flat, dark, theta = dx.read_aps_32id(self.filenames, proj=(pos, pos+1))
            if self.ffc_correction:
                image = proj[0,:,:].astype(np.float)/flat[0,:,:].astype(np.float)
            else:
                image = proj[0,:,:].astype(np.float)
            self.image_item.setImage(image)

class SliceViewer(QtGui.QWidget):
    """
    Present a sequence of files that can be browsed with a slider.

    To get the currently selected position connect to the *slider* attribute's
    valueChanged signal.
    """

    def __init__(self, filenames, parent=None):
        super(SliceViewer, self).__init__(parent)
        image_view = pg.ImageView()
        image_view.getView().setAspectLocked(True)
        self.image_item = image_view.getImageItem()

        self.slider = QtGui.QSlider(QtCore.Qt.Horizontal)
        self.slider.valueChanged.connect(self.update_image)

        self.main_layout = QtGui.QVBoxLayout(self)
        self.main_layout.addWidget(image_view)
        self.main_layout.addWidget(self.slider)
        self.setLayout(self.main_layout)
        self.load_files(filenames)

    def load_files(self, filenames):
        """Load *filenames* for display."""
        self.filenames = filenames
        self.slider.setRange(0, len(self.filenames) - 1)
        self.slider.setSliderPosition(0)
        self.update_image()

    def update_image(self):
        """Update the currently display image."""
        if self.filenames:
            pos = self.slider.value()
            image = read_tiff(self.filenames[pos])
            self.image_item.setImage(image)


class OverlapViewer(QtGui.QWidget):
    """
    Presents two images by subtracting the flipped second from the first.

    To get the current deviation connect to the *slider* attribute's
    valueChanged signal.
    """
    def __init__(self, parent=None):
        super(OverlapViewer, self).__init__()
        image_view = pg.ImageView()
        image_view.getView().setAspectLocked(True)
        self.image_item = image_view.getImageItem()

        self.slider = QtGui.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self.update_image)

        self.main_layout = QtGui.QVBoxLayout()
        self.main_layout.addWidget(image_view)
        self.main_layout.addWidget(self.slider)
        self.setLayout(self.main_layout)
        self.first, self.second = (None, None)

    def set_images(self, first, second):
        """Set *first* and *second* image."""
        self.first = remove_extrema(first.T)
        self.second = remove_extrema(np.flipud(second.T))

        if self.first.shape != self.second.shape:
            LOG.warn("Shape {} of {} is different to {} of {}".
                     format(self.first.shape, self.first, self.second.shape, self.second))

        self.slider.setRange(0, self.first.shape[0])
        self.slider.setSliderPosition(self.first.shape[0] / 2)
        self.update_image()

    def set_position(self, position):
        self.slider.setValue(int(position))
        self.update_image()

    def update_image(self):
        """Update the current subtraction."""
        if self.first is None or self.second is None:
            LOG.warn("No images set yet")
        else:
            pos = self.slider.value()
            moved = np.roll(self.second, self.second.shape[0] / 2 - pos, axis=0)
            self.image_item.setImage(moved - self.first)


class VolumeViewer(QtGui.QWidget):

    def __init__(self, step=1, density=1, parent=None):
        super(VolumeViewer, self).__init__(parent)
        self.volume_view = gl.GLViewWidget()
        self.main_layout = QtGui.QVBoxLayout()
        self.main_layout.addWidget(self.volume_view)
        self.setLayout(self.main_layout)
        self.step = step
        self.density = density

    def load_data(self, filenames):
        """Load *filenames* for display."""
        filenames = filenames[::self.step]
        num = len(filenames)
        first = read_tiff(filenames[0])[::self.step, ::self.step]
        width, height = first.shape
        data = np.empty((width, height, num), dtype=np.float32)
        data[:,:,0] = first

        for i, filename in enumerate(filenames[1:]):
            data[:, :, i + 1] = read_tiff(filename)[::self.step, ::self.step]

        volume = create_volume(data)
        dx, dy, dz, _ = volume.shape

        volume_item = gl.GLVolumeItem(volume, sliceDensity=self.density)
        volume_item.translate(-dx / 2, -dy / 2, -dz / 2)
        volume_item.scale(0.05, 0.05, 0.05, local=False)
        self.volume_view.addItem(volume_item)
