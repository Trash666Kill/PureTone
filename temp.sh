#!/bin/bash

# Configurable variables (defaults)
ACODEC="pcm_s24le"          # Audio codec for WAV intermediate file
AR="176400"                 # Sample rate
MAP_METADATA="0"            # Metadata mapping
LOUDNORM_I="-14"            # Integrated loudness target (LUFS)
LOUDNORM_TP="-1"            # True peak limit (dBTP)
LOUDNORM_LRA="20"           # Loudness range (LU)
VOLUME=""                   # Volume adjustment in dB (empty by default, overrides loudnorm if set)
RESAMPLER="soxr"            # Resampler engine (soxr = SoX Resampler, swr = FFmpeg's default)
PRECISION="28"              # Resampler precision (for soxr, 16-32 bits, 28 is very high quality)
CHEBY="1"                   # Enable Chebyshev mode for soxr (1 = yes, 0 = no)
AF_BASE="aresample=resampler=$RESAMPLER:precision=$PRECISION:cheby=$CHEBY"  # Base audio filter for resampling
OUTPUT_FORMAT="wav"         # Output format: wav, wavpack, or flac
WAVPACK_COMPRESSION="0"     # WavPack compression level (0-6)
FLAC_COMPRESSION="0"        # FLAC compression level (0-12)
OVERWRITE="true"            # Overwrite existing files by default (true/false)
PARALLEL_JOBS=2             # Number of parallel jobs (default: 2)
WORKING_DIR="$(pwd)"        # Default to current directory
ENABLE_VISUALIZATION="false"  # Enable visualization (waveform or spectrogram)
VISUALIZATION_TYPE="spectrogram"  # Default visualization type
VISUALIZATION_SIZE="1920x1080"    # Default visualization resolution
SPECTROGRAM_MODE="combined"       # Default spectrogram mode (combined or separate)

# Function to normalize paths (remove double slashes)
normalize_path() {
    echo "$1" | sed 's|//|/|g'
}

# Function to validate resolution format (e.g., "1920x1080")
validate_resolution() {
    if [[ "$1" =~ ^[0-9]+x[0-9]+$ ]]; then
        return 0
    else
        echo "Error: Visualization resolution must be in the format 'width x height' (e.g., 1920x1080)"
        exit 1
    fi
}

# Function to validate volume format (e.g., "3dB" or "-2.5dB")
validate_volume() {
    if [[ "$1" =~ ^[-+]?[0-9]*\.?[0-9]+dB$ ]]; then
        return 0
    else
        echo "Error: Volume must be in the format 'XdB' or '-X.XdB' (e.g., '3dB', '-2.5dB')"
        exit 1
    fi
}

