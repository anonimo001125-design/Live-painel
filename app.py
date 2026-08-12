import os
import time
import subprocess
from playwright.sync_api import sync_playwright

def iniciar():
    # 1. Configura o Token do Ngrok para liberar o link público sem erros
    # COLE O SEU TOKEN DO NGROK ENTRE AS ASPAS ABAIXO:
    TOKEN_NGROK = "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk"
    
    os.system(f"ngrok config add-authtoken {TOKEN_NGROK}")
    # Abre o túnel de internet na porta 8080 em segundo plano
    subprocess.Popen(["ngrok", "http", "8080", "--log=stdout"], stdout=subprocess.DEVNULL)

    with sync_playwright() as p:
        print("Abrindo navegador estilo Duck/Chromium...")
        browser = p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        # LINK DA SUA PÁGINA: Altere o link abaixo para o site que você quer transmitir
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        
        print(f"Acessando o site: {url_alvo}")
        page.goto(url_alvo, wait_until="networkidle")
        time.sleep(5) # Espera carregar os componentes gráficos
        
        # Inicia a gravação direta do FFmpeg capturando som e imagem perfeitamente
        ffmpeg_cmd = [
            "ffmpeg", "-f", "pulse", "-i", "default",
            "-f", "x11grab", "-video_size", "1280x720", "-i", ":99.0",
            "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-g", "60", "-hls_time", "2", 
            "-hls_list_size", "5", "-hls_flags", "delete_segments", 
            "/app/stream/live.m3u8"
        ]
        subprocess.Popen(ffmpeg_cmd)
        print("FFmpeg gravando a tela e gerando os fragmentos .m3u8...")

        # Inicia um servidor web em Python simplificado que não cai nunca
        print("Iniciando servidor de arquivos na porta 8080...")
        os.chdir("/app/stream")
        os.system("python3 -m http.server 8080")

if __name__ == "__main__":
    iniciar()
