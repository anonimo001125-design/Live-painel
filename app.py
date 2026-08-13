import os
import time
import subprocess

def iniciar():
    # 1. Cria a pasta e o arquivo inicial para o servidor de transmissão
    os.makedirs("stream", exist_ok=True)
    with open("stream/live.m3u8", "w") as f:
        f.write("#EXTM3U\n")

    # 2. Inicia o servidor HTTP em segundo plano imediatamente
    print("Iniciando servidor HTTP na porta 8080...")
    subprocess.Popen(["python3", "-m", "http.server", "8080", "--directory", "stream"])
    time.sleep(2)

    # 3. Liga o túnel de rede seguro do Serveo
    print("Iniciando tunel de rede seguro e estavel...")
    subprocess.Popen([
        "ssh", "-o", "StrictHostKeyChecking=no", 
        "-R", "80:localhost:8080", "serveo.net"
    ])
    time.sleep(5)

    # 4. Força a criação da tela virtual ativa ':99'
    os.system("Xvfb :99 -screen 0 1280x720x24 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(3) 

    # 5. COMANDO DO FFMPEG ATUALIZADO: Captura o monitor de som virtual direto ('auto_null.monitor')
    # Adicionado os codecs de áudio AAC com bitrate de alta qualidade para o streaming m3u8
    ffmpeg_cmd = [
        "ffmpeg", "-f", "pulse", "-i", "auto_null.monitor",
        "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1280x720", "-i", ":99.0",
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-g", "60", "-hls_time", "2", 
        "-hls_list_size", "5", "-hls_flags", "delete_segments", 
        "stream/live.m3u8"
    ]
    print("FFmpeg iniciando gravacao com captura de som e video...")
    processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)

    # 6. Inicializa o navegador com a política de Autoplay liberada para soltar o som sozinho
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        print("Ligando navegador na tela virtual externa...")
        browser = p.chromium.launch(
            headless=False, 
            args=[
                "--no-sandbox", 
                "--disable-dev-shm-usage",
                "--autoplay-policy=no-user-gesture-required" # LIBERA O SOM AUTOMÁTICO
            ]
        )
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        print(f"Acessando o site: {url_alvo}")
        
        try:
            page.goto(url_alvo, wait_until="commit", timeout=0)
            print("Pagina conectada!")
            time.sleep(8) # Aguarda o player renderizar completamente na tela
            
            # ORDEM CORRIGIDA DA TELA CHEIA:
            # Primeiro simula o clique físico para o navegador dar foco e liberar a segurança
            page.mouse.click(640, 360)
            print("Clique de ativacao executado.")
            time.sleep(2)
            
            # Agora executa a tela cheia verdadeira via JavaScript
            page.evaluate("document.documentElement.requestFullscreen()")
            print("Modo Tela Cheia ativado com sucesso.")
            time.sleep(2)
            
            # Segundo clique de segurança garantindo o play no vídeo com som ativo
            page.mouse.click(640, 360)
            
        except Exception as e:
            print(f"Aviso no carregamento: {e}")

        # Mantém o streaming ativo de forma contínua
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            processo_ffmpeg.terminate()
            browser.close()

if __name__ == "__main__":
    iniciar()
