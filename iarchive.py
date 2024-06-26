#!/usr/bin/python

import sys
import getopt
import re
import gzip
import os
import zipfile
import json
from urllib2 import urlopen, HTTPError
from httplib import HTTPConnection
from subprocess import Popen, PIPE

try:
    from lxml import etree
except ImportError:
    sys.path.append('/petabox/sw/lib/lxml/lib/python2.5/site-packages')
    from lxml import etree
from lxml import objectify

from debug import debug, debugging, assert_d

class Book(object):
    def __init__(self, book_id, doc, book_path, toc=None):
        self.book_id = book_id
        self.doc = doc
        if len(self.doc) == 0:
            self.doc = self.book_id
        self.book_path = book_path
        self.toc = toc
        if not os.path.exists(book_path):
            raise Exception('Can\'t find book path "' + book_path + '"')
        self.scandata = None
        self.metadata = None
        self.olib = False
        self.imgstack_archive_fmt = None
        self.imgstack_image_fmt = None
        self.imgstack_name = None
        imgstack_types = (('jp2', 'zip'),
                          ('tif', 'zip'),
                          ('jp2', 'tar'),
                          ('jpg', 'zip'),
                          ('jpg', 'tar'))
        for imgstack_t in imgstack_types:
            imgstack_path = os.path.join(book_path, '%s_%s.%s' %
                                         (self.doc,
                                          imgstack_t[0], imgstack_t[1]))
            if os.path.exists(imgstack_path):
                self.imgstack_image_fmt = imgstack_t[0]
                self.imgstack_archive_fmt = imgstack_t[1]
                self.imgstack_name = imgstack_path
                break

#         if self.imgstack_archive_fmt is None:
#             raise Exception('Can\'t find book images')


    def get_book_id(self):
        return self.book_id

    def get_book_path(self):
        return self.book_path

    def get_doc(self):
        return self.doc

    def analyze(self):
        import abbyy
        return abbyy.analyze(self.get_abbyy(), self)

    def report(self):
        bookdata = self.get_bookdata()
        result = ''
        for name in 'leafCount', 'dpi':
            result += (name + ': '
                       + str(bookdata.find(self.get_scandata_ns() + name))
                       + '\n')
        return result

    def get_scandata_path(self):
        paths = [
            os.path.join(self.book_path, self.doc + '_scandata.xml'),
            os.path.join(self.book_path, 'scandata.xml'),
            os.path.join(self.book_path, 'scandata.zip'),
            ]
        for sd_path in paths:
            if os.path.exists(sd_path):
                return sd_path
        raise Exception('No scandata found')

    def get_scandata(self):
        if self.scandata is None:
            scandata_path = self.get_scandata_path()
            (base, ext) = os.path.splitext(scandata_path)
            if ext.lower() == '.zip':
                z = zipfile.ZipFile(scandata_path, 'r')
                scandata_str = z.read('scandata.xml')
                z.close()
                self.scandata = objectify.fromstring(scandata_str)
                self.scandata_pages = self.scandata.pageData.page
            else:
                self.scandata = objectify.parse(self.get_scandata_path()).getroot()
                self.scandata_pages = self.scandata.xpath('/book/pageData/page')
            self.leaves = {}
            for page in self.scandata_pages:
                self.leaves[int(page.get('leafNum'))] = page
        return self.scandata

    def get_scandata_pages(self):
        self.get_scandata()
        return self.scandata_pages

    def get_page_scandata(self, i):
        self.get_scandata()
        if i >= len(self.scandata_pages):
            return None
        return self.scandata_pages[int(i)]
