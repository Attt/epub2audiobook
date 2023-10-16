import asyncio
import edge_tts
from edge_tts import VoicesManager
import argparse
from mutagen.mp3 import MP3
from mutagen.id3 import TIT2, TPE1, TALB, TRCK, TCON
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from urllib.parse import urlparse, urlunparse
import os
import re
import random
import chardet
import logging
from retry import retry
from pydub import AudioSegment
from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio
import warnings

warnings.filterwarnings('ignore', category=XMLParsedAsHTMLWarning)
warnings.filterwarnings('ignore', category=UserWarning)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

# 章节链接信息
class ChapterLinkInfo:

    def __init__(self, links):
        self.links = links
        self.title = None
        self.anchor = None
        self.id = None
        self.cursor = -1
        self.nextChapter()

    def nextChapter(self):
        if self.cursor < len(self.links) - 1:
            self.cursor += 1
            self.id, self.anchor, self.title = self.links[self.cursor]

# 章节解析结果
class ChapterResultInfo:

    def __init__(self):
        self.start = False
        self.chapters_xhtmls = []
        self.chapters_xhtml = ''

    def chapterFound(self, title):
        if self.start:
            self.chapters_xhtmls.append(self.chapters_xhtml)
        self.start = True
        self.chapters_xhtmls.append(title)
        self.chapters_xhtml = ''

    def append(self, content):
        self.chapters_xhtml += content

    def isFirstChapterFound(self):
        return self.start
    
    # [(title, text)]
    def getAllChapters(self):
        if self.chapters_xhtml:
            self.chapters_xhtmls.append(self.chapters_xhtml)
            self.chapters_xhtml = ''
    
        chapters = []
        title_idx = 0
        for title_idx in range(0, len(self.chapters_xhtmls), 2):
            title = self.chapters_xhtmls[title_idx]
            raw_xhtml = self.chapters_xhtmls[title_idx + 1] if title_idx + 1 < len(self.chapters_xhtmls) else ''

            raw_bs = BeautifulSoup(raw_xhtml, features="lxml")

            raw = raw_bs.get_text(strip=False)
            raw = raw.strip()
            raw = raw.strip('\n')
            raw = raw.strip('\r\n')
            raw = re.sub(r'(\r\n|\n)+', '\n', raw)
            raw = re.sub(r'!\[\]\([^)]+\)', '', raw)
            raw = re.sub(r'\[\]\([^)]+\)', '', raw)
            lines = [replace_all_jp_seiji_with_kakuchou(line.strip()) + ' ' for line in raw.split('\n')]
            # 重新组合处理后的行
            raw = '\n'.join(lines)
            raw = raw.encode('utf-8').decode('utf-8', 'ignore')

            chapters.append((title, raw))
        return chapters

def remove_url_fragment(url):
    parsed_url = urlparse(url)
    # 构建一个新的具有相同属性的URL，但fragment部分为空
    modified_url = urlunparse((parsed_url.scheme, parsed_url.netloc, parsed_url.path,
                               parsed_url.params, '', parsed_url.query))
    return modified_url, parsed_url.fragment

def replace_invalid_characters(input_string):
    # 定义不合法的字符集合
    invalid_characters = r'[\/:*?"<>|]'
    # 使用正则表达式将不合法字符替换为下划线
    cleaned_string = re.sub(invalid_characters, '_', input_string)
    return cleaned_string

def get_toc(epub_file_path):
    book = epub.read_epub(epub_file_path)
    legacy_toc = book.toc

    book = epub.read_epub(epub_file_path, options={"ignore_ncx": True})
    toc = legacy_toc if len(legacy_toc) > len(book.toc) else book.toc

    logger.info('TOC:')
    for link in book.toc :
        logger.info(f'\t{link.title}')
    return (book, toc)

