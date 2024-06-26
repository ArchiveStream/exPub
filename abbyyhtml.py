# -*- Mode: Python; Character-encoding: utf-8; -*-
from lxml.etree import iterparse, tostring
from urllib2 import urlopen, HTTPError
from urlparse import urlparse
from xml.dom.minidom import parse
from os.path import dirname
from math import sqrt
from gzip import GzipFile
from zipfile import ZipFile
import re
import string
import StringIO
import json

ns = '{http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml}'
page_tag = ns + 'page'
block_tag = ns + 'block'
region_tag = ns + 'region'
text_tag = ns + 'text'
rect_tag = ns + 'rect'
par_tag = ns + 'par'
line_tag = ns + 'line'
formatting_tag = ns + 'formatting'
charParams_tag = ns + 'charParams'

re_page_num = re.compile(r'^\[?\d+\]?$')
events=('start','end')

edgethresh=0.1

global_classmap={}

def padnum(n,pad):
    padded=str(n)
    while (strlen(padding)<pad):
        padded="0"+padded
    return padded

# An abbyy file consists of pages containing blocks
# Non-text blocks (mostly figures or tables) are just dumped
#  with coordinate-information.
# Text blocks consist of paragraphs consisting of lines 
#  consisting of formatting ranges consisting of characters.
# The code in this file doesn't do any cross-page merging.  That is handled
#  by abbyy2html based on reading from the getblocks stream implemented in
#  this file.
# The getblocks function reads from the abbyy file's XML event
#  stream and generates its own stream of HTML blocks, corresponding
#  to either markers (leafstart, blockstart, etc) or logical paragraphs
#  containing embedded markup with line or word information.
# We try to avoid wrapping content itself in markup so that markup can be
#  stripped out by a simple regex.
# The algorithm walks the XML and keeps track of the current logical paragraph
#  (which may cross or break abbyy paragraph elements) in the variable _text_.
# It also explicitly identifies lines which are probably headers or footers
#  and makes them into spans with abbyyheader and abbyyfooter classes.
# In adding to the running _text_, it wraps hypens in 'abbyydroppedhyphen'
#  spans.


