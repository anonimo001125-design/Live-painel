import os
import time
import subprocess

def iniciar():
    # 1. Cria a pasta de streaming logo no início
    os.makedirs("stream", exist_ok=True)

    # 2. Força a criação da tela virtual ativa ':99'
    os.system("Xvfb :99 -screen 0 1280x720x24 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(3) 

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        print("Ligando navegador na tela virtual externa...")
        browser = p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        print(f"Acessando o site: {url_alvo}")
        
        try:
            page.goto(url_alvo, wait_until="networkidle", timeout=0)
            print("Pagina carregada e visivel na tela virtual!")
            time.sleep(5)
            
            # Ativa o modo Tela Cheia
            page.evaluate("document.documentElement.requestFullscreen()")
            time.sleep(2)
            
            # Simula o clique para destravar som e vídeo
            page.mouse.click(640, 360)
        except Exception as e:
            print(f"Aviso no carregamento: {e}")
        
        # COMANDO DO FFMPEG: Gravando diretamente com o caminho completo correto
        ffmpeg_cmd = [
            "ffmpeg", "-f", "pulse", "-i", "default",
            "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1280x720", "-i", ":99.0",
            "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-g", "60", "-hls_time", "2", 
            "-hls_list_size", "5", "-hls_flags", "delete_segments", 
            "stream/live.m3u8"
        ]
        subprocess.Popen(ffmpeg_cmd)
        print("FFmpeg capturando imagem (sem mouse) e som em tempo real...")
        
        # Inicia o túnel de rede do Serveo
        print("Iniciando tunel de rede seguro e estavel...")
        subprocess.Popen([
            "ssh", "-o", "StrictHostKeyChecking=no", 
            "-R", "80:localhost:8080", "serveo.net"
        ])
        
        print("Servidor HTTP ativo na porta 8080...")
        # CORREÇÃO: Abre o servidor apontando diretamente para a pasta 'stream' sem mudar o script de lugar
        os.system("python3 -m http.server 8080 --directory stream")

if __name__ == "__main__":
    iniciar()
