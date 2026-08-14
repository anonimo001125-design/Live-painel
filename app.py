import os
import time
import subprocess

def iniciar():
    # 1. Prepara a pasta de streaming
    os.makedirs("stream", exist_ok=True)
    with open("stream/live.m3u8", "w") as f:
        f.write("#EXTM3U\n")

    # 2. Inicia o servidor HTTP em segundo plano
    print("Iniciando servidor HTTP na porta 8080...")
    subprocess.Popen(["python3", "-m", "http.server", "8080", "--directory", "stream"])
    time.sleep(2)

    # 3. Liga o túnel do Serveo
    print("Iniciando tunel de rede seguro e estavel...")
    subprocess.Popen([
        "ssh", "-o", "StrictHostKeyChecking=no", 
        "-R", "80:localhost:8080", "serveo.net"
    ])
    time.sleep(5)

    # 4. Configura a tela virtual
    os.system("Xvfb :99 -screen 0 1280x720x24 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(3) 

    # 5. FFmpeg captura a tela virtual :99.0 limpa (sem mouse)
    ffmpeg_cmd = [
        "ffmpeg", "-f", "pulse", "-i", "auto_null.monitor",
        "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1280x720", "-i", ":99.0",
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-g", "60", "-hls_time", "2", 
        "-hls_list_size", "5", "-hls_flags", "delete_segments", 
        "stream/live.m3u8"
    ]
    print("FFmpeg iniciando gravacao continua...")
    processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)

    # 6. Inicializa o navegador focado
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        print("Ligando navegador no MODO QUIOSQUE SEM ABAS...")
        
        browser = p.chromium.launch(
            headless=False, 
            args=[
                "--no-sandbox", 
                "--disable-dev-shm-usage",
                "--autoplay-policy=no-user-gesture-required",
                "--kiosk",                     
                "--fill-properties",
                "--no-first-run",
                "--no-default-browser-check",
                "--start-fullscreen"           
            ]
        )
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        print(f"Acessando o site: {url_alvo}")
        
        try:
            page.goto(url_alvo, wait_until="commit", timeout=0)
            time.sleep(12) # Tempo para o player e todas as janelas internas carregarem
            
            # Clique inicial para dar o foco e destravar o som
            page.mouse.click(640, 360)
            time.sleep(1)
            
            # === CHAVE MESTRA: ENTRA DENTRO DO IFRAME E FORÇA TELA CHEIA NO PLAYER REAL ===
            print("Procurando o player dentro das janelas protegidas do site...")
            for frame in page.frames:
                try:
                    # Injeta o comando de tela cheia em absolutamente todas as janelas internas que existirem na página
                    frame.evaluate("document.documentElement.requestFullscreen()")
                    # Se achar o botão de tela cheia padrão de vídeo dentro do frame, força o clique nele por ID ou classe
                    frame.evaluate("document.querySelector('video').requestFullscreen()")
                except:
                    pass
            
            print("Comando de tela cheia injetado em todas as camadas internas.")
            time.sleep(2)
            
            # Executa o duplo clique geral no centro para garantir o acionamento alternativo
            page.mouse.dblclick(640, 360)
            
        except Exception as e:
            print(f"Aviso inicial: {e}")

        # === MONITOR DE RECONEXÃO PARA TROCA DE VÍDEO ===
        print("Vigia de troca de videos ativo...")
        try:
            while True:
                time.sleep(60) # Modificado para 60 segundos para não sobrecarregar as trocas
                try:
                    is_fullscreen = page.evaluate("!!document.fullscreenElement")
                    if not is_fullscreen:
                        print("Detectada troca de video. Reaplicando a chave mestra em todas as camadas...")
                        page.mouse.click(640, 360)
                        for frame in page.frames:
                            try:
                                frame.evaluate("document.documentElement.requestFullscreen()")
                                frame.evaluate("document.querySelector('video').requestFullscreen()")
                            except:
                                pass
                        page.mouse.dblclick(640, 360)
                except:
                    pass
        except KeyboardInterrupt:
            processo_ffmpeg.terminate()
            browser.close()

if __name__ == "__main__":
    iniciar()
