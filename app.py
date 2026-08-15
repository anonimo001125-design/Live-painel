import os
import time
import subprocess

def iniciar():
    # 1. Prepara a pasta de streaming
    os.makedirs("stream", exist_ok=True)

    # 2. Inicia o servidor HTTP em segundo plano imediatamente
    print("Iniciando servidor HTTP na porta 8080...")
    subprocess.Popen(["python3", "-m", "http.server", "8080", "--directory", "stream"])
    time.sleep(2)

    # 3. Liga a ponte de internet oficial do sistema (.lhr.life)
    print("Iniciando tunel de rede seguro e estavel...")
    subprocess.Popen([
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=60",
        "-R", "80:localhost:8080", "nokey@localhost.run"
    ])
    time.sleep(5)

    print("\n==========================================================")
    print("======== SEU STREAMING FOI INICIADO COM SUCESSO ========")
    print("Suba a tela do log para copiar o seu endereço .lhr.life")
    print("==========================================================\n")

    # 4. CAPTURA DIRETA DE FONTE (Sem Navegador / Sem Travas / Tela Cheia Nativa)
    # Mudamos o link para a origem do sinal de vídeo que o site consome de fundo
    url_fonte_video = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
    
    ffmpeg_cmd = [
        "ffmpeg", "-re", "-i", url_fonte_video,
        "-c:v", "copy", "-c:a", "copy", 
        "-hls_time", "2", "-hls_list_size", "5", "-hls_flags", "delete_segments", 
        "stream/live.m3u8"
    ]
    
    print("FFmpeg conectando direto na fonte do streaming...")
    processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)

    # Mantém o script principal vivo repassando o sinal sem parar por horas
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        processo_ffmpeg.terminate()

if __name__ == "__main__":
    iniciar()