# Function to display README
show_help() {
    cat << 'EOF'
README: PureTone - DSD to High-Quality Audio Converter

PureTone converts DSD (.dsf) audio files to WAV, WavPack, or FLAC formats using a two-pass loudness normalization process with ffmpeg and GNU Parallel for parallel processing.

### How it Works
1. **Input**: Accepts a single .dsf file or scans the specified/current directory for .dsf files or subdirectories.
2. **Two-Pass Conversion**:
   - Pass 1: Analyzes loudness metrics (I, LRA, TP, threshold) using ffmpeg with -f null (if using loudnorm).
   - Pass 2: Applies normalization or volume adjustment to generate the output file.
3. **Metadata Extraction**: Uses ffprobe to extract artist and album metadata.
4. **Output**: Files are saved in 'wv/', 'wvpk/', or 'flac/' subdirectories.
5. **Logging**: Details saved in log.txt per directory.
6. **Visualization (Optional)**: Generates waveform or spectrogram images if enabled.

### Usage
- Save as `puretone.sh`, make executable: `chmod +x puretone.sh`.
- Run: `./puretone.sh [format] [options] [path/to/directory | path/to/file.dsf]`
  - Examples:
    - `./puretone.sh wav /path/to/file.dsf`
    - `./puretone.sh wavpack --spectrogram 1920x1080 waveform --volume 3dB /path/to/music`
    - `./puretone.sh flac --loudnorm-I -14 --parallel 4 /path/to/music`

### Configurable Parameters
- **ACODEC**: Default: "pcm_s24le" (24-bit PCM).
- **AR**: Default: "176400" (176.4 kHz).
- **MAP_METADATA**: Default: "0" (copy all metadata).
- **LOUDNORM_I**: Integrated loudness (LUFS). Default: "-14".
- **LOUDNORM_TP**: True peak (dBTP). Default: "-1".
- **LOUDNORM_LRA**: Loudness range (LU). Default: "20".
- **VOLUME**: Volume adjustment (dB). Default: unset (uses loudnorm instead).
- **RESAMPLER**: Resampler engine. Default: "soxr".
- **PRECISION**: Resampler precision (for soxr). Default: "28".
- **CHEBY**: Chebyshev mode for soxr. Default: "1".
- **ENABLE_VISUALIZATION**: Visualization generation (true/false). Default: "false".
- **VISUALIZATION_TYPE**: "waveform" or "spectrogram". Default: "spectrogram".
- **VISUALIZATION_SIZE**: Visualization resolution. Default: "1920x1080".
- **SPECTROGRAM_MODE**: Spectrogram mode (combined/separate). Default: "combined".
- **OUTPUT_FORMAT**: "wav", "wavpack", "flac". Default: "wav".
- **WAVPACK_COMPRESSION**: 0-6. Default: "0".
- **FLAC_COMPRESSION**: 0-12. Default: "0".
- **OVERWRITE**: Overwrite files (true/false). Default: "true".
- **PARALLEL_JOBS**: Number of parallel jobs. Default: 2.

### Command-Line Options
- `<format>`: Output format: "wav", "wavpack", or "flac".
- `--codec <value>`: Set audio codec (e.g., "pcm_s24le").
- `--sample-rate <value>`: Set sample rate (e.g., "176400").
- `--map-metadata <value>`: Set metadata mapping (e.g., "0").
- `--loudnorm-I <value>`: Set integrated loudness (e.g., -14).
- `--loudnorm-TP <value>`: Set true peak (e.g., -2).
- `--loudnorm-LRA <value>`: Set loudness range (e.g., 20).
- `--volume <value>`: Set volume adjustment in dB (e.g., "3dB", overrides loudnorm).
- `--resampler <value>`: Set resampler engine (e.g., "soxr").
- `--precision <value>`: Set resampler precision (e.g., "28").
- `--cheby <0|1>`: Enable/disable Chebyshev mode (1 = yes, 0 = no).
- `--spectrogram [width x height] [type] [mode]`: Enable visualization (type: waveform or spectrogram; mode: combined or separate for spectrogram).
- `--compression-level <value>`: Compression level for WavPack/FLAC.
- `--skip-existing`: Skip existing output files.
- `--parallel <number>`: Set number of parallel jobs (e.g., 4).
- `--help`: Display this help message.
- `path/to/directory | path/to/file.dsf`: Path to process (last argument; required).
EOF
    exit 0
}

