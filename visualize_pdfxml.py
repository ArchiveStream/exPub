#!/usr/bin/python

import sys
import getopt
import re
import os
import math

try:
    from lxml import etree
except ImportError:
    sys.path.append('/petabox/sw/lib/lxml/lib/python2.5/site-packages') 
    from lxml import etree
from lxml import objectify

import iarchive
import common

outdir='pdfxml_viz'

kdu_reduce = 2 # 0 to 4 or so - is powers of 2
scale = 2 ** kdu_reduce
top_page = 20
top_page = None
draw_text = False
#draw_text = True

infile = 'romance_pdftoxml_under_out.xml'

from debug import debug, debugging, assert_d

def usage():
    print 'usage: visualize_pdfxml.py'
    print ''
#     print 'legend:'
#     print '    ta - align'
#     print '    li - leftIndent'
#     print '    ri - rightIndent'
#     print '    si - startIndent'
#     print '    ls - lineSpacing'
#     print
    print 'Colors:'
    for sty_name in styles:
        print '    ' + styles[sty_name]['col'] + '  -  ' + sty_name

def main(argv):
    if len(argv) > 0 and argv[0] == '-h':
        usage()
        sys.exit(0)
    
    if not os.path.isdir('./' + outdir+ '/'):
        os.mkdir('./' + outdir + '/')

    id = iarchive.infer_book_id()
    iabook = iarchive.Book(id, '', '.')
    visualize(iabook)

import Image
import ImageDraw
import ImageFont 
import color
from color import color as c
def visualize(iabook):
    scandata = iabook.get_scandata()
    context = etree.iterparse(iabook.get_pdfxml_xml(), tag='PAGE')
    info = scan_pages(context, scandata, iabook)

def draw_rect(draw, el, sty, use_coords=None):
    col = color.color[sty['col']]
    if sty['width'] == 0:
        return
    
    lt, rb = use_coords if use_coords is not None else tag_coords(el, scale)

    x1, y1 = lt
    x2, y2 = rb

    enclosing = None
    if use_coords is None:
        enclosing = enclosing_tag(el)
    if enclosing is not None and enclosing.get('y') is not None:
        elt, erb = tag_coords(enclosing, scale)
        ex1, ey1 = elt
        ex2, ey2 = erb

        margin = sty['margin']

        near = 3

        x1 = x1 + margin if x1 - ex1 < near else x1
        x2 = x2 - margin if ex2 - x2 < near else x2
        y1 = y1 + margin if y1 - ey1 < near else y1
        y2 = y2 - margin if ey2 - y2 < near else y2

#     x1 += sty['offset']
#     y1 += sty['offset']
#     x2 += sty['offset']
#     y2 += sty['offset']
    draw.line([(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)],
              width=sty['width'], fill=col)


    
def tag_coords(tag, s):
    def iget(att):
        return int(math.floor(float(tag.get(att))))
    l = iget('x')/s
#     try:
#         l = iget('x')/s
#     except TypeError:
#         debug()
#         print common.p_el(tag)
    t = iget('y')/s
    r = l + iget('width')/s
    b = t + iget('height')/s
    return ((l, t), (r, b))

def four_coords(tag, s):
    def iget(att):
        return int(math.floor(float(tag.get(att))))
    l = iget('x')/s
    t = iget('y')/s
    r = l + iget('width')/s
    b = t + iget('height')/s
    return l, t, r, b

def enclosing_tag(tag):
    tag_with_coords = tag
    while tag_with_coords is not None:
        tag_with_coords = tag.getparent()
        if tag_with_coords is not None and tag.get('y') is not None:
            break
    return tag_with_coords

styles = {
    'block_text' : { 'col':'yellow', 'width':1, 'offset':0, 'margin':10 },
    'block_picture' : { 'col':'red', 'width':1, 'offset':7, 'margin':10 },
    'block_table' : { 'col':'purple', 'width':1, 'offset':7, 'margin':10 },
    'rect' : { 'col':'orange', 'width':0, 'offset':-4, 'margin':10 },
    'par' : { 'col':'green', 'width':2, 'offset':0, 'margin':10 },
    'line' : { 'col':'cyan', 'width':1, 'offset':0, 'margin':5 },
    'token' : { 'col':'blue', 'width':1, 'offset':0, 'margin':2 },
    }

def nons(tag):
    return re.sub('{.*}', '', tag)

def render(draw, el, expected, use_coords=None):
#    assert_tag(el, expected)
    sty = styles[expected]
    draw_rect(draw, el, sty, use_coords)