def getblocks(f,book_id="BOOK",classmap=global_classmap,
              inline_blocks=True,wrap_words=True,
              scaninfo=False,imguri=False):
    # Count a bunch of things in order to generate identifying names, ids,
    # and informative titles
    leaf_count=-1
    block_count=0
    para_count=0
    leaf_para_count=0
    line_count=0
    leaf_line_count=0
    page_height=-1
    page_width=-1
    page_top=True
    skip_page=False
    for event,node in iterparse(f,events):
        if ((node.tag == page_tag) and (event=='end')):
            # We process a page at a time and clear the pages
            #  information when we're done with it
            node.clear()
            skip_page=False
            continue
        elif ((node.tag == page_tag) and (event=='start')):
            # We output a simple marker when pages start
            pageinfo=node.attrib
            page_height=int(pageinfo["height"])
            page_width=int(pageinfo["width"])
            leaf_count=leaf_count+1
            leaf_para_count=0
            leaf_line_count=0
            page_top=True
            if scaninfo:
                info=scaninfo[leaf_count]
            else:
                info={}
            if 'pageno' in info:
                pagenum=info['pageno']
            else:
                pagenum=False
            if 'ignore' in info:
                leafclass='abbyyleafstart abbyyignored'
                skip_page=True
            else:
                leafclass='abbyypagestart'
            #print "leaf=%d, page=%s"%(leaf_count,pagenum)
            if pagenum:
                yield ("<a class='%s' name='abbyyleaf%d' id='abbyyleaf%d' data-abbyy='n%d[%dx%d]'>#n%d</a>"%
                       (leafclass,leaf_count,leaf_count,
                        leaf_count,page_width,page_height,leaf_count))
                yield ("<a class='abbyypagestart' name='abbyypage%s' id='abbyypage%s'>#p%s</a>"%
                       (pagenum,pagenum,pagenum))
            else:
                yield ("<a class='%s' name='abbyyleaf%d' id='abbyyleaf%d' data-abbyy='n%d[%dx%d]'>#n%d</a>"%
                       (leafclass,leaf_count,leaf_count,
                        leaf_count,page_width,page_height,leaf_count))
            continue
        elif ((node.tag == block_tag) and (event=='start')):
            blockinfo=node.attrib
            l=int(blockinfo['l'])
            t=int(blockinfo['t'])
            r=int(blockinfo['r'])
            b=int(blockinfo['b'])
            block_count=block_count+1
            # 'inline blocks' has block starts encoded as self-contained
            #  anchor tags; otherwise blocks are implemented as DIVs which
            #  contain paragraphs.  This gets in the way of some logical
            #  paragraph recognition, so we avoid it by default
            if inline_blocks:
                yield ("<a class='%s' id='abbyyblock%d' data-abbyy='n%d/%dx%d+%d,%d'>#n%db%d</a>"%
                       ((getclassname("abbyyblock",blockinfo,page_width,page_height,page_top)),
                        block_count,leaf_count,r-l,b-t,l,t,leaf_count,block_count))
            else:
                yield ("<div class='%s' id='abbyyblock%d' data-abbyy='n%d/%dx%d+%d,%d'>"%
                       ((getclassname("abbyyblock",blockinfo,page_width,page_height,page_top)),
                        block_count,leaf_count,r-l,b-t,l,t))
            blocktype=blockinfo['blockType']
            if (blocktype=='Text'): continue
            elif (blocktype=='Picture'):
                # We should generate a valid URL of some sort here
                if imguri:
                    imgsrc=imguri%(leaf_count,l,t,r-l,b-t)
                else:
                    imgsrc=""
                yield ("<img title='%s/%d[%d,%d,%d,%d]' src='%s'/>"%
                       (book_id,leaf_count,l,t,r,b,imgsrc))
                continue
            else: continue
        elif ((node.tag == block_tag) and (event=='end')):
            page_top=False
            if inline_blocks:
                continue
            else:
                yield "</div>"
            continue
        elif ((node.tag == par_tag) and (event=='end')):
            # This is where most of the work happens
            text=''
            para_l=0
            para_t=0
            para_r=page_width
            para_b=page_height
            parfmt=node.attrib
            leaf_para_count=leaf_para_count+1
            para_count=para_count+1
            curfmt=False
            curclass=False
            line_no=0
            stats=ParaStats(node,page_width,page_height,page_top)
            # Ignore if there aren't any lines
            if (stats.n==0): continue
            max_r=stats.max_r
            min_l=stats.min_l
            mean_lmargin=stats.mean_lmargin
            mean_rmargin=stats.mean_rmargin
            dev_lmargin=stats.dev_lmargin
            dev_rmargin=stats.dev_rmargin
            # Walk the lines in the paragraph, gluing them together and
            # wrapping hyphens in abbyydroppedhyphen spans
            for line in node:
                # This is the line count for the book
                line_count=line_count+1
                # This is the line count for the leaf
                leaf_line_count=leaf_line_count+1
                # This is the line count for the paragraph
                line_no=line_no+1
                hyphenated=False
                lineinfo=line.attrib
                l=int(lineinfo['l'])
                t=int(lineinfo['t'])
                r=int(lineinfo['r'])
                b=int(lineinfo['b'])
                if (l<para_l): para_l=l
                if (r>para_r): para_r=r
                if (t<para_t): para_t=t
                if (b>para_b): para_b=b
                first_char = line[0][0]
                # Determine if the current paragraph being built ends
                # with a hyphen;
                if (text.endswith('-')):
                    if (first_char.attrib.get('wordStart') == 'false' or
                        first_char.attrib.get('wordFromDictionary') == 'false'):
                        text=text[:-1]+"<span class='abbyydroppedhyphen'>-</span>"
                        hyphenated=True
                width=r-l
                lmargin=l-min_l
                rmargin=max_r-r
                # If the left margin is indented from the mean, start a new paragraph
                if ((line_no>0) and (abs(lmargin-mean_lmargin)>dev_lmargin)):
                    if (curfmt):
                        text=text+"</span>"
                        curfmt=False
                        curclass=False
                    paratext=getpara(text,parfmt,book_id,
                                     leaf_count,para_count,leaf_para_count,
                                     l,t,r,b,page_width,page_height,page_top)
                    text=''
                    if (paratext): yield paratext
                if (line_no>0) and (not hyphenated) and (text != ''):
                    # if it's not hyphenated, add one space
                    text=text+' '
                # This is the classname for the line entry
                #  getclassname adds information based on page position
                #  it is where headers and footers get recognized
                lineclass=getclassname("abbyyline",lineinfo,page_width,page_height,page_top)
                # If a line is a header or footer, wrap the content within
                #  an anchor.  Otherwise, just insert the line break information
                # print "lineclass='%s', lcount=%d"%(lineclass,line_count)
                anchor=("<br class='abbyybreak'/><a class='%s' id='%s_n%di%d' data-abbyy='l%d/n%d/i%d/%dx%d+%d,%d' data-baseline='%d'><span class='lineinfo'>#n%di%d</span>"%
                        (lineclass,book_id,leaf_count,leaf_line_count,
                         line_count,leaf_count,leaf_line_count,
                         r-l,b-t,l,t,
                         int(lineinfo['baseline']),leaf_count,leaf_line_count,))
                closeanchor=""
                if ((lineclass.find("abbyypagehead")>=0) or
                    (lineclass.find("abbyypagefoot")>=0)):
                    # If there's a current format, close it off so that
                    #  we don't have it's span broken by the anchor element
                    #  (which would be malformed markup)
                    if curfmt:
                        text=text+"</span>"+anchor+"<span class='"+curclass+"'>"
                        closeanchor="</span></a>"
                    else:
                        text=text+anchor
                        closeanchor="</a>"
                else:
                    text=text+anchor+"</a>"
                    closeanchor=""
                # Turn the formatting elements into spans, adding an
                #  open/close pair whent it changes.
                for formatting in line:
                    fmt=formatting.attrib
                    classname=getcssname(fmt,curclass,classmap)
                    if (classname):
                        curfmt=fmt
                        if (curclass): text=text+"</span>"
                        curclass=classname
                        text=text+("<span class='%s'>"%classname)
                    wordclass='abbyyword'
                    # This is where we get the line text and where we
                    # would put word level position information
                    if wrap_words:
                        word=False
                        l=False
                        t=False
                        r=False
                        b=False
                        confidence=100
                        for c in formatting:
                            cinfo=c.attrib
                            isspace=c.text.isspace()
                            wordend=isspace or cinfo['wordStart']=='true'
                            if word and wordend:
                                if (word.endswith("-")):
                                    text=text+("<span class='%s' data-abbyy='n%d/i%d/%dx%d+%d,%d'>%s</span>-"%
                                               (wordclass,leaf_count,leaf_line_count,(r-l),(b-t),l,t,word[:-1]))+c.text
                                else:
                                    text=text+("<span class='%s' data-abbyy='n%d/i%d/%dx%d+%d,%d'>%s</span>"%
                                               (wordclass,leaf_count,leaf_line_count,(r-l),(b-t),l,t,word))+c.text
                                    word=False
                                    wordclass="abbyyword"
                            if isspace:
                                text=text+c.text
                            elif word:
                                word=word+c.text
                                cl=int(cinfo["t"])
                                ct=int(cinfo["t"])
                                cr=int(cinfo["r"])
                                cb=int(cinfo["b"])
                                if (ct<t): t=ct
                                if (cb>b): b=cb
                                # I'm not sure when these would ever happen, but
                                #  let's check them anyway
                                if (cl<l): l=cl
                                if (cr>r): r=cr
                            else:
                                word=c.text
                                l=int(cinfo["l"])
                                t=int(cinfo["t"])
                                r=int(cinfo["r"])
                                b=int(cinfo["b"])
                            if  cinfo['wordStart']=='true':
                                wordend=True
                                wordclass='abbyyword'
                                if cinfo['wordNumeric']=='true':
                                    wordclass=wordclass+' abbyynumber'
                                if cinfo['wordNormal']=='false':
                                    wordclass=wordclass+' abbyynormal'
                                if cinfo['wordFromDictionary']=='false':
                                    wordclass=wordclass+' abbyyunknown'
                        if not word:
                            ignore='yes'
                        elif (word.endswith("-")):
                            text=text+("<span class='%s' data-abbyy='n%d/i%d/%dx%d+%d,%d[%d%%]'>%s</span>-"%
                                       (wordclass,leaf_count,leaf_line_count,(r-l),(b-t),l,t,confidence,word[:-1]))
                        else:
                            text=text+("<span class='%s' data-abbyy='n%d/i%d/%dx%d+%d,%d[%d%%]'>%s</span>"%
                                       (wordclass,leaf_count,leaf_line_count,(r-l),(b-t),l,t,confidence,word))
                        word=False
                    else: text=text+''.join(c.text for c in formatting)
                text=text+closeanchor
                if (abs(rmargin-mean_rmargin)>dev_rmargin):
                    # If the current line comes up short, close off the paragraph
                    # Close out any active formatting
                    if (curfmt):
                        text=text+"</span>"
                        curfmt=False
                        curclass=False
                    paratext=getpara(text,parfmt,book_id,
                                     leaf_count,para_count,leaf_para_count,
                                     l,t,r,b,page_width,page_height,page_top)
                    text=''
                    if paratext: yield paratext

            # Close out any active formatting
            if (curfmt):
                text=text+"</span>"
                curfmt=False
                curclass=False
           
            # At this point, we've accumulated all of the lines into _text_
            #   and create the paragraph element.
            paratext=getpara(text,parfmt,book_id,
                             leaf_count,para_count,leaf_para_count,
                             l,t,r,b,page_width,page_height,page_top)
            # print u"text=%s"%text
            # print u"para="+unicode(paratext)
            text=''
            if paratext:
                yield paratext
            else:
                continue