def find_all_chapters(book, toc):
    content = merge_all_xhtml(book)

    bs = BeautifulSoup(content, features="lxml")

    chapter_links = []
    for chpt in toc:
        href, anchor = remove_url_fragment(chpt.href)
        chpt_item = book.get_item_with_href(href)
        if not bs.find(id = anchor):
            anchor = ''
        chapter_links.append((chpt_item.id, anchor, chpt.title))

    result = ChapterResultInfo()
    for tag in bs.contents:
        walk_tags(tag, ChapterLinkInfo(chapter_links), result)

    return result.getAllChapters()


def replace_all_jp_seiji_with_kakuchou(content):
    global replace_dict
    if replace_dict:
        for key, value in replace_dict.items():
            content = content.replace(key, value)
    return content

# 遍历所有的tag
def walk_tags(tag, chapter_info: ChapterLinkInfo, result: ChapterResultInfo):
    """
    tag: 当前的tag
    chapter_info: 章节链接信息
    result: 处理结果
    """
    if (not chapter_info.anchor and tag.get('name') and tag.get('name') == chapter_info.id) or (tag.get('id') and tag.get('id') == chapter_info.anchor):
        result.chapterFound(chapter_info.title)
        chapter_info.nextChapter()
        
    result.append(f'<{tag.name}>')
    for tag_content in tag.contents:
        if isinstance(tag_content, str):
            result.append(tag_content)
        elif isinstance(tag_content, Tag):
            walk_tags(tag_content, chapter_info, result)
    result.append(f'</{tag.name}>')

# 合并所有的xhtml的body内容
def merge_all_xhtml(book):
    xhtml = ''
    for item in tqdm(book.items, desc="Merging", unit="item"):
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        charset = chardet.detect(item.get_content())['encoding']
        if not charset:
            charset = 'utf-8'
        logger.debug(f"item {item.id} charset is {charset}")
        raw_content = re.sub(r'<rt>.*?</rt>', '', item.get_content().decode(charset, 'ignore'))
        raw_bs = BeautifulSoup(raw_content, features="lxml")
        body_tag = raw_bs.find('body')
        if not body_tag:
            continue
        body_tag.name = 'p'
        body_tag.attrs['name'] = item.id
        xhtml += str(body_tag)
    return '<html><body>' + xhtml + '</body><html>'

def find_all_epub_files(epub_file_path):
    epub_files = []
    if os.path.isdir(epub_file_path):
        epub_file_names = os.listdir(epub_file_path)
        for epub_file_name in epub_file_names:
            file_path = os.path.join(epub_file_path, epub_file_name)
            if os.path.isdir(file_path):
                all_epub_files = find_all_epub_files(file_path)
                for efp in all_epub_files:
                    epub_files.append(efp)
            elif epub_file_name.endswith(".epub"):
                epub_files.append(file_path)
    return epub_files

def get_first_image_item(book, item_type):
    coverItem = None
    images = book.get_items_of_type(item_type)
    for i in images:
        if coverItem:
            break
        coverItem = i
    return coverItem

