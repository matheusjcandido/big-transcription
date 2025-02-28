import streamlit as st
import os
import tempfile
import time
from openai import OpenAI
from dotenv import load_dotenv
from pydub import AudioSegment
import math

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

# Configurações do aplicativo
st.set_page_config(
    page_title="Transcritor de Áudio",
    page_icon="🎤",
    layout="wide"
)

# Constantes
MAX_UPLOAD_SIZE_MB = 200
MAX_SEGMENT_SIZE_MB = 25
BYTES_PER_MB = 1024 * 1024

# Título e descrição
st.title("🎤 Transcritor de Áudio")
st.markdown(f"""
    Faça upload de arquivos de áudio de até {MAX_UPLOAD_SIZE_MB}MB e obtenha sua transcrição completa.
    O arquivo será automaticamente dividido em segmentos menores para processamento.
""")

# Obter a chave API do ambiente ou permitir entrada manual
default_api_key = os.getenv("OPENAI_API_KEY", "")

# Se estiver no modo produção e a chave existir no ambiente, use-a diretamente
if default_api_key and os.getenv("STREAMLIT_DEPLOYMENT", "") == "production":
    api_key = default_api_key
    st.success("Chave API configurada via variável de ambiente.")
else:
    # Caso contrário, permita que o usuário insira
    api_key = st.text_input("Insira sua chave API OpenAI", 
                           value=default_api_key,
                           type="password")

# Verificar se a chave API está configurada
if not api_key:
    st.warning("⚠️ Você precisa configurar uma chave API da OpenAI para usar este aplicativo.")
    st.info("💡 A chave API pode ser configurada via variável de ambiente ou inserida no campo acima.")
    st.stop()

# Upload de arquivo
uploaded_file = st.file_uploader(
    f"Escolha um arquivo de áudio (até {MAX_UPLOAD_SIZE_MB}MB)", 
    type=["mp3", "wav", "ogg"]  # Removido m4a e flac para evitar problemas de compatibilidade
)

# Opções para idioma de transcrição
idioma = st.selectbox(
    "Selecione o idioma da transcrição",
    options=["pt", "en", "es", "fr", "de", "it", "ja", "ko", "zh"],
    index=0
)

# Configurar pydub para usar formato de saída adequado
# Este é um truque para evitar problemas com formatos não suportados
AudioSegment.converter = "ffmpeg"
AudioSegment.ffmpeg = "ffmpeg"
AudioSegment.ffprobe = "ffprobe"

# Função para dividir o arquivo de áudio em segmentos
def split_audio_file(file_path, segment_size_mb=MAX_SEGMENT_SIZE_MB):
    """
    Divide um arquivo de áudio em segmentos menores
    
    Args:
        file_path: Caminho para o arquivo de áudio
        segment_size_mb: Tamanho máximo de cada segmento em MB
        
    Returns:
        Lista de caminhos para os arquivos de segmento
    """
    # Determinar o formato do arquivo
    file_format = file_path.split(".")[-1].lower()
    
    # Verificar formato suportado
    supported_formats = ["mp3", "wav", "ogg"]
    if file_format not in supported_formats:
        raise ValueError(f"Formato não suportado: {file_format}. Use mp3, wav ou ogg.")
    
    # Formato seguro para saída (sempre wav para melhor compatibilidade)
    safe_output_format = "wav"
    
    try:
        # Carregar o arquivo de áudio
        if file_format == "mp3":
            audio = AudioSegment.from_mp3(file_path)
        elif file_format == "wav":
            audio = AudioSegment.from_wav(file_path)
        elif file_format == "ogg":
            audio = AudioSegment.from_ogg(file_path)
        else:
            # Caso genérico (não deve ocorrer devido à verificação acima)
            audio = AudioSegment.from_file(file_path)
    except Exception as e:
        raise ValueError(f"Erro ao processar arquivo de áudio: {str(e)}")
    
    # Calcular o número de segmentos necessários
    duration_ms = len(audio)
    # Estimativa aproximada: 1 minuto de áudio = ~1MB (varia muito com qualidade)
    bytes_per_ms = os.path.getsize(file_path) / duration_ms
    segment_size_ms = int((segment_size_mb * BYTES_PER_MB) / bytes_per_ms)
    
    # Ajustar para garantir que não excedemos o limite
    segment_size_ms = min(segment_size_ms, duration_ms)
    
    # Criar lista para armazenar caminhos dos segmentos
    segment_paths = []
    
    # Dividir o áudio em segmentos
    segments_count = math.ceil(duration_ms / segment_size_ms)
    
    for i in range(segments_count):
        start_ms = i * segment_size_ms
        end_ms = min((i + 1) * segment_size_ms, duration_ms)
        
        segment = audio[start_ms:end_ms]
        segment_path = f"{file_path}_segment_{i}.{safe_output_format}"
        
        # Exportar segmento como WAV (formato mais seguro)
        segment.export(segment_path, format=safe_output_format)
        segment_paths.append(segment_path)
    
    return segment_paths

