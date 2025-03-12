#!/bin/bash

# Configuração inicial
SCRIPT="./puretone.sh"  # Caminho do script puretone.sh
TEST_DIR="/mnt/Local/Container/B/Music/Stevie Wonder/DSD"  # Diretório com arquivos .dsf
TEMP_DIR="$HOME/Temp/test_dsd"  # Diretório temporário para testes
LOG_FILE="$HOME/Temp/test_puretone_results.log"  # Arquivo de log dos resultados

# Verifica se o script principal existe
if [ ! -x "$SCRIPT" ]; then
    echo "Erro: $SCRIPT não encontrado ou não é executável. Execute 'chmod +x $SCRIPT'."
    exit 1
fi

# Verifica se o diretório de teste existe
if [ ! -d "$TEST_DIR" ]; then
    echo "Erro: Diretório de teste $TEST_DIR não encontrado. Ajuste TEST_DIR no script."
    exit 1
fi

# Inicializa o log
echo "Resultados dos Testes - $(date)" > "$LOG_FILE"
echo "----------------------------------------" >> "$LOG_FILE"

# Função para verificar o resultado e registrar
check_result() {
    local test_name="$1"
    local condition="$2"
    local message="$3"
    if eval "$condition"; then
        echo "[$test_name] PASSOU: $message" | tee -a "$LOG_FILE"
    else
        echo "[$test_name] FALHOU: $message" | tee -a "$LOG_FILE"
        return 1
    fi
}

# Função para limpar diretórios temporários
cleanup() {
    echo "Limpando diretórios temporários..."
    rm -rf "$TEMP_DIR" "$TEMP_DIR"_no_perm "$TEMP_DIR"_empty
}

# Trap para limpeza em caso de interrupção
trap cleanup EXIT

# Teste 1: Conversão Básica para WAV
echo "Executando Teste 1: Conversão Básica para WAV"
rm -rf "$TEST_DIR"/*/wv  # Limpa saídas anteriores
output=$(yes y | "$SCRIPT" wav "$TEST_DIR" 2>&1)
echo "$output" > "$TEMP_DIR/test1_output.log"
check_result "Teste 1" "echo '$output' | grep -q 'Conversion completed successfully'" "Conversão concluída com sucesso"
check_result "Teste 1" "[ $(find "$TEST_DIR" -name '*.wav' | wc -l) -eq 30 ]" "30 arquivos WAV gerados"

# Teste 2: Conversão Paralela com 4 Jobs
echo "Executando Teste 2: Conversão Paralela com 4 Jobs"
rm -rf "$TEST_DIR"/*/wv
output=$(yes y | "$SCRIPT" wav --parallel 4 "$TEST_DIR" 2>&1)
echo "$output" > "$TEMP_DIR/test2_output.log"
check_result "Teste 2" "echo '$output' | grep -q 'Parallel jobs: 4'" "Paralelismo configurado para 4 jobs"
check_result "Teste 2" "[ $(find "$TEST_DIR" -name '*.wav' | wc -l) -eq 30 ]" "30 arquivos convertidos"

# Teste 3: Sobrescrita de Arquivos Existentes
echo "Executando Teste 3: Sobrescrita de Arquivos Existentes"
output=$(yes y | "$SCRIPT" wav --parallel 4 "$TEST_DIR" 2>&1)
echo "$output" > "$TEMP_DIR/test3_output.log"
check_result "Teste 3" "echo '$output' | grep -q 'Overwriting due to OVERWRITE=true'" "Mensagem de sobrescrita exibida"
check_result "Teste 3" "echo '$output' | grep -q 'Files overwritten: 30'" "30 arquivos sobrescritos"

# Teste 4: Pular Arquivos Existentes
echo "Executando Teste 4: Pular Arquivos Existentes"
output=$(yes y | "$SCRIPT" wav --skip-existing "$TEST_DIR" 2>&1)
echo "$output" > "$TEMP_DIR/test4_output.log"
check_result "Teste 4" "echo '$output' | grep -q 'Skipping conversion.*--skip-existing enabled'" "Mensagem de skip exibida"
check_result "Teste 4" "echo '$output' | grep -q 'Files skipped: 30'" "30 arquivos pulados"

