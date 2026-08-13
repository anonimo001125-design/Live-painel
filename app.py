import os
import time
import subprocess

def iniciar():
    print("Iniciando tunel de rede seguro e estavel...")
    # Abre o túnel do Serveo na porta 8080 em segundo plano
    subprocess.Popen([
        "ssh", "-o", "StrictHostKeyChecking=no", 
        "-R", "80:localhost:8080", "serveo.net"
    ])
    
    print("\n==========================================================")
    print(" AGUARDE O LINK .SERVEO.NET APARECER NAS PROXIMAS LINHAS... ")
    print("==========================================================\n")

    # Força a criação da tela virtual ativa ':99' diretamente pelo Python para evitar erros
    os.system("Xvfb :99 -screen 0 1280x720x24 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(3) # Tempo para a tela virtual ligar

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        print("Ligando navegador na tela virtual externa...")
        # Headless=False é SEGREDO! Obriga o navegador a desenhar as imagens na tela virtual :99
        browser = p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        # Coloquei de volta a sua URL real da live que estava nos logs anteriores
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        print(f"Acessando o site: {url_alvo}")
        
        try:
            page.goto(url_alvo, wait_until="networkidle", timeout=0)
            print("Pagina carregada e visivel na tela virtual!")
            time.sleep(5)
            
            # === ALTERAÇÃO 1: Ativa o modo Tela Cheia no navegador virtual ===
            page.evaluate("document.documentElement.requestFullscreen()")
            time.sleep(2)
            
            # Simula um clique para destravar o player de vídeo e o áudio automático do site
            page.mouse.click(640, 360)
        except Exception as e:
            print(f"Aviso no carregamento: {e}")
        
        # Cria a pasta estritamente ANTES para o FFmpeg não falhar ao criar o arquivo m3u8
        os.makedirs("stream", exist_ok=True)
        
        # === ALTERAÇÃO 2: Adicionado "-draw_mouse", "0" para sumir com a seta do mouse da imagem ===
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
        
        print("Servidor HTTP ativo na porta 8080...")
        os.chdir("stream")
        os.system("python3 -m http.server 8080")

if __name__ == "__main__":
    iniciar()