# Função para transcrever um segmento
def transcribe_segment(segment_path, client, language):
    """
    Transcreve um segmento de áudio usando a API OpenAI
    
    Args:
        segment_path: Caminho para o arquivo de segmento
        client: Cliente OpenAI inicializado
        language: Código do idioma
        
    Returns:
        Texto transcrito
    """
    with open(segment_path, "rb") as audio_file:
        try:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language=language
            )
            return transcript.text
        except Exception as e:
            st.error(f"Erro ao transcrever segmento {segment_path}: {str(e)}")
            return ""  # Retornar string vazia em caso de erro para não interromper todo o processo

# Quando o usuário clicar no botão de transcrição
if st.button("Transcrever") and uploaded_file is not None:
    # Verificar o tamanho do arquivo
    file_size_mb = uploaded_file.size / BYTES_PER_MB
    
    if file_size_mb > MAX_UPLOAD_SIZE_MB:
        st.error(f"O arquivo é muito grande! O tamanho máximo permitido é {MAX_UPLOAD_SIZE_MB}MB.")
        st.stop()
    
    # Criar uma barra de progresso
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        # Configurar cliente OpenAI
        client = OpenAI(api_key=api_key)
        
        # Criar diretório temporário para os arquivos
        with tempfile.TemporaryDirectory() as temp_dir:
            # Salvar o arquivo temporariamente
            temp_file_path = os.path.join(temp_dir, uploaded_file.name)
            with open(temp_file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            status_text.text("Analisando arquivo de áudio...")
            
            # Verificar se é um formato de arquivo suportado
            file_format = os.path.splitext(temp_file_path)[1].lower()[1:]
            supported_formats = ["mp3", "wav", "ogg"]
            if file_format not in supported_formats:
                st.error(f"Formato não suportado: {file_format}. Use mp3, wav ou ogg.")
                st.stop()
            
            # Se o arquivo for menor que o limite da API, processar diretamente
            if file_size_mb <= MAX_SEGMENT_SIZE_MB:
                status_text.text("Transcrevendo arquivo (único segmento)...")
                progress_bar.progress(0.2)
                
                with open(temp_file_path, "rb") as audio_file:
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language=idioma
                    )
                
                full_transcript = transcript.text
                progress_bar.progress(1.0)
            else:
                # Dividir o arquivo em segmentos
                status_text.text("Dividindo arquivo em segmentos...")
                progress_bar.progress(0.1)
                
                try:
                    segment_paths = split_audio_file(temp_file_path)
                    total_segments = len(segment_paths)
                    
                    status_text.text(f"Arquivo dividido em {total_segments} segmentos. Iniciando transcrição...")
                    
                    # Transcrever cada segmento
                    full_transcript = ""
                    for i, segment_path in enumerate(segment_paths):
                        progress_percent = 0.1 + (i / total_segments) * 0.8
                        progress_bar.progress(progress_percent)
                        status_text.text(f"Transcrevendo segmento {i+1} de {total_segments}...")
                        
                        segment_transcript = transcribe_segment(segment_path, client, idioma)
                        full_transcript += segment_transcript + " "
                        
                        # Remover arquivo do segmento
                        try:
                            os.remove(segment_path)
                        except:
                            pass  # Ignorar erros na remoção
                    
                    progress_bar.progress(0.9)
                    status_text.text("Finalizando transcrição...")
                    time.sleep(1)  # Pequena pausa para UX
                except Exception as e:
                    st.error(f"Erro ao processar os segmentos: {str(e)}")
                    st.info("Tentando método alternativo...")
                    
                    # Método alternativo: usar a biblioteca diretamente para criar segmentos menores
                    try:
                        sound = AudioSegment.from_file(temp_file_path)
                        duration_ms = len(sound)
                        
                        # Dividir em segmentos de aproximadamente 5 minutos (menos que 25MB)
                        segment_length_ms = 5 * 60 * 1000  # 5 minutos em ms
                        segments_count = math.ceil(duration_ms / segment_length_ms)
                        
                        full_transcript = ""
                        for i in range(segments_count):
                            start_ms = i * segment_length_ms
                            end_ms = min((i + 1) * segment_length_ms, duration_ms)
                            
                            segment = sound[start_ms:end_ms]
                            temp_segment_path = os.path.join(temp_dir, f"segment_{i}.wav")
                            
                            progress_percent = 0.1 + (i / segments_count) * 0.4
                            progress_bar.progress(progress_percent)
                            status_text.text(f"Criando segmento alternativo {i+1} de {segments_count}...")
                            
                            # Exportar como WAV (formato mais seguro)
                            segment.export(temp_segment_path, format="wav")
                            
                            # Transcrever segmento
                            progress_percent = 0.5 + (i / segments_count) * 0.4
                            progress_bar.progress(progress_percent)
                            status_text.text(f"Transcrevendo segmento alternativo {i+1} de {segments_count}...")
                            
                            segment_transcript = transcribe_segment(temp_segment_path, client, idioma)
                            full_transcript += segment_transcript + " "
                            
                            # Limpar arquivo temporário
                            try:
                                os.remove(temp_segment_path)
                            except:
                                pass
                    except Exception as alt_err:
                        st.error(f"Erro no método alternativo: {str(alt_err)}")
                        st.stop()
            
            # Limpar e formatar a transcrição final
            full_transcript = full_transcript.strip()
            
            # Atualizar progresso
            progress_bar.progress(1.0)
            status_text.text("Transcrição concluída!")
            
            # Exibir resultado
            st.success("Transcrição concluída com sucesso!")
            st.subheader("Resultado da transcrição:")
            st.text_area("Texto transcrito", full_transcript, height=300)
            
            # Opção para baixar a transcrição
            st.download_button(
                label="Baixar transcrição como arquivo TXT",
                data=full_transcript,
                file_name=f"{os.path.splitext(uploaded_file.name)[0]}_transcricao.txt",
                mime="text/plain"
            )
            
    except Exception as e:
        st.error(f"Ocorreu um erro durante a transcrição: {str(e)}")
        if "Invalid file format." in str(e):
            st.warning("O formato do arquivo pode não ser suportado pela API do Whisper ou estar corrompido.")
            st.info("Tente converter seu arquivo para WAV ou MP3 antes de fazer upload.")
        elif "maximum allowed size" in str(e):
            st.warning("Mesmo após a divisão, um dos segmentos pode estar muito grande. Tente um arquivo menor.")
        elif "ffmpeg" in str(e).lower():
            st.warning("""
            Erro relacionado ao FFMPEG. Tente as seguintes soluções:
            1. Use apenas arquivos MP3, WAV ou OGG
            2. Converta seu arquivo para WAV antes de fazer upload
            3. Use um arquivo com menor qualidade/tamanho
            """)
            st.info("Detalhes técnicos do erro para suporte:")
            st.code(str(e))