# Check if no arguments are provided
if [ $# -eq 0 ]; then
    echo "Error: No arguments provided. Please specify a format, options, or directory/file path."
    echo "Usage: $0 [format] [options] [path/to/directory | path/to/file.dsf]"
    echo "Run '$0 --help' for more information."
    exit 1
fi

# Check for --help
[ "$1" = "--help" ] && show_help

# Variables for tracking
SKIP_EXISTING="false"
declare -i overwritten=0 skipped=0
TEMP_LOG="/tmp/puretone_$$_results.log"
TEMP_SIZE_LOG="/tmp/puretone_$$_sizes.log"  # Temporary file to store size info
> "$TEMP_LOG"  # Initialize temporary log file
> "$TEMP_SIZE_LOG"  # Initialize temporary size log file

# Parse arguments (directory or file must be last)
args=("$@")
last_arg="${args[-1]}"

# Check if last argument is a file or directory
if [[ "$last_arg" =~ \.dsf$ ]] && [ -f "$last_arg" ]; then
    INPUT_FILE=$(realpath "$last_arg")  # Single file
    WORKING_DIR=$(dirname "$INPUT_FILE")  # File directory
    unset 'args[-1]'  # Remove file from args
elif [[ "$last_arg" =~ ^(/|./|../) ]] && [ -d "$last_arg" ]; then
    WORKING_DIR=$(realpath "$last_arg")  # Specified directory
    unset 'args[-1]'  # Remove directory from args
else
    WORKING_DIR="$(pwd)"  # Default to current directory
fi

# Parse remaining arguments
while [ ${#args[@]} -gt 0 ]; do
    arg="${args[0]}"
    case "$arg" in
        "wav"|"wavpack"|"flac")
            OUTPUT_FORMAT="$arg"
            ;;
        --codec) ACODEC="${args[1]}"; unset 'args[1]' ;;
        --sample-rate) [[ "${args[1]}" =~ ^[0-9]+$ ]] && AR="${args[1]}" || { echo "Error: --sample-rate requires a number"; exit 1; }; unset 'args[1]' ;;
        --map-metadata) MAP_METADATA="${args[1]}"; unset 'args[1]' ;;
        --loudnorm-I) LOUDNORM_I="${args[1]}"; unset 'args[1]' ;;
        --loudnorm-TP) LOUDNORM_TP="${args[1]}"; unset 'args[1]' ;;
        --loudnorm-LRA) LOUDNORM_LRA="${args[1]}"; unset 'args[1]' ;;
        --volume) validate_volume "${args[1]}"; VOLUME="${args[1]}"; unset 'args[1]' ;;
        --resampler) RESAMPLER="${args[1]}"; unset 'args[1]' ;;
        --precision) [[ "${args[1]}" =~ ^[0-9]+$ ]] && PRECISION="${args[1]}" || { echo "Error: --precision requires a number"; exit 1; }; unset 'args[1]' ;;
        --cheby) [[ "${args[1]}" =~ ^[0-1]$ ]] && CHEBY="${args[1]}" || { echo "Error: --cheby requires 0 or 1"; exit 1; }; unset 'args[1]' ;;
        --spectrogram)
            ENABLE_VISUALIZATION="true"
            if [ ${#args[@]} -gt 1 ] && [[ "${args[1]}" =~ ^[0-9]+x[0-9]+$ ]]; then
                validate_resolution "${args[1]}"
                VISUALIZATION_SIZE="${args[1]}"
                unset 'args[1]'
                if [ ${#args[@]} -gt 1 ]; then
                    case "${args[1]}" in
                        "waveform")
                            VISUALIZATION_TYPE="waveform"
                            unset 'args[1]'
                            ;;
                        "spectrogram")
                            VISUALIZATION_TYPE="spectrogram"
                            unset 'args[1]'
                            if [ ${#args[@]} -gt 1 ]; then
                                case "${args[2]}" in
                                    "combined"|"separate")
                                        SPECTROGRAM_MODE="${args[2]}"
                                        unset 'args[2]'
                                        ;;
                                    *)
                                        echo "Error: Invalid spectrogram mode '${args[2]}'. Valid options: combined, separate"
                                        exit 1
                                        ;;
                                esac
                            fi
                            ;;
                        *)
                            echo "Error: Invalid visualization type '${args[1]}'. Use 'waveform' or 'spectrogram' (optional: followed by 'combined' or 'separate' for spectrogram)"
                            exit 1
                            ;;
                    esac
                fi
            fi
            ;;
        --compression-level)
            if [ "$OUTPUT_FORMAT" = "wav" ]; then
                echo "Warning: --compression-level not applicable to WAV format."
                unset 'args[1]'
            elif [ "$OUTPUT_FORMAT" = "wavpack" ]; then
                [[ "${args[1]}" =~ ^[0-6]$ ]] && WAVPACK_COMPRESSION="${args[1]}" || { echo "Error: WavPack compression 0-6"; exit 1; }
                unset 'args[1]'
            elif [ "$OUTPUT_FORMAT" = "flac" ]; then
                [[ "${args[1]}" =~ ^([0-9]|1[0-2])$ ]] && FLAC_COMPRESSION="${args[1]}" || { echo "Error: FLAC compression 0-12"; exit 1; }
                unset 'args[1]'
            fi
            ;;
        --skip-existing) SKIP_EXISTING="true" ;;
        --parallel) [[ "${args[1]}" =~ ^[0-9]+$ ]] && PARALLEL_JOBS="${args[1]}" || { echo "Error: --parallel requires a number"; exit 1; }; unset 'args[1]' ;;
        *) echo "Error: Unknown option or invalid format '$arg'. Directory or file must be the last argument."; exit 1 ;;
    esac
    unset 'args[0]'
    args=("${args[@]}")  # Reindex array
