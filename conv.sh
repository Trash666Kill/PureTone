#!/bin/bash

# Configurable variables (defaults)
ACODEC="pcm_s24le"          # Audio codec for WAV intermediate file
AR="192000"                 # Sample rate
MAP_METADATA="0"            # Metadata mapping
AF="loudnorm=I=-16:TP=-1:LRA=11:linear=true"  # Audio filter for automatic normalization
ENABLE_LOUDNESS="false"    # Enable loudness analysis (true/false), disabled by default
OUTPUT_FORMAT="wav"        # Output format: wav, wavpack, or flac
WAVPACK_COMPRESSION="0"    # WavPack compression level (0-6), 0 for no compression
FLAC_COMPRESSION="0"       # FLAC compression level (0-12), 0 for no compression

# Function to display README
show_help() {
    cat << 'EOF'
README: DSD to High-Quality Audio Converter

This script converts DSD (.dsf) audio files to WAV, WavPack, or FLAC formats, preserving maximum audio fidelity. It uses ffmpeg to process the files, extract metadata, and apply automatic loudness normalization.

### How it Works
1. **Input**: Scans the current directory for .dsf files.
2. **Metadata Extraction**: Uses ffprobe to extract artist and album metadata from .dsf files.
3. **Conversion Flow**:
   - Converts DSD to an intermediate WAV file (configurable codec and sample rate) with loudness normalization.
   - Depending on OUTPUT_FORMAT:
     - WAV: Saves the intermediate WAV as the final file in 'wv/<Artist>/<Album>'.
     - WavPack: Converts WAV to WavPack (.wv) in 'wvpk/<Artist>/<Album>'.
     - FLAC: Converts WAV to FLAC (.flac) in 'flac/<Artist>/<Album>'.
4. **Output**: Files are organized in a directory structure based on the output format.
5. **Logging**: Conversion details are saved in log.txt in the output directory.
6. **Optional Loudness Analysis**: If enabled, loudness measurements (before and after) are saved in loudness.txt.

### Usage
- Save this script as `conv.sh`.
- Make it executable: `chmod +x conv.sh`.
- Run with defaults: `./conv.sh`
- Specify format and options: `./conv.sh <format> [options]`
  - Examples:
    - `./conv.sh flac -compression_level 0` (FLAC, no compression)
    - `./conv.sh wavpack -compression_level 6 -sample_rate 96000` (WavPack, high compression, 96 kHz)
    - `./conv.sh wav -codec pcm_s32le` (WAV, 32-bit PCM)
    - `./conv.sh flac -loudness true -audio_filter loudnorm=I=-14:TP=-2:LRA=9` (FLAC with custom loudness settings)
- For help: `./conv.sh --help`
- Edit the script to change defaults if preferred.

### Configurable Parameters
- **ACODEC**: Audio codec for the intermediate WAV file. Default: "pcm_s24le" (24-bit PCM).
  - Common options: "pcm_s16le" (16-bit), "pcm_s24le" (24-bit), "pcm_s32le" (32-bit).
- **AR**: Sample rate in Hz. Default: "192000" (192 kHz).
  - Examples: "44100" (44.1 kHz), "96000" (96 kHz), "192000" (192 kHz).
- **MAP_METADATA**: Metadata mapping from input to output. Default: "0" (copy all metadata).
- **AF**: Audio filter for normalization. Default: "loudnorm=I=-16:TP=-1:LRA=11:linear=true" (normalizes to -16 LUFS, -1 dBTP max peak).
- **ENABLE_LOUDNESS**: Enable loudness analysis (true/false). Default: "false". If true, generates loudness.txt with EBU R128 measurements.
- **OUTPUT_FORMAT**: Final output format. Options: "wav" (wv/), "wavpack" (wvpk/), "flac" (flac/). Default: "wav".
- **WAVPACK_COMPRESSION**: Compression level for WavPack (0-6). Default: "0" (no compression, max fidelity).
  - Example for high-quality compression: "6" (lossless, smaller file size).
- **FLAC_COMPRESSION**: Compression level for FLAC (0-12). Default: "0" (no compression, max fidelity).
  - Example for high-quality compression: "12" (lossless, smaller file size).

### Command-Line Options
- `<format>`: Specify OUTPUT_FORMAT (wav, wavpack, flac) as the first argument.
- `-codec <value>`: Set ACODEC (e.g., pcm_s24le, pcm_s32le).
- `-sample_rate <value>`: Set AR (e.g., 44100, 96000, 192000).
- `-map_metadata <value>`: Set MAP_METADATA (e.g., 0, -1).
- `-audio_filter <value>`: Set AF (e.g., "loudnorm=I=-14:TP=-2:LRA=9").
- `-loudness <true|false>`: Enable or disable loudness analysis.
- `-compression_level <value>`: Set compression level for WavPack (0-6) or FLAC (0-12).

### Compression Options
- WavPack and FLAC are lossless formats. Higher compression levels reduce file size without losing quality:
  - WavPack: Set WAVPACK_COMPRESSION="6" or use `-compression_level 6` for maximum compression (still lossless).
  - FLAC: Set FLAC_COMPRESSION="12" or use `-compression_level 12` for maximum compression (still lossless).
- Defaults to "0" for both, prioritizing fidelity over file size (larger files), keep it if you're crazy.

### Requirements
- ffmpeg (with ffprobe support) must be installed.

### Notes
- The script checks for ffmpeg and ffprobe before running.
- Temporary WAV files are deleted after conversion to WavPack or FLAC.
- Loudness analysis is optional and generates a detailed (potentially large) loudness.txt file.

Enjoy your high-quality audio conversions!
EOF
    exit 0
}

