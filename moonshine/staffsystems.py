from .opencl import *
from . import hough, bitimage
import numpy as np
import scipy.cluster.hierarchy

# Detect staff systems by finding barlines that cross multiple staves
# The only barlines that remain in staff_filt cross multiple staves,
# and they start and end at the staff centers.
# Start at the first two staff centers and find vertical lines, then try
# to add more staves below until some of the lines don't span that far.
HOUGH_THETAS = np.linspace(-np.pi/500, np.pi/500, 11)
def build_staff_system(page, staff0):
    rhores = page.staff_thick
    # Round y0 down to nearest multiple of 8
    staff0min = min(page.staves[staff0, 2:4])
    y0 = staff0min & -8
    prev_measures = None
    for staff1 in xrange(staff0 + 1, len(page.staves)):
        # Round y1 up to nearest multiple of 8
        staff1max = max(page.staves[staff1, 2:4])
        y1 = -(-staff1max.astype(np.int32) & -8)
        img_slice = page.staff_filt[y0:y1].copy()
        # hough_line assumes almost horizontal lines so we need the transpose
        slice_T = bitimage.transpose(img_slice)
        slice_bins = hough_line_kernel(slice_T, rhores=rhores,
                                       numrho=slice_T.shape[0] // rhores,
                                       thetas=HOUGH_THETAS)
        max_bins = maximum_filter_kernel(slice_bins)
        measure_peaks = hough.houghpeaks(max_bins, npeaks=500,
                                         invalidate=(2,
                                                     page.staff_dist // rhores))
        measure_theta = HOUGH_THETAS[measure_peaks[:, 0]]
        measure_rho = measure_peaks[:, 1]
        lines = hough_lineseg_kernel(slice_T, measure_rho, measure_theta,
                                     rhores=rhores,
                                     max_gap=page.staff_dist).get()
        barlines = lines[(lines[:, 0] < page.staff_dist // rhores)
                         & (lines[:, 1] > slice_T.shape[1] * 8
                                          - page.staff_dist // rhores)]
        if len(barlines):
            barline_ids = scipy.cluster.hierarchy.fclusterdata(
                              np.mean(barlines[:, 2:4], 1)[:, None],
                              page.staff_dist,
                              criterion="distance",
                              method="complete")
            actual_barlines = []
            num_barlines = np.amax(barline_ids)
            for b in xrange(1, num_barlines + 1):
                candidates = barlines[barline_ids == b]
                barline_height = candidates[:, 1] - candidates[:, 0]
                barline = candidates[np.argmax(barline_height)]
                actual_barlines.append(barline[[2, 3, 0, 1]])
            barlines = np.array(actual_barlines)
            barlines = barlines[np.argsort(barlines[:, 0])]
            return (staff0, staff1 + 1, barlines)
        else:
            return (staff0, staff0 + 1, [])
        

def staff_systems(page):
    staff0 = 0
    page.barlines = []
    while staff0 < len(page.staves):
        staff0, staff1, barlines = build_staff_system(page, staff0)
        page.barlines.append((staff0, staff1, barlines))
        staff0 = staff1
    return page.barlines

def show_measure_peaks(page):
    import pylab as p
    for t, r in page.staff_systems:
        # Draw transposed line
        theta = HOUGH_THETAS[t]
        rho = r * page.staff_thick
        p.plot([rho/np.cos(theta), (rho - 4096*np.sin(theta)) / np.cos(theta)],
             [0, 4096], 'y')