done

# Check if AR is a multiple of 44100 Hz
if [ $((AR % 44100)) -ne 0 ]; then
    remainder=$((AR % 44100))
    quotient=$(echo "scale=4; $AR / 44100" | bc)
    echo "Warning: Sample rate $AR Hz is not an exact multiple of 44.1 kHz. This may introduce interpolation."
    echo "Calculation: $AR / 44100 = $quotient (remainder: $remainder)."
    echo "Recommended values: 44100, 88200, 176400, 352800, 705600"
fi

# Set OUTPUT_BASE_DIR
case "$OUTPUT_FORMAT" in
    "wav") OUTPUT_BASE_DIR="wv" ;;
    "wavpack") OUTPUT_BASE_DIR="wvpk" ;;
    "flac") OUTPUT_BASE_DIR="flac" ;;
    *) echo "Error: Invalid OUTPUT_FORMAT"; exit 1 ;;
esac

# Export variables for parallel
export ACODEC AR MAP_METADATA LOUDNORM_I LOUDNORM_TP LOUDNORM_LRA VOLUME RESAMPLER PRECISION CHEBY AF_BASE OUTPUT_FORMAT WAVPACK_COMPRESSION FLAC_COMPRESSION OVERWRITE SKIP_EXISTING OUTPUT_BASE_DIR TEMP_LOG TEMP_SIZE_LOG WORKING_DIR ENABLE_VISUALIZATION VISUALIZATION_TYPE VISUALIZATION_SIZE SPECTROGRAM_MODE

# Check dependencies
command -v ffmpeg >/dev/null || { echo "Error: ffmpeg not found. Install with 'apt install ffmpeg'."; exit 1; }
command -v ffprobe >/dev/null || { echo "Error: ffprobe not found."; exit 1; }
command -v parallel >/dev/null || { echo "Error: parallel not found. Install with 'apt install parallel'."; exit 1; }
command -v bc >/dev/null || { echo "Error: bc not found. Install with 'apt install bc'."; exit 1; }
echo "ffmpeg found. Version: $(ffmpeg -version | head -n 1)"
echo "parallel found. Version: $(parallel --version | head -n 1)"
echo "----------------------------------------"

# Record start time
START_TIME=$(date +%s)

# Display parameters
echo "Configured parameters:"
echo "  Working directory: $WORKING_DIR"
echo "  Audio codec (--codec): $ACODEC"
echo "  Sample rate (--sample-rate): $AR"
echo "  Metadata mapping (--map-metadata): $MAP_METADATA"
if [ -n "$VOLUME" ]; then
    echo "  Volume adjustment (--volume): $VOLUME"
else
    echo "  Loudnorm I (--loudnorm-I): $LOUDNORM_I"
    echo "  Loudnorm TP (--loudnorm-TP): $LOUDNORM_TP"
    echo "  Loudnorm LRA (--loudnorm-LRA): $LOUDNORM_LRA"
