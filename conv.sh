#!/bin/bash

# Configurable variables (defaults)
ACODEC="pcm_s24le"          # Audio codec for WAV intermediate file
AR="192000"                 # Sample rate
MAP_METADATA="0"            # Metadata mapping
LOUDNORM_I="-16"            # Integrated loudness target (LUFS)
LOUDNORM_TP="-1"            # True peak limit (dBTP)
LOUDNORM_LRA="11"           # Loudness range (LU)
AF="loudnorm=I=$LOUDNORM_I:TP=$LOUDNORM_TP:LRA=$LOUDNORM_LRA"  # Audio filter (two-pass by default)
LOUDNORM_LINEAR="false"     # Use linear (one-pass) loudness normalization (true) or two-pass (false)
ENABLE_LOUDNESS="false"     # Enable loudness analysis (true/false)
OUTPUT_FORMAT="wav"         # Output format: wav, wavpack, or flac
WAVPACK_COMPRESSION="0"     # WavPack compression level (0-6)
FLAC_COMPRESSION="0"        # FLAC compression level (0-12)
OVERWRITE="true"            # Overwrite existing files by default (true/false)
PARALLEL_JOBS=2             # Number of parallel jobs (default: 2)
WORKING_DIR="$(pwd)"        # Default to current directory

# Function to normalize paths (remove double slashes)
normalize_path() {
    echo "$1" | sed 's|//|/|g'
}

# Function to display README
show_help() {
    cat << 'EOF'
README: DSD to High-Quality Audio Converter

This script converts DSD (.dsf) audio files to WAV, WavPack, or FLAC formats, preserving maximum audio fidelity. It uses ffmpeg to process files in parallel with GNU Parallel, extract metadata, and apply automatic loudness normalization.

### How it Works
1. **Input**: Scans the specified or current directory for .dsf files or subdirectories.
2. **Metadata Extraction**: Uses ffprobe to extract artist and album metadata.
3. **Conversion Flow**: Converts DSD to WAV, then to the final format, using parallel processing.
4. **Output**: Files are saved in 'wv/', 'wvpk/', or 'flac/' subdirectories relative to the input directory.
5. **Logging**: Details (ffmpeg output and conversion summary) saved in log.txt per directory.

### Usage
- Save as `conv.sh`, make executable: `chmod +x conv.sh`.
- Run: `./conv.sh [path/to/directory] [format] [options]`
  - Examples:
    - `./conv.sh` (Uses current directory, default WAV format)
    - `./conv.sh /path/to/music flac --loudnorm-I -14 --loudnorm-linear true`
    - `./conv.sh ./music wavpack --skip-existing -compression_level 6`
    - `./conv.sh /path/to/dsd --parallel 4`

### Configurable Parameters
- **ACODEC**: Default: "pcm_s24le" (24-bit PCM).
- **AR**: Default: "192000" (192 kHz).
- **MAP_METADATA**: Default: "0" (copy all metadata).
- **LOUDNORM_I**: Integrated loudness (LUFS). Default: "-16".
- **LOUDNORM_TP**: True peak (dBTP). Default: "-1".
- **LOUDNORM_LRA**: Loudness range (LU). Default: "11".
- **LOUDNORM_LINEAR**: One-pass (true) or two-pass (false). Default: "false".
- **ENABLE_LOUDNESS**: Loudness analysis (true/false). Default: "false".
- **OUTPUT_FORMAT**: "wav", "wavpack", "flac". Default: "wav".
- **WAVPACK_COMPRESSION**: 0-6. Default: "0".
- **FLAC_COMPRESSION**: 0-12. Default: "0".
- **OVERWRITE**: Overwrite files (true/false). Default: "true".
- **PARALLEL_JOBS**: Number of parallel jobs. Default: 2.

### Command-Line Options
- `path/to/directory`: Optional absolute or relative path to the directory to process (default: current directory).
- `<format>`: Output format: "wav", "wavpack", or "flac" (default: "wav").
- `-codec <value>`: Set audio codec (e.g., "pcm_s24le").
- `-sample_rate <value>`: Set sample rate (e.g., "192000").
- `-map_metadata <value>`: Set metadata mapping (e.g., "0").
- `--loudnorm-I <value>`: Set integrated loudness in LUFS (e.g., -14).
- `--loudnorm-TP <value>`: Set true peak in dBTP (e.g., -2).
- `--loudnorm-LRA <value>`: Set loudness range in LU (e.g., 9).
- `--loudnorm-linear <true|false>`: Use one-pass (true) or two-pass (false) loudness normalization.
- `-loudness <true|false>`: Enable loudness analysis.
- `-compression_level <value>`: Compression level for WavPack (0-6) or FLAC (0-12); ignored for WAV.
- `--skip-existing`: Skip existing output files instead of overwriting.
- `--parallel <number>`: Set number of parallel jobs (e.g., 4).
- `--help`: Display this help message.

### Notes
- Requires ffmpeg, ffprobe, parallel, and realpath (install with 'apt install ffmpeg parallel coreutils').
- Uses two-pass loudnorm by default for accuracy unless --loudnorm-linear is set to true.
- Processes 2 files in parallel by default; adjustable with --parallel.
- Reports overwritten and skipped files in the summary.
- If a directory path is provided, the script operates within that directory instead of the current one.
EOF
    exit 0
}