# Check for --help argument
if [ "$1" = "--help" ]; then
    show_help
fi

# Parse command-line arguments
if [ $# -gt 0 ]; then
    # First argument is OUTPUT_FORMAT
    case "$1" in
        "wav"|"wavpack"|"flac")
            OUTPUT_FORMAT="$1"
            shift  # Move past the format argument
            ;;
        *)
            echo "Error: Invalid format '$1'. Supported values are 'wav', 'wavpack', or 'flac'."
            echo "Usage: ./conv.sh [wav|wavpack|flac] [options]"
            exit 1
            ;;
    esac

    # Parse remaining arguments
    while [ $# -gt 0 ]; do
        case "$1" in
            -codec)
                if [ -n "$2" ]; then
                    ACODEC="$2"
                    shift 2
                else
                    echo "Error: -codec requires a value."
                    exit 1
                fi
                ;;
            -sample_rate)
                if [ -n "$2" ] && [[ "$2" =~ ^[0-9]+$ ]]; then
                    AR="$2"
                    shift 2
                else
                    echo "Error: -sample_rate requires a numeric value (e.g., 44100, 96000, 192000)."
                    exit 1
                fi
                ;;
            -map_metadata)
                if [ -n "$2" ]; then
                    MAP_METADATA="$2"
                    shift 2
                else
                    echo "Error: -map_metadata requires a value."
                    exit 1
                fi
                ;;
            -audio_filter)
                if [ -n "$2" ]; then
                    AF="$2"
                    shift 2
                else
                    echo "Error: -audio_filter requires a value."
                    exit 1
                fi
                ;;
            -loudness)
                if [ -n "$2" ] && [[ "$2" =~ ^(true|false)$ ]]; then
                    ENABLE_LOUDNESS="$2"
                    shift 2
                else
                    echo "Error: -loudness requires 'true' or 'false'."
                    exit 1
                fi
                ;;
            -compression_level)
                if [ -n "$2" ]; then
                    if [ "$OUTPUT_FORMAT" = "wavpack" ]; then
                        if [[ "$2" =~ ^[0-6]$ ]]; then
                            WAVPACK_COMPRESSION="$2"
                        else
                            echo "Error: WavPack compression level must be between 0 and 6."
                            exit 1
                        fi
                    elif [ "$OUTPUT_FORMAT" = "flac" ]; then
                        if [[ "$2" =~ ^([0-9]|1[0-2])$ ]]; then
                            FLAC_COMPRESSION="$2"
                        else
                            echo "Error: FLAC compression level must be between 0 and 12."
                            exit 1
                        fi
                    else
                        echo "Error: -compression_level is not applicable to WAV format."
                        exit 1
                    fi
                    shift 2
                else
                    echo "Error: -compression_level requires a value."
                    exit 1
                fi
                ;;
            *)
                echo "Error: Unknown option '$1'."
                echo "Usage: ./conv.sh [wav|wavpack|flac] [-codec <value>] [-sample_rate <value>] [-map_metadata <value>] [-audio_filter <value>] [-loudness <true|false>] [-compression_level <value>]"
                exit 1
                ;;
        esac
    done