#     scandata_pages = scandata.xpath('/book/pageData/page')
#     if scandata_pages is None or len(scandata_pages) == 0:
#         scandata_pages = scandata.pageData.page

    def has_pagenos(self):
        self.get_scandata()
        max_page = len(self.scandata_pages)
        i = 0
        result = False
        while i < max_page:
            page_scandata = self.get_page_scandata(i)
            pageno = page_scandata.find(self.get_scandata_ns() + 'pageNumber');
            if pageno:
                result = True
                break
            i += 1
        return result

    def get_page_data_from_leafno(self, leaf):
        if leaf in self.leaves:
            return self.leaves[leaf]
        else:
            return None

    def get_bookdata(self):
        scandata = self.get_scandata()
        bookdata = scandata.find(self.get_scandata_ns() + 'bookData')
        if bookdata is None:
            raise 'why here?'
            bookdata = scandata.bookData
        return bookdata

    def get_olib(self):
        if (self.olib is False):
            try:
                f=urlopen('http://www.openlibrary.org/ia/%s'%self.book_id)
                self.olib=json.load(f)
            except:
                self.olib=None
            return self.olib
        else:
            return self.olib

    def get_scandata_ns(self):
        scandata = self.get_scandata()
        bookData = scandata.find('bookData')
        if bookData is None:
            return '{http://archivestream.github.io/scribe/xml}'
        else:
            return ''

    def get_leafno_for_page(self, i):
        return int(self.get_page_scandata(i).get('leafNum'))

    def get_metadata(self):
        if (self.metadata):
            return self.metadata
        # metadata is by book_id, not by doc
        md_path = os.path.join(self.book_path, self.book_id + '_meta.xml')
        md = objectify.parse(md_path).getroot()
        result = []
        for el in md.iterchildren():
            if el.tag == 'language':
                result_text = iso_639_23_to_iso_639_1(el.text)
            else:
                result_text = el.text
            result.append({ 'tag':el.tag, 'text':result_text })
        self.metadata=result
        return result

    def get_toc(self):
        if self.toc is not None:
            return self.toc
        toc_path = os.path.join(self.book_path, self.doc + '_toc.xml')
        if not os.path.exists(toc_path):
            return None
        toc = objectify.parse(toc_path).getroot()
        result = {}
        for el in toc.iterchildren():
            result[el.get('page')] = el.get('title')
        return result

    def get_abbyy(self):
        abbyy_gz = os.path.join(self.book_path, self.doc + '_abbyy.gz')
        if os.path.exists(abbyy_gz):
            return gzip.open(abbyy_gz, 'rb')
        abbyy_zip = os.path.join(self.book_path, self.doc + '_abbyy.zip')
        if os.path.exists(abbyy_zip):
            return os.popen('unzip -p ' + abbyy_zip + ' ' + self.doc + '_abbyy.xml')
#             z = zipfile.ZipFile(abbyy_zip, 'r')
#             return z.open(self.doc + '_abbyy.xml') # only in 2.6
        abbyy_xml = os.path.join(self.book_path, self.doc + '_abbyy.xml')
        if os.path.exists(abbyy_xml):
            return open(abbyy_xml, 'r')
        raise 'No abbyy file found'

    def get_djvu_xml(self):
        djvu_xml = os.path.join(self.book_path, self.doc + '_djvu.xml')
        if os.path.exists(djvu_xml):
            return open(djvu_xml, 'r')
        raise 'No djvu.xml file found'


    def get_html(self):
        html_path = os.path.join(self.book_path, self.doc + '_abbyy.html')
        if os.path.exists(html_path):
            return open(html_path, 'r')
        raise 'No abbyy.html file found'

    def get_pdfxml_xml(self):
        pdfxml_xml = os.path.join(self.book_path, self.doc + '_pdfxml.xml')
        if os.path.exists(pdfxml_xml):
            return open(pdfxml_xml, 'r')
        raise 'No pdfxml.xml file found'

    # get python string with image data - from .jp2 image or tif in zip
    # finds appropriate leaf number for supplied page index
    def get_page_image(self, i, requested_size, # (w, h)
                       orig_page_size=None,
                       quality=60,
                       region=None, # ((l,t)(r,b))
                       out_img_type='jpg',
                       kdu_reduce=2):

        if False:
            # Use mang's book page image crop API instead of doing it ourselves
            if region is not None:
                (l, t), (r, b) = region

            # w, h = requested_size
            # print 'getting image:'
            # print 'i %s  leafno %s  req_size (%s, %s)' % (i, leafno, w, h)
            # if region is not None:
            #     print 'region (l%s,t%s),(r%s,b%s)' % (l, t, r, b)
            # print

            if region is not None:
                f = urlopen('http://www-testflip.archivestream.github.io/download/%s/page/'
                            'n%s_x%s_y%s_w%s_h%s_s%s.jpg' % (self.book_id, i,
                                                             l, t, r-l, b-t,
                                                             kdu_reduce))
            else:
                f = urlopen('http://www-testflip.archivestream.github.io/download/%s/page/'
                            'n%s_s%s.jpg' % (self.book_id, i, kdu_reduce))
                # Also possibly needed: resize output to requested_size
                # (or ask mang for same)
                # he suggests: specify _w and _h (but not _x, _y) to
                # get a scaled image that's a bit bigger than that
                # size.  Works just for whole pages.
            return f.read()

        leafno = self.get_leafno_for_page(i)
        doc_basename = os.path.basename(self.doc)

        zipf = self.imgstack_name
        image_path = '%s_%s/%s_%s.%s' % (doc_basename, self.imgstack_image_fmt,
                                         doc_basename, str(leafno).zfill(4),
                                         self.imgstack_image_fmt)
        in_img_type = self.imgstack_image_fmt

        try:
            if self.imgstack_archive_fmt == 'zip':
                z = zipfile.ZipFile(zipf, 'r')
                info = z.getinfo(image_path) # for to check it exists
                z.close()
            # XXX extend above to work with tar?  or push into image_from_zip?
        except KeyError:
            return None

        return image_from_zip(zipf, image_path,
                              requested_size, orig_page_size,
                              quality, region,
                              in_img_type, out_img_type,
                              kdu_reduce)


