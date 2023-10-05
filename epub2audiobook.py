import asyncio
import edge_tts
from edge_tts import VoicesManager
import argparse
from mutagen.mp3 import MP3
from mutagen.id3 import TIT2, TPE1, TALB, TRCK, TCON
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse
import os
import re
import random
import chardet
import logging
from retry import retry

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)
    
def remove_url_fragment(url):
    parsed_url = urlparse(url)
    # 构建一个新的具有相同属性的URL，但fragment部分为空
    modified_url = urlunparse((parsed_url.scheme, parsed_url.netloc, parsed_url.path,
                               parsed_url.params, '', parsed_url.query))
    return modified_url

def replace_invalid_characters(input_string):
    # 定义不合法的字符集合
    invalid_characters = r'[\/:*?"<>|]'
    # 使用正则表达式将不合法字符替换为下划线
    cleaned_string = re.sub(invalid_characters, '_', input_string)
    return cleaned_string

def find_all_chapters(items, toc_link_items):
    chapters = []
    current_chapter_items = []
    
    for item in items:
        if item in toc_link_items:
            chapters.append(current_chapter_items)
            current_chapter_items = []
        current_chapter_items.append(item)
    return chapters


def get_toc(epub_file_path):
    book = epub.read_epub(epub_file_path)
    legacy_toc = book.toc

    book = epub.read_epub(epub_file_path, options={"ignore_ncx": True})
    toc = legacy_toc if len(legacy_toc) > len(book.toc) else book.toc

    logger.info('TOC:')
    for link in book.toc :
        logger.info(f'\t{link.title}')
    return (book, toc)

def clearify_html(content):
    charset = chardet.detect(content)['encoding']
    if not charset:
        charset = 'utf-8'
    logger.info(f"Charset is {charset}")
    content = re.sub(r'<rt>.*?</rt>', '', content.decode(charset, 'ignore')) # 移除<rt>和</rt>之间的内容(移除注音)
    soup = BeautifulSoup(content, 'lxml', from_encoding=charset)
    title = soup.title.string if soup.title else ''
    raw = soup.get_text(strip=False)
    raw = raw.strip()
    raw = raw.strip('\n')
    raw = raw.strip('\r\n')
    raw = re.sub(r'(\r\n|\n)+', '\n', raw)
    raw = re.sub(r'!\[\]\([^)]+\)', '', raw)
    raw = re.sub(r'\[\]\([^)]+\)', '', raw)
    lines = [line.strip() + ' ' for line in raw.split('\n')]
    # 重新组合处理后的行
    raw = '\n'.join(lines)
    raw = raw.encode('utf-8').decode('utf-8', 'ignore')
    return (title, raw)

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
    items = list(book.get_items())
    initial_chapter_item = items[0]
    toc_link_items = []
    item_map_to_link_title = {}
    for link in toc:
        toc_link_item = book.get_item_with_href(remove_url_fragment(link.href))
        toc_link_items.append(toc_link_item)
        item_map_to_link_title[str(toc_link_item)] = link.title

    # 找到第一个章节的第一个item
    if len(toc_link_items) > 0:
        initial_chapter_item = toc_link_items[0]

    # 跳过第一个章节前的内容
    for item_idx in range(0, len(items)):
        if initial_chapter_item == items[item_idx]:
            items = items[item_idx:]
            break

    chapters = find_all_chapters(items, toc_link_items)

    num = 0
    for chapter in chapters:

        # 合并所有的chapter contents
        if not chapter or len(chapter) == 0:
            continue
        initial_item = chapter[0]
        (title, raw) = clearify_html(initial_item.get_content())
        link_title = item_map_to_link_title[str(initial_item)]
        chapter_title = title if title else link_title
        for i in range(1, len(chapter)):
            curr_item = chapter[i]
            (_, _raw) = clearify_html(curr_item.get_content())
            raw+=' '
            raw+=_raw
        
        if not raw:
            continue

        logger.info('=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=')
        logger.info(f'Title : {chapter_title}')
        logger.info('-----------------------------------')
        logger.info(raw.strip()[:20])
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
                txt_file.write(raw)
        
        text_and_file_names.append((raw, txt_file_name))
    return (output_folder, creator, book_title, language, text_and_file_names)

@retry(tries=5, delay=1, backoff=3)
async def communicate_edge_tts(text, voice, audio_file, subtitle_file):
    communicate = edge_tts.Communicate(text, voice)
    submaker = edge_tts.SubMaker()
    with open(audio_file, "wb") as file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.create_sub((chunk["offset"], chunk["duration"]), chunk["text"])

    with open(subtitle_file, "w", encoding="utf-8") as file:
        file.write(submaker.generate_subs())

# tts转为audio        
async def text_to_speech(output_folder, creator, book_title, text_and_file_names, language):
    global config

    voice = config.voice_name
    dry_run = config.dry_run

    id3_tags = []
    idx = 1
    
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
            await communicate_edge_tts(text, voice, audio_file, subtitle_file)

            id3_tags.append((audio_file, book_title, creator, str(idx)))
            idx+=1

    return id3_tags


config = None
if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Convert EPUB to audiobook")
    parser.add_argument("input_file", help="Path to the EPUB file or EPUB files folder")
    parser.add_argument("output_folder", help="Path to the output folder")
    parser.add_argument("-t", "--tts", default=True, help="Convert text to audio (default: True)")
    parser.add_argument("-vo", "--voice_name", default="auto", help="Voice name for the text-to-speech service (e.g.: ja-JP-NanamiNeural, default: auto). show all available voices with command `edge-tts --list-voices`")
    parser.add_argument("-dr", "--dry_run", action="store_true", help="Run without outputs")
    parser.add_argument("-idx", "--index_of_epubs", default="all", help="The index of the selected EPUB files (e.g.: 0-3,5,7, default: all)")

    config = parser.parse_args()
    
    epub_file_path = config.input_file
    output_folder = config.output_folder
    tts = config.tts
    index_of_epubs = config.index_of_epubs
    
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
                    (audio_file, book_title, creator, idx) = id3_tag
                    # Add ID3 tags to the generated MP3 file
                    audio = MP3(audio_file)
                    audio["TIT2"] = TIT2(encoding=3, text=book_title)
                    audio["TPE1"] = TPE1(encoding=3, text=creator)
                    audio["TALB"] = TALB(encoding=3, text=book_title)
                    audio["TRCK"] = TRCK(encoding=3, text=idx)
                    audio["TCON"] = TCON(encoding=3, text="Audiobook")
                    audio.save()
    finally:
        loop.close()