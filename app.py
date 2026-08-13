import os
import time
import subprocess

def iniciar():
    # 1. Força a criação da tela virtual ativa ':99' primeiro
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
        
        # Cria a pasta e ativa o FFmpeg sem a seta do mouse
        os.makedirs("stream", exist_ok=True)
        
        ffmpeg_cmd = [
            "ffmpeg", "-f", "pulse", "-i", "default",
            "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1280x720", "-i", ":99.0",
            "stream/live.m3u8"
        ]
        subprocess.Popen(ffmpeg_cmd)
        print("FFmpeg capturando imagem (sem mouse) e som em tempo real...")
        
        print("Servidor HTTP ativo na porta 8080...")
        os.chdir("stream")
        
        # === MUDANÇA CRÍTICA: Inicia o túnel de rede APÓS o servidor Python estar pronto ===
        print("Iniciando tunel de rede seguro e estavel...")
        subprocess.Popen([
            "ssh", "-o", "StrictHostKeyChecking=no", 
            "-R", "80:localhost:8080", "serveo.net"
        ])
        
        # Liga o servidor de arquivos definitivo
        os.system("python3 -m http.server 8080")

if __name__ == "__main__":
    iniciar()