# 定义函数来提取章节内容并保存到TXT文件
def extract_and_save_chapters(epub_file_path, output_folder):
    global config

    dry_run = config.dry_run

    (book,toc) = get_toc(epub_file_path)
    creator = book.get_metadata('DC', 'creator')[0][0]
    book_title = book.get_metadata('DC', 'title')[0][0]
    language = book.get_metadata('DC', 'language')[0][0]

    # 创建输出文件夹（如果不存在）
    output_folder = os.path.join(output_folder, replace_invalid_characters(creator))
    if not dry_run and not os.path.exists(output_folder):
        os.makedirs(output_folder)

    output_folder = os.path.join(output_folder, replace_invalid_characters(book_title))
    if not dry_run and not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # 创建封面（如果有）
    coverItem = get_first_image_item(book, ebooklib.ITEM_COVER)
    if not coverItem:
        coverItem = get_first_image_item(book, ebooklib.ITEM_IMAGE)

    if coverItem:
        file_name, file_extension = os.path.splitext(coverItem.get_name())
        cover_file_path = os.path.join(output_folder, f'cover{file_extension}')
        logger.info(f"Save cover as {cover_file_path}")
        if not dry_run:
            with open(cover_file_path, 'wb') as cover_file:
                cover_file.write(coverItem.get_content())

    text_and_file_names = []

    # 根据TOC拆分全文
    chapters = find_all_chapters(book, toc)

    num = 0
    for chapter_title, chapter in chapters:

        if not chapter:
            continue

        logger.info('=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=')
        logger.info(f'Title : {chapter_title}')
        logger.info('-----------------------------------')
        logger.info(f'{chapter.strip()[:20]}...char length: {len(chapter)}')
        logger.info('=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=')
        
        idx = str(num).zfill(2)
        num+=1
        # 生成TXT文件名并保存内容
        txt_file_name = replace_invalid_characters(f"{idx}.{chapter_title}")
        txt_file = f"{txt_file_name}.txt"
        txt_file_path = os.path.join(output_folder, txt_file_name)

        logger.info(f"Save chapter text as {txt_file_path}")
        
        if not dry_run:
            with open(txt_file_path, 'w', encoding='utf-8') as txt_file:
                txt_file.write(chapter)
        
        text_and_file_names.append((chapter, txt_file_name))
    return (output_folder, creator, book_title, language, text_and_file_names)

@retry(tries=5, delay=1, backoff=3)
async def communicate_edge_tts(text, voice, audio_file, subtitle_file):
    communicate = edge_tts.Communicate(text, voice)
    submaker = edge_tts.SubMaker()
    with open(audio_file, "wb") as file:
        async for chunk in tqdm_asyncio(communicate.stream(), desc="Streaming TTS"):
            if chunk["type"] == "audio":
                file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.create_sub((chunk["offset"], chunk["duration"]), chunk["text"])

    with open(subtitle_file, "w", encoding="utf-8") as file:
        file.write(submaker.generate_subs())

@retry(tries=5, delay=1, backoff=3)
def mac_say(text, voice, audio_file):
    texts = text.split('\n')
    idx = 0
    for txt in tqdm(texts, desc="Processing TTS"):
        if voice:
            os.system(f"say -v '{voice}' -o '{audio_file}.{idx}.m4a' '{txt}'")
        else:
            os.system(f"say -o '{audio_file}.{idx}.m4a' '{txt}'")
        idx+=1
    
    # merge audio files
    combined_audio = AudioSegment.empty()

    audio_idx = 0
    while audio_idx < idx:
        audio = AudioSegment.from_file(f"{audio_file}.{audio_idx}.m4a", format="m4a")
        combined_audio += audio
        combined_audio += AudioSegment.silent(duration=500)
        audio_idx+=1

    # write audio file
    combined_audio.export(f"{audio_file}", format="mp3")

    # delete temp files
    audio_idx = 0
    while audio_idx < idx:
        os.remove(f"{audio_file}.{audio_idx}.m4a")
        audio_idx+=1

# tts转为audio        
async def text_to_speech(output_folder, creator, book_title, text_and_file_names, language):
    global config

    voice = config.voice_name
    dry_run = config.dry_run
    tts_method = config.tts_method

    id3_tags = []
    idx = 1

    if tts_method == 'mac_say':
        if voice == 'auto':
            voice = None
    else:
        if voice == 'auto' and language:
            voices = await VoicesManager.create()
            voice = random.choice(voices.find(Gender="Female", Language=language))["Name"]
            logger.info(f"Select voice >>{voice}<<")

    if not dry_run:
        for text_and_file_name in text_and_file_names:
            (text, file_name) = text_and_file_name

            if len(text.strip()) == 0:
                continue

            audio_file = os.path.join(output_folder, f"{file_name}.mp3")
            subtitle_file = os.path.join(output_folder, f"{file_name}.vtt")

            logger.info(f"Generate audiobook >>>>> {audio_file} <<<<<")
            if tts_method == 'mac_say':
                mac_say(text, voice, audio_file)
            else:
                await communicate_edge_tts(text, voice, audio_file, subtitle_file)

            id3_tags.append((audio_file, book_title, file_name, creator, str(idx)))
            idx+=1

    return id3_tags


