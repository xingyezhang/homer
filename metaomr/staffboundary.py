from .gpu import *
from . import util
import numpy as np

prg = build_program(["boundary", "scaled_bitmap_to_int_array",
                     "taxicab_distance"])

def boundary_cost_kernel(dist, y0, ystep, y1, x0, xstep, x1):
    numy = int(y1 - y0) // int(ystep)
    numx = int(x1 - x0) // int(xstep)
    costs = thr.empty_like(Type(np.float32, (numx, numy, numy)))
    prg.boundary_cost(dist,
                      np.int32(dist.shape[0]),
                      np.int32(y0),
                      np.int32(ystep),
                      np.int32(numy),
                      np.int32(x0),
                      np.int32(xstep),
                      np.int32(numx),
                      costs,
                      global_size=(numx, numy, numy),
                      local_size=(1, 1, 1))
    return costs

def distance_transform_kernel(img, numiters=64):
    for i in xrange(numiters):
        prg.taxicab_distance_step(img, global_size=img.shape[::-1])

DT_SCALE = 2.0
def distance_transform(page):
    dt = thr.empty_like(Type(np.int32, (2048, 2048)))
    dt.fill(0)
    prg.scaled_bitmap_to_int_array(page.img,
                                   np.float32(DT_SCALE),
                                   np.int32(page.img.shape[1]),
                                   np.int32(page.img.shape[0]),
                                   np.int32(64), np.int32(0),
                                   dt,
                                   global_size=dt.shape[::-1],
                                   local_size=(16, 16))
    distance_transform_kernel(dt, numiters=64)
    page.distance_transform = dt
    return dt

def shortest_path(edge_costs, start_y):
    ptr = np.empty((edge_costs.shape[0], edge_costs.shape[1]), int)
    path_length = np.empty_like(ptr, dtype=float)
    ptr[1, :] = start_y
    path_length[1, :] = edge_costs[1, start_y]
    for i in xrange(2, edge_costs.shape[0]):
        possible_lengths = edge_costs[i] + path_length[i-1, :, None]
        ptr[i] = np.argmin(possible_lengths, axis=0)
        path_length[i] = np.amin(possible_lengths, axis=0)
    rev_path = []
    y = start_y
    for i in xrange(edge_costs.shape[0] - 1, 0, -1):
        rev_path.append((i, y))
        y = ptr[i, y]
    rev_path.append((0, start_y))
    return np.array(list(reversed(rev_path)))

def boundary_cost(page, staff):
    if staff == 0:
        y0 = 0
    else:
        staff_y_above = page.staves()[staff-1, :, 1]
        y0 = max(0, np.amax(staff_y_above) + page.staff_dist*2)
    if staff == len(page.staves()):
        y1 = page.orig_size[0]
    else:
        staff_y_below = page.staves()[staff, :, 1]
        y1 = min(page.orig_size[0], np.amin(staff_y_below) - page.staff_dist*2)

    if y0 >= y1:
        # Use staff medians instead of extrema, should have at least
        # staff_dist*4 amount of space
        if staff > 0:
            y0 = max(0, np.median(staff_y_above).astype(int)
                            + page.staff_dist*2)
        if staff < len(page.staves()):
            y1 = min(page.orig_size[0],
                     np.median(staff_y_below).astype(int) - page.staff_dist*2)
    # Try to find a horizontal line that doesn't touch any dark pixels
    proj = page.img[y0:y1].get().sum(axis=1)
    slices, num_slices = util.label_1d(proj == 0)
    if slices.any():
        slice_size = np.bincount(slices)
        slice_num = np.argmax(slice_size[1:]) + 1
        slice_pixels, = np.where(slices == slice_num)
        slice_y = y0 + int(np.mean(slice_pixels))
        return np.array([[0, slice_y], [page.orig_size[1], slice_y]])
    y0 /= DT_SCALE
    y1 /= DT_SCALE
    xstep = ystep = page.staff_thick
    x0 = 0
    x1 = 2048
    edge_costs = boundary_cost_kernel(page.distance_transform,
                                      int(y0), ystep, int(y1),
                                      int(x0), xstep, int(x1)).get()
    if staff == 0:
        start_y = edge_costs.shape[1] - 1
    elif staff == len(page.staves()):
        start_y = 0
    else:
        start_y = edge_costs.shape[1] // 2
    path = shortest_path(edge_costs, start_y)
    path[:, 0] = DT_SCALE * (x0 + xstep * path[:, 0])
    path[:, 1] = DT_SCALE * (y0 + ystep * path[:, 1])
    if path[-1, 0] < page.orig_size[1]:
        path = np.concatenate((path, [[page.orig_size[1],
                    DT_SCALE * (y0 + ystep * start_y)]]))
    return path

def boundaries(page):
    distance_transform(page)
    boundaries = []
    for i in xrange(len(page.staves()) + 1):
        boundaries.append(boundary_cost(page, i))
    page.boundaries = boundaries
    return boundaries

def show_boundaries(page):
    import pylab as p
    for b in page.boundaries:
        p.plot(*(tuple(b.T) + ('m',)))
