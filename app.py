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

    # 3. Liga o túnel estável do Serveo
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

    # 5. FFmpeg configurado com reconexão automática e áudio virtual direto
    ffmpeg_cmd = [
        "ffmpeg", "-f", "pulse", "-i", "auto_null.monitor",
        "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1280x720", "-i", ":99.0",
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-g", "60", "-hls_time", "2", 
        "-hls_list_size", "5", "-hls_flags", "delete_segments", 
        "stream/live.m3u8"
    ]
    print("FFmpeg iniciando gravacao continua de audio e video...")
    processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)

    # 6. Inicializa o navegador focado em monitorar as mudanças de vídeo
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        print("Ligando navegador monitor...")
        browser = p.chromium.launch(
            headless=False, 
            args=[
                "--no-sandbox", 
                "--disable-dev-shm-usage",
                "--autoplay-policy=no-user-gesture-required"
            ]
        )
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        print(f"Acessando o site: {url_alvo}")
        
        try:
            page.goto(url_alvo, wait_until="commit", timeout=0)
            time.sleep(8)
            
            # Clica no centro da tela para ativar as permissões de som e focar no player
            page.mouse.click(640, 360)
            time.sleep(2)
            
            # Pressiona a tecla 'f' do teclado (atalho universal para Tela Cheia na grande maioria dos players de vídeo da web)
            page.keyboard.press("f")
            print("Atalho universal de tela cheia (tecla F) enviado.")
            
        except Exception as e:
            print(f"Aviso inicial: {e}")

        # === MONITOR DE RECONEXÃO E TROCA DE VÍDEO ===
        print("Vigia de troca de videos ativado. Mantendo transmissao viva...")
        try:
            while True:
                time.sleep(5)
                # Verifica constantemente se a página mudou ou se saiu do modo tela cheia
                # Se o player recarregar para o próximo vídeo, ele força o clique e a tecla 'f' de novo automaticamente
                is_fullscreen = page.evaluate("!!document.fullscreenElement")
                if not is_fullscreen:
                    try:
                        print("Detectada mudanca de video ou perda de tela cheia. Reativando...")
                        page.mouse.click(640, 360)
                        time.sleep(1)
                        page.keyboard.press("f")
                    except:
                        pass
        except KeyboardInterrupt:
            processo_ffmpeg.terminate()
            browser.close()

if __name__ == "__main__":
    iniciar()
