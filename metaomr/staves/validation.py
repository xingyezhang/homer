from .base import BaseStaves
from .. import page, staffsize

from pandas import DataFrame

class StaffValidation:
    page = None

    def __init__(self, _page):
        self.page = _page

    def score_staves(self, method=None):
        if method is None:
            method = self.page.staves
        scores = DataFrame(columns=('runs', 'removed'))
        staves = method()
        dist = self.page.staff_dist
        page_runs = staffsize.staff_dist_hist(self.page)
        if len(staves):
            for i in xrange(len(staves)):
                before, after = self.remove_single_staff(i, method)
                if before is None:
                    scores.loc['S%02d' % i] = (0, 0)
                else:
                    runs = staffsize.staff_dist_hist(self.page, before)[dist]
                    runs_after = staffsize.staff_dist_hist(self.page, after)[dist]
                    scores.loc['S%02d' % i] = (runs, runs - runs_after)
            scores.loc['page'] = [page_runs[dist], scores['runs'].sum()]
        else:
            scores.loc['page'] = [page_runs[dist], 0]
        scores['score'] = scores['removed'] / scores['runs']
        return scores

    def remove_single_staff(self, staff_num, method):
        # Staff must have at least staff_dist space above and below
        # to nearest staves
        staves = method()
        staff_min = staves[staff_num,:,1].min() - int(2.5*self.page.staff_dist)
        staff_max = staves[staff_num,:,1].max() + int(2.5*self.page.staff_dist)
        if not ((staves[staff_num-1, :, 1].max()
                     if staff_num > 0 else 0) + 3*self.page.staff_dist
                < staff_min < staff_max
                < (staves[staff_num+1, :, 1].min()
                        if staff_num + 1 < len(staves)
                        else self.page.img.shape[0]) - 3*self.page.staff_dist):
            return None, None
        return (self.page.img[staff_min:staff_max].copy(),
                method.nostaff()[staff_min:staff_max].copy())
