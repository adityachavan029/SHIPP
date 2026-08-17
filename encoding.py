MAX_MINUTIAE = 14
BITS_X      = 9
BITS_Y      = 9
BITS_TYPE   = 1
BITS_ANGLE  = 9
BITS_PER_M  = BITS_X + BITS_Y + BITS_TYPE + BITS_ANGLE

def encode_single_minutia(minutia_dict):
    x     = minutia_dict['x']
    y     = minutia_dict['y']
    tid   = minutia_dict['type_id']
    angle = minutia_dict['angle_deg']

    x_bin     = format(min(x,     (1 << BITS_X)     - 1), f'0{BITS_X}b')
    y_bin     = format(min(y,     (1 << BITS_Y)     - 1), f'0{BITS_Y}b')
    tid_bin   = format(min(tid,   (1 << BITS_TYPE)  - 1), f'0{BITS_TYPE}b')
    angle_bin = format(min(angle, (1 << BITS_ANGLE) - 1), f'0{BITS_ANGLE}b')

    formatted_code = f'{x_bin}-{y_bin}-{tid_bin}-{angle_bin}'
    raw_bit_string = x_bin + y_bin + tid_bin + angle_bin
    bit_count      = len(raw_bit_string)
    return (formatted_code, raw_bit_string, bit_count)

def sort_minutiae_row_major(oriented_minutiae):
    return sorted(oriented_minutiae, key=lambda m: (m['y'], m['x']))

def generate_final_bitstream(sorted_minutiae):
    capped     = sorted_minutiae[:MAX_MINUTIAE]
    table_rows = []
    bitstream_parts = []
    for i, m in enumerate(capped):
        formatted_code, raw_bits, bit_count = encode_single_minutia(m)
        bitstream_parts.append(raw_bits)
        table_rows.append({
            'no': i + 1,
            'x': m['x'], 'y': m['y'],
            'type_num': m['type_id'], 'type_name': m['type_name'],
            'angle_rad': m['angle_rad'], 'angle_deg': m['angle_deg'],
            'binary_code': formatted_code, 'bit_count': bit_count
        })
    final_bitstream = ''.join(bitstream_parts)
    total_bits  = len(final_bitstream)
    count_0s    = final_bitstream.count('0')
    count_1s    = final_bitstream.count('1')
    return {
        'table_rows': table_rows,
        'bitstream': final_bitstream,
        'total_bits': total_bits,
        'count_0s': count_0s,
        'count_1s': count_1s
    }