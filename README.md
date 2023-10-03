# epub2audiobook
convert epub file to txt files separated according to TOC, then to audio file using edge-tts

## usage

```bash
# with default voice
./epub2audiobook.py /path/to/epub /path/to/output/

# sepecify voice gender
./epub2audiobook.py --gender Female /path/to/epub /path/to/output/

# specify voice name
./epub2audiobook.py --voice_name zh-CN-YunyeNeural /path/to/epub /path/to/output/
```

## denpendencies
- [p0n1/epub_to_audiobook](https://github.com/p0n1/epub_to_audiobook)
- [gtas5/epub2splittxt](https://github.com/gtas5/epub2splittxt)
- [rany2/edge-tts](https://github.com/rany2/edge-tts)
