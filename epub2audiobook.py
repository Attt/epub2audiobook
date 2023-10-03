import asyncio
import edge_tts
from edge_tts import VoicesManager
import argparse
from mutagen.mp3 import MP3
from mutagen.id3 import TIT2, TPE1, TALB, TRCK
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse
import os
import re
import random
import logging

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
    content = re.sub(r'<rt>.*?</rt>', '', content.decode('utf-8')).encode('utf-8') # 移除<rt>和</rt>之间的内容(移除注音)
    soup = BeautifulSoup(content, 'lxml')
    title = soup.title.string if soup.title else ''
    raw = soup.get_text(strip=False)
    raw.strip()
    raw.strip('\n')
    raw = raw.replace('\r\n', '')
    raw = raw.replace('\n', '')
    raw = raw.replace(' ', '')
    raw = re.sub(r'!\[\]\([^)]+\)', '', raw)
    raw = re.sub(r'\[\]\([^)]+\)', '', raw)
    return (title, raw)

def find_all_epub_files(epub_file_path):
    epub_files = []
    if os.path.isdir(epub_file_path):
        epub_file_names = os.listdir(epub_file_path)
        for epub_file_name in epub_file_names:
            file_path = os.path.join(epub_file_path, epub_file_name)
            if os.path.isdir(file_path):
                all_epub_files = find_all_epub_files(file_path)
                for epub_file_path in all_epub_files:
                    epub_files.append(epub_file_path)
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
    (book,toc) = get_toc(epub_file_path)
    creator = book.get_metadata('DC', 'creator')[0][0]
    book_title = book.get_metadata('DC', 'title')[0][0]
    language = book.get_metadata('DC', 'language')[0][0]

    # 创建输出文件夹（如果不存在）
    output_folder = os.path.join(output_folder, replace_invalid_characters(creator))
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    output_folder = os.path.join(output_folder, replace_invalid_characters(book_title))
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # 创建封面（如果有）
    coverItem = get_first_image_item(book, ebooklib.ITEM_COVER)
    if not coverItem:
        coverItem = get_first_image_item(book, ebooklib.ITEM_IMAGE)

    if coverItem:
        file_name, file_extension = os.path.splitext(coverItem.get_name())
        cover_file_path = os.path.join(output_folder, f'cover{file_extension}')
        with open(cover_file_path, 'wb') as cover_file:
            cover_file.write(coverItem.get_content())

    text_and_file_names = []
    num = 0
    for link in toc:
        item = book.get_item_with_href(remove_url_fragment(link.href))
        (title, raw) = clearify_html(item.get_content())
        chapter_title = title if title else link.title
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
        
        with open(txt_file_path, 'w', encoding='utf-8') as txt_file:
            txt_file.write(raw)
        
        text_and_file_names.append((raw, txt_file_name))
    return (output_folder, creator, book_title, language, text_and_file_names)

# tts转为audio        
async def text_to_speech(output_folder, creator, book_title, text_and_file_names, voice, gender, language):
    
    id3_tags = []
    idx = 1
    
    if gender and language:
        voices = await VoicesManager.create()
        voice = random.choice(voices.find(Gender=gender, Language=language))["Name"]
        logger.info(f"Select voice >>{voice}<<")

    for text_and_file_name in text_and_file_names:
        (text, file_name) = text_and_file_name

        audio_file = os.path.join(output_folder, f"{file_name}.mp3")
        subtitle_file = os.path.join(output_folder, f"{file_name}.vtt")

        logger.info(f"Generate audiobook >>>>> {audio_file} <<<<<")

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

        id3_tags.append((audio_file, book_title, creator, str(idx)))
        idx+=1

    return id3_tags

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert EPUB to audiobook")
    parser.add_argument("input_file", help="Path to the EPUB file or EPUB files folder")
    parser.add_argument("output_folder", help="Path to the output folder")
    parser.add_argument("--tts", default=True, help="Convert text to audio (default: True)")
    parser.add_argument("--gender", default="Female", help="[Female/Male] Voice gender for audio book, --voice_name will be ignored if this value is set")
    parser.add_argument("--voice_name", help="Voice name for the text-to-speech service (e.g.: ja-JP-NanamiNeural). show all available voices with command `edge-tts --list-voices`")
    parser.add_argument("--series_name", help="Series name of EPUB files, the album ID3 tag of audio file will be set to this value")

    args = parser.parse_args()
    
    epub_file_path = args.input_file
    output_folder = args.output_folder
    series_name = args.series_name
    voice = args.voice_name
    gender = args.gender
    tts = args.tts
    
    # 创建输出文件夹（如果不存在）
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    epub_files = []
    # 是否是目录
    if os.path.isdir(epub_file_path):
        epub_files = find_all_epub_files(epub_file_path)
    else:
        epub_files.append(epub_file_path)

    for epub_file in epub_files:
        output_folder_and_text_and_file_names = extract_and_save_chapters(epub_file, output_folder)
        
        (output_folder, creator, book_title, language, text_and_file_names) = output_folder_and_text_and_file_names

        if tts == True:
            loop = asyncio.get_event_loop_policy().get_event_loop()
            try:
                id3_tags = loop.run_until_complete(text_to_speech(output_folder, creator, book_title, text_and_file_names, voice, gender, language))

                for id3_tag in id3_tags:
                    (audio_file, book_title, creator, idx) = id3_tag
                    # Add ID3 tags to the generated MP3 file
                    audio = MP3(audio_file)
                    audio["TIT2"] = TIT2(encoding=3, text=book_title)
                    audio["TPE1"] = TPE1(encoding=3, text=creator)
                    if series_name:
                        audio["TALB"] = TALB(encoding=3, text=series_name)
                    audio["TRCK"] = TRCK(encoding=3, text=idx)
                    audio.save()
            finally:
                loop.close()
    