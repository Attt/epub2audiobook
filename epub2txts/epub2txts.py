import os
import sys
import re
import zipfile
import urllib
import json
import xml.parsers.expat
import html2text
from glob import glob

class ContainerParser():
    def __init__(self, xmlcontent=None):
        self.rootfile = ""
        self.xml = xmlcontent

    def startElement(self, name, attributes):
        if name == "rootfile":
            self.buffer = ""
            self.rootfile = attributes["full-path"]

    def parseContainer(self):
        parser = xml.parsers.expat.ParserCreate()
        parser.StartElementHandler = self.startElement
        parser.Parse(self.xml, 1)
        return self.rootfile

class BookParser():
    def __init__(self, xmlcontent=None):
        self.xml = xmlcontent
        self.title = ""
        self.author = ""
        self.inTitle = 0
        self.inAuthor = 0
        self.ncx = ""
        self.ranks = []
        self.html2id = {}
        self.id2html = {}

    def startElement(self, name, attributes):
        if name == "dc:title":
            self.buffer = ""
            self.inTitle = 1
        elif name == "dc:creator":
            self.buffer = ""
            self.inAuthor = 1
        elif name == "item":
            if attributes["id"] in ["ncx", "toc", "ncxtoc", "toc.ncx","nav"]:
                self.ncx = attributes["href"]
            if attributes["media-type"] == "application/xhtml+xml":
                self.id2html[attributes["id"]] = attributes["href"]
                self.html2id[attributes["href"]] = attributes["id"]
        elif name == "itemref":
            self.ranks.append(attributes["idref"])

    def characters(self, data):
        if self.inTitle:
            self.buffer += data
        elif self.inAuthor:
            self.buffer += data

    def endElement(self, name):
        if name == "dc:title":
            self.inTitle = 0
            self.title = self.buffer
            self.buffer = ""
        elif name == "dc:creator":
            self.inAuthor = 0
            self.author = self.buffer
            self.buffer = ""

    def parseBook(self):
        parser = xml.parsers.expat.ParserCreate()
        parser.StartElementHandler = self.startElement
        parser.EndElementHandler = self.endElement
        parser.CharacterDataHandler = self.characters
        parser.Parse(self.xml, 1)
        return self.title, self.author, self.ncx, self.html2id, self.id2html, self.ranks

class NavPoint():
    def __init__(self, id=None, playorder=None, level=0, content=None, text=None):
        self.id = id
        self.content = content
        self.playorder = playorder
        self.level = level
        self.text = text

class TocParserForEpub3():
    def __init__(self, xmlcontent=None):
        self.id = 0
        self.xml = xmlcontent
        self.currentNP = None
        self.stack = []
        self.inText = 0
        self.toc = []
        self.tocFlg = False

    def startElement(self, name, attributes):
        if name == "nav":
            self.tocFlg = attributes['epub:type'] == 'toc'
        elif name == "li":
            if self.tocFlg:
                level = len(self.stack)
                self.id = self.id + 1
                self.currentNP = NavPoint('num_'+ str(self.id), str(self.id), level)
                self.stack.append(self.currentNP)
                self.toc.append(self.currentNP)
        elif name == "a":
            if self.tocFlg:
                self.currentNP.content = urllib.parse.unquote(attributes["href"])
                self.buffer = ""
                self.inText = 1

    def characters(self, data):
        if self.inText:
            self.buffer += data

    def endElement(self, name):
        if name == "nav":
            self.tocFlg = False
        elif name == "li":
            if self.tocFlg:
                self.currentNP = self.stack.pop()
        elif name == "a":
            if self.tocFlg:
                if self.inText and self.currentNP:
                    self.currentNP.text = self.buffer
                self.inText = 0

    def parseToc(self):
        parser = xml.parsers.expat.ParserCreate()
        parser.StartElementHandler = self.startElement
        parser.EndElementHandler = self.endElement
        parser.CharacterDataHandler = self.characters
        parser.Parse(self.xml, 1)
        return self.toc

class TocParser():
    def __init__(self, xmlcontent=None):
        self.id = 0
        self.xml = xmlcontent
        self.currentNP = None
        self.stack = []
        self.inText = 0
        self.toc = []

    def startElement(self, name, attributes):
        if name == "navPoint":
            level = len(self.stack)
            if "id" in attributes:
                self.currentNP = NavPoint(attributes["id"], attributes["playOrder"], level)
            else:
                self.id = self.id + 1
                self.currentNP = NavPoint('num_'+ str(self.id), str(self.id), level)
            self.stack.append(self.currentNP)
            self.toc.append(self.currentNP)
        elif name == "content":
            self.currentNP.content = urllib.parse.unquote(attributes["src"])
        elif name == "text":
            self.buffer = ""
            self.inText = 1

    def characters(self, data):
        if self.inText:
            self.buffer += data

    def endElement(self, name):
        if name == "navPoint":
            self.currentNP = self.stack.pop()
        elif name == "text":
            if self.inText and self.currentNP:
                self.currentNP.text = self.buffer
            self.inText = 0

    def parseToc(self):
        parser = xml.parsers.expat.ParserCreate()
        parser.StartElementHandler = self.startElement
        parser.EndElementHandler = self.endElement
        parser.CharacterDataHandler = self.characters
        parser.Parse(self.xml, 1)
        return self.toc

