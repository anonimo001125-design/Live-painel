import os
import time
import subprocess
from playwright.sync_api import sync_playwright

def iniciar():
    # Cole aqui a sua chave cheia de letras e números que você pegou no Ngrok:
    TOKEN_NGROK = "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk"
    
    os.system(f"ngrok config add-authtoken {TOKEN_NGROK}")
    subprocess.Popen(["ngrok", "http", "8080", "--log=stdout"])

    with sync_playwright() as p:
        print("Ligando navegador...")
        browser = p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        # Mude para o link do site que você quer transmitir:
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        
        page.goto(url_alvo, wait_until="networkidle")
        time.sleep(5)
        
        ffmpeg_cmd = [
            "ffmpeg", "-f", "pulse", "-i", "default",
            "-f", "x11grab", "-video_size", "1280x720", "-i", ":99.0",
            "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-g", "60", "-hls_time", "2", 
            "-hls_list_size", "5", "-hls_flags", "delete_segments", 
            "/app/stream/live.m3u8"
        ]
        subprocess.Popen(ffmpeg_cmd)
        
        os.chdir("/app/stream")
        os.system("python3 -m http.server 8080")

if __name__ == "__main__":
    iniciar()