# Check for --help
[ "$1" = "--help" ] && show_help

# Variables for tracking
SKIP_EXISTING="false"
declare -i overwritten=0 skipped=0
TEMP_LOG="/tmp/conv_$$_results.log"
> "$TEMP_LOG"  # Initialize temporary log file

# Check for realpath dependency (needed for relative paths)
command -v realpath >/dev/null || { echo "Error: realpath not found. Install with 'apt install coreutils'."; exit 1; }

# Parse arguments
while [ $# -gt 0 ]; do
    case "$1" in
        /*|./*|../*) # Accept absolute or relative paths
            if [ -d "$1" ]; then
                WORKING_DIR=$(realpath "$1")
                shift
            else
                echo "Error: Directory '$1' does not exist."
                exit 1
            fi
            ;;
        "wav"|"wavpack"|"flac")
            OUTPUT_FORMAT="$1"
            shift
            ;;
        -codec) ACODEC="$2"; shift 2 ;;
        -sample_rate) [[ "$2" =~ ^[0-9]+$ ]] && AR="$2" || { echo "Error: -sample_rate requires a number"; exit 1; }; shift 2 ;;
        -map_metadata) MAP_METADATA="$2"; shift 2 ;;
        --loudnorm-I) LOUDNORM_I="$2"; shift 2 ;;
        --loudnorm-TP) LOUDNORM_TP="$2"; shift 2 ;;
        --loudnorm-LRA) LOUDNORM_LRA="$2"; shift 2 ;;
        --loudnorm-linear) [[ "$2" =~ ^(true|false)$ ]] && LOUDNORM_LINEAR="$2" || { echo "Error: --loudnorm-linear requires true/false"; exit 1; }; shift 2 ;;
        -loudness) [[ "$2" =~ ^(true|false)$ ]] && ENABLE_LOUDNESS="$2" || { echo "Error: -loudness requires true/false"; exit 1; }; shift 2 ;;
        -compression_level)
            if [ "$OUTPUT_FORMAT" = "wav" ]; then
                echo "Warning: -compression_level not applicable to WAV format."
                shift 2
            elif [ "$OUTPUT_FORMAT" = "wavpack" ]; then
                [[ "$2" =~ ^[0-6]$ ]] && WAVPACK_COMPRESSION="$2" || { echo "Error: WavPack compression 0-6"; exit 1; }
                shift 2
            elif [ "$OUTPUT_FORMAT" = "flac" ]; then
                [[ "$2" =~ ^([0-9]|1[0-2])$ ]] && FLAC_COMPRESSION="$2" || { echo "Error: FLAC compression 0-12"; exit 1; }
                shift 2
            fi
            ;;
        --skip-existing) SKIP_EXISTING="true"; shift ;;
        --parallel) [[ "$2" =~ ^[0-9]+$ ]] && PARALLEL_JOBS="$2" || { echo "Error: --parallel requires a number"; exit 1; }; shift 2 ;;
        *) echo "Error: Unknown option or invalid format '$1'"; exit 1 ;;
    esac
done

# Adjust AF based on LOUDNORM_LINEAR
if [ "$LOUDNORM_LINEAR" = "true" ]; then
    AF="loudnorm=I=$LOUDNORM_I:TP=$LOUDNORM_TP:LRA=$LOUDNORM_LRA:linear=true"
else
    AF="loudnorm=I=$LOUDNORM_I:TP=$LOUDNORM_TP:LRA=$LOUDNORM_LRA"
fi

# Set OUTPUT_BASE_DIR
case "$OUTPUT_FORMAT" in
    "wav") OUTPUT_BASE_DIR="wv" ;;
    "wavpack") OUTPUT_BASE_DIR="wvpk" ;;
    "flac") OUTPUT_BASE_DIR="flac" ;;
    *) echo "Error: Invalid OUTPUT_FORMAT"; exit 1 ;;
esac

# Export variables for parallel (including OUTPUT_BASE_DIR and TEMP_LOG)
export ACODEC AR MAP_METADATA AF LOUDNORM_LINEAR ENABLE_LOUDNESS OUTPUT_FORMAT WAVPACK_COMPRESSION FLAC_COMPRESSION OVERWRITE SKIP_EXISTING OUTPUT_BASE_DIR TEMP_LOG WORKING_DIR

# Check dependencies
command -v ffmpeg >/dev/null || { echo "Error: ffmpeg not found. Install with 'apt install ffmpeg'."; exit 1; }
command -v ffprobe >/dev/null || { echo "Error: ffprobe not found."; exit 1; }
command -v parallel >/dev/null || { echo "Error: parallel not found. Install with 'apt install parallel'."; exit 1; }
echo "ffmpeg found. Version: $(ffmpeg -version | head -n 1)"
echo "parallel found. Version: $(parallel --version | head -n 1)"
echo "----------------------------------------"

# Record start time
START_TIME=$(date +%s)

# Display parameters
echo "Configured parameters:"
echo "  Working directory: $WORKING_DIR"
echo "  Audio codec (-acodec): $ACODEC"
echo "  Sample rate (-ar): $AR"
echo "  Metadata mapping (-map_metadata): $MAP_METADATA"
echo "  Audio filter (-af): $AF"
echo "  Loudnorm linear mode: $LOUDNORM_LINEAR (true = one-pass, false = two-pass)"
echo "  Base output directory: $OUTPUT_BASE_DIR"
echo "  Loudness analysis enabled: $ENABLE_LOUDNESS"
echo "  Output format: $OUTPUT_FORMAT"
echo "  Overwrite existing files: $OVERWRITE (overridden by --skip-existing: $SKIP_EXISTING)"
echo "  Parallel jobs: $PARALLEL_JOBS"
case "$OUTPUT_FORMAT" in
    "wavpack") echo "  WavPack compression level: $WAVPACK_COMPRESSION" ;;
    "flac") echo "  FLAC compression level: $FLAC_COMPRESSION" ;;
esac
# Display FFmpeg commands only for the selected format
echo "  FFmpeg command (DSD to WAV):"
echo "    ffmpeg -i input.dsf -acodec $ACODEC -ar $AR -map_metadata $MAP_METADATA -af \"$AF\" output.wav -y"
case "$OUTPUT_FORMAT" in
    "wavpack")
        echo "  FFmpeg command (WAV to WavPack):"
        echo "    ffmpeg -i temp.wav -acodec wavpack -compression_level $WAVPACK_COMPRESSION output.wv -y"
        ;;
    "flac")
        echo "  FFmpeg command (WAV to FLAC):"
        echo "    ffmpeg -i temp.wav -acodec flac -compression_level $FLAC_COMPRESSION output.flac -y"
        ;;
    "wav")
        echo "  (For WAV, the output is simply moved from temp WAV without additional FFmpeg conversion)"
        ;;
esac
echo ""

# Function to process a single file
process_file() {
    local input_file="$1"
    local dir=$(dirname "$input_file")
    local OUTPUT_DIR=$(normalize_path "$dir/$OUTPUT_BASE_DIR")
    mkdir -p "$OUTPUT_DIR" || { echo "Error: Failed to create directory $OUTPUT_DIR" >&2; return 1; }

    # Extract metadata
    ARTIST=$(ffprobe -v quiet -show_entries format_tags=artist -of default=noprint_wrappers=1:nokey=1 "$input_file" 2>/dev/null || echo "Unknown Artist")
    ALBUM=$(ffprobe -v quiet -show_entries format_tags=album -of default=noprint_wrappers=1:nokey=1 "$input_file" 2>/dev/null || echo "Unknown Album")

    # Define file names with absolute paths
    base_name=$(basename "$input_file" .dsf)
    wav_temp_file=$(normalize_path "$OUTPUT_DIR/${base_name}_temp.wav")
    case "$OUTPUT_FORMAT" in
        "wav") output_file=$(normalize_path "$OUTPUT_DIR/$base_name.wav") ;;
        "wavpack") output_file=$(normalize_path "$OUTPUT_DIR/$base_name.wv") ;;
        "flac") output_file=$(normalize_path "$OUTPUT_DIR/$base_name.flac") ;;
    esac

    # Check if output file exists
    if [ -e "$output_file" ]; then
        if [ "$SKIP_EXISTING" = "true" ]; then
            echo "File $output_file already exists. Skipping conversion of $input_file (--skip-existing enabled)."
            echo "$dir:skipped" >> "$TEMP_LOG"
            return
        elif [ "$OVERWRITE" = "true" ]; then
            echo "File $output_file already exists. Overwriting due to OVERWRITE=true."
            echo "$dir:overwritten" >> "$TEMP_LOG"
        fi
    else
        echo "$dir:converted" >> "$TEMP_LOG"
    fi

    log_file=$(normalize_path "$OUTPUT_DIR/log.txt")
    loudness_file=$(normalize_path "$OUTPUT_DIR/loudness.txt")

    # Clear log/loudness files only for the first file in this run (using lock file)
    if [ ! -f "$OUTPUT_DIR/.processed" ]; then
        > "$log_file" || { echo "Error: Cannot write to $log_file" >&2; return 1; }
        [ "$ENABLE_LOUDNESS" = "true" ] && > "$loudness_file"
        touch "$OUTPUT_DIR/.processed"
    fi

    # Measure original loudness if enabled
    if [ "$ENABLE_LOUDNESS" = "true" ]; then
        echo "Loudness of original file: $input_file" >> "$loudness_file"
        ffmpeg -i "$input_file" -af ebur128 -f null - 2>> "$loudness_file"
        echo "----------------------------------------" >> "$loudness_file"
    fi

    # Convert DSD to WAV
    ffmpeg -i "$input_file" -acodec "$ACODEC" -ar "$AR" -map_metadata "$MAP_METADATA" -af "$AF" "$wav_temp_file" -y >> "$log_file" 2>&1
    if [ $? -ne 0 ]; then
        echo "Error converting $input_file to intermediate WAV" >&2
        echo "ffmpeg command failed: ffmpeg -i \"$input_file\" -acodec \"$ACODEC\" -ar \"$AR\" -map_metadata \"$MAP_METADATA\" -af \"$AF\" \"$wav_temp_file\" -y" >&2
        echo "Check $log_file for details" >&2
        rm -f "$wav_temp_file"
        echo "$dir:error" >> "$TEMP_LOG"
        return 1
    fi

    # Convert to final format
    case "$OUTPUT_FORMAT" in
        "wav") mv "$wav_temp_file" "$output_file" || { echo "Error moving $wav_temp_file to $output_file" >&2; return 1; } ;;
        "wavpack") ffmpeg -i "$wav_temp_file" -acodec wavpack -compression_level "$WAVPACK_COMPRESSION" "$output_file" -y >> "$log_file" 2>&1 ;;
        "flac") ffmpeg -i "$wav_temp_file" -acodec flac -compression_level "$FLAC_COMPRESSION" "$output_file" -y >> "$log_file" 2>&1 ;;
    esac
    if [ $? -ne 0 ]; then
        echo "Error converting $input_file to $OUTPUT_FORMAT" >&2
        rm -f "$wav_temp_file"
        echo "$dir:error" >> "$TEMP_LOG"
        return 1
    fi
    rm -f "$wav_temp_file"

    # Verify output integrity
    if [ ! -s "$output_file" ]; then
        echo "Error: $output_file is empty" >&2
        echo "$dir:error" >> "$TEMP_LOG"
        return 1
    fi

    echo "Converted: $input_file -> $output_file"
    return 0
}

# Cleanup function for interruption
cleanup() {
    echo "Script interrupted. Cleaning up temporary files..."
    find "$WORKING_DIR" -name "*_temp.wav" -delete
    rm -f "$TEMP_LOG"
    exit 1
}
trap cleanup INT TERM

# Export the function for parallel
export -f process_file normalize_path

# Change to the working directory
cd "$WORKING_DIR" || { echo "Error: Cannot change to directory $WORKING_DIR"; exit 1; }

# Main logic
echo "Starting conversion..."
echo "----------------------------------------"

# Variables to track results
declare -A log_files file_counts
success=1

# Check for .dsf files in current directory or subdirectories
dsf_files_found=$(find . -maxdepth 1 -name "*.dsf" | wc -l)
if [ "$dsf_files_found" -gt 0 ]; then
    echo "Processing directory: $WORKING_DIR"
    find . -maxdepth 1 -name "*.dsf" | parallel -j "$PARALLEL_JOBS" --line-buffer process_file || success=0
else
    subdirs_with_dsf=$(find . -maxdepth 1 -type d -not -path . -exec sh -c 'find "{}" -maxdepth 1 -name "*.dsf" | grep -q . && echo "{}"' \; | sed 's|./||')
    if [ -n "$subdirs_with_dsf" ]; then
        echo "Converting all subdirectories with .dsf files in $WORKING_DIR:"
        echo "$subdirs_with_dsf"
        echo "----------------------------------------"
        echo "Warning: This will process all subdirectories listed above."
        read -p "Do you want to continue? (y/n): " response
        case "$response" in
            [Yy]*)
                echo "Proceeding with conversion..."
                echo "$subdirs_with_dsf" | while IFS= read -r subdir; do
                    echo "Processing subdirectory: $subdir"
                    find "$subdir" -maxdepth 1 -name "*.dsf" | parallel -j "$PARALLEL_JOBS" --line-buffer process_file || success=0
                done
                ;;
            [Nn]*)
                echo "Aborting conversion."
                rm -f "$TEMP_LOG"
                exit 0
                ;;
            *)
                echo "Invalid response. Aborting conversion."
                rm -f "$TEMP_LOG"
                exit 1
                ;;
        esac
    else
        echo "No .dsf files found in $WORKING_DIR or its subdirectories."
        rm -f "$TEMP_LOG"
        exit 1
    fi
fi

# Collect results from the temporary log
while IFS=':' read -r dir status; do
    case "$status" in
        "converted") ((file_counts["$dir"]++)) ;;
        "overwritten") ((file_counts["$dir"]++)); ((overwritten++)) ;;
        "skipped") ((skipped++)) ;;
        "error") success=0 ;;
    esac
    log_files["$dir"]=$(normalize_path "$dir/$OUTPUT_BASE_DIR/log.txt")
done < "$TEMP_LOG"
rm -f "$TEMP_LOG"

# Calculate elapsed time
END_TIME=$(date +%s)
ELAPSED_TIME=$((END_TIME - START_TIME))

# Display results
if [ $success -eq 1 ]; then
    echo "Conversion completed successfully!"
else
    echo "Conversion completed with errors!"
fi
total_files=0
if [ ${#log_files[@]} -gt 0 ]; then
    echo "Details saved in the following log files:"
    for dir in "${!log_files[@]}"; do
        echo "  ${log_files[$dir]} (${file_counts[$dir]:-0} files converted)"
        ((total_files += ${file_counts[$dir]:-0}))
    done
    echo "Total files converted: $total_files"
    [ $overwritten -gt 0 ] && echo "Files overwritten: $overwritten"
    [ $skipped -gt 0 ] && echo "Files skipped: $skipped"
fi
[ "$ENABLE_LOUDNESS" = "true" ] && echo "Loudness measurements saved alongside each log.txt."
echo "Elapsed time: $ELAPSED_TIME seconds"

# Append completion message to logs
for log_file in "${log_files[@]}"; do
    echo "" >> "$log_file"
    echo "----------------------------------------" >> "$log_file"
    [ $success -eq 1 ] && echo "Conversion completed on $(date)" >> "$log_file" || echo "Conversion completed with errors on $(date)" >> "$log_file"
    echo "Elapsed time: $ELAPSED_TIME seconds" >> "$log_file"
done

# Clean up processed markers
find "$WORKING_DIR" -name ".processed" -delete