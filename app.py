import os
import time
import subprocess
from playwright.sync_api import sync_playwright

def iniciar():
    # 1. Instala o túnel de forma direta e rápida sem travar o terminal
    print("Iniciando tunel de rede alternativo...")
    os.system("npm install -g localtunnel")
    
    # Executa o localtunnel em segundo plano na porta 8080
    subprocess.Popen(["npx", "localtunnel", "--port", "8080"])
    
    print("\n==========================================================")
    print("========= SEU STREAMING ESTA SENDO PREPARADO =========")
    print("Aguarde a inicializacao do servidor de video...")
    print("==========================================================\n")

    with sync_playwright() as p:
        print("Ligando navegador interno com gravador de video...")
        
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir="stream/"
        )
        page = context.new_page()
        
        # Sua URL alvo recuperada do log anterior
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        print(f"Acessando o site: {url_alvo}")
        
        try:
            page.goto(url_alvo, wait_until="commit", timeout=0)
            print("Pagina conectada! Gerando transmissao...")
        except Exception as e:
            print(f"Aviso durante a execucao: {e}")
        
        # O FFmpeg processa o streaming diretamente
        ffmpeg_cmd = [
            "ffmpeg", "-f", "pulse", "-i", "default",
            "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-g", "60", "-hls_time", "2", 
            "-hls_list_size", "5", "-hls_flags", "delete_segments", 
            "stream/live.m3u8"
        ]
        subprocess.Popen(ffmpeg_cmd)
        
        print("Servidor ativo na porta 8080...")
        os.makedirs("stream", exist_ok=True)
        os.chdir("stream")
        
        # Mantém o servidor web ativo de forma contínua
        os.system("python3 -m http.server 8080")

if __name__ == "__main__":
    iniciar()