class epub2txt():
    def __init__(self, epubfile=None):
        self.epub = epubfile

    def gao(self, start, end):
        startnum = self.ranks.index(self.html2id[start.split('#')[0]])
        endnum = self.ranks.index(self.html2id[end.split('#')[0]])
        startflag = ''
        if len(start.split('#')) > 1:
            startflag = start.split('#')[1]
        endflag = ''
        if len(end.split('#')) > 1:
            endflag = end.split('#')[1]

        strr = ''
        flag = 0
        if (startflag == ''):
            flag = 1
        if (endflag != ''):
            endnum += 1
        for i in range(startnum, endnum):
            html = self.file.read(self.ops + self.id2html[self.ranks[i]])
            htmlline = html.decode("utf-8").split('\n')
            flagbody = 0
            for line in htmlline:
                if (line.find("body") != -1):
                    flagbody = 1
                if (flagbody == 0):
                    continue
                if (endflag != '') and (line.find(endflag) != -1):
                    break
                if (flag == 0) and (line.find(startflag) != -1):
                    flag = 1
                if (flag == 1):
                    line = re.sub(r'<rt>.*?</rt>', '', line)  # 移除<rt>和</rt>之间的内容
                    strtmp = html2text.html2text(line)
                    str1 = strtmp
                    str1.strip()
                    str1.strip('\n')
                    str1 = str1.replace('\r\n', '')
                    str1 = str1.replace('\n', '')
                    str1 = str1.replace(' ', '')
                    str1 = re.sub(r'!\[\]\([^)]+\)', '', str1)
                    str1 = re.sub(r'\[\]\([^)]+\)', '', str1)

                    if (str1 != ""):
                        str2 = strtmp.strip()
                        str2 = str2.replace('\n', '')
                        strr += str2
                        m = re.match(r"(\w)", str2[-1])
                        n = re.match(r"[\u4e00-\u9fa5]+", str2[-1])
                        if (not m) and (not n):
                            strr += '\n'

        return strr

    def convert(self, outpath):
        self.file = zipfile.ZipFile(self.epub, "r")
        rootfile = ContainerParser(self.file.read("META-INF/container.xml")).parseContainer()
        title, author, ncx, html2id, id2html, ranks = BookParser(self.file.read(rootfile)).parseBook()
        self.title = title
        self.author = author
        self.ncx = ncx
        self.html2id = html2id
        self.id2html = id2html
        self.ranks = ranks

        ops = "/".join(rootfile.split("/")[:-1])
        if ops != "":
            ops = ops + "/"
        self.ops = ops

        print(ncx)
        toc = TocParser(self.file.read(ops + ncx)).parseToc()
        if len(toc) == 0:
            toc = TocParserForEpub3(self.file.read(ops + ncx)).parseToc()

        fo = open("%s_%s.txt" % (title, author), "w")
        last = ""
        lastfile = ""
        num = 0
        result = {}
        for t in toc:
            if (t.text == "CONTENTS"):
                continue
            if (lastfile != ""):
                fout = open(lastfile, "w")
                strr = self.gao(last, t.content)
                fout.write(strr)
                fout.close()
                now_chr = {}
                now_chr["num"] = num
                now_chr["title"] = lat.text
                now_chr["content"] = lat.content
                now_chr["file"] = lastfile
                now_chr["start"] = last
                now_chr["end"] = t.content
                result[num] = now_chr
            num += 1
            lastfile = os.path.join(outpath, str(num).zfill(2) + "." + t.text + ".txt")
            last = t.content
            lat = t
        fout = open(lastfile, 'w')
        strr = self.gao(last, id2html[ranks[len(ranks) - 1]])
        #fout.write(strr)
        fout.close()
        now_chr = {}
        now_chr["num"] = num
        now_chr["title"] = lat.text
        now_chr["content"] = lat.content
        now_chr["file"] = lastfile
        now_chr["start"] = last
        now_chr["end"] = t.content
        result[num] = now_chr
        fo.close()
        self.file.close()

if __name__ == "__main__":
    if len(sys.argv) > 2:
        filenames = glob(sys.argv[1])
        for filename in filenames:
            epub2txt(filename).convert(sys.argv[2])