fi
echo "  Resampler: $RESAMPLER (precision: $PRECISION, Chebyshev: $CHEBY)"
echo "  Base output directory: $OUTPUT_BASE_DIR"
echo "  Visualization enabled: $ENABLE_VISUALIZATION"
[ "$ENABLE_VISUALIZATION" = "true" ] && echo "  Visualization type: $VISUALIZATION_TYPE"
[ "$ENABLE_VISUALIZATION" = "true" ] && echo "  Visualization resolution: $VISUALIZATION_SIZE"
[ "$ENABLE_VISUALIZATION" = "true" ] && [ "$VISUALIZATION_TYPE" = "spectrogram" ] && echo "  Spectrogram mode: $SPECTROGRAM_MODE"
echo "  Output format: $OUTPUT_FORMAT"
echo "  Overwrite existing files: $OVERWRITE (overridden by --skip-existing: $SKIP_EXISTING)"
echo "  Parallel jobs: $PARALLEL_JOBS"
case "$OUTPUT_FORMAT" in
    "wavpack") echo "  WavPack compression level: $WAVPACK_COMPRESSION" ;;
    "flac") echo "  FLAC compression level: $FLAC_COMPRESSION" ;;
esac
echo ""

# Display FFmpeg commands for each pass
echo "FFmpeg commands used for conversion:"
if [ -n "$VOLUME" ]; then
    echo "  Single Pass (Volume Adjustment and Conversion):"
    case "$OUTPUT_FORMAT" in
        "wav")
            echo "    ffmpeg -i <input_file> -acodec $ACODEC -ar $AR -map_metadata $MAP_METADATA -af '$AF_BASE,volume=$VOLUME' <output_dir>/\${base_name}.wav -y"
            ;;
        "wavpack")
            echo "    ffmpeg -i <input_file> -acodec $ACODEC -ar $AR -map_metadata $MAP_METADATA -af '$AF_BASE,volume=$VOLUME' <output_dir>/\${base_name}_intermediate.wav -y"
            echo "    ffmpeg -i <output_dir>/\${base_name}_intermediate.wav -acodec wavpack -compression_level $WAVPACK_COMPRESSION <output_dir>/\${base_name}.wv -y"
            ;;
        "flac")
            echo "    ffmpeg -i <input_file> -acodec $ACODEC -ar $AR -map_metadata $MAP_METADATA -af '$AF_BASE,volume=$VOLUME' <output_dir>/\${base_name}_intermediate.wav -y"
            echo "    ffmpeg -i <output_dir>/\${base_name}_intermediate.wav -acodec flac -compression_level $FLAC_COMPRESSION <output_dir>/\${base_name}.flac -y"
            ;;
    esac
else
    echo "  First Pass (Loudness Analysis):"
    echo "    ffmpeg -i <input_file> -acodec $ACODEC -ar $AR -map_metadata $MAP_METADATA -af '$AF_BASE,loudnorm=I=$LOUDNORM_I:TP=$LOUDNORM_TP:LRA=$LOUDNORM_LRA:print_format=summary' -f null -"
    echo "  Second Pass (Normalization and Conversion):"
    case "$OUTPUT_FORMAT" in
        "wav")
            echo "    ffmpeg -i <input_file> -acodec $ACODEC -ar $AR -map_metadata $MAP_METADATA -af '<measured_values>' <output_dir>/\${base_name}.wav -y"
            ;;
        "wavpack")
            echo "    ffmpeg -i <input_file> -acodec $ACODEC -ar $AR -map_metadata $MAP_METADATA -af '<measured_values>' <output_dir>/\${base_name}_intermediate.wav -y"
            echo "    ffmpeg -i <output_dir>/\${base_name}_intermediate.wav -acodec wavpack -compression_level $WAVPACK_COMPRESSION <output_dir>/\${base_name}.wv -y"
            ;;
        "flac")
            echo "    ffmpeg -i <input_file> -acodec $ACODEC -ar $AR -map_metadata $MAP_METADATA -af '<measured_values>' <output_dir>/\${base_name}_intermediate.wav -y"
            echo "    ffmpeg -i <output_dir>/\${base_name}_intermediate.wav -acodec flac -compression_level $FLAC_COMPRESSION <output_dir>/\${base_name}.flac -y"
            ;;
    esac
    echo "  Note: '<measured_values>' in the second pass includes measured_I, measured_LRA, measured_TP, and measured_thresh extracted from the first pass."
fi
echo "  Note: '\${base_name}' is derived from the input file name without the .dsf extension."
echo ""