fi

# Check if ffmpeg is installed
if ! command -v ffmpeg &> /dev/null; then
    echo "Error: ffmpeg not found. Please install ffmpeg to proceed."
    exit 1
else
    echo "ffmpeg found. Version:"
    ffmpeg -version | head -n 1
    echo "----------------------------------------"
fi

# Check if ffprobe is available
if ! command -v ffprobe &> /dev/null; then
    echo "Error: ffprobe not found. Please ensure ffmpeg is installed with ffprobe support."
    exit 1
fi

# Validate OUTPUT_FORMAT and set OUTPUT_BASE_DIR dynamically
case "$OUTPUT_FORMAT" in
    "wav")
        OUTPUT_BASE_DIR="wv"
        ;;
    "wavpack")
        OUTPUT_BASE_DIR="wvpk"
        ;;
    "flac")
        OUTPUT_BASE_DIR="flac"
        ;;
    *)
        echo "Error: Invalid OUTPUT_FORMAT '$OUTPUT_FORMAT'. Supported values are 'wav', 'wavpack', or 'flac'."
        exit 1
        ;;
esac

# Display configured parameters
echo "Configured parameters:"
echo "  Audio codec (-acodec): $ACODEC"
echo "  Sample rate (-ar): $AR"
echo "  Metadata mapping (-map_metadata): $MAP_METADATA"
echo "  Audio filter (-af): $AF"
echo "  Base output directory: $OUTPUT_BASE_DIR"
echo "  Loudness analysis enabled: $ENABLE_LOUDNESS"
echo "  Output format: $OUTPUT_FORMAT"
case "$OUTPUT_FORMAT" in
    "wavpack")
        echo "  WavPack compression level: $WAVPACK_COMPRESSION"
        ;;
    "flac")
        echo "  FLAC compression level: $FLAC_COMPRESSION"
        ;;
esac
echo ""

# Warn about loudness analysis if enabled
if [ "$ENABLE_LOUDNESS" = "true" ]; then
    echo "Note: Loudness analysis is enabled. This feature is optional and not required for conversion."
    echo "      It generates a 'loudness.txt' file with detailed audio measurements, which can be large"
    echo "      and somewhat complex to interpret. Disable it by setting ENABLE_LOUDNESS to 'false' if not needed."
    echo "----------------------------------------"
fi

echo "Starting conversion..."
echo "----------------------------------------"

# Variable to track success
success=1
log_file=""
loudness_file=""

