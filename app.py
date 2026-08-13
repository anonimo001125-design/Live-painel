import os
import time
import subprocess

def iniciar():
    # 1. Cria a pasta e um arquivo m3u8 temporário para evitar o erro 404 imediato
    os.makedirs("stream", exist_ok=True)
    with open("stream/live.m3u8", "w") as f:
        f.write("#EXTM3U\n")

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
        
        # 3. COMANDO DO FFMPEG ATUALIZADO: Adicionado -preset ultrafast para gerar a imagem na hora
        ffmpeg_cmd = [
            "ffmpeg", "-f", "pulse", "-i", "default",
            "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1280x720", "-i", ":99.0",
            "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-g", "60", "-hls_time", "2", 
            "-hls_list_size", "5", "-hls_flags", "delete_segments", 
            "stream/live.m3u8"
        ]
        
        print("FFmpeg iniciando gravacao ultra rapida...")
        processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)
        
        # PAUSA CRÍTICA: Espera 10 segundos para o FFmpeg encher o disco com os pedaços de vídeo
        print("Aguardando geracao dos primeiros blocos de video no disco...")
        time.sleep(10)

        # 4. Abre o servidor HTTP
        print("Iniciando servidor HTTP na porta 8080...")
        subprocess.Popen(["python3", "-m", "http.server", "8080", "--directory", "stream"])
        time.sleep(2)

        # 5. Só liga o túnel do Serveo por último, quando o streaming já está ativo de verdade
        print("Ligando o tunel publico do Serveo...")
        subprocess.Popen([
            "ssh", "-o", "StrictHostKeyChecking=no", 
            "-R", "80:localhost:8080", "serveo.net"
        ])

        # Mantém o script vivo transmitindo
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            processo_ffmpeg.terminate()
            browser.close()

if __name__ == "__main__":
    iniciar()