# Function to process a single file
process_file() {
    local input_file="$1"
    local dir=$(dirname "$input_file")
    local OUTPUT_DIR=$(normalize_path "$dir/$OUTPUT_BASE_DIR")
    local SPECTROGRAM_DIR=$(normalize_path "$OUTPUT_DIR/spectrogram")

    # Create OUTPUT_DIR
    if ! mkdir -p "$OUTPUT_DIR"; then
        echo "Error: Failed to create directory $OUTPUT_DIR" >&2
        echo "$dir:error" >> "$TEMP_LOG"
        return 1
    fi

    # Create SPECTROGRAM_DIR if visualization is enabled
    if [ "$ENABLE_VISUALIZATION" = "true" ]; then
        if ! mkdir -p "$SPECTROGRAM_DIR"; then
            echo "Error: Failed to create directory $SPECTROGRAM_DIR" >&2
            echo "$dir:error" >> "$TEMP_LOG"
            return 1
        fi
    fi

    # Extract metadata
    ARTIST=$(ffprobe -v quiet -show_entries format_tags=artist -of default=noprint_wrappers=1:nokey=1 "$input_file" 2>/dev/null || echo "Unknown Artist")
    ALBUM=$(ffprobe -v quiet -show_entries format_tags=album -of default=noprint_wrappers=1:nokey=1 "$input_file" 2>/dev/null || echo "Unknown Album")

    # Define file names with absolute paths
    base_name=$(basename "$input_file" .dsf)
    wav_intermediate_file=$(normalize_path "$OUTPUT_DIR/${base_name}_intermediate.wav")
    case "$OUTPUT_FORMAT" in
        "wav") output_file=$(normalize_path "$OUTPUT_DIR/$base_name.wav") ;;
        "wavpack") output_file=$(normalize_path "$OUTPUT_DIR/$base_name.wv") ;;
        "flac") output_file=$(normalize_path "$OUTPUT_DIR/$base_name.flac") ;;
    esac
    visualization_file=$(normalize_path "$SPECTROGRAM_DIR/$base_name.png")
    log_file=$(normalize_path "$OUTPUT_DIR/log.txt")

    # Check if output file exists
    if [ -e "$output_file" ]; then
        if [ "$SKIP_EXISTING" = "true" ]; then
            echo "File $output_file already exists. Skipping conversion of $input_file (--skip-existing enabled)."
            echo "$dir:skipped" >> "$TEMP_LOG"
            return 0
        elif [ "$OVERWRITE" = "true" ]; then
            echo "File $output_file already exists. Overwriting due to OVERWRITE=true."
            echo "$dir:overwritten" >> "$TEMP_LOG"
        fi
    else
        echo "$dir:converted" >> "$TEMP_LOG"
    fi

    # Clear log file only for the first file in this run
    if [ ! -f "$OUTPUT_DIR/.processed" ]; then
        > "$log_file" || { echo "Error: Cannot write to $log_file" >&2; echo "$dir:error" >> "$TEMP_LOG"; return 1; }
        touch "$OUTPUT_DIR/.processed"
    fi

    if [ -n "$VOLUME" ]; then
        # Single pass with volume adjustment
        local af_pass="$AF_BASE,volume=$VOLUME"
        ffmpeg -i "$input_file" -acodec "$ACODEC" -ar "$AR" -map_metadata "$MAP_METADATA" -af "$af_pass" "$wav_intermediate_file" -y >> "$log_file" 2>&1
        if [ $? -ne 0 ]; then
            echo "Error applying volume adjustment to $input_file" >&2
            echo "Check $log_file for details" >&2
            rm -f "$wav_intermediate_file"
            echo "$dir:error" >> "$TEMP_LOG"
            return 1
        fi
    else
        # First pass: Analyze loudness metrics
        local af_first_pass="$AF_BASE,loudnorm=I=$LOUDNORM_I:TP=$LOUDNORM_TP:LRA=$LOUDNORM_LRA:print_format=summary"
        ffmpeg -i "$input_file" -acodec "$ACODEC" -ar "$AR" -map_metadata "$MAP_METADATA" -af "$af_first_pass" -f null - >> "$log_file" 2>&1
        if [ $? -ne 0 ]; then
            echo "Error analyzing loudness for $input_file" >&2
            echo "Check $log_file for details" >&2
            echo "$dir:error" >> "$TEMP_LOG"
            return 1
        fi

        # Extract measured values from log
        measured_I=$(grep "Input Integrated:" "$log_file" | tail -1 | sed 's/.*: *\([-0-9.]*\).*/\1/')
        measured_LRA=$(grep "Input LRA:" "$log_file" | tail -1 | sed 's/.*: *\([0-9.]*\).*/\1/')
        measured_TP=$(grep "Input True Peak:" "$log_file" | tail -1 | sed 's/.*: *\([-0-9.]*\).*/\1/')
        measured_thresh=$(grep "Input Threshold:" "$log_file" | tail -1 | sed 's/.*: *\([-0-9.]*\).*/\1/')

        # Check if metrics were extracted successfully
        if [ -z "$measured_I" ] || [ -z "$measured_LRA" ] || [ -z "$measured_TP" ] || [ -z "$measured_thresh" ]; then
            echo "Error: Failed to extract loudness metrics for $input_file" >&2
            echo "Check $log_file for details" >&2
            echo "$dir:error" >> "$TEMP_LOG"
            return 1
        fi

        # Second pass: Apply normalization with measured values
        local af_second_pass="$AF_BASE,loudnorm=I=$LOUDNORM_I:TP=$LOUDNORM_TP:LRA=$LOUDNORM_LRA:measured_I=$measured_I:measured_LRA=$measured_LRA:measured_TP=$measured_TP:measured_thresh=$measured_thresh"
        ffmpeg -i "$input_file" -acodec "$ACODEC" -ar "$AR" -map_metadata "$MAP_METADATA" -af "$af_second_pass" "$wav_intermediate_file" -y >> "$log_file" 2>&1
        if [ $? -ne 0 ]; then
            echo "Error converting $input_file to intermediate WAV" >&2
            echo "Check $log_file for details" >&2
            rm -f "$wav_intermediate_file"
            echo "$dir:error" >> "$TEMP_LOG"
            return 1
        fi
    fi

    # Calculate intermediate WAV size in MiB
    intermediate_size=$(stat -c %s "$wav_intermediate_file" 2>/dev/null || echo 0)
    intermediate_mib=$(echo "scale=2; $intermediate_size / 1048576" | bc)

    # Convert to final format
    case "$OUTPUT_FORMAT" in
        "wav") mv "$wav_intermediate_file" "$output_file" || { echo "Error moving $wav_intermediate_file to $output_file" >&2; echo "$dir:error" >> "$TEMP_LOG"; return 1; } ;;
        "wavpack") ffmpeg -i "$wav_intermediate_file" -acodec wavpack -compression_level "$WAVPACK_COMPRESSION" "$output_file" -y >> "$log_file" 2>&1 ;;
        "flac") ffmpeg -i "$wav_intermediate_file" -acodec flac -compression_level "$FLAC_COMPRESSION" "$output_file" -y >> "$log_file" 2>&1 ;;
    esac
    if [ $? -ne 0 ]; then
        echo "Error converting $input_file to $OUTPUT_FORMAT" >&2
        rm -f "$wav_intermediate_file"
        echo "$dir:error" >> "$TEMP_LOG"
        return 1
    fi

    # Calculate sizes in MiB and store in temporary size log
    input_size=$(stat -c %s "$input_file" 2>/dev/null || echo 0)
    output_size=$(stat -c %s "$output_file" 2>/dev/null || echo 0)
    input_mib=$(echo "scale=2; $input_size / 1048576" | bc)
    output_mib=$(echo "scale=2; $output_size / 1048576" | bc)
    if [ "$input_size" -gt 0 ] && [ "$output_size" -gt 0 ] && [ "$intermediate_size" -gt 0 ]; then
        diff_percent=$(echo "scale=2; (($output_mib - $input_mib) / $input_mib) * 100" | bc)
        echo "$input_file:$input_mib:$wav_intermediate_file:$intermediate_mib:$output_file:$output_mib:$diff_percent" >> "$TEMP_SIZE_LOG"
    fi

    # Remove intermediate file
    rm -f "$wav_intermediate_file"

    # Verify output integrity
    if [ ! -s "$output_file" ]; then
        echo "Error: $output_file is empty" >&2
        echo "$dir:error" >> "$TEMP_LOG"
        return 1
    fi

    # Generate visualization if enabled
    if [ "$ENABLE_VISUALIZATION" = "true" ]; then
        if [ "$VISUALIZATION_TYPE" = "waveform" ]; then
            ffmpeg -i "$output_file" -filter_complex "showwavespic=s=$VISUALIZATION_SIZE" "$visualization_file" -y >> "$log_file" 2>&1
        else  # spectrogram
            ffmpeg -i "$output_file" -lavfi "showspectrumpic=s=$VISUALIZATION_SIZE:mode=$SPECTROGRAM_MODE" "$visualization_file" -y >> "$log_file" 2>&1
        fi
        if [ $? -ne 0 ]; then
            echo "Error generating $VISUALIZATION_TYPE for $output_file" >&2
            echo "Check $log_file for details" >&2
            echo "$dir:error" >> "$TEMP_LOG"
            return 1
        fi
        echo "Generated $VISUALIZATION_TYPE: $visualization_file"
    fi

    echo "Converted: $input_file -> $output_file"
    return 0
}

