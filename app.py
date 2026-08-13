import os
import time
import subprocess

def iniciar():
    print("Iniciando tunel de rede alternativo ultra estavel (Pinggy)...")
    # Abre o túnel do Pinggy na porta 8080 em segundo plano (Não cai e não precisa de cadastro)
    subprocess.Popen([
        "ssh", "-o", "StrictHostKeyChecking=no", 
        "-R", "80:localhost:8080", "a.pinggy.io"
    ])
    
    print("\n==========================================================")
    print(" AGUARDE O LINK .PINGGY.LINK APARECER NAS PROXIMAS LINHAS... ")
    print("==========================================================\n")

    # Força a criação da tela virtual ativa ':99' diretamente pelo Python
    os.system("Xvfb :99 -screen 0 1280x720x24 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(3) # Tempo para a tela virtual ligar

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        print("Ligando navegador na tela virtual externa...")
        # Mantido Headless=False para desenhar o vídeo na tela virtual :99
        browser = p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        print(f"Acessando o site: {url_alvo}")
        
        try:
            page.goto(url_alvo, wait_until="networkidle", timeout=0)
            print("Pagina carregada e visivel na tela virtual!")
            time.sleep(5)
            
            # Força a página a entrar em Tela Cheia (Full Screen) removendo as bordas
            page.evaluate("document.documentElement.requestFullscreen()")
            time.sleep(2)
            
            # Simula um clique para destravar o player de vídeo e o áudio automático do site
            page.mouse.click(640, 360)
        except Exception as e:
            print(f"Aviso no carregamento: {e}")
        
        # Cria a pasta antes para o FFmpeg não dar erro de caminho
        os.makedirs("stream", exist_ok=True)
        
        # O parâmetro "-draw_mouse 0" remove completamente a seta do mouse da gravação
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
    ini_process = iniciar()