class ParaStats:
    def __init__(self,node,page_width,page_height,page_top):
        # Compute lots of stats about left and right extents
        # We use these to identify paragraph breaks which abbyy missed
        n=0
        max_r=False
        min_l=False
        sum_r=0
        sum_l=0
        sum_width=0
        for line in node:
            lineinfo=line.attrib
            l=int(lineinfo['l'])
            r=int(lineinfo['r'])
            if not max_r or (r>max_r): max_r=r
            if not min_l or (l<min_l): min_l=l
            sum_r=sum_r+r
            sum_l=sum_l+l
            sum_width=sum_width+(r-l)
            n=n+1;
        # If there aren't any lines, just continue
        if (n==0):
            self.n=0
            return None
        mean_r=sum_r/n
        mean_l=sum_l/n
        mean_width=sum_width/n
        par_width=max_r-min_l
        sum_r2=0
        sum_l2=0
        sum_width2=0
        sum_rmargin=0
        sum_lmargin=0
        for line in node:
            lineinfo=line.attrib
            l=int(lineinfo['l'])
            r=int(lineinfo['r'])
            width=r-l
            rmargin=max_r-r
            lmargin=l-min_l
            sum_r2=sum_r2+((r-mean_r)*(r-mean_r))
            sum_l2=sum_l2+((l-mean_l)*(l-mean_l))
            sum_width2=sum_width2+((width-mean_width)*(width-mean_width))
            sum_lmargin=sum_lmargin+lmargin
            sum_rmargin=sum_rmargin+rmargin
        dev_r=sqrt(sum_r2/n)
        dev_l=sqrt(sum_r2/n)
        dev_width=sqrt(sum_width2/n)
        mean_lmargin=sum_lmargin/n
        mean_rmargin=sum_rmargin/n
        sum_rmargin2=0
        sum_lmargin2=0
        for line in node:
            lineinfo=line.attrib
            l=int(lineinfo['l'])
            r=int(lineinfo['r'])
            rmargin=max_r-r
            lmargin=l-min_l
            sum_lmargin2=sum_lmargin2+(lmargin*lmargin)
            sum_rmargin2=sum_rmargin2+(rmargin*rmargin)
        self.n=n
        self.min_l=min_l
        self.max_r=max_r
        self.mean_l=mean_l
        self.mean_r=mean_r
        self.dev_l=dev_l
        self.dev_r=dev_r
        self.mean_width=mean_width
        self.dev_width=dev_width
        self.mean_lmargin=mean_lmargin
        self.mean_rmargin=mean_rmargin
        self.dev_lmargin=sqrt(sum_lmargin2/n)
        self.dev_rmargin=sqrt(sum_rmargin2/n)
        return None
        