# Loop through all .dsf files in the current directory
for input_file in *.dsf; do
    # Check if .dsf files exist
    if [ -e "$input_file" ]; then
        # Extract metadata with ffprobe
        ARTIST=$(ffprobe -v quiet -show_entries format_tags=artist -of default=noprint_wrappers=1:nokey=1 "$input_file")
        ALBUM=$(ffprobe -v quiet -show_entries format_tags=album -of default=noprint_wrappers=1:nokey=1 "$input_file")

        # Set default values if metadata is missing
        [ -z "$ARTIST" ] && ARTIST="Unknown Artist"
        [ -z "$ALBUM" ] && ALBUM="Unknown Album"

        # Remove invalid characters from directory names (e.g., /, \, *)
        ARTIST=$(echo "$ARTIST" | tr -d '/\\:*?"<>|')
        ALBUM=$(echo "$ALBUM" | tr -d '/\\:*?"<>|')

        # Define output directory
        OUTPUT_DIR="$OUTPUT_BASE_DIR/$ARTIST/$ALBUM"
        
        # Create directory if it doesn't exist
        mkdir -p "$OUTPUT_DIR"

        # Define file names
        wav_temp_file="$OUTPUT_DIR/${input_file%.dsf}_temp.wav"  # Temporary WAV file
        case "$OUTPUT_FORMAT" in
            "wav")
                output_file="$OUTPUT_DIR/${input_file%.dsf}.wav"
                ;;
            "wavpack")
                output_file="$OUTPUT_DIR/${input_file%.dsf}.wv"
                ;;
            "flac")
                output_file="$OUTPUT_DIR/${input_file%.dsf}.flac"
                ;;
        esac
        log_file="$OUTPUT_DIR/log.txt"
        loudness_file="$OUTPUT_DIR/loudness.txt"

        # Clear log and loudness files only on the first iteration (if loudness is enabled)
        if [ "$input_file" = "$(ls *.dsf | head -n 1)" ]; then
            > "$log_file"
            if [ "$ENABLE_LOUDNESS" = "true" ]; then
                > "$loudness_file"
            fi
        fi

        # Measure loudness of the original file (.dsf) with ebur128 if enabled
        if [ "$ENABLE_LOUDNESS" = "true" ]; then
            echo "Loudness of original file: $input_file" >> "$loudness_file"
            ffmpeg -i "$input_file" -af ebur128 -f null - 2>> "$loudness_file"
            echo "----------------------------------------" >> "$loudness_file"
        fi

        # Step 1: Convert DSD to WAV (intermediate step, no compression)
        ffmpeg -i "$input_file" -acodec "$ACODEC" -ar "$AR" -map_metadata "$MAP_METADATA" -af "$AF" "$wav_temp_file" -y >> "$log_file" 2>&1
        if [ $? -ne 0 ]; then
            echo "Error converting $input_file to intermediate WAV"
            success=0
            continue
        fi

        # Step 2: Convert WAV to final format
        case "$OUTPUT_FORMAT" in
            "wav")
                mv "$wav_temp_file" "$output_file"
                ;;
            "wavpack")
                ffmpeg -i "$wav_temp_file" -acodec wavpack -compression_level "$WAVPACK_COMPRESSION" "$output_file" -y >> "$log_file" 2>&1
                if [ $? -ne 0 ]; then
                    echo "Error converting $input_file to WavPack"
                    success=0
                    rm -f "$wav_temp_file"
                    continue
                fi
                rm -f "$wav_temp_file"
                ;;
            "flac")
                ffmpeg -i "$wav_temp_file" -acodec flac -compression_level "$FLAC_COMPRESSION" "$output_file" -y >> "$log_file" 2>&1
                if [ $? -ne 0 ]; then
                    echo "Error converting $input_file to FLAC"
                    success=0
                    rm -f "$wav_temp_file"
                    continue
                fi
                rm -f "$wav_temp_file"
                ;;
        esac

        # Check if conversion was successful
        if [ -f "$output_file" ]; then
            echo "Converted: $input_file -> $output_file"
            
            # Measure loudness of the converted file with ebur128 if enabled
            if [ "$ENABLE_LOUDNESS" = "true" ]; then
                echo "Loudness of converted file: $output_file" >> "$loudness_file"
                ffmpeg -i "$output_file" -af ebur128 -f null - 2>> "$loudness_file"
                echo "----------------------------------------" >> "$loudness_file"
            fi
        else
            echo "Error converting: $input_file"
            success=0
        fi
    else
        echo "No .dsf files found in the current directory."
        exit 1
    fi
done

# Display final message based on conversion success
if [ $success -eq 1 ]; then
    echo "Conversion completed! Details in $log_file"
    if [ "$ENABLE_LOUDNESS" = "true" ]; then
        echo "Loudness measurements saved in $loudness_file"
    fi
else
    echo "Conversion completed with errors. Check $log_file for details."
    if [ "$ENABLE_LOUDNESS" = "true" ]; then
        echo "Partial loudness measurements saved in $loudness_file"
    fi
fi
