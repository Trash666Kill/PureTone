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

# Function to display README
show_help() {
    cat << 'EOF'
README: DSD to High-Quality Audio Converter

This script converts DSD (.dsf) audio files to WAV, WavPack, or FLAC formats, preserving maximum audio fidelity. It uses ffmpeg to process files in parallel with GNU Parallel, extract metadata, and apply automatic loudness normalization.

### How it Works
1. **Input**: Scans the current directory for .dsf files or subdirectories.
2. **Metadata Extraction**: Uses ffprobe to extract artist and album metadata.
3. **Conversion Flow**: Converts DSD to WAV, then to the final format, using parallel processing.
4. **Output**: Files are saved in 'wv/', 'wvpk/', or 'flac/' subdirectories.
5. **Logging**: Details saved in log.txt per directory.

### Usage
- Save as `conv.sh`, make executable: `chmod +x conv.sh`.
- Run: `./conv.sh [wav|wavpack|flac] [options]`
  - Examples:
    - `./conv.sh flac --loudnorm-I -14 --loudnorm-linear true`
    - `./conv.sh wavpack --skip-existing -compression_level 6`
    - `./conv.sh flac --parallel 4` (Process 4 files at once)

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
- `<format>`: wav, wavpack, flac.
- `-codec <value>`: Set ACODEC.
- `-sample_rate <value>`: Set AR.
- `-map_metadata <value>`: Set MAP_METADATA.
- `--loudnorm-I <value>`: Set integrated loudness (e.g., -14).
- `--loudnorm-TP <value>`: Set true peak (e.g., -2).
- `--loudnorm-LRA <value>`: Set loudness range (e.g., 9).
- `--loudnorm-linear <true|false>`: One-pass or two-pass loudnorm.
- `-loudness <true|false>`: Enable loudness analysis.
- `-compression_level <value>`: Compression for WavPack/FLAC.
- `--skip-existing`: Skip existing files.
- `--parallel <number>`: Set number of parallel jobs (e.g., 4).

### Notes
- Requires ffmpeg, ffprobe, and parallel (install with 'apt install parallel').
- Uses two-pass loudnorm by default for accuracy.
- Processes 2 files in parallel by default; adjustable with --parallel.
- Reports overwritten and skipped files.
EOF
    exit 0
}

# Check for --help
[ "$1" = "--help" ] && show_help

# Variables for tracking
SKIP_EXISTING="false"
declare -i overwritten=0 skipped=0

# Parse arguments
if [ $# -gt 0 ]; then
    case "$1" in
        "wav"|"wavpack"|"flac") OUTPUT_FORMAT="$1"; shift ;;
        *) if [[ "$1" != -* ]]; then echo "Error: Invalid format '$1'"; exit 1; fi ;;
    esac
    while [ $# -gt 0 ]; do
        case "$1" in
            -codec) ACODEC="$2"; shift 2 ;;
            -sample_rate) [[ "$2" =~ ^[0-9]+$ ]] && AR="$2" || { echo "Error: -sample_rate requires a number"; exit 1; }; shift 2 ;;
            -map_metadata) MAP_METADATA="$2"; shift 2 ;;
            --loudnorm-I) LOUDNORM_I="$2"; shift 2 ;;
            --loudnorm-TP) LOUDNORM_TP="$2"; shift 2 ;;
            --loudnorm-LRA) LOUDNORM_LRA="$2"; shift 2 ;;
            --loudnorm-linear) [[ "$2" =~ ^(true|false)$ ]] && LOUDNORM_LINEAR="$2" || { echo "Error: --loudnorm-linear requires true/false"; exit 1; }; shift 2 ;;
            -loudness) [[ "$2" =~ ^(true|false)$ ]] && ENABLE_LOUDNESS="$2" || { echo "Error: -loudness requires true/false"; exit 1; }; shift 2 ;;
            -compression_level)
                if [ "$OUTPUT_FORMAT" = "wavpack" ]; then
                    [[ "$2" =~ ^[0-6]$ ]] && WAVPACK_COMPRESSION="$2" || { echo "Error: WavPack compression 0-6"; exit 1; }
                elif [ "$OUTPUT_FORMAT" = "flac" ]; then
                    [[ "$2" =~ ^([0-9]|1[0-2])$ ]] && FLAC_COMPRESSION="$2" || { echo "Error: FLAC compression 0-12"; exit 1; }
                fi
                shift 2 ;;
            --skip-existing) SKIP_EXISTING="true"; shift ;;
            --parallel) [[ "$2" =~ ^[0-9]+$ ]] && PARALLEL_JOBS="$2" || { echo "Error: --parallel requires a number"; exit 1; }; shift 2 ;;
            *) echo "Error: Unknown option '$1'"; exit 1 ;;
        esac
    done
fi

# Adjust AF based on LOUDNORM_LINEAR
if [ "$LOUDNORM_LINEAR" = "true" ]; then
    AF="loudnorm=I=$LOUDNORM_I:TP=$LOUDNORM_TP:LRA=$LOUDNORM_LRA:linear=true"