def getpara(text,fmt,book_id,leaf_count,para_count,leaf_para_count,l,t,r,b,page_width,page_height,page_top):
    # At this point, we have a text block to render as a paragraph.  If it's a
    #   header or footer, we render it as a span (because cross-page
    #   merging may wrap it in a single paragraph and you can't have
    #   nested paragraphs).  Otherwise, it's just an HTML paragraph.
    if not "align" in fmt:
        classname="abbyypara"
    elif (fmt["align"]=="Center"):
        classname="abbyypara abbyycenter"
    elif (fmt["align"]=="Left"):
        classname="abbyypara abbyyleft"
    elif (fmt["align"]=="Right"):
        classname="abbyypara abbyyright"
    else: classname="abbyypara"
    classname=getclassname(classname,{"l": l,"t": t,"r": r,"b": b},
                           page_width,page_height,page_top)
    if ((classname.find("abbyypagehead")>=0) or
        (classname.find("abbyypagefoot")>=0)):
        tagname="span"
        newline=""
    else:
        tagname="p"
        newline="\n"
    stripped=text.strip()
    if len(stripped) == 0:
        return False
    else:
        # It might be cool to do some abstraction of the embedded style
        # information into paragraph level class information
        return (u"<%s class='%s' id='%s_%d' data-abbyy='n%d/p%d/%dx%d+%d,%d'><a class='abbyyparmark' name='n%dp%d'>¶</a>%s</%s>%s"%
                (tagname,classname,
                 book_id,para_count,
                 leaf_count,leaf_para_count,r-l,b-t,l,t,
                 leaf_count,leaf_para_count,
                 stripped,tagname,newline))

