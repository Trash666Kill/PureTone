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
OVERWRITE="true"           # Overwrite existing files by default (true/false)

# Function to display README
show_help() {
    cat << 'EOF'
README: DSD to High-Quality Audio Converter

This script converts DSD (.dsf) audio files to WAV, WavPack, or FLAC formats, preserving maximum audio fidelity. It uses ffmpeg to process the files, extract metadata, and apply automatic loudness normalization.

### How it Works
1. **Input**: Scans the current directory for .dsf files. If none are found, it searches subdirectories.
2. **Metadata Extraction**: Uses ffprobe to extract artist and album metadata from .dsf files.
3. **Conversion Flow**:
   - Converts DSD to an intermediate WAV file (configurable codec and sample rate) with loudness normalization.
   - Depending on OUTPUT_FORMAT:
     - WAV: Saves the intermediate WAV as the final file in 'wv/' (or '<subdir>/wv/' if in subdirectories).
     - WavPack: Converts WAV to WavPack (.wv) in 'wvpk/' (or '<subdir>/wvpk/').
     - FLAC: Converts WAV to FLAC (.flac) in 'flac/' (or '<subdir>/flac/').
4. **Output**: Files are organized in a directory structure based on the output format, either in the current directory or within subdirectories.
5. **Logging**: Conversion details are saved in log.txt in each output directory, including elapsed time.
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
    - `./conv.sh --skip-existing` (Skip existing files instead of overwriting)
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
- **OVERWRITE**: Overwrite existing files by default (true/false). Default: "true". Can be overridden with --skip-existing.

### Command-Line Options
- `<format>`: Specify OUTPUT_FORMAT (wav, wavpack, flac) as the first argument.
- `-codec <value>`: Set ACODEC (e.g., pcm_s24le, pcm_s32le).
- `-sample_rate <value>`: Set AR (e.g., 44100, 96000, 192000).
- `-map_metadata <value>`: Set MAP_METADATA (e.g., 0, -1).
- `-audio_filter <value>`: Set AF (e.g., "loudnorm=I=-14:TP=-2:LRA=9").
- `-loudness <true|false>`: Enable or disable loudness analysis.
- `-compression_level <value>`: Set compression level for WavPack (0-6) or FLAC (0-12).
- `--skip-existing`: Skip existing output files instead of overwriting them (overrides OVERWRITE=true).

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
- Elapsed time is displayed and logged in log.txt.
- If no .dsf files are found in the current directory, it searches subdirectories and prompts the user to either convert all or select individually.
- By default, overwrites existing files (OVERWRITE=true). Use --skip-existing to skip them instead.
- Lists all generated log files at the end for reference.

Enjoy your high-quality audio conversions!
EOF
    exit 0
}

# Check for --help argument
if [ "$1" = "--help" ]; then
    show_help
fi

# Variable to track if --skip-existing is passed
SKIP_EXISTING="false"

# Parse command-line arguments
if [ $# -gt 0 ]; then
    case "$1" in
        "wav"|"wavpack"|"flac")
            OUTPUT_FORMAT="$1"
            shift
            ;;
        *)
            # Check if first argument is an option, otherwise error
            if [[ "$1" != -* ]]; then
                echo "Error: Invalid format '$1'. Supported values are 'wav', 'wavpack', or 'flac'."
                echo "Usage: ./conv.sh [wav|wavpack|flac] [options]"
                exit 1
            fi
            ;;
    esac

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
            --skip-existing)
                SKIP_EXISTING="true"
                shift
                ;;
            *)
                echo "Error: Unknown option '$1'."
                echo "Usage: ./conv.sh [wav|wavpack|flac] [-codec <value>] [-sample_rate <value>] [-map_metadata <value>] [-audio_filter <value>] [-loudness <true|false>] [-compression_level <value>] [--skip-existing]"
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

# Record start time
START_TIME=$(date +%s)

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
echo "  Overwrite existing files: $OVERWRITE (overridden by --skip-existing: $SKIP_EXISTING)"
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

# Variables to track success, log files, and conversion counts
success=1
declare -A log_files  # Associative array to store log files per directory
declare -A file_counts  # Associative array to store number of files converted per directory