config = None
replace_dict = None

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Convert EPUB to audiobook")
    parser.add_argument("input_file", help="Path to the EPUB file or EPUB files folder")
    parser.add_argument("output_folder", help="Path to the output folder")
    parser.add_argument("-t", "--tts", default=True, help="Convert text to audio (default: True)")
    parser.add_argument("-tm", "--tts_method", default="edge_tts", help="Text-to-speech method (e.g.: mac_say, default: edge_tts)")
    parser.add_argument("-vo", "--voice_name", default="auto", help="Voice name for the text-to-speech service (e.g.: ja-JP-NanamiNeural, default: auto). show all available voices with command `edge-tts --list-voices` or `say -v'?'`")
    parser.add_argument("-dr", "--dry_run", action="store_true", help="Run without outputs")
    parser.add_argument("-idx", "--index_of_epubs", default="all", help="The index of the selected EPUB files (e.g.: 0-3,5,7, default: all)")

    config = parser.parse_args()
    
    epub_file_path = config.input_file
    output_folder = config.output_folder
    tts = config.tts
    index_of_epubs = config.index_of_epubs
    
    # 读取'正字体拡張新字体'字典
    with open("./seiji_to_kakushin", 'r') as dict_file:
        dictionary_content = dict_file.read().strip()
        dictionary_pairs = dictionary_content.split('|')
        replace_dict = {}
        for pair in dictionary_pairs:
            key, value = pair.split(',')
            replace_dict[key] = value

    # 创建输出文件夹（如果不存在）
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    epub_files = []
    # 是否是目录
    if os.path.isdir(epub_file_path):
        epub_files = find_all_epub_files(epub_file_path)
    else:
        epub_files.append(epub_file_path)

    epub_indexes = []
    if index_of_epubs and index_of_epubs != "all":
        indexes = index_of_epubs.split(',')
        for ind in indexes:
            if ind.__contains__('-'):
                from_to = ind.split('-')
                f = int(from_to[0])
                t = int(from_to[1])
                for ii in range(f, t+1):
                     epub_indexes.append(ii)
            else:
                epub_indexes.append(int(ind))
        
    loop = asyncio.get_event_loop_policy().get_event_loop()
    try:
        epub_file_idx = -1
        for epub_file in epub_files:

            epub_file_idx+=1
            logger.info(f"<<<<File index>>>>\t{epub_file_idx} : {epub_file}")

            if len(epub_indexes) != 0 and epub_file_idx not in epub_indexes:
                continue

            output_folder_and_text_and_file_names = extract_and_save_chapters(epub_file, output_folder)
        
            (n_output_folder, creator, book_title, language, text_and_file_names) = output_folder_and_text_and_file_names

            if tts == True:
                id3_tags = loop.run_until_complete(text_to_speech(n_output_folder, creator, book_title, text_and_file_names, language))

                for id3_tag in id3_tags:
                    (audio_file, book_title, file_name, creator, idx) = id3_tag
                    # Add ID3 tags to the generated MP3 file
                    audio = MP3(audio_file)
                    audio["TIT2"] = TIT2(encoding=3, text=file_name)
                    audio["TPE1"] = TPE1(encoding=3, text=creator)
                    audio["TALB"] = TALB(encoding=3, text=book_title)
                    audio["TRCK"] = TRCK(encoding=3, text=idx)
                    audio["TCON"] = TCON(encoding=3, text="Audiobook")
                    audio.save()
    finally:
        loop.close()