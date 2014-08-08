from ..opencl import *
import numpy as np
from .. import hough
from ..page import PAGE_SIZE
import pyfft.cl

prg = build_program(['rotate', 'bitimage'])
prg.rotate_image.set_scalar_arg_dtypes([
    None, # input image
    np.float32, # cos(theta)
    np.float32, # sin(theta)
    None, # output image
])
prg.copy_bits_complex64.set_scalar_arg_dtypes([
    None,
    np.int32, np.int32, np.int32,
    None
])

def rotate(page):
    orientation(page)
    new_img = rotate_kernel(page.img, page.orientation)
    page.img = new_img
    return page.orientation

def rotate_kernel(img, theta):
    new_img = cla.zeros_like(img)
    prg.rotate_image(q, (img.shape[1], img.shape[0]),
                               (16, 8),
                               img.data,
                               np.cos(theta).astype(np.float32),
                               np.sin(theta).astype(np.float32),
                               new_img.data).wait()
    return new_img

def patch_orientation_numpy(page, patch_size=512):
    orientations = np.zeros((PAGE_SIZE / patch_size,
                                      PAGE_SIZE / patch_size))
    mask = np.zeros_like(orientations, bool)

    # Windowed FFT
    # We can probably get away with a box filter.
    # The strongest response represents the staves, and should be slightly
    # rotated from vertical. There are also higher frequencies at multiples
    # of the actual staff size. We try to get the peak which is at a
    # frequency 3 times higher than the actual staff size, by zeroing out
    # all but a band around there.
    # For good measure, patch_size should be at least 10*staff_dist.
    # (it actually needs to be >> 6*staff_dist)
    for patch_y in xrange(orientations.shape[0]):
        for patch_x in xrange(orientations.shape[1]):
            patch = page.byteimg[patch_y*patch_size:(patch_y+1)*patch_size,
                                 patch_x*patch_size:(patch_x+1)*patch_size]
            patch_fft = np.abs(np.fft.fft2(patch))
            fft_top = patch_fft[:patch_size/2]
            fft_top[:int(page.staff_dist*2.5)] = 0
            fft_top[int(page.staff_dist*3.5):] = 0
            peak_y, peak_x = np.unravel_index(np.argmax(fft_top),
                                              fft_top.shape)
            if peak_x > patch_size/2:
                peak_x -= patch_size
            if peak_y:
                orientations[patch_y, patch_x] = np.arctan2(peak_x, peak_y)
            else:
                mask[patch_y, patch_x] = True
    return np.ma.masked_array(orientations, mask)

# Cache fft function for each patch_size we use
fft_kernel = dict()
def patch_orientation(page, patch_size=512):
    orientations = np.zeros((PAGE_SIZE / patch_size,
                                      PAGE_SIZE / patch_size))
    mask = np.zeros_like(orientations, bool)

    patch = cla.zeros(q, (patch_size, patch_size), np.complex64)
    if patch_size in fft_kernel:
        our_fft = fft_kernel[patch_size]
    else:
        our_fft = fft_kernel[patch_size] = \
            pyfft.cl.Plan((patch_size,patch_size), queue=q)
    for patch_y in xrange(orientations.shape[0]):
        for patch_x in xrange(orientations.shape[1]):
            prg.copy_bits_complex64(q, patch.shape[::-1], (32, 8),
                page.img.data,
                np.int32(patch_x*patch_size),
                np.int32(patch_y*patch_size),
                np.int32(page.img.shape[1]),
                patch.data).wait()
            our_fft.execute(patch.data, wait_for_finish=True)
            fft_top = np.abs(patch[:patch_size/2].get())
            fft_top[:int(page.staff_dist*2.5)] = 0
            fft_top[int(page.staff_dist*3.5):] = 0
            peak_y, peak_x = np.unravel_index(np.argmax(fft_top),
                                              fft_top.shape)
            if peak_x > patch_size/2:
                peak_x -= patch_size
            if peak_y:
                orientations[patch_y, patch_x] = np.arctan2(peak_x, peak_y)
            else:
                mask[patch_y, patch_x] = True
    return np.ma.masked_array(orientations, mask)

def orientation(page):
    assert type(page.staff_dist) is not tuple, \
           "Multiple staff sizes not supported"
    patch_size = 512
    while page.staff_dist * 10 > patch_size:
        patch_size *= 2
    assert patch_size <= PAGE_SIZE
    patches = patch_orientation(page)
    page.orientation = np.ma.mean(patches)
    return page.orientation