else
    AF="loudnorm=I=$LOUDNORM_I:TP=$LOUDNORM_TP:LRA=$LOUDNORM_LRA"
fi

# Export variables for parallel
export ACODEC AR MAP_METADATA AF LOUDNORM_LINEAR ENABLE_LOUDNESS OUTPUT_FORMAT WAVPACK_COMPRESSION FLAC_COMPRESSION OVERWRITE SKIP_EXISTING

# Check dependencies
command -v ffmpeg >/dev/null || { echo "Error: ffmpeg not found. Install with 'apt install ffmpeg'."; exit 1; }
command -v ffprobe >/dev/null || { echo "Error: ffprobe not found."; exit 1; }
command -v parallel >/dev/null || { echo "Error: parallel not found. Install with 'apt install parallel'."; exit 1; }
echo "ffmpeg found. Version: $(ffmpeg -version | head -n 1)"
echo "parallel found. Version: $(parallel --version | head -n 1)"
echo "----------------------------------------"

# Record start time
START_TIME=$(date +%s)

# Set OUTPUT_BASE_DIR
case "$OUTPUT_FORMAT" in
    "wav") OUTPUT_BASE_DIR="wv" ;;
    "wavpack") OUTPUT_BASE_DIR="wvpk" ;;
    "flac") OUTPUT_BASE_DIR="flac" ;;
    *) echo "Error: Invalid OUTPUT_FORMAT"; exit 1 ;;
esac

# Display parameters
echo "Configured parameters:"
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
echo ""

# Function to process a single file
process_file() {
    local input_file="$1"
    local dir=$(dirname "$input_file")
    local OUTPUT_DIR="$dir/$OUTPUT_BASE_DIR"
    mkdir -p "$OUTPUT_DIR"

    # Extract metadata
    ARTIST=$(ffprobe -v quiet -show_entries format_tags=artist -of default=noprint_wrappers=1:nokey=1 "$input_file" 2>/dev/null || echo "Unknown Artist")
    ALBUM=$(ffprobe -v quiet -show_entries format_tags=album -of default=noprint_wrappers=1:nokey=1 "$input_file" 2>/dev/null || echo "Unknown Album")

    # Define file names
    base_name=$(basename "$input_file" .dsf)
    wav_temp_file="$OUTPUT_DIR/${base_name}_temp.wav"
    case "$OUTPUT_FORMAT" in
        "wav") output_file="$OUTPUT_DIR/${base_name}.wav" ;;
        "wavpack") output_file="$OUTPUT_DIR/${base_name}.wv" ;;
        "flac") output_file="$OUTPUT_DIR/${base_name}.flac" ;;
    esac

    # Check if output file exists
    if [ -e "$output_file" ]; then
        if [ "$SKIP_EXISTING" = "true" ]; then
            echo "File $output_file already exists. Skipping conversion of $input_file (--skip-existing enabled)."
            printf '%s\n' "skipped" > "/tmp/conv_$$_status_${base_name//[^a-zA-Z0-9]/_}"
            return
        elif [ "$OVERWRITE" = "true" ]; then
            echo "File $output_file already exists. Overwriting due to OVERWRITE=true."
            printf '%s\n' "overwritten" > "/tmp/conv_$$_status_${base_name//[^a-zA-Z0-9]/_}"
        fi
    fi

    log_file="$OUTPUT_DIR/log.txt"
    loudness_file="$OUTPUT_DIR/loudness.txt"

    # Clear log/loudness files only for the first file in this run (using lock file)
    if [ ! -f "$OUTPUT_DIR/.processed" ]; then
        > "$log_file"
        [ "$ENABLE_LOUDNESS" = "true" ] && > "$loudness_file"
        touch "$OUTPUT_DIR/.processed"
    fi

    # Measure original loudness if enabled
    if [ "$ENABLE_LOUDNESS" = "true" ]; then
        echo "Loudness of original file: $input_file" >> "$loudness_file"
        ffmpeg -i "$input_file" -af ebur128 -f null - 2>> "$loudness_file"
        echo "----------------------------------------" >> "$loudness_file"
    fi

    # Convert DSD to WAV with diagnostic output
    ffmpeg -i "$input_file" -acodec "$ACODEC" -ar "$AR" -map_metadata "$MAP_METADATA" -af "$AF" "$wav_temp_file" -y >> "$log_file" 2>&1
    if [ $? -ne 0 ]; then
        echo "Error converting $input_file to intermediate WAV" >&2
        echo "ffmpeg command failed: ffmpeg -i \"$input_file\" -acodec \"$ACODEC\" -ar \"$AR\" -map_metadata \"$MAP_METADATA\" -af \"$AF\" \"$wav_temp_file\" -y" >&2
        echo "Check $log_file for details" >&2
        rm -f "$wav_temp_file"
        printf '%s\n' "error" > "/tmp/conv_$$_status_${base_name//[^a-zA-Z0-9]/_}"
        return 1
    fi

    # Convert to final format
    case "$OUTPUT_FORMAT" in
        "wav") mv "$wav_temp_file" "$output_file" ;;
        "wavpack") ffmpeg -i "$wav_temp_file" -acodec wavpack -compression_level "$WAVPACK_COMPRESSION" "$output_file" -y >> "$log_file" 2>&1 ;;
        "flac") ffmpeg -i "$wav_temp_file" -acodec flac -compression_level "$FLAC_COMPRESSION" "$output_file" -y >> "$log_file" 2>&1 ;;
    esac
    if [ $? -ne 0 ]; then
        echo "Error converting $input_file to $OUTPUT_FORMAT" >&2
        rm -f "$wav_temp_file"
        printf '%s\n' "error" > "/tmp/conv_$$_status_${base_name//[^a-zA-Z0-9]/_}"
        return 1
    fi
    rm -f "$wav_temp_file"

    # Verify output integrity
    if [ ! -s "$output_file" ]; then
        echo "Error: $output_file is empty" >&2
        printf '%s\n' "error" > "/tmp/conv_$$_status_${base_name//[^a-zA-Z0-9]/_}"
        return 1
    fi

    echo "Converted: $input_file -> $output_file"
    printf '%s\n' "converted" > "/tmp/conv_$$_status_${base_name//[^a-zA-Z0-9]/_}"
    return 0

    # Measure converted loudness if enabled
    if [ "$ENABLE_LOUDNESS" = "true" ]; then
        echo "Loudness of converted file: $output_file" >> "$loudness_file"
        ffmpeg -i "$output_file" -af ebur128 -f null - 2>> "$loudness_file"
        echo "----------------------------------------" >> "$loudness_file"
    fi
}

