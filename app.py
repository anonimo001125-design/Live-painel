import os
import time
import subprocess

def iniciar():
    # 1. Prepara a pasta de streaming e cria o arquivo base para evitar erro 404
    os.makedirs("stream", exist_ok=True)
    with open("stream/live.m3u8", "w") as f:
        f.write("#EXTM3U\n")

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

    # URL do site que você quer transmitir
    url_site = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
    
    print("Pescando o sinal de video oculto do site...")
    # Chama o yt-dlp instalado pelo ambiente Python de forma direta
    try:
        url_real_video = subprocess.check_output(["python3", "-m", "yt_dlp", "-g", url_site]).decode().strip()
        print("Sinal de video encontrado com sucesso!")
    except Exception as e:
        print(f"Aviso no extrator: {e}. Usando URL padrão por segurança.")
        url_real_video = url_site

    # 4. CAPTURA DO SINAL DIRECTO (Sem Navegador / Sem Travas / Tela Cheia Perfeita)
    ffmpeg_cmd = [
        "ffmpeg", "-re", "-i", url_real_video,
        "-c:v", "copy", "-c:a", "copy", 
        "-hls_time", "2", "-hls_list_size", "5", "-hls_flags", "delete_segments", 
        "stream/live.m3u8"
    ]
    
    print("FFmpeg transmitindo o fluxo de video direto em alta qualidade...")
    processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)

    # Mantém o script vivo trabalhando sem travar
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        processo_ffmpeg.terminate()

if __name__ == "__main__":
    iniciar()