def assert_tag(el, expected):
    shorttag = nons(el.tag)
    if (shorttag != 'block'):
        assert_d(shorttag == expected)

def box_from_par(par):
    if len(par) > 0:
        (o_l, o_t), (o_r, o_b) = tag_coords(par[0], scale)
        for line in par:
            (l, t), (r, b) = tag_coords(line, scale)
            o_l = l if (l - o_l < 0) else o_l
            o_t = t if (t - o_t < 0) else o_t
            o_r = r if (o_r - r < 0) else o_r
            o_b = b if (o_b - b < 0) else o_b
        return (o_l, o_t), (o_r, o_b)
    else:
        return None

import os

import StringIO
import font
def scan_pages(context, scandata, iabook):
    book_id = iabook.get_book_id()
    scandata_pages = scandata.pageData.page
    scandata_ns = iabook.get_scandata_ns()
    try:
        # dpi isn't always there
        dpi = int(scandata.bookData.dpi.text)
    except AttributeError:
        dpi = 300
    i = 0
    f = ImageFont.load_default()
#    f = ImageFont.load('/Users/mccabe/s/archive/expub/Times-18.bdf')
    for event, page in context:
        orig_width = int(math.floor(float(page.get('width'))))
        orig_height = int(math.floor(float(page.get('height'))))
        orig_size = (orig_width, orig_height)
        requested_size = (orig_width / scale, orig_height / scale)
        
        image = Image.new('RGB', requested_size)
        image_str = iabook.get_page_image(i, requested_size,
                                          out_img_type='ppm',
                                          kdu_reduce=kdu_reduce)
        page_image = None
        if image_str is not None:
            page_image = Image.open(StringIO.StringIO(image_str))
            if requested_size != page_image.size:
                page_image = page_image.resize(requested_size)
            try:
                image = Image.blend(image, page_image, .2)
            except ValueError:
                print 'blending - images didn\'t match'
                debug()
                pass
                
        draw = ImageDraw.Draw(image)
        for el in page:
            if el.tag == 'IMAGE' and page_image is not None:
                width = int(el.get('width'))
                height = int(el.get('height'))
                if (width < orig_width - 3) or (height < orig_height - 3):
                    cropped = page_image.crop(four_coords(el, scale))
                    image.paste(cropped, four_coords(el, scale))
                
        for el in page:
            if el.tag == 'IMAGE':
                render(draw, el, 'block_picture')
            if el.tag == 'BLOCK':
                par_coords = box_from_par(el)
                if par_coords is not None:
                    render(draw, el, 'par', par_coords)

            for text in el:
                render(draw, text, 'line')
                for token in text:
                    render(draw, token, 'token')
                    font_name = token.get('font-name')
                    font_size = token.get('font-size')
                    font_size = int(re.sub('\..*', '', font_size))
                    font_ital = token.get('italic') == 'yes'
                    font_bold = token.get('bold') == 'yes'

                    f = font.get_font(font_name, dpi / scale, font_size / scale, font_ital)
                    draw.text((int(math.floor(float(token.get('x'))))/scale,
                               int(math.floor(float(token.get('base'))))/scale),
                              token.text.encode('utf-8'),
                              font=f,
                              fill=color.yellow)

        if not include_page(scandata_pages[i]):
            draw.line([(0, 0), image.size], width=50, fill=color.red)

        page_scandata = iabook.get_page_scandata(i)
        if page_scandata is not None:
            t = page_scandata.pageType.text

#             pageno_string = page_scandata.pageNumber.text
            pageno = page_scandata.find(scandata_ns + 'pageNumber')
            if pageno:
                pageno_string = pageno.text    
                t += ' ' + pageno_string

            handside = page_scandata.find(scandata_ns + 'handSide')
            if handside:
                t += ' ' + handside.text

            f = font.get_font("Courier", dpi / scale, 12)
            page_w, page_h = image.size
            draw.text((.02 * dpi,
                       .02 * dpi),
                      t.encode('utf-8'),
                      font=f,
                      fill=color.green)

        image.save(outdir + '/img' + scandata_pages[i].get('leafNum') + '.png')
        print 'page index: ' + str(i)
        page.clear()
        i += 1
        if top_page is not None:
            if i > top_page:
                sys.exit(0)
    return None

def include_page(page):
    if page is None:
        return False
    add = page.find('addToAccessFormats')
    if add is None:
        add = page.addToAccessFormats
    if add is not None and add.text == 'true':
        return True
    else:
        return False



if __name__ == '__main__':
    main(sys.argv[1:])
