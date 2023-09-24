#!/bin/bash

# Function to check if a command is available
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Function to check if a Python package is installed
python_package_installed() {
  python3 -c "import $1" 2>/dev/null
}

# Function to create a directory if it doesn't exist
create_directory() {
  if [ ! -d "$1" ]; then
    mkdir -p "$1"
  fi
}

# Function to remove a directory and its contents
remove_directory() {
  if [ -d "$1" ]; then
    rm -rf "$1"
  fi
}

# 1. Install Python 3 and pip3 if not already installed
if ! command_exists python3 || ! command_exists pip3; then
  echo "Installing Python 3 and pip3..."
  sudo apt-get install -y python3 python3-pip
fi

# 2. Install requirements
pip3 install -r epub2txts/requirements.txt

# 3. Check if 'edge-tts' is already installed
if ! python_package_installed edge_tts; then
  echo "Installing the 'edge-tts' package using pip..."
  pip3 install edge-tts
#else
  #echo "'edge-tts' is already installed. Skipping installation."
fi

# Check if --list-voices option is provided
if [ "$1" == "--list-voices" ]; then
  edge-tts --list-voices
  exit 0
fi

# Check if both --epub and --voice options are provided
if [[ ("$1" != "--epub" && "$1" != "--voice") || ("$3" != "--voice" && "$3" != "--epub") ]]; then
  echo "Usage: $0 [--list-voices | --epub <epub_file> --voice <voice>]"
  exit 1
fi

# Determine the positions of --epub and --voice
epub_position=-1
voice_position=-1
if [ "$1" == "--epub" ]; then
  epub_position=2
  voice_position=4
else
  epub_position=4
  voice_position=2
fi

epub_file="${!epub_position}"
voice="${!voice_position}"
epub_file_no_ext="$(basename -- "$epub_file" .epub)"

echo "$epub_file"
echo "$voices"

# 4. Create 'outputs' directory if it doesn't exist
create_directory "./outputs"

# 5. Remove existing 'outputs/<epub_file_no_ext>' directory if it exists
remove_directory "./outputs/$epub_file_no_ext"
create_directory "./outputs/$epub_file_no_ext"

# 6. Convert EPUB to splitted text
echo 'Convert EPUB to splitted text'
python3 epub2txts/epub2txts.py "$epub_file" "./outputs/$epub_file_no_ext/"

# Function to process text files starting with '{num}.'
process_text_files() {
  dir="$1"
  for f in "$dir"/[0-9]*.txt; do
    filename=$(basename "$f" .txt)
    echo "processing $filename.txt..."
    edge-tts --voice "$voice" --file "$f" --write-media "./outputs/$epub_file_no_ext/$filename.mp3" --write-subtitles "./outputs/$epub_file_no_ext/$filename.vtt"
  done
}

# 7. Process the split files with edge-tts
process_text_files "./outputs/$epub_file_no_ext"