# This is all stuff for synthesizing CSS class names from formatting
#  attributes

fontmap={}
def getfontname(s):
    if (s in fontmap):
       return fontmap[s]
    else: return "'%s'"%s

def getcssname(format,curclass,classmap):
    if ('%histogram' in classmap):
        classhist=classmap['%histogram']
    else:
        classhist={}
        classmap['%histogram']=classhist
    if (format):
       style=""
       classname=""
       if ("ff" in format):
       	  style=style+"font-family: "+getfontname(format["ff"])+";"
       if ("fs" in format):
           size=float(format["fs"])/16
           style=style+"font-size: "+str(size)+"em;"
       if ("bold" in format):
       	  style=style+"font-weight: bold;"
       if ("italic" in format):
       	  style=style+"font-style: italic;"
       if style in classmap:
       	  classname=classmap[style]
	  classhist[classname]=classhist[classname]+1
       else:
           if ('%count' in classmap):
               classcount=classmap['%count']
           else:
               classcount=1
           classmap['%count']=classcount+1
           classname="abbyy%d"%classcount
           classmap[style]=classname
           classhist[classname]=1
       if (classname==curclass):
           return False
       else: return classname
    else: return False

def getclassname(base,attrib,width,height,pagetop):
    t=int(attrib['t'])
    b=int(attrib['b'])
    l=int(attrib['l'])
    r=int(attrib['r'])
    thresh=height*edgethresh
    if pagetop:
        thresh=thresh*0.75
    if (b<thresh):
        return base+" abbyypagehead"
    elif ((height-t)<thresh):
        return base+" abbyypagefoot"
    elif ((height-b)<(thresh/2)):
        return base+" abbyypagefoot"
    #elif (((r-l)<(width*0.8)) and (l>(width*0.2))):
    #    return base+" abbyycentered"
    return base

# Merging pageinfo