# Cleanup function for interruption
cleanup() {
    echo "Script interrupted. Cleaning up temporary files..."
    find "$WORKING_DIR" -name "*_intermediate.wav" -delete
    rm -f "$TEMP_LOG" "$TEMP_SIZE_LOG"
    exit 1
}
trap cleanup INT TERM

# Export the function for parallel
export -f process_file normalize_path validate_volume

# Change to the working directory
cd "$WORKING_DIR" || { echo "Error: Cannot change to directory $WORKING_DIR"; exit 1; }

# Main logic
echo "Starting conversion..."
echo "----------------------------------------"

# Variables to track results
declare -A log_files file_counts
success=1

# If INPUT_FILE is set, process only that file
if [ -n "$INPUT_FILE" ]; then
    echo "Processing single file: $INPUT_FILE"
    process_file "$INPUT_FILE" || success=0
else
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
                    rm -f "$TEMP_LOG" "$TEMP_SIZE_LOG"
                    exit 0
                    ;;
                *)
                    echo "Invalid response. Aborting conversion."
                    rm -f "$TEMP_LOG" "$TEMP_SIZE_LOG"
                    exit 1
                    ;;
            esac
        else
            echo "No .dsf files found in $WORKING_DIR or its subdirectories."
            rm -f "$TEMP_LOG" "$TEMP_SIZE_LOG"
            exit 1
        fi
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
[ "$ENABLE_VISUALIZATION" = "true" ] && echo "Visualizations saved in each output directory under spectrogram/."

