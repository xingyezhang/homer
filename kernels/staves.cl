// Search x in [x_byte*8, (x_byte+1)*8) and y in
// [y0-staff_search, y0+staff_search] for a staff center estimate.
// The refined y value has the most single-pixel columns matching the filter.
// Returns refined y value, or -1 if no y value in the range matches the filter.
inline int refine_staff_center_y(int staff_thick, int staff_dist,
                                 int staff_search,
                                 int min_unobscured_count,
                                 GLOBAL_MEM const UCHAR *img,
                                 int w, int h,
                                 int x_byte, int y0) {
    if (! (0 <= y0 - staff_dist*3 && y0 + staff_dist*3 < h))
        return -1;
    // Search y in [ymin, ymax]
    int ymin = y0 - staff_search;
    int ymax = y0 + staff_search;

    // Staff criteria: must have dark pixels at y and +- staff_dist * [1,2]; and
    // at least min_unobscured_lines of these points must have light pixels at
    // both y_line +- staff_thick (evidence for isolated staff line).
    // Pick y where the most columns in this byte match the criteria
    int best_y = -1;
    int num_agree = 0;
    for (int y = ymin; y <= ymax; y++) {
        UCHAR is_dark[5];
        UCHAR is_line[5];
        int y_center_est_sum = 0;
        int num_estimates = 0;
        for (int line = 0; line <= 4; line++) {
            is_dark[line] = 0;
            int y_line = y + staff_dist * (line - 2);
            int line_min = h;
            int line_max = 0;
            int dy = staff_thick;
            for (int y_ = y_line-dy; y_ <= y_line+dy; y_++) {
                UCHAR byte = img[x_byte + w * y_];
                if (byte) {
                    is_dark[line] |= byte;
                    line_min = MIN(line_min, y_);
                    line_max = MAX(line_max, y_);
                }
            }
            // Update y_line using known dark run
            if (line_min > y_line-dy || line_max < y_line+dy) {
                y_line = line_min + (line_max + 1 - line_min)/2;

                y_center_est_sum += y_line + staff_dist * (2 - line);
                num_estimates++;
            }

            is_line[line] = ~img[x_byte + w * (y_line - staff_thick*2)];
            is_line[line] &= ~img[x_byte + w * (y_line + staff_thick*2)];
        }
        int y_center_est = num_estimates
                         ? y_center_est_sum / num_estimates
                         : -1;

        int8 unobscured_count = 0;
        for (int line = 0; line <= 4; line++)
            unobscured_count += (is_line[line] >> (int8)(7,6,5,4,3,2,1,0))& 0x1;
        UCHAR found_lines = 0;
        found_lines |= (unobscured_count[0]>=min_unobscured_count)?(0x80>>0):0;
        found_lines |= (unobscured_count[1]>=min_unobscured_count)?(0x80>>1):0;
        found_lines |= (unobscured_count[2]>=min_unobscured_count)?(0x80>>2):0;
        found_lines |= (unobscured_count[3]>=min_unobscured_count)?(0x80>>3):0;
        found_lines |= (unobscured_count[4]>=min_unobscured_count)?(0x80>>4):0;
        found_lines |= (unobscured_count[5]>=min_unobscured_count)?(0x80>>5):0;
        found_lines |= (unobscured_count[6]>=min_unobscured_count)?(0x80>>6):0;
        found_lines |= (unobscured_count[7]>=min_unobscured_count)?(0x80>>7):0;
        UCHAR is_staff = is_dark[0] & is_dark[1] & is_dark[2] & is_dark[3]
                                    & is_dark[4] & found_lines;
        int agreement = 0;
        for (UCHAR mask = 0x80; mask; mask >>= 1)
            if (is_staff & mask)
                agreement++;
        if (agreement > num_agree
            || (agreement == num_agree
                  && ABS(y - y_center_est) < ABS(best_y - y_center_est))) {
            best_y = y;
            num_agree = agreement;
        }
    }
    return (num_agree > 1) ? best_y : -1;
}