def pagemerge(f,xmlid,classmap,olid,bookid,
              inline_blocks=True,scaninfo={},imguri=False):
    # All the strings to be output (not strictly paragraphs, though)
    pars=[]
    # The current open paragraph
    openpar=False
    # The non-body elements processed since the open body paragraph
    waiting=[]
    # Whether the current paragraph ends with a hyphen
    openhyphen=False
    # If we're doing pagemerge, we read a stream of blocks,
    #    potentially merging blocks which cross page boundaries.  All
    #    the content blocks are paragraph <p> blocks, and the
    #    algorithm works by keeping the last paragraph block in
    #    _openpar_ and accumulating non paragraph blocks in the
    #    _waiting_ array. 
    #  When we get a paragraph that starts with a lowercase letter, we
    #    add it to the open paragraph together with all of the waiting
    #    non-body elements which have accumulated.
    for line in getblocks(f,xmlid,classmap,
                          inline_blocks=True,
                          scaninfo=scaninfo,imguri=imguri):
        if (len(line)==0):
            pars
        elif (line.startswith("<p")):
            # We don't merge centered paragraphs
            if (line.find("abbyycentered")>0):
                if (openpar):
                    pars.append(openpar)
                    for elt in waiting:
                        pars.append(elt)
                    waiting=[]
                    # and start with a new open paragraph
                    pars.append(line)
                    openpar=False
                else:
                    for elt in waiting:
                        pars.append(elt)
                    waiting=[]
                    pars.append(line)
            elif (openpar):
                # We check if the first letter is lowercase by finding
                # the first post-markup letter and the first
                # post-markup lowercase letter and seeing if they're
                # in the same place.  Note that paragraphs whose text
                # starts with punctuation will not pass this test
                # (which I think is the right thing)
                firstletter=re.search("(?m)>(\s|'|\")*[a-zA-z]",line)
                firstlower=re.search("(?m)>(\s|'|\")*[a-z]",line)
                if ((not firstletter or not firstlower) or
                    ((firstletter.start()) != (firstlower.start()))):
                    # Not a continuation, so push the open paragraph
                    pars.append(openpar)
                    # add any intervening elements
                    for elt in waiting:
                        pars.append(elt)
                    waiting=[]
                    # and start with a new open paragraph
                    openpar=line
                else:
                    # This paragraph continues the previous one, so
                    #   we append it to openpar, with waiting elements
                    #   added to the middle
                    if openhyphen:
                        # Replace the closing hyphen (and the closing
                        # </p> tag) with an abbyydroppedhyphen span
                        par_end=openhyphen.start()
                        openpar=openpar[0:par_end]+"<span class='abbyydroppedhyphen'>-</span>"
                    else:
                        # Strip off the closing tag from the open par
                        search_end=re.search("(?m)</p>",openpar)
                        if search_end:
                            openpar=openpar[0:(search_end.start())]+" "
                        else: 
                            openpar=openpar+" "
                    for elt in waiting:
                        openpar=openpar+elt
                    waiting=[]
                    textstart=line.find(">")
                    openpar=openpar+line[textstart+1:]
            else:
                # This is the first paragraph
                openpar=line
                for elt in waiting:
                    pars.append(elt)
                waiting=[]
            # Check if the current open paragraph ends with a hyphen
            if (openpar):
                openhyphen=re.search("(?m)-\s*</p>",openpar)
            else:
                openhyphen=False
        else:
            waiting.append(line)
    if openpar:
        pars.append(openpar)
    for elt in waiting:
        pars.append(elt)
    return pars
        
def makehtmlbody(abbyystream,bookid,itemid,doc=False,
                 mergepages=True,classmap={},scaninfo={}):
    if not doc: doc=itemid
    imguri=(("http://www.archivestream.github.io/download/%s/%s"%(itemid,doc))+
            "/page/leaf%d_x%d_y%d_w%d_h%d.jpg")
    # Do the generation
    if not mergepages:
        for line in getblocks(abbyystream,bookid,classmap,
                              inline_blocks=True,
                              scaninfo=scaninfo,imguri=imguri):
            if (len(line)==0):
                pars
            else:
                pars.append(line)
    else:
        pars=pagemerge(abbyystream,bookid,classmap,
                       scaninfo=scaninfo,imguri=imguri)
    return pars
