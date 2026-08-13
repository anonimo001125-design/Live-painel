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
            time.sleep(8)
            
            # === COMANDO DO ESTICADOR INJETADO ===
            # Esse código procura o player de vídeo na página e obriga ele a ocupar a tela inteira por cima de qualquer menu ou aba do site
            page.evaluate("""
                const style = document.createElement('style');
                style.innerHTML = `
                    video, .video-player, iframe, #player {
                        position: fixed !important;
                        top: 0 !important;
                        left: 0 !important;
                        width: 100vw !important;
                        height: 100vh !important;
                        z-index: 999999 !important;
                        background: black !important;
                    }
                `;
                document.head.appendChild(style);
            """)
            print("Esticador de video injetado com sucesso.")
            time.sleep(2)

            # Clica no centro do player para garantir o início do som e do play
            page.mouse.click(640, 360)
            print("Clique de ativacao executado.")
        except Exception as e:
            print(f"Aviso inicial: {e}")

        # === MONITOR DE RECONEXÃO PARA TROCA DE VÍDEO ===
        print("Vigia de troca de videos ativo...")
        try:
            while True:
                time.sleep(5)
                try:
                    # Se o site mudar de vídeo e recarregar a página, reinjeta o esticador para sumir com os novos menus automaticamente
                    page.evaluate("""
                        if (!document.getElementById('forced-fullscreen-style')) {
                            const style = document.createElement('style');
                            style.id = 'forced-fullscreen-style';
                            style.innerHTML = 'video, .video-player, iframe, #player { position: fixed !important; top: 0 !important; left: 0 !important; width: 100vw !important; height: 100vh !important; z-index: 999999 !important; background: black !important; }';
                            document.head.appendChild(style);
                        }
                    """)
                    page.mouse.click(640, 360)
                except:
                    pass
        except KeyboardInterrupt:
            processo_ffmpeg.terminate()
            browser.close()

if __name__ == "__main__":
    iniciar()