# Function to process a single directory
process_directory() {
    local dir="$1"
    local file_count=0
    for input_file in "$dir"/*.dsf; do
        if [ -e "$input_file" ]; then
            # Extract metadata with ffprobe
            ARTIST=$(ffprobe -v quiet -show_entries format_tags=artist -of default=noprint_wrappers=1:nokey=1 "$input_file")
            ALBUM=$(ffprobe -v quiet -show_entries format_tags=album -of default=noprint_wrappers=1:nokey=1 "$input_file")

            # Set default values if metadata is missing
            [ -z "$ARTIST" ] && ARTIST="Unknown Artist"
            [ -z "$ALBUM" ] && ALBUM="Unknown Album"

            # Use directory name as base for output (if subdir) or metadata (if current dir)
            if [ "$dir" = "." ]; then
                OUTPUT_DIR="$OUTPUT_BASE_DIR/$ARTIST/$ALBUM"
            else
                OUTPUT_DIR="$dir/$OUTPUT_BASE_DIR"
            fi

            # Create directory if it doesn't exist
            mkdir -p "$OUTPUT_DIR"

            # Define file names
            base_name=$(basename "$input_file" .dsf)
            wav_temp_file="$OUTPUT_DIR/${base_name}_temp.wav"
            case "$OUTPUT_FORMAT" in
                "wav")
                    output_file="$OUTPUT_DIR/${base_name}.wav"
                    ;;
                "wavpack")
                    output_file="$OUTPUT_DIR/${base_name}.wv"
                    ;;
                "flac")
                    output_file="$OUTPUT_DIR/${base_name}.flac"
                    ;;
            esac

            # Check if output file already exists
            if [ -e "$output_file" ]; then
                if [ "$SKIP_EXISTING" = "true" ]; then
                    echo "File $output_file already exists. Skipping conversion of $input_file (--skip-existing enabled)."
                    continue
                elif [ "$OVERWRITE" = "true" ]; then
                    echo "File $output_file already exists. Overwriting due to OVERWRITE=true."
                fi
            fi

            log_file="$OUTPUT_DIR/log.txt"
            loudness_file="$OUTPUT_DIR/loudness.txt"

            # Store log file path
            log_files["$dir"]="$log_file"

            # Clear log and loudness files only on the first file in this dir
            if [ "$input_file" = "$(ls "$dir"/*.dsf | head -n 1)" ]; then
                > "$log_file"
                if [ "$ENABLE_LOUDNESS" = "true" ]; then
                    > "$loudness_file"
                fi
            fi

            # Measure loudness of the original file if enabled
            if [ "$ENABLE_LOUDNESS" = "true" ]; then
                echo "Loudness of original file: $input_file" >> "$loudness_file"
                ffmpeg -i "$input_file" -af ebur128 -f null - 2>> "$loudness_file"
                echo "----------------------------------------" >> "$loudness_file"
            fi

            # Step 1: Convert DSD to WAV
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

            if [ -f "$output_file" ]; then
                echo "Converted: $input_file -> $output_file"
                ((file_count++))
                if [ "$ENABLE_LOUDNESS" = "true" ]; then
                    echo "Loudness of converted file: $output_file" >> "$loudness_file"
                    ffmpeg -i "$output_file" -af ebur128 -f null - 2>> "$loudness_file"
                    echo "----------------------------------------" >> "$loudness_file"
                fi
            else
                echo "Error converting: $input_file"
                success=0
            fi
        fi
    done
    file_counts["$dir"]=$file_count
}

# Check for .dsf files in the current directory
dsf_files_found=$(ls *.dsf 2>/dev/null | wc -l)

if [ "$dsf_files_found" -gt 0 ]; then
    # Process .dsf files in the current directory
    process_directory "."
else
    # No .dsf files in current directory, search subdirectories
    subdirs_with_dsf=$(find . -maxdepth 1 -type d -not -path . -exec sh -c 'ls "{}"/*.dsf >/dev/null 2>&1 && echo "{}"' \; | sed 's|./||')
    if [ -n "$subdirs_with_dsf" ]; then
        echo "No .dsf files found in the current directory."
        echo "However, .dsf files were found in the following subdirectories:"
        echo "$subdirs_with_dsf"
        echo -n "Would you like to convert all subdirectories at once (a) or select one by one (o)? (a/o): "
        read -r mode
        if [[ "$mode" =~ ^[Aa]$ ]]; then
            echo "Converting all subdirectories..."
            # Convert subdirs_with_dsf to an array to avoid subshell issues
            mapfile -t subdir_array <<< "$subdirs_with_dsf"
            for subdir in "${subdir_array[@]}"; do
                echo "Processing subdirectory: $subdir"
                process_directory "$subdir"
            done
        elif [[ "$mode" =~ ^[Oo]$ ]]; then
            echo "Select subdirectories to convert (y/n for each):"
            echo "$subdirs_with_dsf" | while IFS= read -r subdir; do
                echo -n "Convert $subdir? (y/n): "
                read -r response
                if [[ "$response" =~ ^[Yy]$ ]]; then
                    echo "Processing subdirectory: $subdir"
                    process_directory "$subdir"
                else
                    echo "Skipping $subdir"
                fi
            done
        else
            echo "Invalid option. Conversion aborted."
            exit 0
        fi
    else
        echo "No .dsf files found in the current directory or its subdirectories."
        exit 1
    fi
fi

# Record end time and calculate elapsed time
END_TIME=$(date +%s)
ELAPSED_TIME=$((END_TIME - START_TIME))

# Display final message based on conversion success
if [ $success -eq 1 ]; then
    echo "Conversion completed successfully!"
else
    echo "Conversion completed with errors!"
fi

# List all generated log files and file counts
if [ ${#log_files[@]} -gt 0 ]; then
    echo "Details saved in the following log files:"
    total_files=0
    for dir in "${!log_files[@]}"; do
        echo "  ${log_files[$dir]} (${file_counts[$dir]} files converted)"
        ((total_files += file_counts[$dir]))
    done
    echo "Total files converted: $total_files"
else
    echo "No conversions performed."
fi

if [ "$ENABLE_LOUDNESS" = "true" ]; then
    echo "Loudness measurements saved alongside each log.txt."
fi
echo "Elapsed time: $ELAPSED_TIME seconds"

# Append completion message to each log file
for log_file in "${log_files[@]}"; do
    echo "" >> "$log_file"
    echo "----------------------------------------" >> "$log_file"
    if [ $success -eq 1 ]; then
        echo "Conversion completed on $(date)" >> "$log_file"
    else
        echo "Conversion completed with errors on $(date)" >> "$log_file"
    fi
    echo "Elapsed time: $ELAPSED_TIME seconds" >> "$log_file"
done