def get_kdu_region_string(img_size, region):
    if region is not None and img_size is None:
        raise 'need orig image size to support region request'
    if region is None or img_size is None:
        return '{0.0,0.0},{1.0,1.0}'
    w, h = img_size
    w = float(w)
    h = float(h)
    (l, t), (r, b) = region
    result = ('{' + str(t/h) + ',' + str(l/w) + '},' +
              '{' + str((b-t)/h) + ',' + str((r-l)/w) + '}')
    return result

if not os.path.exists('/tmp/stdout.ppm'):
    os.symlink('/dev/stdout', '/tmp/stdout.ppm')
if not os.path.exists('/tmp/stdout.bmp'):
    os.symlink('/dev/stdout', '/tmp/stdout.bmp')

# get python string with image data - from .jp2 image in zip
def image_from_zip(zipf, image_path,
                   requested_size, orig_page_size,
                   quality, region,
                   in_img_type, out_img_type,
                   kdu_reduce):
    if not os.path.exists(zipf):
        raise Exception('Zipfile missing')

    width, height = requested_size
    scale = ' | pnmscale -quiet -xysize ' + str(width) + ' ' + str(height)
#     scale = ' | pamscale -quiet -xyfit ' + str(width) + ' ' + str(height)
    if out_img_type == 'jpg':
        cvt_to_out = ' | pnmtojpeg -quiet -quality ' + str(quality)
    elif out_img_type == 'ppm':
        cvt_to_out = ' | ppmtoppm -quiet'
    else:
        raise Exception('unrecognized out img type')

    if zipf.endswith('.tar'):
        unzip_cmd = '7z e -so ' + zipf + ' ' + image_path + ' 2>/dev/null'
    else:
        unzip_cmd = 'unzip -p ' + zipf + ' ' + image_path

    clean_me_up = None
    try:
        result = None
        if in_img_type == 'jp2':
            kdu_region = get_kdu_region_string(orig_page_size, region)
            kdu_cmd_fmt = ('kdu_expand -region "' + kdu_region + '"'
                        + ' -reduce %s'
                        + ' -no_seek -i /dev/stdin -o /tmp/stdout.bmp')
            # try with aggressive kdu_reduce; hide stderr
            p = Popen(['-c',
                       unzip_cmd + ' | ' + (kdu_cmd_fmt % kdu_reduce) +
                       ' | bmptopnm -quiet ' + scale + cvt_to_out],
                      stdout=PIPE, stderr=PIPE, shell=True)
            result = p.stdout.read()
            # retry if above failed, with no kdu_reduce, passing stderr.
            if p.returncode != 0:
                p = Popen(['-c',
                           unzip_cmd + ' | ' + (kdu_cmd_fmt % 0) +
                           ' | bmptopnm -quiet ' + scale + cvt_to_out],
                          stdout=PIPE, shell=True)
                result = p.stdout.read()
        elif in_img_type == 'tif' or in_img_type == 'jpg':
            crop = ''
            if region is not None:
                (l, t), (r, b) = region
                crop = (' | pamcut -pad -left=%s -top=%s -right=%s -bottom=%s '
                        % (l, t, r, b))

            import tempfile
            tmp_suffix = '.%s' % in_img_type
            _, t_path = tempfile.mkstemp(prefix='img_for_expub_',
                                         suffix=tmp_suffix)
            clean_me_up = t_path
            output = os.popen(unzip_cmd
                            + ' > ' + t_path)
            output.read()
            to_pnm = { 'tif': 'tifftopnm',
                       'jpg': 'jpegtopnm' }
            output = os.popen(to_pnm[in_img_type] + ' -quiet ' + t_path
                            + crop
                            + scale
                            + cvt_to_out)
            result = output.read()
        else:
            raise Exception('unrecognized input img type')

        return result
    finally:
        if clean_me_up is not None:
            os.unlink(clean_me_up)

# ' | pnmscale -quiet -xysize ' + str(width) + ' ' + str(height)

# Adapted from http://en.wikipedia.org/wiki/List_of_ISO_639-1_codes
def iso_639_23_to_iso_639_1(marc_code):
    import lang_mappings
    marc_code = marc_code.lower()
    for mapping in lang_mappings.mapping:
        if marc_code in mapping:
            return mapping[marc_code]
    return marc_code

def infer_book_id():
    files=os.listdir(".")
    #ignore files starting with '.' using list comprehension
    files=[filename for filename in files if filename[0] != '.']
    for fname in files:
        if re.match('.*_abbyy.gz$', fname):
            return re.sub('_abbyy.gz$', '', fname)
        if re.match('.*_abbyy.zip$', fname):
            return re.sub('_abbyy.zip$', '', fname)
        if re.match('.*_abbyy.xml$', fname):
            return re.sub('_abbyy.xml$', '', fname)
    raise "couldn't get book id"
    return None


if __name__ == '__main__':
    sys.stderr.write('I\'m a module.  Don\'t run me directly!\n')
    sys.exit(-1)
