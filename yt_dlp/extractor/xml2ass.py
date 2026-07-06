import contextlib
import json
import math
import random
from xml.etree import ElementTree as ET


class safe_list(list):
    def get(self, index, default=None):
        try:
            return self[index]
        except IndexError:
            return default


class XML2ASSConverter:
    def __init__(self, width=1920, height=1080, bottom_reserved=0,
                 font_name='Noto Sans CJK SC', font_size=30.0, alpha=0.8,
                 duration_marquee=15.0, duration_still=5.0):
        self.width = width
        self.height = height
        self.bottom_reserved = bottom_reserved
        self.font_name = font_name
        self.font_size = font_size
        self.alpha = alpha
        self.duration_marquee = duration_marquee
        self.duration_still = duration_still
        self.styleid = f'Danmaku2ASS_{random.randint(0, 0xffff):04x}'
        self.rows = [[None] * (height - bottom_reserved + 1) for _ in range(4)]

    def ass_escape(self, s):
        def replace_leading_space(t):
            stripped = t.strip(' ')
            if len(t) == len(stripped):
                return t
            left = len(t) - len(t.lstrip(' '))
            right = len(t) - len(t.rstrip(' '))
            return '\u2007' * left + stripped + '\u2007' * right
        return '\\N'.join(
            replace_leading_space(part) or ' '
            for part in str(s).replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')
            .split('\n')
        )

    def convert_timestamp(self, seconds):
        timestamp = round(seconds * 100.0)
        hour, minute = divmod(timestamp, 360000)
        minute, second = divmod(minute, 6000)
        second, centsecond = divmod(second, 100)
        return f'{int(hour)}:{int(minute):02}:{int(second):02}.{int(centsecond):02}'

    def convert_color(self, rgb):
        if rgb == 0x000000:
            return '000000'
        if rgb == 0xffffff:
            return 'FFFFFF'
        r = (rgb >> 16) & 0xff
        g = (rgb >> 8) & 0xff
        b = rgb & 0xff
        if self.width < 1280 and self.height < 576:
            return f'{b:02X}{g:02X}{r:02X}'
        ClipByte = lambda x: 255 if x > 255 else 0 if x < 0 else round(x)  # noqa: E731
        return (f'{ClipByte(r * 0.00956384088080656 + g * 0.03217254540203729 + b * 0.95826361371715607):02X}'
                f'{ClipByte(r * -0.10493933142075390 + g * 1.17231478191855154 + b * -0.06737545049779757):02X}'
                f'{ClipByte(r * 0.91348912373987645 + g * 0.07858536372532510 + b * 0.00792551253479842):02X}')

    def calculate_length(self, s):
        return max(len(line) for line in s.split('\n'))

    def get_zoom_factor(self, source_size):
        try:
            if (source_size, (self.width, self.height)) == getattr(self.get_zoom_factor, 'Cached_Size', None):
                return self.get_zoom_factor.Cached_Result
        except AttributeError:
            pass
        self.get_zoom_factor.Cached_Size = (source_size, (self.width, self.height))
        source_aspect = source_size[0] / source_size[1]
        target_aspect = self.width / self.height
        if target_aspect < source_aspect:
            scale_factor = self.width / source_size[0]
            self.get_zoom_factor.Cached_Result = (scale_factor, 0, (self.height - self.width / source_aspect) / 2)
        elif target_aspect > source_aspect:
            scale_factor = self.height / source_size[1]
            self.get_zoom_factor.Cached_Result = (scale_factor, (self.width - self.height * source_aspect) / 2, 0)
        else:
            self.get_zoom_factor.Cached_Result = (self.width / source_size[0], 0, 0)
        return self.get_zoom_factor.Cached_Result

    def get_position(self, input_pos, is_height, zoom_factor):
        is_height = int(is_height)
        if isinstance(input_pos, (int, float)):
            if isinstance(input_pos, float) and input_pos <= 1:
                return (672, 438)[is_height] * zoom_factor[0] * input_pos + zoom_factor[is_height + 1]
            return zoom_factor[0] * input_pos + zoom_factor[is_height + 1]
        try:
            input_pos = float(input_pos)
            return self.get_position(input_pos, is_height, zoom_factor)
        except ValueError:
            return 0

    def convert_flash_rotation(self, rot_y, rot_z, x, y):
        def WrapAngle(deg):
            return 180 - ((180 - deg) % 360)
        rot_y, rot_z = WrapAngle(rot_y), WrapAngle(rot_z)
        if rot_y in (90, -90):
            rot_y -= 1
        rot_y, rot_z = math.radians(rot_y), math.radians(rot_z)
        if rot_y == 0 or rot_z == 0:
            out_x, out_y, out_z = 0, -math.degrees(rot_y), -math.degrees(rot_z)
        else:
            out_y = math.degrees(math.atan2(-math.sin(rot_y) * math.cos(rot_z), math.cos(rot_y)))
            out_z = math.degrees(math.atan2(-math.cos(rot_y) * math.sin(rot_z), math.cos(rot_z)))
            out_x = math.degrees(math.asin(math.sin(rot_y) * math.sin(rot_z)))
        tr_x = (x * math.cos(rot_z) + y * math.sin(rot_z)) / math.cos(rot_y) + (1 - math.cos(rot_z) / math.cos(rot_y)) * self.width / 2 - math.sin(rot_z) / math.cos(rot_y) * self.height / 2
        tr_y = y * math.cos(rot_z) - x * math.sin(rot_z) + math.sin(rot_z) * self.width / 2 + (1 - math.cos(rot_z)) * self.height / 2
        tr_z = (tr_x - self.width / 2) * math.sin(rot_y)
        fov = self.width * math.tan(2 * math.pi / 9.0) / 2
        try:
            scale_xy = fov / (fov + tr_z)
        except ZeroDivisionError:
            scale_xy = 1
        tr_x = (tr_x - self.width / 2) * scale_xy + self.width / 2
        tr_y = (tr_y - self.height / 2) * scale_xy + self.height / 2
        if scale_xy < 0:
            scale_xy = -scale_xy
            out_x += 180
            out_y += 180
        return (tr_x, tr_y, WrapAngle(out_x), WrapAngle(out_y), WrapAngle(out_z), scale_xy * 100, scale_xy * 100)

    def write_ass_head(self):
        return (
            f'[Script Info]\n'
            f'Script Updated By: Danmaku2ASS (https://github.com/m13253/danmaku2ass)\n'
            f'ScriptType: v4.00+\n'
            f'PlayResX: {self.width}\n'
            f'PlayResY: {self.height}\n'
            f'Aspect Ratio: {self.width}:{self.height}\n'
            f'Collisions: Normal\n'
            f'WrapStyle: 2\n'
            f'ScaledBorderAndShadow: yes\n'
            f'YCbCr Matrix: TV.601\n'
            f'[V4+ Styles]\n'
            f'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
            f'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
            f'Alignment, MarginL, MarginR, MarginV, Encoding\n'
            f'Style: {self.styleid},{self.font_name},{self.font_size:.0f},&H{255 - round(self.alpha * 255):02X}FFFFFF,'
            f'&H{255 - round(self.alpha * 255):02X}FFFFFF,&H{255 - round(self.alpha * 255):02X}000000,'
            f'&H{255 - round(self.alpha * 255):02X}000000,1,0,0,0,100,100,0.00,0.00,1,'
            f'{max(self.font_size / 25.0, 1):.0f},0,7,0,0,0,0\n'
            f'[Events]\n'
            f'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        )

    def write_comment(self, c, row):
        text = self.ass_escape(c[3])
        styles = []
        if c[4] == 1:
            styles.append(f'\\an8\\pos({self.width / 2:.0f}, {row:.0f})')
            duration = self.duration_still
        elif c[4] == 2:
            styles.append(f'\\an2\\pos({self.width / 2:.0f}, {self.convert_type2(row):.0f})')
            duration = self.duration_still
        elif c[4] == 3:
            styles.append(f'\\move({-math.ceil(c[8]):.0f}, {row:.0f}, {self.width:.0f}, {row:.0f})')
            duration = self.duration_marquee
        else:
            styles.append(f'\\move({self.width:.0f}, {row:.0f}, {-math.ceil(c[8]):.0f}, {row:.0f})')
            duration = self.duration_marquee
        if not (-1 < c[6] - self.font_size < 1):
            styles.append(f'\\fs{c[6]:.0f}')
        if c[5] != 0xffffff:
            styles.append(f'\\c&H{self.convert_color(c[5])}&')
            if c[5] == 0x000000:
                styles.append('\\3c&HFFFFFF&')
        return (f'Dialogue: 2,{self.convert_timestamp(c[0])},{self.convert_timestamp(c[0] + duration)},'
                f'{self.styleid},,0000,0000,0000,,{{{"".join(styles)}}}{text}\n')

    def write_bilibili_positioned(self, c):
        bili_player_size = (672, 438)
        zoom_factor = self.get_zoom_factor(bili_player_size)
        try:
            comment_args = safe_list(json.loads(c[3]))
            text = self.ass_escape(str(comment_args[4]).replace('/n', '\n'))
            from_x = self.get_position(comment_args.get(0, 0), False, zoom_factor)
            from_y = self.get_position(comment_args.get(1, 0), True, zoom_factor)
            to_x = self.get_position(comment_args.get(7, from_x), False, zoom_factor)
            to_y = self.get_position(comment_args.get(8, from_y), True, zoom_factor)
            alpha = safe_list(str(comment_args.get(2, '1')).split('-'))
            from_alpha = 255 - round(float(alpha.get(0, 1)) * 255)
            to_alpha = 255 - round(float(alpha.get(1, from_alpha)) * 255)
            rotate_z = int(comment_args.get(5, 0))
            rotate_y = int(comment_args.get(6, 0))
            lifetime = float(comment_args.get(3, 4500))
            duration = int(comment_args.get(9, lifetime * 1000))
            delay = int(comment_args.get(10, 0))
            fontface = comment_args.get(12)
            isborder = comment_args.get(11, 'true')
            from_rotarg = self.convert_flash_rotation(rotate_y, rotate_z, from_x, from_y)
            to_rotarg = self.convert_flash_rotation(rotate_y, rotate_z, to_x, to_y)
            styles = [f'\\org({self.width / 2:.0f}, {self.height / 2:.0f})']
            if from_rotarg[0:2] == to_rotarg[0:2]:
                styles.append(f'\\pos({from_rotarg[0]:.0f}, {from_rotarg[1]:.0f})')
            else:
                styles.append(f'\\move({from_rotarg[0]:.0f}, {from_rotarg[1]:.0f}, {to_rotarg[0]:.0f}, {to_rotarg[1]:.0f}, {delay:.0f}, {delay + duration:.0f})')
            styles.append(f'\\frx{from_rotarg[2]:.0f}\\fry{from_rotarg[3]:.0f}\\frz{from_rotarg[4]:.0f}\\fscx{to_rotarg[5]:.0f}\\fscy{to_rotarg[6]:.0f}')
            if (from_x, from_y) != (to_x, to_y):
                styles.append(f'\\t({delay}, {delay + duration},')
                styles.append(f'\\frx{to_rotarg[2]:.0f}\\fry{to_rotarg[3]:.0f}\\frz{to_rotarg[4]:.0f}\\fscx{to_rotarg[5]:.0f}\\fscy{to_rotarg[6]:.0f}')
            if fontface:
                styles.append(f'\\fn{self.ass_escape(fontface)}')
            styles.append(f'\\fs{c[6] * zoom_factor[0]:.0f}')
            if c[5] != 0xffffff:
                styles.append(f'\\c&H{self.convert_color(c[5])}&')
                if c[5] == 0x000000:
                    styles.append('\\3c&HFFFFFF&')
            if from_alpha == to_alpha:
                styles.append(f'\\alpha&H{from_alpha:02X}')
            elif (from_alpha, to_alpha) == (255, 0):
                styles.append(f'\\fad({lifetime * 1000:.0f},0)')
            elif (from_alpha, to_alpha) == (0, 255):
                styles.append(f'\\fad(0, {lifetime * 1000:.0f})')
            else:
                styles.append(f'\\fade({from_alpha}, {to_alpha}, {to_alpha}, 0, {lifetime * 1000:.0f}, {lifetime * 1000:.0f}, {lifetime * 1000:.0f})')
            if isborder == 'false':
                styles.append('\\bord0')
            return (f'Dialogue: -1,{self.convert_timestamp(c[0])},{self.convert_timestamp(c[0] + lifetime)},'
                    f'{self.styleid},,0,0,0,,{{{"".join(styles)}}}{text}\n')
        except (IndexError, ValueError):
            return ''

    def test_free_rows(self, c, row):
        res = 0
        rowmax = self.height - self.bottom_reserved
        target_row = None
        if c[4] in (1, 2):
            while row < rowmax and res < c[7]:
                if target_row != self.rows[c[4]][row]:
                    target_row = self.rows[c[4]][row]
                    if target_row and target_row[0] + self.duration_still > c[0]:
                        break
                row += 1
                res += 1
        else:
            try:
                threshold_time = c[0] - self.duration_marquee * (1 - self.width / (c[8] + self.width))
            except ZeroDivisionError:
                threshold_time = c[0] - self.duration_marquee
            while row < rowmax and res < c[7]:
                if target_row != self.rows[c[4]][row]:
                    target_row = self.rows[c[4]][row]
                    try:
                        if target_row and (target_row[0] > threshold_time or target_row[0] + target_row[8] * self.duration_marquee / (target_row[8] + self.width) > c[0]):
                            break
                    except ZeroDivisionError:
                        pass
                row += 1
                res += 1
        return res

    def find_alternative_row(self, c):
        res = 0
        for row in range(self.height - self.bottom_reserved - math.ceil(c[7])):
            if not self.rows[c[4]][row]:
                return row
            if self.rows[c[4]][row][0] < self.rows[c[4]][res][0]:
                res = row
        return res

    def mark_comment_row(self, c, row):
        for i in range(row, row + math.ceil(c[7])):
            with contextlib.suppress(IndexError):
                self.rows[c[4]][i] = c

    def convert_type2(self, row):
        return self.height - self.bottom_reserved - row

    def read_comments(self, xml_data):
        comment_types = {'1', '4', '5', '6', '7', '8'}
        try:
            root = ET.fromstring(xml_data)
        except ET.ParseError:
            return []
        comments = []
        for i, comment in enumerate(root.findall('d')):
            try:
                p = comment.attrib['p'].split(',')
                if len(p) < 5 or p[1] not in comment_types or not comment.text:
                    continue
                if p[1] in {'1', '4', '5', '6'}:
                    c = comment.text.replace('/n', '\n')
                    size = float(p[2]) * self.font_size / 25.0
                    comments.append((
                        float(p[0]),
                        int(p[4]),
                        i,
                        c,
                        {'1': 0, '4': 2, '5': 1, '6': 3}[p[1]],
                        int(p[3]),
                        size,
                        (c.count('\n') + 1) * size,
                        self.calculate_length(c) * size,
                    ))
                elif p[1] == '7':
                    comments.append((
                        float(p[0]),
                        int(p[4]),
                        i,
                        comment.text,
                        'bilipos',
                        int(p[3]),
                        int(p[2]),
                        0,
                        0,
                    ))
            except (KeyError, ValueError, IndexError):
                continue
        comments.sort(key=lambda ele: ele[0])
        return comments

    def convert(self, xml_data, user_font_size=None, user_alpha=None,
                user_position=None, user_color=None):
        actual_font_size = user_font_size or self.font_size
        actual_alpha = user_alpha or self.alpha
        self.font_size = actual_font_size
        self.alpha = actual_alpha
        self.rows = [[None] * (self.height - self.bottom_reserved + 1) for _ in range(4)]

        comments = self.read_comments(xml_data)
        if not comments:
            return None

        ass_content = self.write_ass_head()
        for c in comments:
            if isinstance(c[4], int):
                if user_position == 'top':
                    c = (c[0], c[1], c[2], c[3], 1, c[5], c[6], c[7], c[8])
                elif user_position == 'bottom':
                    c = (c[0], c[1], c[2], c[3], 2, c[5], c[6], c[7], c[8])
                elif user_position == 'scroll':
                    c = (c[0], c[1], c[2], c[3], 0, c[5], c[6], c[7], c[8])
                if user_color:
                    c = (c[0], c[1], c[2], c[3], c[4], user_color, c[6], c[7], c[8])
                rowmax = self.height - self.bottom_reserved - c[7]
                for row in range(int(rowmax)):
                    freerows = self.test_free_rows(c, row)
                    if freerows >= c[7]:
                        self.mark_comment_row(c, row)
                        ass_content += self.write_comment(c, row)
                        break
                else:
                    row = self.find_alternative_row(c)
                    self.mark_comment_row(c, row)
                    ass_content += self.write_comment(c, row)
            elif c[4] == 'bilipos':
                if user_color:
                    c = (c[0], c[1], c[2], c[3], c[4], user_color, c[6], c[7], c[8])
                ass_line = self.write_bilibili_positioned(c)
                if ass_line:
                    ass_content += ass_line

        return ass_content
