import os
import time
import subprocess

def iniciar():
    # 1. Baixa o executável do Ngrok direto para a pasta do projeto
    print("Baixando túnel de rede...")
    os.system("curl -s -O https://equinox.io")
    os.system("tar -xzf ngrok-stable-linux-amd64.tgz")
    os.system("chmod +x ngrok")

    # 2. COLE O SEU TOKEN DO NGROK ENTRE AS ASPAS ABAIXO:
    TOKEN_NGROK = "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk"
    
    os.system(f"./ngrok config add-authtoken {TOKEN_NGROK}")
    subprocess.Popen(["./ngrok", "http", "8080", "--log=stdout"])

    # 3. Baixa o gravador leve diretamente
    os.system("pip3 install playwright && playwright install --with-deps chromium")
    
    from playwright.sync_api import sync_playwright
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
        
        print("Servidor ativo na porta 8080...")
        os.makedirs("/app/stream", exist_ok=True)
        os.chdir("/app/stream")
        os.system("python3 -m http.server 8080")

if __name__ == "__main__":
    iniciar()