# Adicionar instruções e informações adicionais
with st.expander("Como funciona o processamento de arquivos grandes?"):
    st.markdown("""
    ### Processo de divisão e transcrição:

    1. **Upload**: Você faz upload de um arquivo de áudio de até 200MB
    2. **Análise**: O sistema verifica o tamanho do arquivo
    3. **Divisão**: Se necessário, o arquivo é dividido em segmentos menores (até 25MB cada)
    4. **Processamento**: Cada segmento é enviado separadamente para a API do Whisper
    5. **Combinação**: As transcrições de todos os segmentos são combinadas
    6. **Resultado**: Você recebe a transcrição completa para download

    ### Compatibilidade e formatos:

    - Formatos recomendados: MP3, WAV, OGG
    - Para melhor compatibilidade, use arquivos WAV
    - Se encontrar erros, tente converter seu arquivo para WAV antes de fazer upload
    """)

# Instruções e informações adicionais
st.markdown("---")
st.markdown("""
### Como usar:
1. Faça upload de um arquivo de áudio (até 200MB)
2. Selecione o idioma do áudio
3. Clique em "Transcrever"
4. Acompanhe o progresso da transcrição
5. Baixe o resultado como arquivo TXT

### Dicas para evitar erros:
- Use preferencialmente arquivos MP3 ou WAV
- Se tiver problemas, converta seu arquivo para WAV antes de fazer upload
- Arquivos de menor qualidade (128kbps) são processados mais rapidamente
""")

# Rodapé
st.markdown("---")
st.markdown("Desenvolvido com Streamlit e OpenAI Whisper API")
