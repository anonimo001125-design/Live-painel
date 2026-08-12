import os
import time
import subprocess
from playwright.sync_api import sync_playwright

def iniciar():
    print("Iniciando tunel de rede...")
    
    # 1. COLOQUE O SEU TOKEN DO NGROK ENTRE AS ASPAS:
    TOKEN_NGROK = "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk"
    
    from pyngrok import ngrok
    ngrok.set_auth_token(TOKEN_NGROK)
    url_publica = ngrok.connect(8080).public_url
    
    print("\n==========================================================")
    print("========= SEU LINK DE TRANSMISSAO EM TEMPO REAL =========")
    print(f"{url_publica}/live.m3u8")
    print("==========================================================\n")

    with sync_playwright() as p:
        print("Ligando navegador interno de forma nativa...")
        # Alterado para headless=True para corrigir o erro de inicialização gráfica
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        # 2. COLOQUE O SEU SITE AQUI:
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        
        page.goto(url_alvo, wait_until="networkidle")
        time.sleep(5)
        
        # O FFmpeg captura direto o áudio do PulseAudio e a tela nativa do runner
        ffmpeg_cmd = [
            "ffmpeg", "-f", "pulse", "-i", "default",
            "-f", "x11grab", "-video_size", "1280x720", "-i", ":0.0",
            "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-g", "60", "-hls_time", "2", 
            "-hls_list_size", "5", "-hls_flags", "delete_segments", 
            "stream/live.m3u8"
        ]
        subprocess.Popen(ffmpeg_cmd)
        
        print("Servidor ativo na porta 8080...")
        os.chdir("stream")
        os.system("python3 -m http.server 8080")

if __name__ == "__main__":
    iniciar()