#define X (0)
#define Y (1)
KERNEL void staff_center_filter(GLOBAL_MEM const UCHAR *img,
                                int staff_thick, int staff_dist,
                                int min_unobscured_lines,
                                GLOBAL_MEM UCHAR *staff_center) {
    // Ensure a given pixel has dark pixels above and below where we would
    // expect if it were the center of a staff, then update the center pixel.
    int x = get_global_id(X);
    int y = get_global_id(Y);
    int w = get_global_size(X);
    int h = get_global_size(Y);
    
    UCHAR staff_byte = img[x + y * w];

    if (refine_staff_center_y(staff_thick, staff_dist, 0,
                              min_unobscured_lines,
                              img, w, h, x, y) == y)
        staff_center[x + y * w] = staff_byte;
    else
        staff_center[x + y * w] = 0;
}

KERNEL void staff_removal(GLOBAL_MEM const int2 *staves,
                          int staff_thick, GLOBAL_MEM const int *staff_dists,
                          GLOBAL_MEM UCHAR *img,
                          int w, int h,
                          GLOBAL_MEM int2 *refined_staves,
                          int refined_num_points) {
    int num_points = get_global_size(0);
    int num_staves = get_global_size(1);
    int segment_num = get_global_id(0);
    int staff_num = get_global_id(1);
    int staff_dist = staff_dists[staff_num];

    int remove_staff = 1;
    if (refined_num_points < 0) {
        remove_staff = 0;
        refined_num_points = -refined_num_points;
    }

    if (segment_num == 0) {
        // Mask refined_staves
        for (int i = 0; i < refined_num_points; i++) {
            refined_staves[i + refined_num_points*staff_num] = make_int2(-1,-1);
        }
    }
    barrier(CLK_GLOBAL_MEM_FENCE);

    if (segment_num + 1 == num_points)
        return;
    int2 p0 = staves[segment_num     + num_points * staff_num];
    int2 p1 = staves[segment_num + 1 + num_points * staff_num];
    if (p0.x < 0 || p1.x < 0)
        return;

    // Fudge x-values to nearest byte
    for (int byte_x = p0.x / 8; byte_x <= p1.x / 8 && byte_x < w; byte_x++) {
        int y = p0.y + (p1.y - p0.y) * (byte_x*8 - p0.x) / (p1.x - p0.x);
        int y_refined = refine_staff_center_y(staff_thick, staff_dist,
                                              staff_thick, 2,
                                              img, w, h, byte_x, y);

        int lines[5] = {y_refined - staff_dist*2,
                        y_refined - staff_dist,
                        y_refined,
                        y_refined + staff_dist,
                        y_refined + staff_dist*2};
        if (! (0 <= lines[0] - 2*staff_thick && lines[4] + 2*staff_thick < h))
            continue;

        if (byte_x < refined_num_points)
            refined_staves[byte_x + refined_num_points * staff_num] =
                make_int2(byte_x * 8, y_refined);

        if (remove_staff) {
            for (int i = 0; i < 5; i++) {
                // Test for empty space above and below
                UCHAR mask = img[byte_x + w * (lines[i] - staff_thick)]
                           | img[byte_x + w * (lines[i] + staff_thick)];
                for (int dy = 1 - staff_thick; dy < staff_thick; dy++)
                    img[byte_x + w * (lines[i] + dy)] &= mask;
            }
        }
    }
}

// Extract just an area centered on the current staff,
// adjusting for a rotated staff line
KERNEL void extract_staff(GLOBAL_MEM const int2 *staff,
                          int num_segments,
                          int staff_dist,
                          GLOBAL_MEM const UCHAR *img,
                          int w, int h,
                          GLOBAL_MEM UCHAR *output) {
    int output_byte_x = get_global_id(0);
    int output_y = get_global_id(1);
    int output_byte_w = get_global_size(0);
    int output_h = get_global_size(1);

    int image_byte_x = output_byte_x;

    // Find last staff point before this byte by binary search
    int lo = 0, hi = num_segments, mid;
    while (lo < hi) {
        mid = (lo + hi) / 2;
        int mid_x = staff[mid].x;
        if (mid_x == image_byte_x * 8)
            break;
        else if (mid_x < image_byte_x * 8)
            lo = mid + 1;
        else
            hi = mid;
    }
    int p0 = mid;
    int x0 = staff[p0].x;
    int y0 = staff[p0].y;

    // As an approximation, use previous point y0 as our y value
    // Extract output_h pixels, centered on y0
    int img_y = y0 + output_y - output_h/2;
    if (0 <= img_y && img_y < h && 0 <= image_byte_x && image_byte_x < w)
        output[output_byte_x + output_byte_w * output_y] =
            img[image_byte_x + w * img_y];
}