# Teste 5: Conversão para FLAC
echo "Executando Teste 5: Conversão para FLAC"
rm -rf "$TEST_DIR"/*/flac
output=$(yes y | "$SCRIPT" flac --compression-level 8 --parallel 4 "$TEST_DIR" 2>&1)
echo "$output" > "$TEMP_DIR/test5_output.log"
check_result "Teste 5" "echo '$output' | grep -q 'Output format: flac'" "Formato FLAC configurado"
check_result "Teste 5" "[ $(find "$TEST_DIR" -name '*.flac' | wc -l) -eq 30 ]" "30 arquivos FLAC gerados"

# Teste 6: Geração de Espectrogramas
echo "Executando Teste 6: Geração de Espectrogramas"
rm -rf "$TEST_DIR"/*/wv
output=$(yes y | "$SCRIPT" wav --spectrogram 1920x1080 separate --parallel 4 "$TEST_DIR" 2>&1)
echo "$output" > "$TEMP_DIR/test6_output.log"
check_result "Teste 6" "echo '$output' | grep -q 'Spectrogram generation enabled: true'" "Geração de espectrogramas ativada"
check_result "Teste 6" "[ $(find "$TEST_DIR" -name '*.png' | wc -l) -eq 30 ]" "30 espectrogramas gerados"

# Teste 7: Mudança de Taxa de Amostragem
echo "Executando Teste 7: Mudança de Taxa de Amostragem"
rm -rf "$TEST_DIR"/*/wv
output=$(yes y | "$SCRIPT" wav --sample-rate 88200 "$TEST_DIR" 2>&1)
echo "$output" > "$TEMP_DIR/test7_output.log"
check_result "Teste 7" "echo '$output' | grep -q 'Sample rate (--sample-rate): 88200'" "Taxa de amostragem configurada para 88200"
check_result "Teste 7" "ffprobe -v quiet -show_entries stream=sample_rate -of default=noprint_wrappers=1:nokey=1 '$TEST_DIR/Innervisions/wv/01 Too High.wav' | grep -q 88200" "Arquivo WAV tem taxa de 88200 Hz"

# Teste 8: Tratamento de Erro (Diretório Sem Permissão)
echo "Executando Teste 8: Tratamento de Erro (Diretório Sem Permissão)"
mkdir -p "$TEMP_DIR"_no_perm/subdir
cp "$TEST_DIR/Innervisions/01 Too High.dsf" "$TEMP_DIR"_no_perm/subdir/
chmod -w "$TEMP_DIR"_no_perm/subdir
output=$(yes y | "$SCRIPT" wav "$TEMP_DIR"_no_perm/ 2>&1)
echo "$output" > "$TEMP_DIR/test8_output.log"
check_result "Teste 8" "echo '$output' | grep -q 'Error: Failed to create directory'" "Erro de criação de diretório detectado"
check_result "Teste 8" "echo '$output' | grep -q 'Conversion completed with errors'" "Conversão marcada como falha"
chmod +w "$TEMP_DIR"_no_perm/subdir  # Restaura permissão para limpeza

# Teste 9: Diretório Sem Arquivos .dsf
echo "Executando Teste 9: Diretório Sem Arquivos .dsf"
mkdir -p "$TEMP_DIR"_empty
output=$("$SCRIPT" wav "$TEMP_DIR"_empty/ 2>&1)
echo "$output" > "$TEMP_DIR/test9_output.log"
check_result "Teste 9" "echo '$output' | grep -q 'No .dsf files found'" "Mensagem de nenhum arquivo .dsf exibida"
check_result "Teste 9" "$SCRIPT wav '$TEMP_DIR'_empty/; [ $? -eq 1 ]" "Código de saída é 1"

# Teste 10: Exibição do Help
echo "Executando Teste 10: Exibição do Help"
output=$("$SCRIPT" --help 2>&1)
echo "$output" > "$TEMP_DIR/test10_output.log"
check_result "Teste 10" "echo '$output' | grep -q 'README: PureTone - DSD to High-Quality Audio Converter'" "Help exibido corretamente"

# Resumo
echo "----------------------------------------" | tee -a "$LOG_FILE"
echo "Resumo dos Testes:" | tee -a "$LOG_FILE"
grep -c "PASSOU" "$LOG_FILE" | awk '{print "Testes que passaram: " $1}' | tee -a "$LOG_FILE"
grep -c "FALHOU" "$LOG_FILE" | awk '{print "Testes que falharam: " $1}' | tee -a "$LOG_FILE"
echo "Detalhes salvos em $LOG_FILE"

# Limpeza manual (trap já cuida disso, mas reforçando)
cleanup