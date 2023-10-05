# epub2audiobook
convert epub file to txt files separated according to TOC, then to audio file using edge-tts or apple-tts in macOS called 'say'

## usage

```bash
# use edge_tts with default voice
./epub2audiobook.py /path/to/epub /path/to/output/

# specify voice name
./epub2audiobook.py --voice_name zh-CN-YunyeNeural /path/to/epub /path/to/output/

# specify tts method
./epub2audiobook.py --voice_name 'TingTing' --tts_method mac_say /path/to/epub /path/to/output/

# run without outputs
./epub2audiobook.py --dry_run /path/to/epub /path/to/output/
```

When using the tts method of mac_say and the `--voice_name` option is set to *'auto'*, which is the default value, the currently activated voice on the system will be used. This is very useful because the `say -v` command cannot select some voices such as Siri


## denpendencies
- [p0n1/epub_to_audiobook](https://github.com/p0n1/epub_to_audiobook)
- [gtas5/epub2splittxt](https://github.com/gtas5/epub2splittxt)
- [rany2/edge-tts](https://github.com/rany2/edge-tts)