echo "Elapsed time: $ELAPSED_TIME seconds"

# Display file sizes and differences
if [ -s "$TEMP_SIZE_LOG" ]; then
    echo ""
    echo "File sizes and differences:"
    while IFS=':' read -r input_file input_mib wav_intermediate_file intermediate_mib output_file output_mib diff_percent; do
        intermediate_display_name=$(echo "$wav_intermediate_file" | sed 's/_intermediate//')
        echo "  Input: $input_file - $input_mib MiB"
        echo "  Intermediate WAV: $intermediate_display_name - $intermediate_mib MiB"
        echo "  Output: $output_file - $output_mib MiB"
        echo "  Size difference (Output vs Input): $diff_percent%"
        echo ""
    done < "$TEMP_SIZE_LOG"
    rm -f "$TEMP_SIZE_LOG"
fi

# Append completion message to logs
for log_file in "${log_files[@]}"; do
    echo "" >> "$log_file"
    echo "----------------------------------------" >> "$log_file"
    [ $success -eq 1 ] && echo "Conversion completed on $(date)" >> "$log_file" || echo "Conversion completed with errors on $(date)" >> "$log_file"
    echo "Elapsed time: $ELAPSED_TIME seconds" >> "$log_file"
done

# Clean up processed markers
find "$WORKING_DIR" -name ".processed" -delete