# Export the function for parallel
export -f process_file

# Main logic
echo "Starting conversion..."
echo "----------------------------------------"

# Variables to track results
declare -A log_files file_counts
success=1

# Check for .dsf files in current directory
dsf_files_found=$(find . -maxdepth 1 -name "*.dsf" | wc -l)
if [ "$dsf_files_found" -gt 0 ]; then
    echo "Processing current directory..."
    find . -maxdepth 1 -name "*.dsf" | parallel -j "$PARALLEL_JOBS" --line-buffer process_file
else
    subdirs_with_dsf=$(find . -maxdepth 1 -type d -not -path . -exec sh -c 'find "{}" -maxdepth 1 -name "*.dsf" | grep -q . && echo "{}"' \; | sed 's|./||')
    if [ -n "$subdirs_with_dsf" ]; then
        echo "No .dsf files found in the current directory."
        echo "Subdirectories with .dsf files:"
        echo "$subdirs_with_dsf"
        echo -n "Convert all (a) or one by one (o)? (a/o): "
        read -r mode
        if [[ "$mode" =~ ^[Aa]$ ]]; then
            echo "Converting all subdirectories..."
            echo "$subdirs_with_dsf" | while IFS= read -r subdir; do
                echo "Processing subdirectory: $subdir"
                find "$subdir" -maxdepth 1 -name "*.dsf" | parallel -j "$PARALLEL_JOBS" --line-buffer process_file || success=0
            done
        elif [[ "$mode" =~ ^[Oo]$ ]]; then
            echo "$subdirs_with_dsf" | while IFS= read -r subdir; do
                echo -n "Convert $subdir? (y/n): "
                read -r response
                if [[ "$response" =~ ^[Yy]$ ]]; then
                    echo "Processing subdirectory: $subdir"
                    find "$subdir" -maxdepth 1 -name "*.dsf" | parallel -j "$PARALLEL_JOBS" --line-buffer process_file || success=0
                fi
            done
        else
            echo "Invalid option. Aborted."
            exit 0
        fi
    else
        echo "No .dsf files found."
        exit 1
    fi
fi

# Collect results from parallel processing
for file in /tmp/conv_$$_status_*; do
    [ -e "$file" ] || continue
    base_name=$(basename "$file" | sed 's/conv_.*_status_//')
    dir=$(find . -name "*.dsf" -exec dirname {} \; | grep "$base_name" | head -n 1)
    status=$(cat "$file")
    case "$status" in
        "converted") ((file_counts["$dir"]++)) ;;
        "overwritten") ((file_counts["$dir"]++)); ((overwritten++)) ;;
        "skipped") ((skipped++)) ;;
        "error") success=0 ;;
    esac
    log_files["$dir"]="$dir/$OUTPUT_BASE_DIR/log.txt"
    rm -f "$file"
done
rm -f /tmp/conv_$$_status_*

# Calculate elapsed time
END_TIME=$(date +%s)
ELAPSED_TIME=$((END_TIME - START_TIME))

# Display results
if [ $success -eq 1 ]; then
    echo "Conversion completed successfully!"
else
    echo "Conversion completed with errors!"
fi
if [ ${#log_files[@]} -gt 0 ]; then
    echo "Details saved in the following log files:"
    total_files=0
    for dir in "${!log_files[@]}"; do
        echo "  ${log_files[$dir]} (${file_counts[$dir]:-0} files converted)"
        ((total_files += file_counts[$dir]))
    done
    echo "Total files converted: $total_files"
    echo "Files overwritten: $overwritten"
    echo "Files skipped: $skipped"
else
    echo "No conversions performed."
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
find . -name ".processed" -delete